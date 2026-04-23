from __future__ import annotations

import os
import re

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from app.agents.config import DEFAULT_MODEL_NANO


class FapContestationJudgmentMetadata(BaseModel):
    """Dados relevantes extraídos da primeira página do relatório de julgamento FAP."""

    establishment_cnpj: str | None = Field(default=None, description='CNPJ do estabelecimento')
    validity_year: str | None = Field(default=None, description='Vigência do julgamento')
    process_status: str | None = Field(default=None, description='Situação do processo')
    protocol_number: str | None = Field(default=None, description='Número do protocolo')
    administrative_instance: str | None = Field(default=None, description='Instância administrativa')
    analyst_name: str | None = Field(default=None, description='Analista responsável')
    analysis_finished_at: str | None = Field(default=None, description='Data de finalização da análise')
    version_number: str | None = Field(default=None, description='Número da versão')
    transmission_datetime: str | None = Field(default=None, description='Data e hora de transmissão')
    publication_date: str | None = Field(default=None, description='Data de publicação')


class FapContestationJudgmentMetadataAgent:
    """Agente para extrair metadados da primeira página do relatório de julgamento FAP."""

    REQUIRED_FIELDS_FOR_REGEX_ONLY = (
        'establishment_cnpj',
        'validity_year',
        'process_status',
        'protocol_number',
        'transmission_datetime',
    )

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or DEFAULT_MODEL_NANO

    def _extract_first_page_section(self, markdown_content: str, max_chars: int = 2500) -> str:
        """Tenta isolar a primeira página do markdown usando marcadores comuns."""
        text = (markdown_content or '').strip()
        if not text:
            return ''

        # Marcadores comuns de troca de página em extrações markdown
        page_break_patterns = [
            r'\n\s*[-#]{0,3}\s*page\s*2\b',
            r'\n\s*[-#]{0,3}\s*página\s*2\b',
            r'\n\s*[-#]{0,3}\s*pagina\s*2\b',
            r'\n\s*\[\s*page\s*2\s*\]',
            r'\n\s*\[\s*página\s*2\s*\]',
            r'\n\s*\f',
        ]

        lower_text = text.lower()
        split_indexes: list[int] = []
        for pattern in page_break_patterns:
            match = re.search(pattern, lower_text, flags=re.IGNORECASE)
            if match:
                split_indexes.append(match.start())

        if split_indexes:
            first_page = text[: min(split_indexes)]
        else:
            first_page = text[:max_chars]

        return first_page.strip()

    @staticmethod
    def _extract_transmission_datetime(first_page_content: str) -> str | None:
        """Extrai 'Data Transmissão' em formato brasileiro com horário, quando disponível."""
        if not first_page_content:
            return None

        patterns = [
            r'Data\s+Transmiss[aã]o\s*:?\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})',
            r'Data\s+de\s+Transmiss[aã]o\s*:?\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})',
        ]

        for pattern in patterns:
            match = re.search(pattern, first_page_content, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    @staticmethod
    def _extract_publication_date(first_page_content: str) -> str | None:
        """Extrai 'Data Publicação' em formato brasileiro (dd/mm/aaaa), quando disponível."""
        if not first_page_content:
            return None

        patterns = [
            r'Data\s+Publica[cç][aã]o\s*:?\s*(\d{2}/\d{2}/\d{4})',
            r'Data\s+de\s+Publica[cç][aã]o\s*:?\s*(\d{2}/\d{2}/\d{4})',
            r'Data\s+Publica[cç][aã]o\s+(?:no\s+)?D\.?O\.?U\.?\s*:?\s*(\d{2}/\d{2}/\d{4})',
            r'Data\s+Publica[cç][aã]o\s*:?\s*(?:\n\s*)?(\d{2}/\d{2}/\d{4})',
        ]

        for pattern in patterns:
            match = re.search(pattern, first_page_content, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    @staticmethod
    def _extract_establishment_cnpj(first_page_content: str) -> str | None:
        if not first_page_content:
            return None

        patterns = [
            r'Estabelecimento\s*:?\s*([\d./\-]{14,18})',
            r'CNPJ\s+do\s+Estabelecimento\s*: ?\s*([\d./\-]{14,18})',
            r'CNPJ\s*: ?\s*([\d./\-]{14,18})',
        ]
        for pattern in patterns:
            match = re.search(pattern, first_page_content, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_validity_year(first_page_content: str) -> str | None:
        if not first_page_content:
            return None

        patterns = [
            r'Vig[êe]ncia\s*: ?\s*(\d{4})',
            r'Vig[êe]ncia\s+do\s+FAP\s*: ?\s*(\d{4})',
            r'Vig[êe]ncia\s*:?\s*(?:\n\s*)?(\d{4})',
            r'Ano\s+de\s+Vig[êe]ncia\s*:?\s*(\d{4})',
        ]
        for pattern in patterns:
            match = re.search(pattern, first_page_content, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_protocol_number(first_page_content: str) -> str | None:
        if not first_page_content:
            return None

        patterns = [
            r'N[uú]mero\s+do\s+Protocolo\s*: ?\s*([A-Za-z0-9./\-]+)',
            r'Protocolo\s*(?:n[oº°.]?|n[uú]mero)?\s*: ?\s*([A-Za-z0-9./\-]+)',
            r'N[uú]mero\s+do\s+Protocolo\s*:?\s*(?:\n\s*)?([A-Za-z0-9./\-]+)',
            r'Protocolo\s*:?\s*(?:\n\s*)?([A-Za-z0-9./\-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, first_page_content, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_process_status(first_page_content: str) -> str | None:
        if not first_page_content:
            return None

        patterns = [
            r'Situa[cç][aã]o\s+do\s+Processo\s*: ?\s*([^\n]+)',
            r'Situa[cç][aã]o\s*: ?\s*([^\n]+)',
            r'Status\s+do\s+Processo\s*:?\s*([^\n]+)',
            r'Situa[cç][aã]o\s+do\s+Processo\s*:?\s*(?:\n\s*)?([^\n]+)',
            r'Status\s+do\s+Processo\s*:?\s*(?:\n\s*)?([^\n]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, first_page_content, flags=re.IGNORECASE)
            if match:
                value = re.sub(r'\s+', ' ', match.group(1)).strip(' :-\n\t')
                if value:
                    return value
        return None

    @staticmethod
    def _extract_administrative_instance(first_page_content: str) -> str | None:
        if not first_page_content:
            return None

        patterns = [
            r'Inst[âa]ncia\s*:?\s*([^\n]+)',
            r'Inst[âa]ncia\s+Administrativ[ao]\s*:?\s*([^\n]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, first_page_content, flags=re.IGNORECASE)
            if match:
                value = re.sub(r'\s+', ' ', match.group(1)).strip(' :-\n\t')
                if value:
                    return FapContestationJudgmentMetadataAgent._normalize_administrative_instance(value)
        return None

    @staticmethod
    def _normalize_administrative_instance(value: str | None) -> str | None:
        if not value:
            return None

        normalized = re.sub(r'\s+', ' ', str(value)).strip(' :-\n\t')
        normalized = re.sub(r'^Administrativo\s+', '', normalized, flags=re.IGNORECASE)
        return normalized or None

    @staticmethod
    def _extract_analyst_name(first_page_content: str) -> str | None:
        if not first_page_content:
            return None

        match = re.search(r'Analista\s+Respons[aá]vel\s*:?\s*([^\n]+)', first_page_content, flags=re.IGNORECASE)
        if not match:
            return None

        value = re.sub(r'\s+', ' ', match.group(1)).strip(' :-\n\t')
        return value or None

    @staticmethod
    def _extract_analysis_finished_at(first_page_content: str) -> str | None:
        if not first_page_content:
            return None

        match = re.search(
            r'An[aá]lise\s+Finalizada\s+Em\s*:?\s*(\d{2}/\d{2}/\d{4})',
            first_page_content,
            flags=re.IGNORECASE,
        )
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_version_number(first_page_content: str) -> str | None:
        if not first_page_content:
            return None

        patterns = [
            r'N[ºo°]\s*Vers[aã]o\s*:?\s*([^\n]+)',
            r'Vers[aã]o\s*:?\s*([^\n]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, first_page_content, flags=re.IGNORECASE)
            if match:
                value = re.sub(r'\s+', ' ', match.group(1)).strip(' :-\n\t')
                if value:
                    return value
        return None

    def _extract_metadata_with_regex(self, first_page_content: str) -> FapContestationJudgmentMetadata:
        return FapContestationJudgmentMetadata(
            establishment_cnpj=self._extract_establishment_cnpj(first_page_content),
            validity_year=self._extract_validity_year(first_page_content),
            process_status=self._extract_process_status(first_page_content),
            protocol_number=self._extract_protocol_number(first_page_content),
            administrative_instance=self._extract_administrative_instance(first_page_content),
            analyst_name=self._extract_analyst_name(first_page_content),
            analysis_finished_at=self._extract_analysis_finished_at(first_page_content),
            version_number=self._extract_version_number(first_page_content),
            transmission_datetime=self._extract_transmission_datetime(first_page_content),
            publication_date=self._extract_publication_date(first_page_content),
        )

    def _has_all_required_fields_for_regex_only(self, metadata: FapContestationJudgmentMetadata) -> bool:
        for field_name in self.REQUIRED_FIELDS_FOR_REGEX_ONLY:
            if not getattr(metadata, field_name, None):
                return False
        return True

    def extract_from_first_page(self, markdown_content: str) -> FapContestationJudgmentMetadata:
        """Extrai metadados relevantes da primeira página do relatório em markdown."""
        first_page_content = self._extract_first_page_section(markdown_content)

        if not first_page_content:
            return FapContestationJudgmentMetadata()

        # Caminho rápido: regex cobre a maioria dos campos em milissegundos.
        regex_metadata = self._extract_metadata_with_regex(first_page_content)
        print(f'[MetadataAgent] regex_data={regex_metadata.model_dump()}')
        if self._has_all_required_fields_for_regex_only(regex_metadata):
            print('[MetadataAgent] origem=regex-only | todos os campos principais foram preenchidos por regex')
            return regex_metadata

        missing_fields = [
            field_name
            for field_name in self.REQUIRED_FIELDS_FOR_REGEX_ONLY
            if not getattr(regex_metadata, field_name, None)
        ]
        print(
            f'[MetadataAgent] origem=regex+ia | faltaram campos importantes no regex: {", ".join(missing_fields)}'
        )

        prompt = (
            'Extraia APENAS os campos solicitados da primeira página do relatório de julgamento de contestação do FAP.\n'
            'Se um campo não existir, retorne null.\n'
            'Use o texto literal encontrado no documento para os valores.\n\n'
            f'TEXTO DA PRIMEIRA PAGINA:\n{first_page_content}'
        )

        try:
            llm = ChatOpenAI(model=self.model_name, temperature=0).with_structured_output(
                FapContestationJudgmentMetadata
            )

            llm_metadata = llm.invoke([
                {
                    'role': 'system',
                    'content': (
                        'Você é um extrator de metadados documentais jurídicos. '
                        'Retorne somente os campos do schema solicitado.'
                    ),
                },
                {'role': 'user', 'content': prompt},
            ])
            print(f'[MetadataAgent] ia_data={llm_metadata.model_dump()}')
        except Exception:
            # Em erro do LLM, mantém extração determinística por regex.
            print('[MetadataAgent] origem=regex-only | falha ao consultar IA, mantendo resultado por regex')
            return regex_metadata

        # Merge: prioriza regex (mais determinístico) e completa com LLM quando faltar valor.
        merged = FapContestationJudgmentMetadata(
            establishment_cnpj=regex_metadata.establishment_cnpj or llm_metadata.establishment_cnpj,
            validity_year=regex_metadata.validity_year or llm_metadata.validity_year,
            process_status=regex_metadata.process_status or llm_metadata.process_status,
            protocol_number=regex_metadata.protocol_number or llm_metadata.protocol_number,
            administrative_instance=self._normalize_administrative_instance(
                regex_metadata.administrative_instance or llm_metadata.administrative_instance
            ),
            analyst_name=regex_metadata.analyst_name or llm_metadata.analyst_name,
            analysis_finished_at=regex_metadata.analysis_finished_at or llm_metadata.analysis_finished_at,
            version_number=regex_metadata.version_number or llm_metadata.version_number,
            transmission_datetime=regex_metadata.transmission_datetime or llm_metadata.transmission_datetime,
            publication_date=regex_metadata.publication_date or llm_metadata.publication_date,
        )

        llm_filled_fields = [
            field_name
            for field_name in merged.model_fields
            if not getattr(regex_metadata, field_name, None) and getattr(merged, field_name, None)
        ]
        if llm_filled_fields:
            print(
                f'[MetadataAgent] origem=regex+ia | IA complementou campos: {", ".join(llm_filled_fields)}'
            )
        else:
            print('[MetadataAgent] origem=regex+ia | IA chamada, mas regex já cobria os campos finais')

        return merged
