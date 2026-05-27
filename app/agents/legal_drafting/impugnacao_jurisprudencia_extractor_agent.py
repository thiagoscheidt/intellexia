"""Agente de extração de jurisprudências embutidas em peças-modelo de impugnação.

Recebe o PDF/DOCX completo e retorna todos os blocos jurisprudenciais encontrados,
incluindo citações indiretas, ementas sem prefixo EMENTA:, acórdãos transcritos e
fundamentos jurisprudenciais narrativos.
"""

from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from app.agents.config import DEFAULT_MODEL_ROBUST
from app.agents.core.file_agent import FileAgent


TIPOS_VALIDOS = {
    "ementa",
    "trecho_recuado",
    "citacao_indireta",
    "acordao_transcrito",
    "ratio_decidendi",
    "fundamento_jurisprudencial",
}

SECOES_VALIDAS = {
    "introduction",
    "preliminary",
    "merit_by_thesis",
    "requests",
    "general",
}


class JurisprudenciaExtraida(BaseModel):
    texto_integral: str = Field(
        description="Texto COMPLETO do bloco jurisprudencial sem cortes, incluindo ementa, ratio decidendi e atribuição."
    )
    tribunal: Optional[str] = Field(
        default=None,
        description="Sigla do tribunal. Ex: TRF4, STJ, STF, TRF2, TRF3.",
    )
    processo: Optional[str] = Field(
        default=None,
        description="Número do processo. Ex: 5015482-56.2021.4.04.7100.",
    )
    relator: Optional[str] = Field(
        default=None,
        description="Nome do relator conforme consta no documento.",
    )
    orgao_julgador: Optional[str] = Field(
        default=None,
        description="Turma ou câmara julgadora. Ex: 2ª Turma.",
    )
    data_julgamento: Optional[str] = Field(
        default=None,
        description="Data do julgamento no formato encontrado no documento.",
    )
    tipo: str = Field(
        description=(
            "Tipo da citação. Use um dos valores: "
            "ementa | trecho_recuado | citacao_indireta | acordao_transcrito | "
            "ratio_decidendi | fundamento_jurisprudencial"
        )
    )
    secao_origem: str = Field(
        default="general",
        description=(
            "Seção da peça de onde a jurisprudência foi extraída. Use um dos valores: "
            "introduction (qualificação, abertura, síntese dos fatos) | "
            "preliminary (preliminares, ilegitimidade, prescrição, prejudiciais) | "
            "merit_by_thesis (mérito, teses de impugnação, fundamentos de direito) | "
            "requests (pedidos, requerimentos finais) | "
            "general (não identificado ou transversal)"
        ),
    )
    fundamento_principal: Optional[str] = Field(
        default=None,
        description="Resumo em uma linha do entendimento central da jurisprudência.",
    )
    palavras_chave: list[str] = Field(
        default_factory=list,
        description="Palavras-chave jurídicas relevantes para busca semântica.",
    )


class JurisprudenciasExtraidas(BaseModel):
    jurisprudencias: list[JurisprudenciaExtraida] = Field(
        default_factory=list,
        description="Lista completa de todas as jurisprudências encontradas no documento.",
    )


_SYSTEM_PROMPT = """Você é um sistema especializado em extração de jurisprudência de peças jurídicas.

Analise o documento integralmente considerando:
- estrutura visual, recuos e formatação
- blocos destacados e trechos centralizados
- continuidade de citações entre páginas
- ementas com ou sem o prefixo "EMENTA:"
- acórdãos transcritos, ratio decidendi e trechos entre aspas
- citações indiretas e fundamentos jurisprudenciais narrativos

Considere como jurisprudência QUALQUER trecho que:
- cite tribunal, processo ou julgado — mesmo sem identificação completa
- reproduza entendimento judicial
- transcreva decisão, ementa, fundamentos do julgado ou voto
- reproduza ratio decidendi
- inicie com "No referido julgado", "No mesmo sentido", "Conforme entendimento",
  "A jurisprudência entende", "Assim decidiu", "conforme precedente"
- continue jurisprudência iniciada em página anterior

Para cada jurisprudência:
- Extraia o texto INTEGRAL sem cortes — nunca resuma nem truncue
- Identifique tribunal, processo, relator, órgão julgador e data quando disponíveis
- Classifique o tipo conforme os valores permitidos
- Gere palavras-chave jurídicas relevantes para busca semântica
- Sintetize o fundamento central em uma linha

PROIBIDO:
- Resumir ou cortar trechos de jurisprudência
- Omitir jurisprudências longas
- Agrupar jurisprudências distintas em um único item
- Inventar dados que não constam no documento
""".strip()


class ImpugnacaoJurisprudenciaExtractorAgent:
    """Extrai todos os blocos jurisprudenciais de uma peça-modelo usando LLM + arquivo completo."""

    def __init__(self, model_name: Optional[str] = None, temperature: float = 0.0):
        self.model_name = model_name or os.getenv(
            "IMPUGNACAO_JURIS_EXTRACTOR_MODEL",
            DEFAULT_MODEL_ROBUST,
        )
        self.temperature = temperature

    def extract(self, file_path: str) -> list[JurisprudenciaExtraida]:
        """Recebe o caminho do arquivo e retorna lista de jurisprudências extraídas."""
        if not file_path:
            return []

        try:
            file_part = FileAgent().build_openrouter_file_part(file_path)
        except Exception as error:
            print(f"[JurisprudenciaExtractorAgent] Falha ao preparar arquivo: {error}")
            return []

        llm = ChatOpenAI(
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=16000,
        ).with_structured_output(JurisprudenciasExtraidas)

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Extraia TODAS as jurisprudências deste documento. "
                            "Não omita nenhuma, independentemente do formato ou comprimento."
                        ),
                    },
                    file_part,
                ],
            },
        ]

        try:
            result: JurisprudenciasExtraidas = llm.invoke(messages)
            sanitized = self._sanitize(result)
            print(
                f"[JurisprudenciaExtractorAgent] {len(sanitized)} jurisprudência(s) extraída(s) de {file_path}"
            )
            return sanitized
        except Exception as error:
            print(f"[JurisprudenciaExtractorAgent] Falha na extração: {error}")
            return []

    @staticmethod
    def _sanitize(result: JurisprudenciasExtraidas) -> list[JurisprudenciaExtraida]:
        sanitized: list[JurisprudenciaExtraida] = []
        seen: set[str] = set()

        for item in result.jurisprudencias or []:
            text = (item.texto_integral or "").strip()
            if not text or len(text) < 60:
                continue

            # Deduplicação por início do texto
            key = text[:120].lower()
            if key in seen:
                continue
            seen.add(key)

            # Normaliza tipo
            tipo = (item.tipo or "").strip().lower()
            if tipo not in TIPOS_VALIDOS:
                tipo = "fundamento_jurisprudencial"
            item.tipo = tipo

            # Normaliza secao_origem
            secao = (item.secao_origem or "").strip().lower()
            if secao not in SECOES_VALIDAS:
                secao = "general"
            item.secao_origem = secao

            # Limpa campos opcionais
            item.tribunal = (item.tribunal or "").strip().upper() or None
            item.processo = (item.processo or "").strip() or None
            item.relator = (item.relator or "").strip() or None
            item.orgao_julgador = (item.orgao_julgador or "").strip() or None
            item.data_julgamento = (item.data_julgamento or "").strip() or None
            item.fundamento_principal = (item.fundamento_principal or "").strip() or None
            item.palavras_chave = [
                w.strip() for w in (item.palavras_chave or []) if (w or "").strip()
            ][:12]

            sanitized.append(item)

        return sanitized
