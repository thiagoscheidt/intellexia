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
from app.models import Benefit, FapContestationJudgmentReport, db


class FapContestationJudgmentReportService:
    """Service para gerenciamento e processamento de relatórios de julgamento de contestação do FAP.

    Implementa parsing de markdown e importação dos benefícios para a tabela central `benefits`.
    """

    def __init__(self, flask_app):
        self.app = flask_app
        self.metadata_agent = FapContestationJudgmentMetadataAgent()

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

    def parse_block(self, block: str) -> dict | None:
        """Faz parsing de um bloco de benefício."""
        if not block or not block.strip():
            return None

        result: dict[str, str | None] = {}

        # número + espécie do benefício
        match = re.search(
            r'^\s*[:\-]?\s*(\d{8,}).{0,120}?Esp[ée]cie do Benef[ií]cio\s+([A-Za-z0-9]+)',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None

        result['benefit_number'] = match.group(1).strip()
        result['benefit_type'] = match.group(2).strip().upper()

        # status
        status_match = re.search(r'Status\s+(Deferido|Indeferido)', block, flags=re.IGNORECASE)
        result['raw_status'] = status_match.group(1).strip() if status_match else None

        # justificativa
        result['justification'] = self.extract_between(block, 'Justificativa', 'Status')

        # parecer
        opinion = self.extract_between(block, 'Parecer')
        if opinion:
            opinion = re.split(r'\bN[uú]mero do Benef[ií]cio\b', opinion, flags=re.IGNORECASE)[0].strip()
        result['opinion'] = opinion

        return result

    def parse_beneficios_from_markdown(self, markdown_content: str) -> list[dict]:
        """Função principal para extrair benefícios do markdown."""
        text = self.normalize_markdown(markdown_content)
        blocks = self.split_blocks(text)
        print(blocks[0][:200] if blocks else 'Nenhum bloco encontrado para parsing.')

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

        for item in extracted_benefits:
            benefit_number = str(item.get('benefit_number') or '').strip()
            if not benefit_number:
                continue

            benefit = Benefit.query.filter_by(
                law_firm_id=report.law_firm_id,
                benefit_number=benefit_number,
            ).first()

            if benefit is None:
                benefit = Benefit(
                    law_firm_id=report.law_firm_id,
                    benefit_number=benefit_number,
                )
                db.session.add(benefit)

            benefit.benefit_type = item.get('benefit_type') or benefit.benefit_type
            benefit.status = self._map_status(item.get('raw_status'))
            benefit.justification = item.get('justification')
            benefit.opinion = item.get('opinion')

            # Enriquecimento com metadados da primeira página
            if metadata is not None:
                if getattr(metadata, 'establishment_cnpj', None):
                    benefit.employer_cnpj = metadata.establishment_cnpj
                if getattr(metadata, 'validity_year', None):
                    benefit.fap_vigencia_years = str(metadata.validity_year)

            # Rastreabilidade de origem
            source_note = f'Relatório FAP importado (id={report.id}, arquivo={report.original_filename})'
            if benefit.notes:
                if source_note not in benefit.notes:
                    benefit.notes = f'{benefit.notes}\n{source_note}'
            else:
                benefit.notes = source_note

            benefit.updated_at = datetime.utcnow()
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
                    report.status = 'processing'
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
