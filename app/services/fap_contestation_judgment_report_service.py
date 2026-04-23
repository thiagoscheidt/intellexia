from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import re
from time import perf_counter

from rich import print
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.agents.fap.fap_contestation_judgment_metadata_agent import (
    FapContestationJudgmentMetadataAgent,
)
from app.agents.fap.fap_contestation_classifier_agent import FAPContestationClassifierAgent
from app.models import (
    Benefit,
    BenefitFapSourceHistory,
    FapVigenciaCnpj,
    Client,
    FapContestationCat,
    FapContestationCatSourceHistory,
    FapContestationJudgmentReport,
    FapContestationPayrollMass,
    FapContestationPayrollMassSourceHistory,
    FapContestationEmploymentLink,
    FapContestationEmploymentLinkSourceHistory,
    FapContestationTurnoverRate,
    FapContestationTurnoverRateSourceHistory,
    db,
)
from app.services.open_cnpj_service import OpenCNPJService


class FapContestationJudgmentReportService:
    """Service para gerenciamento e processamento de relatórios de julgamento de contestação do FAP.

    Implementa parsing de markdown e importação dos benefícios para a tabela central `benefits`.
    """

    def __init__(self, flask_app):
        self.app = flask_app
        self.metadata_agent = FapContestationJudgmentMetadataAgent()
        self.classifier_agent = FAPContestationClassifierAgent()
        self.open_cnpj_service = OpenCNPJService()

    @staticmethod
    def _build_benefit_classification_text(benefit: Benefit) -> str:
        """Monta o texto base para classificação do benefício."""
        candidate_fields = [
            benefit.second_instance_justification,
            benefit.first_instance_justification,
            benefit.justification,
            benefit.second_instance_opinion,
            benefit.first_instance_opinion,
            benefit.opinion,
            benefit.notes,
        ]
        parts = [str(value).strip() for value in candidate_fields if value and str(value).strip()]
        return "\n\n".join(parts)

    def classify_benefits_contestation_topics(
        self,
        *,
        batch_size: int = 200,
        benefit_id: int | None = None,
        law_firm_id: int | None = None,
        force_reclassify: bool = False,
        parallel_workers: int = 1,
    ) -> dict[str, int]:
        """Classifica benefícios em lote e persiste o tópico de contestação FAP.

        Args:
            batch_size: Quantos benefícios processar antes de cada commit.
            benefit_id: Se informado, classifica apenas esse benefício.
            law_firm_id: Se informado, restringe ao escritório.
            force_reclassify: Se True, reclassifica mesmo os que já têm tópico.
            parallel_workers: Número de chamadas LLM simultâneas (default=1, sequencial).
        """
        with self.app.app_context():
            effective_batch_size = max(1, int(batch_size))
            effective_workers = max(1, int(parallel_workers))
            query = Benefit.query

            if benefit_id is not None:
                query = query.filter(Benefit.id == benefit_id)

            if law_firm_id is not None:
                query = query.filter(Benefit.law_firm_id == law_firm_id)

            if not force_reclassify:
                query = query.filter(
                    (Benefit.fap_contestation_topic.is_(None))
                    | (Benefit.fap_contestation_topic == '')
                )

            benefits = query.order_by(Benefit.id.asc()).all()
            if not benefits:
                print('Nenhum benefício elegível para classificação.')
                return {
                    'total': 0,
                    'classified': 0,
                    'errors': 0,
                    'updated': 0,
                }

            total = len(benefits)
            classified = 0
            errors = 0
            updated = 0

            # Extrai textos na thread principal para não passar objetos SQLAlchemy às threads.
            tasks = [
                (benefit, self._build_benefit_classification_text(benefit), benefit.law_firm_id)
                for benefit in benefits
            ]

            def _classify_text(text: str, benefit_law_firm_id: int | None) -> str:
                # Cada thread precisa do próprio app context — Flask-SQLAlchemy usa
                # sessões thread-local vinculadas ao contexto da aplicação.
                with self.app.app_context():
                    result = self.classifier_agent.classify(text, law_firm_id=benefit_law_firm_id)
                return str(result.get('topic') or '').strip() or 'OUTROS ARGUMENTOS'

            completed = 0
            with ThreadPoolExecutor(max_workers=effective_workers) as executor:
                future_to_benefit = {
                    executor.submit(_classify_text, text, benefit_law_firm_id): benefit
                    for benefit, text, benefit_law_firm_id in tasks
                }

                for future in as_completed(future_to_benefit):
                    benefit = future_to_benefit[future]
                    completed += 1

                    try:
                        topic = future.result()
                        if benefit.fap_contestation_topic != topic:
                            benefit.fap_contestation_topic = topic
                            benefit.updated_at = datetime.utcnow()
                            updated += 1
                        classified += 1
                    except Exception as exc:
                        errors += 1
                        print(f'Erro ao classificar benefício #{benefit.id}: {exc}')

                    if completed % effective_batch_size == 0:
                        try:
                            db.session.commit()
                        except Exception as commit_exc:
                            db.session.rollback()
                            print(f'Erro ao salvar lote na classificação de benefícios: {commit_exc}')
                            raise

                        print(
                            f'Classificação de benefícios: {completed}/{total} '
                            f'(classificados={classified}, atualizados={updated}, erros={errors})'
                        )

            try:
                db.session.commit()
            except Exception as commit_exc:
                db.session.rollback()
                print(f'Erro ao salvar classificação final de benefícios: {commit_exc}')
                raise

            print(
                'Classificação concluída: '
                f'total={total}, classificados={classified}, atualizados={updated}, erros={errors}'
            )

            return {
                'total': total,
                'classified': classified,
                'errors': errors,
                'updated': updated,
            }

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

        client = self._find_client_by_cnpj(law_firm_id, cnpj_digits)
        if client is not None:
            return client, None, cnpj_formatado

        # Cliente não encontrado na base: consulta a API para obter os dados cadastrais.
        lookup_result = self.open_cnpj_service.lookup_company(cnpj_formatado)
        company_data = lookup_result.get('data') if lookup_result.get('success') else None

        if not company_data:
            return None, None, cnpj_formatado

        client = Client(
            law_firm_id=law_firm_id,
            name=company_data.get('razao_social') or f'Empresa {cnpj_formatado}',
            cnpj=cnpj_formatado,
        )
        db.session.add(client)

        # Preenche campos cadastrais com os dados retornados pela API.
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

    def _upsert_benefit_vigencia_cnpj(
        self,
        law_firm_id: int,
        employer_cnpj_raw: str | None,
        vigencia_year_raw: str | int | None,
    ) -> FapVigenciaCnpj | None:
        employer_cnpj_digits = self._normalize_cnpj(employer_cnpj_raw)
        if len(employer_cnpj_digits) != 14:
            return None

        vigencia_year = str(vigencia_year_raw or '').strip()
        if not vigencia_year:
            return None

        vigencia_now = datetime.utcnow()
        vigencia_insert_stmt = mysql_insert(FapVigenciaCnpj.__table__).values(
            law_firm_id=law_firm_id,
            employer_cnpj=employer_cnpj_digits,
            vigencia_year=vigencia_year,
            created_at=vigencia_now,
            updated_at=vigencia_now,
        )
        vigencia_upsert_stmt = vigencia_insert_stmt.on_duplicate_key_update(
            updated_at=vigencia_insert_stmt.inserted.updated_at,
        )
        db.session.execute(vigencia_upsert_stmt)

        with db.session.no_autoflush:
            record = FapVigenciaCnpj.query.filter_by(
                law_firm_id=law_firm_id,
                employer_cnpj=employer_cnpj_digits,
                vigencia_year=vigencia_year,
            ).first()

        return record

    def _extract_typed_blocks_with_pdfplumber(self, file_path: str | Path) -> list[tuple[str, str]]:
        """Extrai texto do PDF uma única vez e retorna blocos tipados."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f'Arquivo não encontrado: {path}')

        if path.suffix.lower() != '.pdf':
            raise ValueError('O método com pdfplumber aceita apenas arquivos PDF.')

        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError('pdfplumber não está instalado no ambiente atual.') from exc

        def normalize_page_text(page_text: str) -> str:
            text = page_text.replace('\r\n', '\n').replace('\r', '\n')
            text = re.sub(r'[ \t]+', ' ', text)
            text = re.sub(r'\n{3,}', '\n\n', text)
            return text.strip()

        page_texts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(
                    x_tolerance=2,
                    y_tolerance=3,
                    layout=False,
                    use_text_flow=True,
                )
                if page_text:
                    page_texts.append(normalize_page_text(page_text))

        if not page_texts:
            raise ValueError('pdfplumber não retornou texto para o arquivo informado.')

        text = self.normalize_markdown('\n\n'.join(page_texts))
        return self._split_all_blocks(text)

    def extract_all_sections_with_pdfplumber(self, file_path: str | Path) -> tuple[dict[str, list[dict]], dict[str, float]]:
        """Extrai e faz parsing de todas as seções em uma única leitura do PDF."""
        typed_blocks = self._extract_typed_blocks_with_pdfplumber(file_path)

        extracted_sections: dict[str, list[dict]] = {
            'benefits': [],
            'cats': [],
            'payroll_masses': [],
            'employment_links': [],
            'turnover_rates': [],
        }
        parse_timings: dict[str, float] = {
            'benefits': 0.0,
            'cats': 0.0,
            'payroll_masses': 0.0,
            'employment_links': 0.0,
            'turnover_rates': 0.0,
        }

        for block_type, block in typed_blocks:
            if not block or not block.strip():
                continue

            started_at = perf_counter()
            if block_type == 'benefit':
                parsed = self.parse_block(block)
                parse_timings['benefits'] += perf_counter() - started_at
                if parsed:
                    extracted_sections['benefits'].append(parsed)
                continue

            if block_type == 'cat':
                parsed = self.parse_cat_block(block)
                parse_timings['cats'] += perf_counter() - started_at
                if parsed:
                    extracted_sections['cats'].append(parsed)
                continue

            if block_type == 'payroll_mass':
                parsed = self.parse_payroll_mass_block(block)
                parse_timings['payroll_masses'] += perf_counter() - started_at
                if parsed:
                    extracted_sections['payroll_masses'].append(parsed)
                continue

            if block_type == 'employment_link':
                parsed = self.parse_employment_link_block(block)
                parse_timings['employment_links'] += perf_counter() - started_at
                if parsed:
                    extracted_sections['employment_links'].append(parsed)
                continue

            if block_type == 'turnover_rate':
                parsed = self.parse_turnover_rate_block(block)
                parse_timings['turnover_rates'] += perf_counter() - started_at
                if parsed:
                    extracted_sections['turnover_rates'].append(parsed)

        return extracted_sections, parse_timings

    def extract_benefits_with_pdfplumber(self, file_path: str | Path) -> list[dict]:
        """Extrai benefícios diretamente do PDF com pdfplumber, sem integrar ao fluxo principal.

        O método preserva a estrutura textual do documento para facilitar a separação
        por blocos de benefício em PDFs que parecem tabela, mas na prática são texto
        posicionado com linhas horizontais.

        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f'Arquivo não encontrado: {path}')

        if path.suffix.lower() != '.pdf':
            raise ValueError('O método com pdfplumber aceita apenas arquivos PDF.')

        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError('pdfplumber não está instalado no ambiente atual.') from exc

        def normalize_page_text(page_text: str) -> str:
            text = page_text.replace('\r\n', '\n').replace('\r', '\n')
            text = re.sub(r'[ \t]+', ' ', text)
            text = re.sub(r'\n{3,}', '\n\n', text)
            return text.strip()

        page_texts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(
                    x_tolerance=2,
                    y_tolerance=3,
                    layout=False,
                    use_text_flow=True,
                )
                if page_text:
                    page_texts.append(normalize_page_text(page_text))

        if not page_texts:
            raise ValueError('pdfplumber não retornou texto para o arquivo informado.')

        text = self.normalize_markdown('\n\n'.join(page_texts))
        typed_blocks = self._split_all_blocks(text)

        benefits: list[dict] = []
        for block_type, block in typed_blocks:
            if not block or not block.strip():
                continue
            if block_type == 'cat':
                continue
            parsed = self.parse_block(block)
            if parsed:
                benefits.append(parsed)

        return benefits

    def extract_cats_with_pdfplumber(self, file_path: str | Path) -> list[dict]:
        """Extrai CATs diretamente do PDF com pdfplumber."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f'Arquivo não encontrado: {path}')

        if path.suffix.lower() != '.pdf':
            raise ValueError('O método com pdfplumber aceita apenas arquivos PDF.')

        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError('pdfplumber não está instalado no ambiente atual.') from exc

        def normalize_page_text(page_text: str) -> str:
            text = page_text.replace('\r\n', '\n').replace('\r', '\n')
            text = re.sub(r'[ \t]+', ' ', text)
            text = re.sub(r'\n{3,}', '\n\n', text)
            return text.strip()

        page_texts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(
                    x_tolerance=2,
                    y_tolerance=3,
                    layout=False,
                    use_text_flow=True,
                )
                if page_text:
                    page_texts.append(normalize_page_text(page_text))

        if not page_texts:
            return []

        text = self.normalize_markdown('\n\n'.join(page_texts))
        typed_blocks = self._split_all_blocks(text)

        cats: list[dict] = []
        for block_type, block in typed_blocks:
            if not block or not block.strip():
                continue
            if block_type != 'cat':
                continue
            parsed = self.parse_cat_block(block)
            if parsed:
                cats.append(parsed)

        return cats

    def extract_payroll_masses_with_pdfplumber(self, file_path: str | Path) -> list[dict]:
        """Extrai entradas de Massa Salarial diretamente do PDF com pdfplumber."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f'Arquivo não encontrado: {path}')

        if path.suffix.lower() != '.pdf':
            raise ValueError('O método com pdfplumber aceita apenas arquivos PDF.')

        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError('pdfplumber não está instalado no ambiente atual.') from exc

        def normalize_page_text(page_text: str) -> str:
            text = page_text.replace('\r\n', '\n').replace('\r', '\n')
            text = re.sub(r'[ \t]+', ' ', text)
            text = re.sub(r'\n{3,}', '\n\n', text)
            return text.strip()

        page_texts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(
                    x_tolerance=2,
                    y_tolerance=3,
                    layout=False,
                    use_text_flow=True,
                )
                if page_text:
                    page_texts.append(normalize_page_text(page_text))

        if not page_texts:
            return []

        text = self.normalize_markdown('\n\n'.join(page_texts))
        typed_blocks = self._split_all_blocks(text)

        payroll_masses: list[dict] = []
        for block_type, block in typed_blocks:
            if not block or not block.strip():
                continue
            if block_type != 'payroll_mass':
                continue
            parsed = self.parse_payroll_mass_block(block)
            if parsed:
                payroll_masses.append(parsed)

        return payroll_masses

    def extract_employment_links_with_pdfplumber(self, file_path: str | Path) -> list[dict]:
        """Extrai entradas de Número Médio de Vínculos diretamente do PDF com pdfplumber."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f'Arquivo não encontrado: {path}')

        if path.suffix.lower() != '.pdf':
            raise ValueError('O método com pdfplumber aceita apenas arquivos PDF.')

        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError('pdfplumber não está instalado no ambiente atual.') from exc

        def normalize_page_text(page_text: str) -> str:
            text = page_text.replace('\r\n', '\n').replace('\r', '\n')
            text = re.sub(r'[ \t]+', ' ', text)
            text = re.sub(r'\n{3,}', '\n\n', text)
            return text.strip()

        page_texts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(
                    x_tolerance=2,
                    y_tolerance=3,
                    layout=False,
                    use_text_flow=True,
                )
                if page_text:
                    page_texts.append(normalize_page_text(page_text))

        if not page_texts:
            return []

        text = self.normalize_markdown('\n\n'.join(page_texts))
        typed_blocks = self._split_all_blocks(text)

        employment_links: list[dict] = []
        for block_type, block in typed_blocks:
            if not block or not block.strip():
                continue
            if block_type != 'employment_link':
                continue
            parsed = self.parse_employment_link_block(block)
            if parsed:
                employment_links.append(parsed)

        return employment_links

    def extract_turnover_rates_with_pdfplumber(self, file_path: str | Path) -> list[dict]:
        """Extrai entradas de Taxa Média de Rotatividade diretamente do PDF com pdfplumber."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f'Arquivo não encontrado: {path}')

        if path.suffix.lower() != '.pdf':
            raise ValueError('O método com pdfplumber aceita apenas arquivos PDF.')

        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError('pdfplumber não está instalado no ambiente atual.') from exc

        def normalize_page_text(page_text: str) -> str:
            text = page_text.replace('\r\n', '\n').replace('\r', '\n')
            text = re.sub(r'[ \t]+', ' ', text)
            text = re.sub(r'\n{3,}', '\n\n', text)
            return text.strip()

        page_texts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(
                    x_tolerance=2,
                    y_tolerance=3,
                    layout=False,
                    use_text_flow=True,
                )
                if page_text:
                    page_texts.append(normalize_page_text(page_text))

        if not page_texts:
            return []

        text = self.normalize_markdown('\n\n'.join(page_texts))
        typed_blocks = self._split_all_blocks(text)

        turnover_rates: list[dict] = []
        for block_type, block in typed_blocks:
            if not block or not block.strip():
                continue
            if block_type != 'turnover_rate':
                continue
            parsed = self.parse_turnover_rate_block(block)
            if parsed:
                turnover_rates.append(parsed)

        return turnover_rates

    def extract_metadata_from_first_page_with_pdfplumber(self, file_path: str | Path):
        """Extrai metadados da primeira página via pdfplumber.

        Método isolado para comparar com o caminho atual baseado em markdown.
        Não altera o fluxo principal de processamento.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f'Arquivo não encontrado: {path}')

        if path.suffix.lower() != '.pdf':
            raise ValueError('O método com pdfplumber aceita apenas arquivos PDF.')

        try:
            import pdfplumber
        except ImportError as exc:
            raise ImportError('pdfplumber não está instalado no ambiente atual.') from exc

        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                raise ValueError('PDF sem páginas para extração de metadados.')

            first_page_text = pdf.pages[0].extract_text(
                x_tolerance=2,
                y_tolerance=3,
                layout=False,
                use_text_flow=True,
            )

        if not first_page_text or not first_page_text.strip():
            raise ValueError('pdfplumber não retornou texto da primeira página.')

        normalized_first_page = first_page_text.replace('\r\n', '\n').replace('\r', '\n')
        normalized_first_page = re.sub(r'[ \t]+', ' ', normalized_first_page)
        normalized_first_page = re.sub(r'\n{3,}', '\n\n', normalized_first_page)
        normalized_first_page = self.normalize_markdown(normalized_first_page)

        return self.metadata_agent.extract_from_first_page(normalized_first_page)

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
    def _split_all_blocks(text: str) -> list[tuple[str, str]]:
        """Divide o documento em blocos tipados (benefit, cat ou payroll_mass).

        Estratégia em três passos:
        1. Localiza a seção CAT pelo cabeçalho "Comunicação de Acidente de Trabalho (CAT)"
           e divide seu conteúdo por "Número da CAT" para obter cada CAT individualmente.
        2. Localiza a seção Massa Salarial pelo cabeçalho "Massa Salarial" e divide seu
           conteúdo por "CNPJ" + "Competência" para obter cada entrada individualmente.
        3. O restante do texto (antes/depois das seções especiais) é dividido por
           "Número do Benefício" — comportamento original inalterado.

        Retorna lista de tuplas (tipo, conteúdo) onde tipo é 'benefit', 'cat' ou 'payroll_mass'.
        """
        blocks: list[tuple[str, str]] = []

        # --- Passo 1: seção CAT ---
        # Busca pelo cabeçalho da seção CAT. Valida que é de fato o cabeçalho
        # (e não uma menção dentro de uma justificativa) exigindo que "Número da CAT"
        # apareça nos próximos 300 caracteres após o match.
        _cat_candidate = re.search(
            r'Comunica[cç][aã]o\s+de\s+Acidente\s+de\s+Trabalho\s*\(CAT\)',
            text,
            flags=re.IGNORECASE,
        )
        if _cat_candidate and re.search(
            r'\bN[uú]mero\s+da\s+CAT\b',
            text[_cat_candidate.end():_cat_candidate.end() + 300],
            flags=re.IGNORECASE,
        ):
            cat_section_match = _cat_candidate
        else:
            cat_section_match = None

        if cat_section_match:
            before_cat_section = text[:cat_section_match.start()]
            after_cat_header = text[cat_section_match.end():]

            first_benefit_match = re.search(
                r'\bN[uú]mero\s+do\s+Benef[ií]cio\b', after_cat_header, flags=re.IGNORECASE
            )
            if first_benefit_match:
                cat_section_content = after_cat_header[:first_benefit_match.start()]
                benefit_section_text = before_cat_section + after_cat_header[first_benefit_match.start():]
            else:
                cat_section_content = after_cat_header
                benefit_section_text = before_cat_section

            cat_parts = re.split(r'\bN[uú]mero\s+da\s+CAT\b', cat_section_content, flags=re.IGNORECASE)
            for cat_content in cat_parts[1:]:
                if cat_content.strip():
                    blocks.append(('cat', 'Número da CAT ' + cat_content))
        else:
            benefit_section_text = text

        # --- Passo 2: seção Massa Salarial ---
        payroll_section_match = re.search(
            r'\bMassa\s+Salarial\b',
            benefit_section_text,
            flags=re.IGNORECASE,
        )

        if payroll_section_match:
            before_payroll = benefit_section_text[:payroll_section_match.start()]
            after_payroll_header = benefit_section_text[payroll_section_match.end():]

            # The payroll mass section ends at the next known top-level section header.
            # Recognised terminators:
            #   - "Número do Benefício"  (more benefits follow)
            #   - "Número Médio de Vínculos"  (different contestation type)
            #   - "Comunicação de Acidente de Trabalho" (CAT section, unlikely but safe)
            next_section_match = re.search(
                r'\bN[uú]mero\s+do\s+Benef[ií]cio\b'
                r'|\bN[uú]mero\s+M[eé]dio\s+de\s+V[ií]nculos\b'
                r'|\bTaxa\s+M[eé]dia\s+de\s+Rotatividade\b'
                r'|\bComunica[cç][aã]o\s+de\s+Acidente\s+de\s+Trabalho\b',
                after_payroll_header,
                flags=re.IGNORECASE,
            )
            if next_section_match:
                payroll_section_content = after_payroll_header[:next_section_match.start()]
                benefit_section_text = before_payroll + after_payroll_header[next_section_match.start():]
            else:
                payroll_section_content = after_payroll_header
                benefit_section_text = before_payroll

            # Split payroll section into individual entries by "CNPJ XX Competência"
            payroll_parts = re.split(
                r'(?=CNPJ\s+[\d./\-]+\s+Compet[êe]ncia\b)',
                payroll_section_content,
                flags=re.IGNORECASE,
            )
            for payroll_content in payroll_parts:
                if payroll_content.strip() and re.search(r'CNPJ\s+[\d./\-]+', payroll_content, flags=re.IGNORECASE):
                    blocks.append(('payroll_mass', payroll_content))

        # --- Passo 2.5: seção Número Médio de Vínculos ---
        employment_link_section_match = re.search(
            r'\bN[uú]mero\s+M[eé]dio\s+de\s+V[ií]nculos\b',
            benefit_section_text,
            flags=re.IGNORECASE,
        )

        if employment_link_section_match:
            before_employment_links = benefit_section_text[:employment_link_section_match.start()]
            after_employment_links_header = benefit_section_text[employment_link_section_match.end():]

            # The employment link section ends at the next known top-level section header.
            next_el_section_match = re.search(
                r'\bN[uú]mero\s+do\s+Benef[ií]cio\b'
                r'|\bMassa\s+Salarial\b'
                r'|\bTaxa\s+M[eé]dia\s+de\s+Rotatividade\b'
                r'|\bComunica[cç][aã]o\s+de\s+Acidente\s+de\s+Trabalho\b',
                after_employment_links_header,
                flags=re.IGNORECASE,
            )
            if next_el_section_match:
                employment_link_section_content = after_employment_links_header[:next_el_section_match.start()]
                benefit_section_text = before_employment_links + after_employment_links_header[next_el_section_match.start():]
            else:
                employment_link_section_content = after_employment_links_header
                benefit_section_text = before_employment_links

            # Split employment link section into individual entries by "CNPJ XX Competência"
            employment_link_parts = re.split(
                r'(?=CNPJ\s+[\d./\-]+\s+Compet[êe]ncia\b)',
                employment_link_section_content,
                flags=re.IGNORECASE,
            )
            for el_content in employment_link_parts:
                if el_content.strip() and re.search(r'CNPJ\s+[\d./\-]+', el_content, flags=re.IGNORECASE):
                    blocks.append(('employment_link', el_content))

        # --- Passo 2.75: seção Taxa Média de Rotatividade ---
        turnover_section_match = re.search(
            r'\bTaxa\s+M[eé]dia\s+de\s+Rotatividade\b',
            benefit_section_text,
            flags=re.IGNORECASE,
        )

        if turnover_section_match:
            before_turnover = benefit_section_text[:turnover_section_match.start()]
            after_turnover_header = benefit_section_text[turnover_section_match.end():]

            next_tr_section_match = re.search(
                r'\bN[uú]mero\s+do\s+Benef[ií]cio\b'
                r'|\bMassa\s+Salarial\b'
                r'|\bN[uú]mero\s+M[eé]dio\s+de\s+V[ií]nculos\b'
                r'|\bComunica[cç][aã]o\s+de\s+Acidente\s+de\s+Trabalho\b',
                after_turnover_header,
                flags=re.IGNORECASE,
            )
            if next_tr_section_match:
                turnover_section_content = after_turnover_header[:next_tr_section_match.start()]
                benefit_section_text = before_turnover + after_turnover_header[next_tr_section_match.start():]
            else:
                turnover_section_content = after_turnover_header
                benefit_section_text = before_turnover

            turnover_parts = re.split(
                r'(?=CNPJ\s+[\d./\-]+\s+Ano\s+\d{4}\b)',
                turnover_section_content,
                flags=re.IGNORECASE,
            )
            for tr_content in turnover_parts:
                if tr_content.strip() and re.search(r'CNPJ\s+[\d./\-]+', tr_content, flags=re.IGNORECASE):
                    blocks.append(('turnover_rate', tr_content))

        # --- Passo 3: blocos de benefícios (lógica original preservada) ---
        benefit_parts = re.split(r'\bN[uú]mero\s+do\s+Benef[ií]cio\b', benefit_section_text, flags=re.IGNORECASE)
        for benefit_content in benefit_parts[1:]:
            if benefit_content.strip():
                blocks.append(('benefit', benefit_content))

        return blocks

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
    def _extract_status_text(section: str) -> str | None:
        """Extrai o texto bruto do campo Status sem confundir ocorrências em frases livres."""
        if not section:
            return None

        status_keyword_pattern = r'(?:Indeferido|Deferido|Analyzing|Pendente|Pending)'

        explicit_label_match = re.search(
            rf'\bStatus\b\s*(?:[:\-]\s*|\s+|\n\s*)(?P<value>{status_keyword_pattern}[^\n\r]*)',
            section,
            flags=re.IGNORECASE,
        )
        if explicit_label_match:
            value = re.sub(r'\s+', ' ', explicit_label_match.group('value')).strip(' :-\n\t')
            return value or None

        return None

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

        # Fallback para layout em que os rótulos ficam em cima e os valores
        # aparecem somente no trecho inicial da 1a instância.
        fallback_value = self._extract_benefit_type_from_first_instance_header(block)
        if fallback_value:
            return fallback_value

        # Fallback final: captura qualquer token BXX no bloco quando os layouts
        # esperados não forem reconhecidos.
        any_benefit_type_match = re.search(r'\bB(\d{2})\b', block, flags=re.IGNORECASE)
        if any_benefit_type_match:
            return f"B{any_benefit_type_match.group(1)}"
        return None

    def _extract_first_instance_header_lines(self, block: str) -> list[str]:
        first_section, _ = self._extract_instance_sections(block)
        if not first_section:
            return []

        # Limita ao cabeçalho da 1a instância (antes de justificativa/parecer/status).
        cut_match = re.search(r'\bJustificativa\b|\bStatus\b|\bParecer\b', first_section, flags=re.IGNORECASE)
        header_chunk = first_section[:cut_match.start()] if cut_match else first_section

        return [line.strip() for line in header_chunk.split('\n') if line.strip()]

    @staticmethod
    def _extract_pre_first_instance_label_lines(block: str) -> list[str]:
        first_match = re.search(r'Administrativo\s*1\s*[ªa]\s*inst[âa]ncia', block, flags=re.IGNORECASE)
        if not first_match:
            return []

        labels_chunk = block[:first_match.start()]
        lines = [line.strip() for line in labels_chunk.split('\n') if line.strip()]

        # Remove linha inicial com NB isolado quando presente.
        if lines and re.fullmatch(r'\d{8,}', lines[0]):
            lines = lines[1:]

        return lines

    def _extract_shifted_layout_value_by_label(
        self,
        block: str,
        label_pattern: str,
        value_pattern: str | None = None,
    ) -> str | None:
        label_lines = self._extract_pre_first_instance_label_lines(block)
        value_lines = self._extract_first_instance_header_lines(block)
        if not label_lines or not value_lines:
            return None

        for idx, label_line in enumerate(label_lines):
            if not re.search(label_pattern, label_line, flags=re.IGNORECASE):
                continue
            if idx >= len(value_lines):
                continue

            candidate = value_lines[idx].strip()
            if not candidate:
                continue
            if value_pattern and not re.fullmatch(value_pattern, candidate, flags=re.IGNORECASE):
                continue

            return candidate

        return None

    def _extract_benefit_type_from_first_instance_header(self, block: str) -> str | None:
        mapped_value = self._extract_shifted_layout_value_by_label(
            block,
            r'Esp[ée]cie\s+do\s+Benef[ií]cio',
            r'(?:B)?\d{2}',
        )
        if mapped_value:
            normalized = self._normalize_benefit_type(mapped_value)
            if normalized:
                return normalized

        for line in self._extract_first_instance_header_lines(block):
            match = re.fullmatch(r'(?:B)?(\d{2})', line, flags=re.IGNORECASE)
            if match:
                return f"B{match.group(1)}"
        return None

    def _extract_birth_date_from_first_instance_header(self, block: str):
        mapped_value = self._extract_shifted_layout_value_by_label(
            block,
            r'Data\s+de\s+Nascimento\s+do\s+Empregado',
            r'\d{2}/\d{2}/\d{4}',
        )
        if mapped_value:
            mapped_date = self._parse_br_date(mapped_value)
            current_year = datetime.utcnow().year
            # Garante plausibilidade mínima para data de nascimento e evita
            # capturar datas operacionais (ex.: DIB/acidente) em layouts deslocados.
            if mapped_date and mapped_date.year <= current_year - 14:
                return mapped_date

        dates = []
        for line in self._extract_first_instance_header_lines(block):
            match = re.fullmatch(r'(\d{2}/\d{2}/\d{4})', line)
            if not match:
                continue

            parsed_date = self._parse_br_date(match.group(1))
            if parsed_date:
                dates.append(parsed_date)

        if not dates:
            return None

        current_year = datetime.utcnow().year
        plausible_birth_dates = [d for d in dates if d.year <= current_year - 14]
        if plausible_birth_dates:
            return min(plausible_birth_dates)

        return min(dates)

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
        # Regra restritiva: só aceita data imediatamente após o rótulo do DCB
        # para evitar capturar outras datas (ex.: data de nascimento) quando DCB está vazio.
        inline_match = re.search(
            r'Data\s+Cessa[cç][aã]o\s+Benef[ií]cio\s*\(?DCB\)?\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})\b',
            block,
            flags=re.IGNORECASE,
        )
        if inline_match:
            return self._parse_br_date(inline_match.group(1))

        label_match = re.search(
            r'Data\s+Cessa[cç][aã]o\s+Benef[ií]cio\s*\(?DCB\)?',
            block,
            flags=re.IGNORECASE,
        )
        if label_match:
            local_snippet = block[label_match.end():label_match.end() + 24]
            local_date_match = re.search(r'^\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})\b', local_snippet)
            if local_date_match:
                return self._parse_br_date(local_date_match.group(1))

        # Ex.: "DCB: 24/01/2013"
        match = re.search(r'\bDCB\s*:\s*(\d{2}/\d{2}/\d{4})\b', block, flags=re.IGNORECASE)
        return self._parse_br_date(match.group(1)) if match else None

    def _extract_insured_birth_date(self, block: str):
        # Ex.: "Data de Nascimento do Empregado 27/08/1964"
        # Limita a busca ao trecho imediatamente após o rótulo para não capturar
        # datas operacionais (DIB/acidente) em layouts deslocados.
        label_match = re.search(r'Data\s+de\s+Nascimento\s+do\s+Empregado', block, flags=re.IGNORECASE)
        if label_match:
            local_snippet = block[label_match.end():label_match.end() + 80]
            date_match = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', local_snippet)
            if date_match:
                parsed_local_date = self._parse_br_date(date_match.group(1))
                if parsed_local_date:
                    return parsed_local_date

        # Fallback para formatos abreviados eventualmente extraídos do PDF.
        match = re.search(
            r'\bData\s+de\s+Nascimento\b\s*:?\s*(\d{2}/\d{2}/\d{4})\b',
            block,
            flags=re.IGNORECASE,
        )
        if match:
            return self._parse_br_date(match.group(1))

        # Fallback para layout com valores deslocados para o cabeçalho da 1a instância.
        return self._extract_birth_date_from_first_instance_header(block)

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
            return {'status': None, 'status_raw': None, 'justification': None, 'opinion': None}

        status_label_pattern = (
            r'\bStatus\b(?=\s*(?:[:\-]|\n|\r|Indeferido\b|Deferido\b|Analyzing\b|Pendente\b|Pending\b))'
        )

        justification = self._extract_text_between_keywords(
            section,
            r'\bJustificativa\b',
            [status_label_pattern, r'\bParecer\b'],
        )

        # O status pode aparecer isolado após os rótulos "Status"/"Parecer" por quebra de layout.
        labeled_status_match = re.search(
            r'\bStatus\b\s*(?:[:\-]\s*|\s+|\n\s*)(Indeferido|Deferido|Analyzing|Pendente|Pending)\b',
            section,
            flags=re.IGNORECASE,
        )
        status_match = labeled_status_match or re.search(
            r'\b(Indeferido|Deferido|Analyzing|Pendente|Pending)\b',
            section,
            flags=re.IGNORECASE,
        )
        fallback_status = status_match.group(1).capitalize() if status_match else None

        # Texto completo do status: captura somente o valor ligado ao rótulo real "Status".
        status_raw = self._extract_status_text(section)
        if not status_raw and status_match:
            # Fallback: usa o valor normalizado quando o layout vier muito quebrado.
            status_raw = status_match.group(1).capitalize()

        # Prioriza o valor de status_raw para reduzir falso positivo vindo de justificativa/parecer.
        status = None
        if status_raw:
            status_from_raw_match = re.search(
                r'\b(Indeferido|Deferido|Analyzing|Pendente|Pending)\b',
                status_raw,
                flags=re.IGNORECASE,
            )
            if status_from_raw_match:
                status = status_from_raw_match.group(1).capitalize()

        if not status:
            status = fallback_status

        # Parecer: adiciona delimitadores para evitar capturar "Sumário dos Elementos Contestados" do próximo bloco
        opinion = self._extract_text_between_keywords(
            section,
            r'\bParecer\b',
            [r'\bSum[aá]rio\s+dos\s+Elementos\s+Contestados\b', r'\bN[aã]o\s+deve\s+ser\s+considerado\b'],
        )
        if opinion:
            opinion = re.sub(r'^(Status\s*)?(Deferido|Indeferido)\b\s*', '', opinion, flags=re.IGNORECASE).strip()
            opinion = opinion or None

        return {
            'status': status,
            'status_raw': status_raw or None,
            'justification': justification,
            'opinion': opinion,
        }

    def _extract_instance_sections(self, block: str) -> tuple[str | None, str | None]:
        first_section = None
        second_section = None

        first_match = re.search(r'Administrativo\s*1\s*[ªa]\s*inst[âa]ncia', block, flags=re.IGNORECASE)
        second_match = re.search(r'Administrativo\s*2\s*[ªa]\s*inst[âa]ncia', block, flags=re.IGNORECASE)
        first_justification_match = re.search(r'\bJustificativa\b', block, flags=re.IGNORECASE)
        end_match = re.search(
            r'\bNB\s*:|Informa[cç][oõ]es\s+de\s+Revis[aã]o\s+de\s+Benef[ií]cio|Dados\s+do\s+Benef[ií]cio|Sum[aá]rio\s+dos\s+Elementos\s+Contestados',
            block,
            flags=re.IGNORECASE,
        )

        if first_match:
            first_end = second_match.start() if second_match else (end_match.start() if end_match else len(block))

            # Modo padrão (rígido): começa após o título da 1a instância.
            strict_first_section = block[first_match.end():first_end]

            # Fallback somente para layout anômalo: quando "Justificativa" aparece
            # antes do título da 1a instância e a seção rígida não contém os marcadores
            # usuais de decisão. Isso evita impacto nos PDFs já bem estruturados.
            use_pre_heading_justification = False
            if first_justification_match and first_justification_match.start() < first_match.start():
                has_decision_markers_in_strict = bool(
                    re.search(r'\bJustificativa\b|\bStatus\b|\bParecer\b', strict_first_section, flags=re.IGNORECASE)
                )
                use_pre_heading_justification = not has_decision_markers_in_strict

            first_start = first_justification_match.start() if use_pre_heading_justification else first_match.end()
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
            return 

        result: dict[str, object | None] = {}

        # número do benefício
        # Em alguns documentos há texto residual do benefício anterior no início do bloco.
        # Prioriza o número que aparece imediatamente antes de "Espécie do Benefício".
        number_with_species = re.search(
            r'(\d{8,})\s*(?:\n|\r\n?)\s*Esp[ée]cie\s+do\s+Benef[ií]cio',
            block,
            flags=re.IGNORECASE,
        )
        if number_with_species:
            result['benefit_number'] = number_with_species.group(1).strip()
            block = block[number_with_species.start():]
        else:
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
        result['first_instance_status_raw'] = first_decision.get('status_raw')
        result['first_instance_justification'] = first_decision.get('justification')
        result['first_instance_opinion'] = first_decision.get('opinion')

        result['second_instance_status'] = second_decision.get('status')
        result['second_instance_status_raw'] = second_decision.get('status_raw')
        result['second_instance_justification'] = second_decision.get('justification')
        result['second_instance_opinion'] = second_decision.get('opinion')

        # Se tem justificativa na 1a instância mas não tem status, marca como 'analyzing'.
        if result['first_instance_justification'] and not result['first_instance_status']:
            result['first_instance_status'] = 'analyzing'

        # Se tem justificativa na 2a instância mas não tem status, marca como 'analyzing'.
        if result['second_instance_justification'] and not result['second_instance_status']:
            result['second_instance_status'] = 'analyzing'

        # status consolidado prioriza os textos "raw" por instância e usa status simples como fallback.
        result['raw_status'] = (
            result['second_instance_status_raw']
            or result['second_instance_status']
            or result['first_instance_status_raw']
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

    def parse_cat_block(self, block: str) -> dict | None:
        """Faz parsing de um bloco de CAT (Comunicação de Acidente de Trabalho)."""
        if not block or not block.strip():
            return None

        result: dict[str, object | None] = {}
        result['tipo'] = 'CAT'

        # Número da CAT
        cat_match = re.search(r'N[uú]mero\s+da\s+CAT\s+(\d+)', block, flags=re.IGNORECASE)
        if not cat_match:
            return None
        result['benefit_number'] = cat_match.group(1).strip()
        result['cat_number'] = result['benefit_number']

        # CNPJ do Empregador constante na CAT
        cnpj_match = re.search(
            r'CNPJ\s+do\s+Empregador\s+constante\s+na\s+CAT\s+([\d./\-]+)',
            block,
            flags=re.IGNORECASE,
        )
        result['employer_cnpj'] = cnpj_match.group(1).strip() if cnpj_match else None

        # NIT do Empregado
        nit_match = re.search(r'NIT\s+do\s+Empregado\s+(\d{8,20})', block, flags=re.IGNORECASE)
        result['insured_nit'] = nit_match.group(1).strip() if nit_match else None

        # Datas
        result['accident_date'] = self._extract_date_after_label(
            block, r'Data\s+do\s+Acidente\s+de\s+Trabalho'
        )
        result['insured_date_of_birth'] = self._extract_insured_birth_date(block)
        result['cat_registration_date'] = self._extract_date_after_label(
            block, r'Data\s+de\s+Cadastramento\s+da\s+CAT'
        )
        result['insured_death_date'] = self._extract_date_after_label(
            block, r'Data\s+de\s+[OÓ]bito\s+do\s+Empregado'
        )

        # Bloqueio
        bloqueio_match = re.search(r'\bBloqueio\s+(\S+)', block, flags=re.IGNORECASE)
        result['cat_block'] = bloqueio_match.group(1).strip() if bloqueio_match else None

        # Decisões administrativas (mesma estrutura dos benefícios)
        first_section, second_section = self._extract_instance_sections(block)
        first_decision = self._extract_instance_decision(first_section or '')
        second_decision = self._extract_instance_decision(second_section or '')

        result['first_instance_status'] = first_decision.get('status')
        result['first_instance_status_raw'] = first_decision.get('status_raw')
        result['first_instance_justification'] = first_decision.get('justification')
        result['first_instance_opinion'] = first_decision.get('opinion')

        result['second_instance_status'] = second_decision.get('status')
        result['second_instance_status_raw'] = second_decision.get('status_raw')
        result['second_instance_justification'] = second_decision.get('justification')
        result['second_instance_opinion'] = second_decision.get('opinion')

        if result['first_instance_justification'] and not result['first_instance_status']:
            result['first_instance_status'] = 'analyzing'
        if result['second_instance_justification'] and not result['second_instance_status']:
            result['second_instance_status'] = 'analyzing'

        result['raw_status'] = (
            result['second_instance_status_raw']
            or result['second_instance_status']
            or result['first_instance_status_raw']
            or result['first_instance_status']
            or None
        )
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
        result['decisions_summary'] = self._build_decision_summary(result)

        return result

    def parse_payroll_mass_block(self, block: str) -> dict | None:
        """Faz parsing de um bloco de Massa Salarial."""
        if not block or not block.strip():
            return None

        result: dict[str, object | None] = {}
        result['tipo'] = 'MassaSalarial'

        # CNPJ
        cnpj_match = re.search(r'CNPJ\s+([\d./\-]+)', block, flags=re.IGNORECASE)
        if not cnpj_match:
            return None
        result['employer_cnpj'] = cnpj_match.group(1).strip()

        # Competência (e.g. "11/2023")
        competence_match = re.search(r'Compet[êe]ncia\s+(\d{1,2}/\d{4})', block, flags=re.IGNORECASE)
        result['competence'] = competence_match.group(1).strip() if competence_match else None

        if not result['competence']:
            return None

        # Total Remunerações
        total_match = re.search(
            r'Total\s+Remunera[cç][oõ]es\s+R\$\s*([\d.,]+)',
            block,
            flags=re.IGNORECASE,
        )
        result['total_remuneration'] = self._parse_br_decimal(total_match.group(1)) if total_match else None

        # Valor Massa Salarial Solicitado (1ª instância — captured from first instance section)
        first_section, second_section = self._extract_instance_sections(block)

        def _extract_requested_value(section_text: str):
            if not section_text:
                return None
            val_match = re.search(
                r'Valor\s+Massa\s+Salarial\s+Solicitado\s+R\$\s*([\d.,]+)',
                section_text,
                flags=re.IGNORECASE,
            )
            if val_match:
                return self._parse_br_decimal(val_match.group(1))
            return None

        result['first_instance_requested_value'] = _extract_requested_value(first_section)
        result['second_instance_requested_value'] = _extract_requested_value(second_section)

        # If no instance-level values found, try on the full block
        if result['first_instance_requested_value'] is None:
            val_match = re.search(
                r'Valor\s+Massa\s+Salarial\s+Solicitado\s+R\$\s*([\d.,]+)',
                block,
                flags=re.IGNORECASE,
            )
            if val_match:
                result['first_instance_requested_value'] = self._parse_br_decimal(val_match.group(1))

        # Administrative decisions (same structure as benefits and CATs)
        first_decision = self._extract_instance_decision(first_section or '')
        second_decision = self._extract_instance_decision(second_section or '')

        result['first_instance_status'] = first_decision.get('status')
        result['first_instance_status_raw'] = first_decision.get('status_raw')
        result['first_instance_justification'] = first_decision.get('justification')
        result['first_instance_opinion'] = first_decision.get('opinion')

        result['second_instance_status'] = second_decision.get('status')
        result['second_instance_status_raw'] = second_decision.get('status_raw')
        result['second_instance_justification'] = second_decision.get('justification')
        result['second_instance_opinion'] = second_decision.get('opinion')

        if result['first_instance_justification'] and not result['first_instance_status']:
            result['first_instance_status'] = 'analyzing'
        if result['second_instance_justification'] and not result['second_instance_status']:
            result['second_instance_status'] = 'analyzing'

        result['raw_status'] = (
            result['second_instance_status_raw']
            or result['second_instance_status']
            or result['first_instance_status_raw']
            or result['first_instance_status']
            or None
        )
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
        result['decisions_summary'] = self._build_decision_summary(result)

        return result

    def parse_employment_link_block(self, block: str) -> dict | None:
        """Faz parsing de um bloco de Número Médio de Vínculos."""
        if not block or not block.strip():
            return None

        result: dict[str, object | None] = {}
        result['tipo'] = 'NumeroMedioVinculos'

        # CNPJ
        cnpj_match = re.search(r'CNPJ\s+([\d./\-]+)', block, flags=re.IGNORECASE)
        if not cnpj_match:
            return None
        result['employer_cnpj'] = cnpj_match.group(1).strip()

        # Competência (e.g. "01/2022")
        competence_match = re.search(r'Compet[êe]ncia\s+(\d{1,2}/\d{4})', block, flags=re.IGNORECASE)
        result['competence'] = competence_match.group(1).strip() if competence_match else None

        if not result['competence']:
            return None

        # Quantidade original
        quantity_match = re.search(r'Quantidade\s+(\d+)', block, flags=re.IGNORECASE)
        result['quantity'] = int(quantity_match.group(1)) if quantity_match else None

        # Número Vínculo Solicitado por instância
        first_section, second_section = self._extract_instance_sections(block)

        def _extract_requested_quantity(section_text: str):
            if not section_text:
                return None
            qty_match = re.search(
                r'N[uú]mero\s+V[ií]nculo\s+Solicitado\s*(\d+)',
                section_text,
                flags=re.IGNORECASE,
            )
            if qty_match:
                return int(qty_match.group(1))
            return None

        result['first_instance_requested_quantity'] = _extract_requested_quantity(first_section)
        result['second_instance_requested_quantity'] = _extract_requested_quantity(second_section)

        # If no instance-level values found, try on the full block
        if result['first_instance_requested_quantity'] is None:
            qty_match = re.search(
                r'N[uú]mero\s+V[ií]nculo\s+Solicitado\s*(\d+)',
                block,
                flags=re.IGNORECASE,
            )
            if qty_match:
                result['first_instance_requested_quantity'] = int(qty_match.group(1))

        # Administrative decisions (same structure as benefits, CATs and payroll masses)
        first_decision = self._extract_instance_decision(first_section or '')
        second_decision = self._extract_instance_decision(second_section or '')

        result['first_instance_status'] = first_decision.get('status')
        result['first_instance_status_raw'] = first_decision.get('status_raw')
        result['first_instance_justification'] = first_decision.get('justification')
        result['first_instance_opinion'] = first_decision.get('opinion')

        result['second_instance_status'] = second_decision.get('status')
        result['second_instance_status_raw'] = second_decision.get('status_raw')
        result['second_instance_justification'] = second_decision.get('justification')
        result['second_instance_opinion'] = second_decision.get('opinion')

        if result['first_instance_justification'] and not result['first_instance_status']:
            result['first_instance_status'] = 'analyzing'
        if result['second_instance_justification'] and not result['second_instance_status']:
            result['second_instance_status'] = 'analyzing'

        result['raw_status'] = (
            result['second_instance_status_raw']
            or result['second_instance_status']
            or result['first_instance_status_raw']
            or result['first_instance_status']
            or None
        )
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
        result['decisions_summary'] = self._build_decision_summary(result)

        return result

    def parse_turnover_rate_block(self, block: str) -> dict | None:
        """Faz parsing de um bloco de Taxa Média de Rotatividade."""
        if not block or not block.strip():
            return None

        result: dict[str, object | None] = {}
        result['tipo'] = 'TaxaMediaRotatividade'

        # CNPJ (required)
        cnpj_match = re.search(r'CNPJ\s+([\d./\-]+)', block, flags=re.IGNORECASE)
        if not cnpj_match:
            return None
        result['employer_cnpj'] = cnpj_match.group(1).strip()

        # Ano (required — unique key for this type)
        year_match = re.search(r'\bAno\s+(\d{4})\b', block, flags=re.IGNORECASE)
        if not year_match:
            return None
        result['year'] = year_match.group(1).strip()

        # Taxa de Rotatividade (decimal, e.g. "40,0000")
        taxa_match = re.search(
            r'Taxa\s+de\s+Rotatividade\s+([\d.,]+)',
            block,
            flags=re.IGNORECASE,
        )
        result['turnover_rate'] = self._parse_br_decimal(taxa_match.group(1)) if taxa_match else None

        # Admissões (plain count — word boundary prevents matching "Nº Admissões Solicitado")
        adm_match = re.search(r'\bAdmiss[o\xf5]es\s+(\d+)', block, flags=re.IGNORECASE)
        result['admissions'] = int(adm_match.group(1)) if adm_match else None

        # Rescisões
        res_match = re.search(r'\bRescis[o\xf5]es\s+(\d+)', block, flags=re.IGNORECASE)
        result['dismissals'] = int(res_match.group(1)) if res_match else None

        # Número de Vínculos no Início do Ano
        init_match = re.search(
            r'N[u\xfa]mero\s+de\s+V[i\xed]nculos\s+no\s+In[i\xed]cio\s+do\s+Ano\s+(\d+)',
            block,
            flags=re.IGNORECASE,
        )
        result['initial_links_count'] = int(init_match.group(1)) if init_match else None

        # Valores solicitados por instância
        first_section, second_section = self._extract_instance_sections(block)

        def _extract_requested(section_text: str):
            if not section_text:
                return None, None, None
            adm_sol = re.search(
                r'N[o\xba\xb0\.]\s*Admiss[o\xf5]es\s+Solicitado\s+(\d+)',
                section_text, flags=re.IGNORECASE,
            )
            res_sol = re.search(
                r'N[o\xba\xb0\.]\s*Rescis[o\xf5]es\s+Solicitado\s+(\d+)',
                section_text, flags=re.IGNORECASE,
            )
            ini_sol = re.search(
                r'N[o\xba\xb0\.]\s*Inicial\s+V[i\xed]nculos\s+Solicitado\s+(\d+)',
                section_text, flags=re.IGNORECASE,
            )
            return (
                int(adm_sol.group(1)) if adm_sol else None,
                int(res_sol.group(1)) if res_sol else None,
                int(ini_sol.group(1)) if ini_sol else None,
            )

        req_adm1, req_res1, req_ini1 = _extract_requested(first_section)
        req_adm2, req_res2, req_ini2 = _extract_requested(second_section)

        # Fallback: se não há seções, procura no bloco todo
        if req_adm1 is None and req_res1 is None and req_ini1 is None:
            req_adm1, req_res1, req_ini1 = _extract_requested(block)

        result['first_instance_requested_admissions'] = req_adm1
        result['first_instance_requested_dismissals'] = req_res1
        result['first_instance_requested_initial_links'] = req_ini1
        result['second_instance_requested_admissions'] = req_adm2
        result['second_instance_requested_dismissals'] = req_res2
        result['second_instance_requested_initial_links'] = req_ini2

        # Decisões administrativas
        first_decision = self._extract_instance_decision(first_section or '')
        second_decision = self._extract_instance_decision(second_section or '')

        result['first_instance_status'] = first_decision.get('status')
        result['first_instance_status_raw'] = first_decision.get('status_raw')
        result['first_instance_justification'] = first_decision.get('justification')
        result['first_instance_opinion'] = first_decision.get('opinion')
        result['second_instance_status'] = second_decision.get('status')
        result['second_instance_status_raw'] = second_decision.get('status_raw')
        result['second_instance_justification'] = second_decision.get('justification')
        result['second_instance_opinion'] = second_decision.get('opinion')

        if result['first_instance_justification'] and not result['first_instance_status']:
            result['first_instance_status'] = 'analyzing'
        if result['second_instance_justification'] and not result['second_instance_status']:
            result['second_instance_status'] = 'analyzing'

        result['raw_status'] = (
            result['second_instance_status_raw']
            or result['second_instance_status']
            or result['first_instance_status_raw']
            or result['first_instance_status']
            or None
        )
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
        result['decisions_summary'] = self._build_decision_summary(result)

        return result

    @staticmethod
    def _parse_br_decimal(value: str | None):
        """Converte valor monetário brasileiro (e.g. '87.182,85') para Decimal."""
        from decimal import Decimal, InvalidOperation
        if not value:
            return None
        cleaned = value.strip().replace('.', '').replace(',', '.')
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None

    @staticmethod
    def _should_apply_cat_update(cat_id: int, reference_dt, is_new_cat: bool) -> bool:
        """Decide se a atualização da CAT deve ser aplicada com base na data de referência do arquivo.

        Usa a mesma lógica de `_should_apply_benefit_update`: só sobrescreve dados se o
        arquivo que está sendo importado for mais recente que o último arquivo já registrado.
        """
        if is_new_cat:
            return True

        latest_history = (
            FapContestationCatSourceHistory.query
            .filter(FapContestationCatSourceHistory.cat_id == cat_id)
            .filter(
                db.func.coalesce(
                    FapContestationCatSourceHistory.publication_datetime,
                    FapContestationCatSourceHistory.transmission_datetime,
                ).is_not(None)
            )
            .order_by(
                db.func.coalesce(
                    FapContestationCatSourceHistory.publication_datetime,
                    FapContestationCatSourceHistory.transmission_datetime,
                ).desc()
            )
            .first()
        )

        latest_reference = (
            latest_history.publication_datetime
            or latest_history.transmission_datetime
            if latest_history else None
        )
        if latest_reference is None:
            return True

        if reference_dt is None:
            return False

        return reference_dt > latest_reference

    @staticmethod
    def _map_status(raw_status: str | None) -> str:
        if not raw_status:
            return 'pending'

        normalized = re.sub(r'\s+', ' ', str(raw_status)).strip().lower()

        # Ordem importa: "indeferido" contém o token "deferido".
        if 'indefer' in normalized:
            return 'rejected'
        if 'defer' in normalized:
            return 'approved'
        if 'analy' in normalized or 'analis' in normalized:
            return 'analyzing'
        if 'pend' in normalized:
            return 'pending'
        return 'pending'

    @staticmethod
    def _should_apply_benefit_update(benefit_id: int, reference_dt, is_new_benefit: bool) -> bool:
        if is_new_benefit:
            return True

        latest_history = (
            BenefitFapSourceHistory.query
            .filter(BenefitFapSourceHistory.benefit_id == benefit_id)
            .filter(
                db.func.coalesce(
                    BenefitFapSourceHistory.publication_datetime,
                    BenefitFapSourceHistory.transmission_datetime,
                ).is_not(None)
            )
            .order_by(
                db.func.coalesce(
                    BenefitFapSourceHistory.publication_datetime,
                    BenefitFapSourceHistory.transmission_datetime,
                ).desc()
            )
            .first()
        )

        latest_reference = (
            latest_history.publication_datetime
            or latest_history.transmission_datetime
            if latest_history else None
        )
        if latest_reference is None:
            return True

        if reference_dt is None:
            return False

        return reference_dt > latest_reference

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
        employer_vigencia_record: FapVigenciaCnpj | None = None

        if metadata is not None and getattr(metadata, 'establishment_cnpj', None):
            employer_client, employer_company_data, employer_cnpj_formatted = self._upsert_client_from_cnpj(
                law_firm_id=report.law_firm_id,
                cnpj_raw=metadata.establishment_cnpj,
            )

        transmission_dt = self._parse_br_datetime(
            getattr(metadata, 'transmission_datetime', None) if metadata is not None else None
        )
        publication_date = self._parse_br_date(
            getattr(metadata, 'publication_date', None) if metadata is not None else None
        )
        publication_dt = datetime.combine(publication_date, datetime.min.time()) if publication_date else None
        reference_dt = publication_dt or transmission_dt

        if metadata is not None:
            metadata_cnpj = employer_cnpj_formatted or getattr(metadata, 'establishment_cnpj', None)
            metadata_vigencia = getattr(metadata, 'validity_year', None)
            employer_vigencia_record = self._upsert_benefit_vigencia_cnpj(
                law_firm_id=report.law_firm_id,
                employer_cnpj_raw=metadata_cnpj,
                vigencia_year_raw=metadata_vigencia,
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

            should_apply_update = self._should_apply_benefit_update(
                benefit_id=benefit.id,
                reference_dt=reference_dt,
                is_new_benefit=is_new_benefit,
            )

            if should_apply_update:
                benefit.benefit_type = item.get('benefit_type') or benefit.benefit_type
                benefit.insured_nit = item.get('insured_nit') or benefit.insured_nit
                benefit.benefit_start_date = item.get('benefit_start_date') or benefit.benefit_start_date
                benefit.benefit_end_date = item.get('benefit_end_date') or benefit.benefit_end_date
                benefit.insured_date_of_birth = item.get('insured_date_of_birth') or benefit.insured_date_of_birth

                benefit.first_instance_status = item.get('first_instance_status')
                benefit.first_instance_status_raw = item.get('first_instance_status_raw')
                benefit.first_instance_justification = item.get('first_instance_justification')
                benefit.first_instance_opinion = item.get('first_instance_opinion')

                benefit.second_instance_status = item.get('second_instance_status')
                benefit.second_instance_status_raw = item.get('second_instance_status_raw')
                benefit.second_instance_justification = item.get('second_instance_justification')
                benefit.second_instance_opinion = item.get('second_instance_opinion')

                benefit.status = self._map_status(item.get('raw_status'))
                benefit.justification = item.get('justification')
                benefit.opinion = item.get('opinion')

                if employer_client is not None:
                    benefit.client = employer_client

                if employer_vigencia_record is not None:
                    benefit.fap_vigencia_cnpj = employer_vigencia_record

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
                elif employer_client is not None:
                    benefit.employer_name = employer_client.name or benefit.employer_name
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

            history_now = datetime.utcnow()
            history_insert_stmt = mysql_insert(BenefitFapSourceHistory.__table__).values(
                law_firm_id=report.law_firm_id,
                benefit_id=benefit.id,
                report_id=report.id,
                knowledge_base_id=report.knowledge_base_id,
                action='added' if is_new_benefit else 'updated',
                transmission_datetime=transmission_dt,
                publication_datetime=publication_dt,
                created_at=history_now,
                updated_at=history_now,
            )
            history_upsert_stmt = history_insert_stmt.on_duplicate_key_update(
                knowledge_base_id=history_insert_stmt.inserted.knowledge_base_id,
                action=history_insert_stmt.inserted.action,
                transmission_datetime=history_insert_stmt.inserted.transmission_datetime,
                publication_datetime=history_insert_stmt.inserted.publication_datetime,
                updated_at=history_insert_stmt.inserted.updated_at,
            )
            db.session.execute(history_upsert_stmt)

            if should_apply_update:
                imported_count += 1

        return imported_count

    def _upsert_cats_from_report(
        self,
        report: FapContestationJudgmentReport,
        extracted_cats: list[dict],
        metadata=None,
    ) -> int:
        """Insere ou atualiza CATs extraídas do relatório na tabela cats.

        Usa a mesma lógica de `_upsert_benefits_from_report`: só sobrescreve dados de
        instâncias se o arquivo sendo importado for mais recente que o último registrado.
        Registra histórico de fonte (arquivo) para cada CAT.
        """
        imported_count = 0

        employer_client: Client | None = None
        employer_company_data: dict | None = None
        employer_cnpj_formatted: str | None = None
        employer_vigencia_record: FapVigenciaCnpj | None = None

        if metadata is not None and getattr(metadata, 'establishment_cnpj', None):
            employer_client, employer_company_data, employer_cnpj_formatted = self._upsert_client_from_cnpj(
                law_firm_id=report.law_firm_id,
                cnpj_raw=metadata.establishment_cnpj,
            )

        transmission_dt = self._parse_br_datetime(
            getattr(metadata, 'transmission_datetime', None) if metadata is not None else None
        )
        publication_date = self._parse_br_date(
            getattr(metadata, 'publication_date', None) if metadata is not None else None
        )
        publication_dt = datetime.combine(publication_date, datetime.min.time()) if publication_date else None
        reference_dt = publication_dt or transmission_dt

        if metadata is not None:
            metadata_cnpj = employer_cnpj_formatted or getattr(metadata, 'establishment_cnpj', None)
            metadata_vigencia = getattr(metadata, 'validity_year', None)
            employer_vigencia_record = self._upsert_benefit_vigencia_cnpj(
                law_firm_id=report.law_firm_id,
                employer_cnpj_raw=metadata_cnpj,
                vigencia_year_raw=metadata_vigencia,
            )

        for item in extracted_cats:
            cat_number = str(item.get('benefit_number') or '').strip()
            if not cat_number:
                continue

            cat = FapContestationCat.query.filter_by(
                law_firm_id=report.law_firm_id,
                report_id=report.id,
                cat_number=cat_number,
            ).first()

            is_new_cat = cat is None
            if is_new_cat:
                cat = FapContestationCat(
                    law_firm_id=report.law_firm_id,
                    report_id=report.id,
                    cat_number=cat_number,
                )
                db.session.add(cat)

            db.session.flush()

            should_apply_update = self._should_apply_cat_update(
                cat_id=cat.id,
                reference_dt=reference_dt,
                is_new_cat=is_new_cat,
            )

            if should_apply_update:
                cat.employer_cnpj = item.get('employer_cnpj') or cat.employer_cnpj
                cat.employer_cnpj_assigned = item.get('employer_cnpj_assigned') or cat.employer_cnpj_assigned

                if employer_company_data is not None:
                    cat.employer_name = employer_company_data.get('razao_social') or cat.employer_name
                elif employer_client is not None:
                    cat.employer_name = employer_client.name or cat.employer_name

                # Vínculo com vigência FAP
                if employer_vigencia_record is not None:
                    cat.vigencia_id = employer_vigencia_record.id
                    cat.vigencia_year = employer_vigencia_record.vigencia_year
                elif cat.vigencia_year is None and metadata is not None:
                    metadata_vigencia = getattr(metadata, 'validity_year', None)
                    if metadata_vigencia:
                        cat.vigencia_year = str(metadata_vigencia).strip()

                cat.insured_nit = item.get('insured_nit') or cat.insured_nit
                cat.insured_date_of_birth = item.get('insured_date_of_birth') or cat.insured_date_of_birth
                cat.insured_death_date = item.get('insured_death_date') or cat.insured_death_date
                cat.accident_date = item.get('accident_date') or cat.accident_date
                cat.cat_registration_date = item.get('cat_registration_date') or cat.cat_registration_date
                cat.cat_block = item.get('cat_block') or cat.cat_block

                cat.first_instance_status = item.get('first_instance_status')
                cat.first_instance_status_raw = item.get('first_instance_status_raw')
                cat.first_instance_justification = item.get('first_instance_justification')
                cat.first_instance_opinion = item.get('first_instance_opinion')
                cat.second_instance_status = item.get('second_instance_status')
                cat.second_instance_status_raw = item.get('second_instance_status_raw')
                cat.second_instance_justification = item.get('second_instance_justification')
                cat.second_instance_opinion = item.get('second_instance_opinion')
                cat.status = self._map_status(item.get('raw_status'))
                cat.justification = item.get('justification')
                cat.opinion = item.get('opinion')

                decisions_summary = item.get('decisions_summary')
                source_note = f'Relatório FAP importado (id={report.id}, arquivo={report.original_filename})'
                notes_parts = [source_note]
                if decisions_summary:
                    notes_parts.append(decisions_summary)
                cat.notes = '\n'.join(notes_parts)

                cat.updated_at = datetime.utcnow()
                imported_count += 1

            # Registra histórico de arquivo para rastreabilidade (idempotente em concorrência)
            cat_history_now = datetime.utcnow()
            cat_history_insert_stmt = mysql_insert(FapContestationCatSourceHistory.__table__).values(
                law_firm_id=report.law_firm_id,
                cat_id=cat.id,
                report_id=report.id,
                knowledge_base_id=report.knowledge_base_id,
                action='added' if is_new_cat else 'updated',
                transmission_datetime=transmission_dt,
                publication_datetime=publication_dt,
                created_at=cat_history_now,
                updated_at=cat_history_now,
            )
            cat_history_upsert_stmt = cat_history_insert_stmt.on_duplicate_key_update(
                knowledge_base_id=cat_history_insert_stmt.inserted.knowledge_base_id,
                action=cat_history_insert_stmt.inserted.action,
                transmission_datetime=cat_history_insert_stmt.inserted.transmission_datetime,
                publication_datetime=cat_history_insert_stmt.inserted.publication_datetime,
                updated_at=cat_history_insert_stmt.inserted.updated_at,
            )
            db.session.execute(cat_history_upsert_stmt)

        return imported_count

    @staticmethod
    def _should_apply_payroll_mass_update(payroll_mass_id: int, reference_dt, is_new: bool) -> bool:
        """Decide se a atualização de Massa Salarial deve ser aplicada com base na data de referência."""
        if is_new:
            return True

        latest_history = (
            FapContestationPayrollMassSourceHistory.query
            .filter(FapContestationPayrollMassSourceHistory.payroll_mass_id == payroll_mass_id)
            .filter(
                db.func.coalesce(
                    FapContestationPayrollMassSourceHistory.publication_datetime,
                    FapContestationPayrollMassSourceHistory.transmission_datetime,
                ).is_not(None)
            )
            .order_by(
                db.func.coalesce(
                    FapContestationPayrollMassSourceHistory.publication_datetime,
                    FapContestationPayrollMassSourceHistory.transmission_datetime,
                ).desc()
            )
            .first()
        )

        latest_reference = (
            latest_history.publication_datetime
            or latest_history.transmission_datetime
            if latest_history else None
        )
        if latest_reference is None:
            return True
        if reference_dt is None:
            return False
        return reference_dt > latest_reference

    def _upsert_payroll_masses_from_report(
        self,
        report: FapContestationJudgmentReport,
        extracted_masses: list[dict],
        metadata=None,
    ) -> int:
        """Insere ou atualiza entradas de Massa Salarial extraídas do relatório.

        Usa a mesma lógica de `_upsert_cats_from_report`.
        """
        imported_count = 0

        employer_client: Client | None = None
        employer_company_data: dict | None = None
        employer_cnpj_formatted: str | None = None
        employer_vigencia_record: FapVigenciaCnpj | None = None

        if metadata is not None and getattr(metadata, 'establishment_cnpj', None):
            employer_client, employer_company_data, employer_cnpj_formatted = self._upsert_client_from_cnpj(
                law_firm_id=report.law_firm_id,
                cnpj_raw=metadata.establishment_cnpj,
            )

        transmission_dt = self._parse_br_datetime(
            getattr(metadata, 'transmission_datetime', None) if metadata is not None else None
        )
        publication_date = self._parse_br_date(
            getattr(metadata, 'publication_date', None) if metadata is not None else None
        )
        publication_dt = datetime.combine(publication_date, datetime.min.time()) if publication_date else None
        reference_dt = publication_dt or transmission_dt

        if metadata is not None:
            metadata_cnpj = employer_cnpj_formatted or getattr(metadata, 'establishment_cnpj', None)
            metadata_vigencia = getattr(metadata, 'validity_year', None)
            employer_vigencia_record = self._upsert_benefit_vigencia_cnpj(
                law_firm_id=report.law_firm_id,
                employer_cnpj_raw=metadata_cnpj,
                vigencia_year_raw=metadata_vigencia,
            )

        for item in extracted_masses:
            employer_cnpj_raw = item.get('employer_cnpj')
            competence = str(item.get('competence') or '').strip()
            if not employer_cnpj_raw or not competence:
                continue

            employer_cnpj_digits = self._normalize_cnpj(employer_cnpj_raw)
            if not employer_cnpj_digits:
                continue

            payroll_mass = FapContestationPayrollMass.query.filter_by(
                law_firm_id=report.law_firm_id,
                report_id=report.id,
                employer_cnpj=employer_cnpj_digits,
                competence=competence,
            ).first()

            is_new = payroll_mass is None
            if is_new:
                payroll_mass = FapContestationPayrollMass(
                    law_firm_id=report.law_firm_id,
                    report_id=report.id,
                    employer_cnpj=employer_cnpj_digits,
                    competence=competence,
                )
                db.session.add(payroll_mass)

            db.session.flush()

            should_apply_update = self._should_apply_payroll_mass_update(
                payroll_mass_id=payroll_mass.id,
                reference_dt=reference_dt,
                is_new=is_new,
            )

            if should_apply_update:
                if employer_company_data is not None:
                    payroll_mass.employer_name = employer_company_data.get('razao_social') or payroll_mass.employer_name
                elif employer_client is not None:
                    payroll_mass.employer_name = employer_client.name or payroll_mass.employer_name

                if employer_vigencia_record is not None:
                    payroll_mass.vigencia_id = employer_vigencia_record.id
                    payroll_mass.vigencia_year = employer_vigencia_record.vigencia_year
                elif payroll_mass.vigencia_year is None and metadata is not None:
                    metadata_vigencia = getattr(metadata, 'validity_year', None)
                    if metadata_vigencia:
                        payroll_mass.vigencia_year = str(metadata_vigencia).strip()

                payroll_mass.total_remuneration = item.get('total_remuneration') or payroll_mass.total_remuneration
                payroll_mass.first_instance_requested_value = (
                    item.get('first_instance_requested_value') or payroll_mass.first_instance_requested_value
                )
                payroll_mass.second_instance_requested_value = (
                    item.get('second_instance_requested_value') or payroll_mass.second_instance_requested_value
                )

                payroll_mass.first_instance_status = item.get('first_instance_status')
                payroll_mass.first_instance_status_raw = item.get('first_instance_status_raw')
                payroll_mass.first_instance_justification = item.get('first_instance_justification')
                payroll_mass.first_instance_opinion = item.get('first_instance_opinion')
                payroll_mass.second_instance_status = item.get('second_instance_status')
                payroll_mass.second_instance_status_raw = item.get('second_instance_status_raw')
                payroll_mass.second_instance_justification = item.get('second_instance_justification')
                payroll_mass.second_instance_opinion = item.get('second_instance_opinion')
                payroll_mass.status = self._map_status(item.get('raw_status'))
                payroll_mass.justification = item.get('justification')
                payroll_mass.opinion = item.get('opinion')

                decisions_summary = item.get('decisions_summary')
                source_note = f'Relatório FAP importado (id={report.id}, arquivo={report.original_filename})'
                notes_parts = [source_note]
                if decisions_summary:
                    notes_parts.append(decisions_summary)
                payroll_mass.notes = '\n'.join(notes_parts)

                payroll_mass.updated_at = datetime.utcnow()
                imported_count += 1

            payroll_history_now = datetime.utcnow()
            payroll_history_insert_stmt = mysql_insert(FapContestationPayrollMassSourceHistory.__table__).values(
                law_firm_id=report.law_firm_id,
                payroll_mass_id=payroll_mass.id,
                report_id=report.id,
                knowledge_base_id=report.knowledge_base_id,
                action='added' if is_new else 'updated',
                transmission_datetime=transmission_dt,
                publication_datetime=publication_dt,
                created_at=payroll_history_now,
                updated_at=payroll_history_now,
            )
            payroll_history_upsert_stmt = payroll_history_insert_stmt.on_duplicate_key_update(
                knowledge_base_id=payroll_history_insert_stmt.inserted.knowledge_base_id,
                action=payroll_history_insert_stmt.inserted.action,
                transmission_datetime=payroll_history_insert_stmt.inserted.transmission_datetime,
                publication_datetime=payroll_history_insert_stmt.inserted.publication_datetime,
                updated_at=payroll_history_insert_stmt.inserted.updated_at,
            )
            db.session.execute(payroll_history_upsert_stmt)

        return imported_count

    @staticmethod
    def _should_apply_turnover_rate_update(turnover_rate_id: int, reference_dt, is_new: bool) -> bool:
        """Decide se a atualização de Taxa de Rotatividade deve ser aplicada com base na data de referência."""
        if is_new:
            return True

        latest_history = (
            FapContestationTurnoverRateSourceHistory.query
            .filter(FapContestationTurnoverRateSourceHistory.turnover_rate_id == turnover_rate_id)
            .filter(
                db.func.coalesce(
                    FapContestationTurnoverRateSourceHistory.publication_datetime,
                    FapContestationTurnoverRateSourceHistory.transmission_datetime,
                ).is_not(None)
            )
            .order_by(
                db.func.coalesce(
                    FapContestationTurnoverRateSourceHistory.publication_datetime,
                    FapContestationTurnoverRateSourceHistory.transmission_datetime,
                ).desc()
            )
            .first()
        )

        latest_reference = (
            latest_history.publication_datetime
            or latest_history.transmission_datetime
            if latest_history else None
        )
        if latest_reference is None:
            return True
        if reference_dt is None:
            return False
        return reference_dt > latest_reference

    @staticmethod
    def _should_apply_employment_link_update(employment_link_id: int, reference_dt, is_new: bool) -> bool:
        """Decide se a atualização de Vínculo deve ser aplicada com base na data de referência."""
        if is_new:
            return True

        latest_history = (
            FapContestationEmploymentLinkSourceHistory.query
            .filter(FapContestationEmploymentLinkSourceHistory.employment_link_id == employment_link_id)
            .filter(
                db.func.coalesce(
                    FapContestationEmploymentLinkSourceHistory.publication_datetime,
                    FapContestationEmploymentLinkSourceHistory.transmission_datetime,
                ).is_not(None)
            )
            .order_by(
                db.func.coalesce(
                    FapContestationEmploymentLinkSourceHistory.publication_datetime,
                    FapContestationEmploymentLinkSourceHistory.transmission_datetime,
                ).desc()
            )
            .first()
        )

        latest_reference = (
            latest_history.publication_datetime
            or latest_history.transmission_datetime
            if latest_history else None
        )
        if latest_reference is None:
            return True
        if reference_dt is None:
            return False
        return reference_dt > latest_reference

    def _upsert_employment_links_from_report(
        self,
        report: FapContestationJudgmentReport,
        extracted_links: list[dict],
        metadata=None,
    ) -> int:
        """Insere ou atualiza entradas de Número Médio de Vínculos extraídas do relatório.

        Usa a mesma lógica de `_upsert_payroll_masses_from_report`.
        """
        imported_count = 0

        employer_client: Client | None = None
        employer_company_data: dict | None = None
        employer_cnpj_formatted: str | None = None
        employer_vigencia_record: FapVigenciaCnpj | None = None

        if metadata is not None and getattr(metadata, 'establishment_cnpj', None):
            employer_client, employer_company_data, employer_cnpj_formatted = self._upsert_client_from_cnpj(
                law_firm_id=report.law_firm_id,
                cnpj_raw=metadata.establishment_cnpj,
            )

        transmission_dt = self._parse_br_datetime(
            getattr(metadata, 'transmission_datetime', None) if metadata is not None else None
        )
        publication_date = self._parse_br_date(
            getattr(metadata, 'publication_date', None) if metadata is not None else None
        )
        publication_dt = datetime.combine(publication_date, datetime.min.time()) if publication_date else None
        reference_dt = publication_dt or transmission_dt

        if metadata is not None:
            metadata_cnpj = employer_cnpj_formatted or getattr(metadata, 'establishment_cnpj', None)
            metadata_vigencia = getattr(metadata, 'validity_year', None)
            employer_vigencia_record = self._upsert_benefit_vigencia_cnpj(
                law_firm_id=report.law_firm_id,
                employer_cnpj_raw=metadata_cnpj,
                vigencia_year_raw=metadata_vigencia,
            )

        for item in extracted_links:
            employer_cnpj_raw = item.get('employer_cnpj')
            competence = str(item.get('competence') or '').strip()
            if not employer_cnpj_raw or not competence:
                continue

            employer_cnpj_digits = self._normalize_cnpj(employer_cnpj_raw)
            if not employer_cnpj_digits:
                continue

            employment_link = FapContestationEmploymentLink.query.filter_by(
                law_firm_id=report.law_firm_id,
                report_id=report.id,
                employer_cnpj=employer_cnpj_digits,
                competence=competence,
            ).first()

            is_new = employment_link is None
            if is_new:
                employment_link = FapContestationEmploymentLink(
                    law_firm_id=report.law_firm_id,
                    report_id=report.id,
                    employer_cnpj=employer_cnpj_digits,
                    competence=competence,
                )
                db.session.add(employment_link)

            db.session.flush()

            should_apply_update = self._should_apply_employment_link_update(
                employment_link_id=employment_link.id,
                reference_dt=reference_dt,
                is_new=is_new,
            )

            if should_apply_update:
                if employer_company_data is not None:
                    employment_link.employer_name = employer_company_data.get('razao_social') or employment_link.employer_name
                elif employer_client is not None:
                    employment_link.employer_name = employer_client.name or employment_link.employer_name

                if employer_vigencia_record is not None:
                    employment_link.vigencia_id = employer_vigencia_record.id
                    employment_link.vigencia_year = employer_vigencia_record.vigencia_year
                elif employment_link.vigencia_year is None and metadata is not None:
                    metadata_vigencia = getattr(metadata, 'validity_year', None)
                    if metadata_vigencia:
                        employment_link.vigencia_year = str(metadata_vigencia).strip()

                employment_link.quantity = item.get('quantity') if item.get('quantity') is not None else employment_link.quantity
                employment_link.first_instance_requested_quantity = (
                    item.get('first_instance_requested_quantity')
                    if item.get('first_instance_requested_quantity') is not None
                    else employment_link.first_instance_requested_quantity
                )
                employment_link.second_instance_requested_quantity = (
                    item.get('second_instance_requested_quantity')
                    if item.get('second_instance_requested_quantity') is not None
                    else employment_link.second_instance_requested_quantity
                )

                employment_link.first_instance_status = item.get('first_instance_status')
                employment_link.first_instance_status_raw = item.get('first_instance_status_raw')
                employment_link.first_instance_justification = item.get('first_instance_justification')
                employment_link.first_instance_opinion = item.get('first_instance_opinion')
                employment_link.second_instance_status = item.get('second_instance_status')
                employment_link.second_instance_status_raw = item.get('second_instance_status_raw')
                employment_link.second_instance_justification = item.get('second_instance_justification')
                employment_link.second_instance_opinion = item.get('second_instance_opinion')
                employment_link.status = self._map_status(item.get('raw_status'))
                employment_link.justification = item.get('justification')
                employment_link.opinion = item.get('opinion')

                decisions_summary = item.get('decisions_summary')
                source_note = f'Relatório FAP importado (id={report.id}, arquivo={report.original_filename})'
                notes_parts = [source_note]
                if decisions_summary:
                    notes_parts.append(decisions_summary)
                employment_link.notes = '\n'.join(notes_parts)

                employment_link.updated_at = datetime.utcnow()
                imported_count += 1

            employment_history_now = datetime.utcnow()
            employment_history_insert_stmt = mysql_insert(FapContestationEmploymentLinkSourceHistory.__table__).values(
                law_firm_id=report.law_firm_id,
                employment_link_id=employment_link.id,
                report_id=report.id,
                knowledge_base_id=report.knowledge_base_id,
                action='added' if is_new else 'updated',
                transmission_datetime=transmission_dt,
                publication_datetime=publication_dt,
                created_at=employment_history_now,
                updated_at=employment_history_now,
            )
            employment_history_upsert_stmt = employment_history_insert_stmt.on_duplicate_key_update(
                knowledge_base_id=employment_history_insert_stmt.inserted.knowledge_base_id,
                action=employment_history_insert_stmt.inserted.action,
                transmission_datetime=employment_history_insert_stmt.inserted.transmission_datetime,
                publication_datetime=employment_history_insert_stmt.inserted.publication_datetime,
                updated_at=employment_history_insert_stmt.inserted.updated_at,
            )
            db.session.execute(employment_history_upsert_stmt)

        return imported_count

    def _upsert_turnover_rates_from_report(
        self,
        report: FapContestationJudgmentReport,
        extracted_rates: list[dict],
        metadata=None,
    ) -> int:
        """Insere ou atualiza entradas de Taxa Média de Rotatividade extraídas do relatório."""
        imported_count = 0

        employer_client: Client | None = None
        employer_company_data: dict | None = None
        employer_cnpj_formatted: str | None = None
        employer_vigencia_record: FapVigenciaCnpj | None = None

        if metadata is not None and getattr(metadata, 'establishment_cnpj', None):
            employer_client, employer_company_data, employer_cnpj_formatted = self._upsert_client_from_cnpj(
                law_firm_id=report.law_firm_id,
                cnpj_raw=metadata.establishment_cnpj,
            )

        transmission_dt = self._parse_br_datetime(
            getattr(metadata, 'transmission_datetime', None) if metadata is not None else None
        )
        publication_date = self._parse_br_date(
            getattr(metadata, 'publication_date', None) if metadata is not None else None
        )
        publication_dt = datetime.combine(publication_date, datetime.min.time()) if publication_date else None
        reference_dt = publication_dt or transmission_dt

        if metadata is not None:
            metadata_cnpj = employer_cnpj_formatted or getattr(metadata, 'establishment_cnpj', None)
            metadata_vigencia = getattr(metadata, 'validity_year', None)
            employer_vigencia_record = self._upsert_benefit_vigencia_cnpj(
                law_firm_id=report.law_firm_id,
                employer_cnpj_raw=metadata_cnpj,
                vigencia_year_raw=metadata_vigencia,
            )

        for item in extracted_rates:
            employer_cnpj_raw = item.get('employer_cnpj')
            year = str(item.get('year') or '').strip()
            if not employer_cnpj_raw or not year:
                continue

            employer_cnpj_digits = self._normalize_cnpj(employer_cnpj_raw)
            if not employer_cnpj_digits:
                continue

            turnover_rate = FapContestationTurnoverRate.query.filter_by(
                law_firm_id=report.law_firm_id,
                report_id=report.id,
                employer_cnpj=employer_cnpj_digits,
                year=year,
            ).first()

            is_new = turnover_rate is None
            if is_new:
                turnover_rate = FapContestationTurnoverRate(
                    law_firm_id=report.law_firm_id,
                    report_id=report.id,
                    employer_cnpj=employer_cnpj_digits,
                    year=year,
                )
                db.session.add(turnover_rate)

            db.session.flush()

            should_apply_update = self._should_apply_turnover_rate_update(
                turnover_rate_id=turnover_rate.id,
                reference_dt=reference_dt,
                is_new=is_new,
            )

            if should_apply_update:
                if employer_company_data is not None:
                    turnover_rate.employer_name = employer_company_data.get('razao_social') or turnover_rate.employer_name
                elif employer_client is not None:
                    turnover_rate.employer_name = employer_client.name or turnover_rate.employer_name

                if employer_vigencia_record is not None:
                    turnover_rate.vigencia_id = employer_vigencia_record.id
                    turnover_rate.vigencia_year = employer_vigencia_record.vigencia_year
                elif turnover_rate.vigencia_year is None and metadata is not None:
                    metadata_vigencia = getattr(metadata, 'validity_year', None)
                    if metadata_vigencia:
                        turnover_rate.vigencia_year = str(metadata_vigencia).strip()

                turnover_rate.turnover_rate = item.get('turnover_rate') if item.get('turnover_rate') is not None else turnover_rate.turnover_rate
                turnover_rate.admissions = item.get('admissions') if item.get('admissions') is not None else turnover_rate.admissions
                turnover_rate.dismissals = item.get('dismissals') if item.get('dismissals') is not None else turnover_rate.dismissals
                turnover_rate.initial_links_count = item.get('initial_links_count') if item.get('initial_links_count') is not None else turnover_rate.initial_links_count

                turnover_rate.first_instance_requested_admissions = (
                    item.get('first_instance_requested_admissions')
                    if item.get('first_instance_requested_admissions') is not None
                    else turnover_rate.first_instance_requested_admissions
                )
                turnover_rate.first_instance_requested_dismissals = (
                    item.get('first_instance_requested_dismissals')
                    if item.get('first_instance_requested_dismissals') is not None
                    else turnover_rate.first_instance_requested_dismissals
                )
                turnover_rate.first_instance_requested_initial_links = (
                    item.get('first_instance_requested_initial_links')
                    if item.get('first_instance_requested_initial_links') is not None
                    else turnover_rate.first_instance_requested_initial_links
                )
                turnover_rate.second_instance_requested_admissions = (
                    item.get('second_instance_requested_admissions')
                    if item.get('second_instance_requested_admissions') is not None
                    else turnover_rate.second_instance_requested_admissions
                )
                turnover_rate.second_instance_requested_dismissals = (
                    item.get('second_instance_requested_dismissals')
                    if item.get('second_instance_requested_dismissals') is not None
                    else turnover_rate.second_instance_requested_dismissals
                )
                turnover_rate.second_instance_requested_initial_links = (
                    item.get('second_instance_requested_initial_links')
                    if item.get('second_instance_requested_initial_links') is not None
                    else turnover_rate.second_instance_requested_initial_links
                )

                turnover_rate.first_instance_status = item.get('first_instance_status')
                turnover_rate.first_instance_status_raw = item.get('first_instance_status_raw')
                turnover_rate.first_instance_justification = item.get('first_instance_justification')
                turnover_rate.first_instance_opinion = item.get('first_instance_opinion')
                turnover_rate.second_instance_status = item.get('second_instance_status')
                turnover_rate.second_instance_status_raw = item.get('second_instance_status_raw')
                turnover_rate.second_instance_justification = item.get('second_instance_justification')
                turnover_rate.second_instance_opinion = item.get('second_instance_opinion')
                turnover_rate.status = self._map_status(item.get('raw_status'))
                turnover_rate.justification = item.get('justification')
                turnover_rate.opinion = item.get('opinion')

                decisions_summary = item.get('decisions_summary')
                source_note = f'Relatório FAP importado (id={report.id}, arquivo={report.original_filename})'
                notes_parts = [source_note]
                if decisions_summary:
                    notes_parts.append(decisions_summary)
                turnover_rate.notes = '\n'.join(notes_parts)

                turnover_rate.updated_at = datetime.utcnow()
                imported_count += 1

            turnover_history_now = datetime.utcnow()
            turnover_history_insert_stmt = mysql_insert(FapContestationTurnoverRateSourceHistory.__table__).values(
                law_firm_id=report.law_firm_id,
                turnover_rate_id=turnover_rate.id,
                report_id=report.id,
                knowledge_base_id=report.knowledge_base_id,
                action='added' if is_new else 'updated',
                transmission_datetime=transmission_dt,
                publication_datetime=publication_dt,
                created_at=turnover_history_now,
                updated_at=turnover_history_now,
            )
            turnover_history_upsert_stmt = turnover_history_insert_stmt.on_duplicate_key_update(
                knowledge_base_id=turnover_history_insert_stmt.inserted.knowledge_base_id,
                action=turnover_history_insert_stmt.inserted.action,
                transmission_datetime=turnover_history_insert_stmt.inserted.transmission_datetime,
                publication_datetime=turnover_history_insert_stmt.inserted.publication_datetime,
                updated_at=turnover_history_insert_stmt.inserted.updated_at,
            )
            db.session.execute(turnover_history_upsert_stmt)

        return imported_count

    def process_single_report(
        self,
        report_id: int,
    ) -> tuple[bool, int, str | None]:
        """Processa um único relatório."""
        report = FapContestationJudgmentReport.query.get(report_id)
        if report is None:
            return False, 0, 'Relatório não encontrado.'

        report.status = 'processing'
        report.error_message = None
        report.updated_at = datetime.utcnow()
        db.session.commit()

        try:
            extraction_started_at = perf_counter()

            step_started_at = perf_counter()
            metadata = self.extract_metadata_from_first_page_with_pdfplumber(report.file_path)
            print(f'Relatório #{report.id} | etapa metadata levou {perf_counter() - step_started_at:.2f}s')

            step_started_at = perf_counter()
            extracted_sections, parse_timings = self.extract_all_sections_with_pdfplumber(report.file_path)
            extracted_benefits = extracted_sections['benefits']
            extracted_cats = extracted_sections['cats']
            extracted_payroll_masses = extracted_sections['payroll_masses']
            extracted_employment_links = extracted_sections['employment_links']
            extracted_turnover_rates = extracted_sections['turnover_rates']

            print(f'Relatório #{report.id} | etapa extraction_single_pass levou {perf_counter() - step_started_at:.2f}s')
            print(f'Relatório #{report.id} | etapa benefits (parse) levou {parse_timings["benefits"]:.2f}s')
            print(f'Relatório #{report.id} | etapa cats (parse) levou {parse_timings["cats"]:.2f}s')
            print(f'Relatório #{report.id} | etapa payroll_masses (parse) levou {parse_timings["payroll_masses"]:.2f}s')
            print(f'Relatório #{report.id} | etapa employment_links (parse) levou {parse_timings["employment_links"]:.2f}s')
            print(f'Relatório #{report.id} | etapa turnover_rates (parse) levou {parse_timings["turnover_rates"]:.2f}s')
            print(f'Relatório #{report.id} | extração completa levou {perf_counter() - extraction_started_at:.2f}s')

            print(
                f'Relatório #{report.id}: {len(extracted_benefits)} benefício(s), '
                f'{len(extracted_cats)} CAT(s), '
                f'{len(extracted_payroll_masses)} Massa(s) Salarial(s), '
                f'{len(extracted_employment_links)} Vínculo(s) e '
                f'{len(extracted_turnover_rates)} Taxa(s) de Rotatividade identificado(s) via pdfplumber.'
            )

            imported_count = self._upsert_benefits_from_report(report, extracted_benefits, metadata)
            imported_cats = self._upsert_cats_from_report(report, extracted_cats, metadata)
            imported_payroll_masses = self._upsert_payroll_masses_from_report(report, extracted_payroll_masses, metadata)
            imported_employment_links = self._upsert_employment_links_from_report(report, extracted_employment_links, metadata)
            imported_turnover_rates = self._upsert_turnover_rates_from_report(report, extracted_turnover_rates, metadata)

            report.imported_benefits_count = imported_count
            report.status = 'completed'
            report.processed_at = datetime.utcnow()
            report.updated_at = datetime.utcnow()
            db.session.commit()

            print(
                f'Relatório #{report.id} processado com sucesso. '
                f'Benefícios: {imported_count}, CATs: {imported_cats}, '
                f'Massas Salariais: {imported_payroll_masses}, Vínculos: {imported_employment_links}, '
                f'Taxas de Rotatividade: {imported_turnover_rates}'
            )
            return True, imported_count, None
        except Exception as exc:
            db.session.rollback()

            report = FapContestationJudgmentReport.query.get(report_id)
            if report is None:
                return False, 0, str(exc)

            report.error_message = str(exc)
            report.status = 'error'
            report.updated_at = datetime.utcnow()

            db.session.commit()
            print(f'Erro ao processar relatório #{report_id}: {exc}')
            return False, 0, str(exc)

    def process_pending_reports(
        self,
        batch_size: int = 100,
        report_id: int | None = None,
        include_errors: bool = False,
    ) -> int:
        """Processa relatórios pendentes, extraindo benefícios do markdown e importando na tabela central."""
        with self.app.app_context():
            query = FapContestationJudgmentReport.query

            if report_id:
                query = query.filter(FapContestationJudgmentReport.id == report_id)
            else:
                statuses = ['pending', 'queued']
                if include_errors:
                    statuses.append('error')
                query = query.filter(FapContestationJudgmentReport.status.in_(statuses))

            effective_batch_size = 1 if report_id else max(1, int(batch_size))

            reports = (
                query.order_by(FapContestationJudgmentReport.uploaded_at.asc())
                .limit(effective_batch_size)
                .all()
            )

            if not reports:
                print('Nenhum relatório pendente para processamento.')
                return 0

            processed_reports = 0

            for report in reports:
                success, _, _ = self.process_single_report(report.id)
                if success:
                    processed_reports += 1

            return processed_reports
