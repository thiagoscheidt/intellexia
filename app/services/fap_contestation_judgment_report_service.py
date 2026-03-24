from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from rich import print
from markitdown import MarkItDown
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat

from app.agents.fap.fap_contestation_judgment_metadata_agent import (
    FapContestationJudgmentMetadataAgent,
)
from app.models import Benefit, BenefitFapSourceHistory, Client, FapContestationJudgmentReport, db
from app.services.open_cnpj_service import OpenCNPJService


class FapContestationJudgmentReportService:
    """Service para gerenciamento e processamento de relatórios de julgamento de contestação do FAP.

    Implementa parsing de markdown e importação dos benefícios para a tabela central `benefits`.
    """

    def __init__(self, flask_app):
        self.app = flask_app
        self.metadata_agent = FapContestationJudgmentMetadataAgent()
        self.open_cnpj_service = OpenCNPJService()

    @staticmethod
    def _normalize_cnpj(cnpj: str | None) -> str:
        return ''.join(ch for ch in (cnpj or '') if ch.isdigit())

    @staticmethod
    def _format_cnpj(cnpj_digits: str) -> str:
        if len(cnpj_digits) != 14:
            return cnpj_digits
        return f'{cnpj_digits[:2]}.{cnpj_digits[2:5]}.{cnpj_digits[5:8]}/{cnpj_digits[8:12]}-{cnpj_digits[12:14]}'

    def _find_client_by_cnpj(self, law_firm_id: int, cnpj_digits: str) -> Client | None:
        if not cnpj_digits:
            return None

        clients = Client.query.filter_by(law_firm_id=law_firm_id).all()
        for client in clients:
            if self._normalize_cnpj(client.cnpj) == cnpj_digits:
                return client
        return None

    def _upsert_client_from_cnpj(self, law_firm_id: int, cnpj_raw: str | None) -> tuple[Client | None, dict | None, str | None]:
        cnpj_digits = self._normalize_cnpj(cnpj_raw)
        if len(cnpj_digits) != 14:
            return None, None, None

        cnpj_formatado = self._format_cnpj(cnpj_digits)
        is_matriz = cnpj_digits[8:12] == '0001'
        lookup_result = self.open_cnpj_service.lookup_company(cnpj_formatado)
        company_data = lookup_result.get('data') if lookup_result.get('success') else None

        if not company_data:
            return None, None, cnpj_formatado

        client = self._find_client_by_cnpj(law_firm_id, cnpj_digits)
        if client is None:
            client = Client(
                law_firm_id=law_firm_id,
                name=company_data.get('razao_social') or f'Empresa {cnpj_formatado}',
                cnpj=cnpj_formatado,
            )
            db.session.add(client)
        else:
            client.name = company_data.get('razao_social') or client.name
            client.cnpj = cnpj_formatado

        # Sincroniza campos cadastrais principais quando disponíveis.
        client.street = company_data.get('logradouro') or client.street
        client.number = company_data.get('numero') or client.number
        client.district = company_data.get('bairro') or client.district
        client.city = company_data.get('municipio') or client.city
        client.state = company_data.get('uf') or client.state
        client.zip_code = company_data.get('cep') or client.zip_code
        if is_matriz:
            client.has_branches = True
        client.updated_at = datetime.utcnow()

        return client, company_data, cnpj_formatado

    def convert_report_to_markdown(self, file_path: str | Path) -> str:
        """Converte um relatório de julgamento do FAP para markdown usando Docling."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f'Arquivo não encontrado: {path}')

        file_ext = path.suffix.lower()
        if file_ext == '.pdf':
            pipeline_options = PdfPipelineOptions(
                do_ocr=False,
                generate_page_images=False,
                do_table_structure=False,
                enable_parallel_processing=True,
            )
            converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
            )
        else:
            converter = DocumentConverter()

        result = converter.convert(str(path))
        markdown_content = result.document.export_to_markdown() if result and result.document else ''

        if not markdown_content.strip():
            raise ValueError('Docling não retornou conteúdo em markdown para o arquivo informado.')

        return markdown_content

    def convert_report_to_markdown_with_markitdown(self, file_path: str | Path) -> str:
        """Converte um relatório de julgamento do FAP para markdown usando MarkItDown."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f'Arquivo não encontrado: {path}')

        converter = MarkItDown()
        result = converter.convert(str(path))
        markdown_content = (result.text_content or '') if result else ''

        if not markdown_content.strip():
            raise ValueError('MarkItDown não retornou conteúdo em markdown para o arquivo informado.')

        return markdown_content

    @staticmethod
    def normalize_markdown(text: str) -> str:
        """Limpeza básica do markdown antes do parsing dos benefícios."""
        if not text:
            return ''

        cleaned = text.replace('**', '')
        cleaned = cleaned.replace('\r\n', '\n').replace('\r', '\n')
        cleaned = cleaned.replace('\x0c', '\n')

        filtered_lines: list[str] = []
        for raw_line in cleaned.split('\n'):
            line = raw_line.strip()
            if not line:
                continue

            # Remove apenas linhas isoladas de cabeçalho/rodapé, sem apagar o corpo da página.
            if re.fullmatch(r'MINIST[ÉE]RIO DA PREVID[ÊE]NCIA SOCIAL', line, flags=re.IGNORECASE):
                continue
            if re.fullmatch(r'P[aá]gina\s+\d+\s+de\s+\d+', line, flags=re.IGNORECASE):
                continue

            filtered_lines.append(line)

        cleaned = '\n'.join(filtered_lines)
        cleaned = re.sub(r'\n{2,}', '\n', cleaned)
        return cleaned.strip()

    @staticmethod
    def split_blocks(text: str) -> list[str]:
        """Divide o documento em blocos de benefícios."""
        return re.split(r'\bN[uú]mero do Benef[ií]cio\b', text, flags=re.IGNORECASE)

    @staticmethod
    def extract_between(text: str, start: str, end: str | None = None) -> str | None:
        """Extrai texto entre delimitadores."""
        start_match = re.search(re.escape(start), text, flags=re.IGNORECASE)
        if not start_match:
            return None

        segment = text[start_match.end():]
        if end:
            end_match = re.search(re.escape(end), segment, flags=re.IGNORECASE)
            if end_match:
                return segment[:end_match.start()].strip() or None

        return segment.strip() or None

    @staticmethod
    def extract_field_value(block: str, label: str, next_labels: list[str] | None = None) -> str | None:
        """Extrai o valor de um campo identificado por label no bloco."""
        next_labels = next_labels or []
        label_match = re.search(re.escape(label), block, flags=re.IGNORECASE)
        if not label_match:
            return None

        segment = block[label_match.end():]
        end_indexes: list[int] = []
        for next_label in next_labels:
            next_match = re.search(re.escape(next_label), segment, flags=re.IGNORECASE)
            if next_match:
                end_indexes.append(next_match.start())

        value = segment[:min(end_indexes)] if end_indexes else segment
        value = re.sub(r'\s+', ' ', value).strip(' :-\n\t')
        return value or None

    @staticmethod
    def _extract_text_between_keywords(text: str, start_pattern: str, end_patterns: list[str] | None = None) -> str | None:
        start_match = re.search(start_pattern, text, flags=re.IGNORECASE)
        if not start_match:
            return None

        segment = text[start_match.end():]
        end_indexes: list[int] = []
        for end_pattern in end_patterns or []:
            end_match = re.search(end_pattern, segment, flags=re.IGNORECASE)
            if end_match:
                end_indexes.append(end_match.start())

        value = segment[:min(end_indexes)] if end_indexes else segment
        value = re.sub(r'\s+', ' ', value).strip(' :-\n\t')
        return value or None

    @staticmethod
    def _normalize_benefit_type(raw_value: str | None) -> str | None:
        if not raw_value:
            return None
        match = re.search(r'(?:B)?(\d{2})', raw_value, flags=re.IGNORECASE)
        if not match:
            return None
        return f"B{match.group(1)}"

    def _extract_benefit_type(self, block: str) -> str | None:
        patterns = [
            r'Esp[ée]cie do Benef[ií]cio\s*[:\-]?\s*(B?\d{2})\b',
            r'\bEsp[ée]cie\s*:\s*(B?\d{2})\b',
            r'\bNB\s*:\s*(\d{2})\s*/',
        ]
        for pattern in patterns:
            match = re.search(pattern, block, flags=re.IGNORECASE)
            if match:
                normalized = self._normalize_benefit_type(match.group(1))
                if normalized:
                    return normalized
        return None

    @staticmethod
    def _parse_br_date(value: str | None):
        if not value:
            return None
        try:
            return datetime.strptime(value, '%d/%m/%Y').date()
        except ValueError:
            return None

    @staticmethod
    def _parse_br_datetime(value: str | None):
        if not value:
            return None

        normalized = str(value).strip()
        for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M'):
            try:
                return datetime.strptime(normalized, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _extract_date_after_label(block: str, label_pattern: str, max_chars: int = 300):
        label_match = re.search(label_pattern, block, flags=re.IGNORECASE)
        if not label_match:
            return None

        snippet = block[label_match.end():label_match.end() + max_chars]
        date_match = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', snippet)
        if not date_match:
            return None

        return FapContestationJudgmentReportService._parse_br_date(date_match.group(1))

    def _extract_dib(self, block: str):
        # Ex.: "Data Início Benefício (DIB) 22/11/2012"
        value = self._extract_date_after_label(
            block,
            r'Data\s+In[ií]cio\s+Benef[ií]cio\s*\(?DIB\)?',
        )
        if value:
            return value

        # Ex.: "DIB: 22/11/2012"
        match = re.search(r'\bDIB\s*:\s*(\d{2}/\d{2}/\d{4})\b', block, flags=re.IGNORECASE)
        return self._parse_br_date(match.group(1)) if match else None

    def _extract_dcb(self, block: str):
        # Ex.: "Data Cessação Benefício (DCB) 24/01/2013"
        value = self._extract_date_after_label(
            block,
            r'Data\s+Cessa[cç][aã]o\s+Benef[ií]cio\s*\(?DCB\)?',
        )
        if value:
            return value

        # Ex.: "DCB: 24/01/2013"
        match = re.search(r'\bDCB\s*:\s*(\d{2}/\d{2}/\d{4})\b', block, flags=re.IGNORECASE)
        return self._parse_br_date(match.group(1)) if match else None

    def _extract_insured_birth_date(self, block: str):
        # Ex.: "Data de Nascimento do Empregado 27/08/1964"
        value = self._extract_date_after_label(
            block,
            r'Data\s+de\s+Nascimento\s+do\s+Empregado',
        )
        if value:
            return value

        # Fallback para formatos abreviados eventualmente extraídos do PDF.
        match = re.search(
            r'\bData\s+de\s+Nascimento\b\s*:?\s*(\d{2}/\d{2}/\d{4})\b',
            block,
            flags=re.IGNORECASE,
        )
        return self._parse_br_date(match.group(1)) if match else None

    @staticmethod
    def _extract_benefit_situation(block: str) -> str | None:
        # Formato comum: "Situação: Ativo"
        match_inline = re.search(r'\bSitua[cç][aã]o\s*:\s*([^\n]+)', block, flags=re.IGNORECASE)
        if match_inline:
            value = re.sub(r'\s+', ' ', match_inline.group(1)).strip(' :-\n\t')
            if value and not re.search(r'^(OL\s+|DIB|DCB|RMI|Esp[ée]cie)\b', value, flags=re.IGNORECASE):
                return value

        # Formato quebrado em linha: "Situação:" + próxima linha com valor
        match_multiline = re.search(
            r'\bSitua[cç][aã]o\s*:\s*\n\s*([^\n]+)',
            block,
            flags=re.IGNORECASE,
        )
        if match_multiline:
            value = re.sub(r'\s+', ' ', match_multiline.group(1)).strip(' :-\n\t')
            if value:
                return value

        return None

    def _extract_instance_decision(self, section: str) -> dict[str, str | None]:
        if not section:
            return {'status': None, 'justification': None, 'opinion': None}

        justification = self._extract_text_between_keywords(
            section,
            r'\bJustificativa\b',
            [r'\bStatus\b', r'\bParecer\b'],
        )

        # O status pode aparecer isolado após os rótulos "Status"/"Parecer" por quebra de layout.
        status_match = re.search(r'\b(Deferido|Indeferido)\b', section, flags=re.IGNORECASE)
        status = status_match.group(1).capitalize() if status_match else None

        opinion = self._extract_text_between_keywords(section, r'\bParecer\b', [])
        if opinion:
            opinion = re.sub(r'^(Status\s*)?(Deferido|Indeferido)\b\s*', '', opinion, flags=re.IGNORECASE).strip()
            opinion = opinion or None

        return {
            'status': status,
            'justification': justification,
            'opinion': opinion,
        }

    def _extract_instance_sections(self, block: str) -> tuple[str | None, str | None]:
        first_section = None
        second_section = None

        first_match = re.search(r'Administrativo\s*1\s*[ªa]\s*inst[âa]ncia', block, flags=re.IGNORECASE)
        second_match = re.search(r'Administrativo\s*2\s*[ªa]\s*inst[âa]ncia', block, flags=re.IGNORECASE)
        end_match = re.search(
            r'\bNB\s*:|Informa[cç][oõ]es\s+de\s+Revis[aã]o\s+de\s+Benef[ií]cio|Dados\s+do\s+Benef[ií]cio',
            block,
            flags=re.IGNORECASE,
        )

        if first_match:
            first_start = first_match.end()
            first_end = second_match.start() if second_match else (end_match.start() if end_match else len(block))
            first_section = block[first_start:first_end].strip() or None

        if second_match:
            second_start = second_match.end()
            second_end = end_match.start() if end_match and end_match.start() > second_start else len(block)
            second_section = block[second_start:second_end].strip() or None

        return first_section, second_section

    @staticmethod
    def _build_decision_summary(parsed: dict) -> str | None:
        chunks: list[str] = []

        for label, prefix in [
            ('first_instance', '1a instancia administrativa'),
            ('second_instance', '2a instancia administrativa'),
        ]:
            status = parsed.get(f'{label}_status')
            justification = parsed.get(f'{label}_justification')
            opinion = parsed.get(f'{label}_opinion')

            if not any([status, justification, opinion]):
                continue

            parts = [f'{prefix}:']
            if status:
                parts.append(f'status={status}')
            if justification:
                parts.append(f'justificativa={justification}')
            if opinion:
                parts.append(f'parecer={opinion}')
            chunks.append(' | '.join(parts))

        if not chunks:
            return None

        return '[DECISOES_ADMIN_FAP] ' + ' || '.join(chunks)

    def parse_block(self, block: str) -> dict | None:
        """Faz parsing de um bloco de benefício."""
        if not block or not block.strip():
            return None

        result: dict[str, object | None] = {}

        # número do benefício
        match = re.search(r'^\s*[:\-]?\s*(\d{8,})', block, flags=re.IGNORECASE)
        if not match:
            return None

        result['benefit_number'] = match.group(1).strip()

        # espécie do benefício: aceita layout em linha e em seção "Dados do Benefício".
        result['benefit_type'] = self._extract_benefit_type(block)

        # NIT do empregado
        nit_match = re.search(r'NIT do Empregado\s+(\d{8,20})', block, flags=re.IGNORECASE)
        result['insured_nit'] = nit_match.group(1).strip() if nit_match else None

        # Datas principais do benefício
        result['benefit_start_date'] = self._extract_dib(block)
        result['benefit_end_date'] = self._extract_dcb(block)
        result['insured_date_of_birth'] = self._extract_insured_birth_date(block)

        # situação do benefício (ex.: Ativo) extraída do trecho NB/CONREV
        result['benefit_situation'] = self._extract_benefit_situation(block)

        # decisões administrativas por instância
        first_section, second_section = self._extract_instance_sections(block)
        first_decision = self._extract_instance_decision(first_section or '')
        second_decision = self._extract_instance_decision(second_section or '')

        result['first_instance_status'] = first_decision.get('status')
        result['first_instance_justification'] = first_decision.get('justification')
        result['first_instance_opinion'] = first_decision.get('opinion')

        result['second_instance_status'] = second_decision.get('status')
        result['second_instance_justification'] = second_decision.get('justification')
        result['second_instance_opinion'] = second_decision.get('opinion')

        # status consolidado prioriza 2a instância, depois 1a.
        result['raw_status'] = (
            result['second_instance_status']
            or result['first_instance_status']
            or None
        )

        # mantém compatibilidade com colunas atuais: prioriza 2a instância e fallback para 1a.
        result['justification'] = (
            result['second_instance_justification']
            or result['first_instance_justification']
            or self.extract_between(block, 'Justificativa', 'Status')
        )
        result['opinion'] = (
            result['second_instance_opinion']
            or result['first_instance_opinion']
            or self.extract_between(block, 'Parecer')
        )

        # resumo textual para preservar decisões por instância nas colunas existentes.
        result['decisions_summary'] = self._build_decision_summary(result)

        return result

    def parse_beneficios_from_markdown(self, markdown_content: str) -> list[dict]:
        """Função principal para extrair benefícios do markdown."""
        text = self.normalize_markdown(markdown_content)
        blocks = self.split_blocks(text)

        results: list[dict] = []
        for block in blocks:
            parsed = self.parse_block(block)
            if parsed:
                results.append(parsed)
        return results

    @staticmethod
    def _map_status(raw_status: str | None) -> str:
        if not raw_status:
            return 'pending'

        normalized = raw_status.strip().lower()
        if normalized == 'deferido':
            return 'approved'
        if normalized == 'indeferido':
            return 'rejected'
        return 'pending'

    def _upsert_benefits_from_report(
        self,
        report: FapContestationJudgmentReport,
        extracted_benefits: list[dict],
        metadata,
    ) -> int:
        imported_count = 0

        if not extracted_benefits:
            return 0

        employer_client: Client | None = None
        employer_company_data: dict | None = None
        employer_cnpj_formatted: str | None = None

        if metadata is not None and getattr(metadata, 'establishment_cnpj', None):
            employer_client, employer_company_data, employer_cnpj_formatted = self._upsert_client_from_cnpj(
                law_firm_id=report.law_firm_id,
                cnpj_raw=metadata.establishment_cnpj,
            )

        transmission_dt = self._parse_br_datetime(
            getattr(metadata, 'transmission_datetime', None) if metadata is not None else None
        )

        for item in extracted_benefits:
            benefit_number = str(item.get('benefit_number') or '').strip()
            if not benefit_number:
                continue

            is_new_benefit = False
            benefit = Benefit.query.filter_by(
                law_firm_id=report.law_firm_id,
                benefit_number=benefit_number,
            ).first()

            if benefit is None:
                is_new_benefit = True
                benefit = Benefit(
                    law_firm_id=report.law_firm_id,
                    benefit_number=benefit_number,
                )
                db.session.add(benefit)

            db.session.flush()

            benefit.benefit_type = item.get('benefit_type') or benefit.benefit_type
            benefit.insured_nit = item.get('insured_nit') or benefit.insured_nit
            benefit.benefit_start_date = item.get('benefit_start_date') or benefit.benefit_start_date
            benefit.benefit_end_date = item.get('benefit_end_date') or benefit.benefit_end_date
            benefit.insured_date_of_birth = item.get('insured_date_of_birth') or benefit.insured_date_of_birth

            benefit.first_instance_status = item.get('first_instance_status')
            benefit.first_instance_justification = item.get('first_instance_justification')
            benefit.first_instance_opinion = item.get('first_instance_opinion')

            benefit.second_instance_status = item.get('second_instance_status')
            benefit.second_instance_justification = item.get('second_instance_justification')
            benefit.second_instance_opinion = item.get('second_instance_opinion')

            benefit.status = self._map_status(item.get('raw_status'))
            benefit.justification = item.get('justification')
            benefit.opinion = item.get('opinion')

            if employer_client is not None:
                benefit.client = employer_client

            # Enriquecimento com metadados da primeira página
            if metadata is not None:
                if getattr(metadata, 'establishment_cnpj', None):
                    benefit.employer_cnpj = employer_cnpj_formatted or metadata.establishment_cnpj
                if getattr(metadata, 'validity_year', None):
                    benefit.fap_vigencia_years = str(metadata.validity_year)

            # Enriquecimento adicional com OpenCNPJ para campos existentes de empresa no benefício
            if employer_company_data is not None:
                benefit.employer_name = employer_company_data.get('razao_social') or benefit.employer_name
                benefit.employer_cnpj = employer_cnpj_formatted or benefit.employer_cnpj

            # Rastreabilidade de origem
            source_note = f'Relatório FAP importado (id={report.id}, arquivo={report.original_filename})'
            decisions_summary = item.get('decisions_summary')
            if benefit.notes:
                if source_note not in benefit.notes:
                    benefit.notes = f'{benefit.notes}\n{source_note}'
                if decisions_summary and decisions_summary not in benefit.notes:
                    benefit.notes = f'{benefit.notes}\n{decisions_summary}'
            else:
                benefit.notes = source_note
                if decisions_summary:
                    benefit.notes = f'{benefit.notes}\n{decisions_summary}'

            benefit.updated_at = datetime.utcnow()

            history = BenefitFapSourceHistory.query.filter_by(
                benefit_id=benefit.id,
                report_id=report.id,
            ).first()

            if history is None:
                history = BenefitFapSourceHistory(
                    law_firm_id=report.law_firm_id,
                    benefit_id=benefit.id,
                    report_id=report.id,
                )
                db.session.add(history)

            history.knowledge_base_id = report.knowledge_base_id
            history.action = 'added' if is_new_benefit else 'updated'
            history.transmission_datetime = transmission_dt
            history.updated_at = datetime.utcnow()

            imported_count += 1

        return imported_count

    def process_pending_reports(
        self,
        batch_size: int = 10,
        report_id: int | None = None,
        include_errors: bool = False,
    ) -> int:
        """Processa relatórios pendentes, extraindo benefícios do markdown e importando na tabela central."""
        with self.app.app_context():
            query = FapContestationJudgmentReport.query

            if report_id:
                query = query.filter(FapContestationJudgmentReport.id == report_id)
            else:
                statuses = ['pending']
                if include_errors:
                    statuses.append('error')
                query = query.filter(FapContestationJudgmentReport.status.in_(statuses))

            reports = (
                query.order_by(FapContestationJudgmentReport.uploaded_at.asc())
                .limit(max(1, int(batch_size)))
                .all()
            )

            if not reports:
                print('Nenhum relatório pendente para processamento.')
                return 0

            processed_reports = 0

            for report in reports:
                try:
                    #report.status = 'processing'
                    report.error_message = None
                    report.updated_at = datetime.utcnow()
                    db.session.commit()

                    markdown_content = self.convert_report_to_markdown_with_markitdown(report.file_path)
                    metadata = self.metadata_agent.extract_from_first_page(markdown_content)
                    extracted_benefits = self.parse_beneficios_from_markdown(markdown_content)

                    print(
                        f'Relatório #{report.id}: {len(extracted_benefits)} benefício(s) identificado(s) no markdown.'
                    )

                    imported_count = self._upsert_benefits_from_report(report, extracted_benefits, metadata)

                    report.imported_benefits_count = imported_count
                    report.status = 'completed'
                    report.processed_at = datetime.utcnow()
                    report.updated_at = datetime.utcnow()
                    db.session.commit()

                    processed_reports += 1
                    print(
                        f'Relatório #{report.id} processado com sucesso. '
                        f'Benefícios importados/atualizados: {imported_count}'
                    )
                except Exception as exc:
                    db.session.rollback()
                    report.status = 'error'
                    report.error_message = str(exc)
                    report.updated_at = datetime.utcnow()
                    db.session.commit()
                    print(f'Erro ao processar relatório #{report.id}: {exc}')

            return processed_reports
