from __future__ import annotations

import re

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI


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

    def __init__(self, model_name: str = 'gpt-5-mini'):
        self.model_name = model_name

    def _extract_first_page_section(self, markdown_content: str, max_chars: int = 12000) -> str:
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

    def extract_from_first_page(self, markdown_content: str) -> FapContestationJudgmentMetadata:
        """Extrai metadados relevantes da primeira página do relatório em markdown."""
        first_page_content = self._extract_first_page_section(markdown_content)

        if not first_page_content:
            return FapContestationJudgmentMetadata()

        prompt = (
            'Extraia APENAS os campos solicitados da primeira página do relatório de julgamento de contestação do FAP.\n'
            'Se um campo não existir, retorne null.\n'
            'Use o texto literal encontrado no documento para os valores.\n\n'
            f'TEXTO DA PRIMEIRA PAGINA:\n{first_page_content}'
        )

        llm = ChatOpenAI(model=self.model_name, temperature=0).with_structured_output(
            FapContestationJudgmentMetadata
        )

        metadata = llm.invoke([
            {
                'role': 'system',
                'content': (
                    'Você é um extrator de metadados documentais jurídicos. '
                    'Retorne somente os campos do schema solicitado.'
                ),
            },
            {'role': 'user', 'content': prompt},
        ])

        # Fallback determinístico para cenários em que o LLM não retorna o campo.
        if not getattr(metadata, 'transmission_datetime', None):
            metadata.transmission_datetime = self._extract_transmission_datetime(first_page_content)

        return metadata
