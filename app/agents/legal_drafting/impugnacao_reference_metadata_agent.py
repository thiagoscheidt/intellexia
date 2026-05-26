"""Agente: extração automática de metadados de peças-modelo de impugnação.

Recebe o INÍCIO do texto da peça (após extração via DocumentProcessorService)
e devolve metadados sugeridos para preencher a `ImpugnacaoReferenceModel`:

- title (sugestão de título descritivo, sem dados sensíveis)
- case_name (razão social, se aparecer)
- trf_region (TRF1..TRF6, detectada pelo endereçamento)
- generation_mode ('A' mérito ou 'B' defesa procedimental)
- quality_score (0–5, default 3.0)

Em qualquer falha do LLM, cai para um fallback determinístico baseado no
nome do arquivo.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI


_VALID_TRF = {"TRF1", "TRF2", "TRF3", "TRF4", "TRF5", "TRF6"}
_VALID_MODE = {"A", "B"}


# Heurísticas regex de fallback para TRF caso o LLM falhe.
_TRF_REGEX_HINTS: list[tuple[str, str]] = [
    ("TRF1", r"\btrf\s*1\b|1\D{0,3}regi[aã]o|tribunal\s+regional\s+federal\s+da\s+1"),
    ("TRF2", r"\btrf\s*2\b|2\D{0,3}regi[aã]o|tribunal\s+regional\s+federal\s+da\s+2"),
    ("TRF3", r"\btrf\s*3\b|3\D{0,3}regi[aã]o|tribunal\s+regional\s+federal\s+da\s+3"),
    ("TRF4", r"\btrf\s*4\b|4\D{0,3}regi[aã]o|tribunal\s+regional\s+federal\s+da\s+4"),
    ("TRF5", r"\btrf\s*5\b|5\D{0,3}regi[aã]o|tribunal\s+regional\s+federal\s+da\s+5"),
    ("TRF6", r"\btrf\s*6\b|6\D{0,3}regi[aã]o|tribunal\s+regional\s+federal\s+da\s+6"),
]


class ImpugnacaoReferenceMetadata(BaseModel):
    title: str = Field(
        ...,
        description=(
            "Título sintético da peça (até 120 chars). Pode citar setor/segmento "
            "e ano de vigência. NUNCA inclua CPF, CNPJ, NIT ou nome de pessoa física."
        ),
    )
    case_name: Optional[str] = Field(
        None,
        description=(
            "Razão social da empresa autora, se aparecer no cabeçalho/qualificação "
            "da peça. Retorne null se não conseguir identificar."
        ),
    )
    trf_region: Optional[str] = Field(
        None,
        description=(
            "Região do TRF (TRF1..TRF6) detectada pelo endereçamento da peça. "
            "Retorne null se não conseguir identificar."
        ),
    )
    generation_mode: Optional[str] = Field(
        None,
        description=(
            "'A' se a peça é focada em MÉRITO técnico (cálculo do FAP, nexo, "
            "benefícios). 'B' se é focada em DEFESA procedimental (tempestividade, "
            "legitimidade, vícios formais). Null se não conseguir decidir."
        ),
    )
    quality_score: float = Field(
        3.0,
        description="Pontuação subjetiva de qualidade da peça de 0 a 5. Default 3.0.",
    )


_SYSTEM_PROMPT = """Você é um analista jurídico que extrai metadados de peças-modelo
de impugnação à contestação de FAP (Fator Acidentário de Prevenção).

Receberá o INÍCIO de uma peça (até 6000 caracteres) e deve devolver SOMENTE
metadados estruturados, sem inventar dados que não constam no texto.

Regras:
- title: título curto e descritivo (até 120 chars). NÃO inclua CPF, CNPJ,
  NIT ou nome de pessoa física. Pode citar setor/segmento e ano da vigência
  se aparecerem.
- case_name: razão social da empresa autora, se aparecer; null caso contrário.
- trf_region: detecte pelo endereçamento (ex.: "Justiça Federal da Seção
  Judiciária do RS" → TRF4). Use somente TRF1..TRF6 ou null.
- generation_mode: 'A' (mérito técnico predominante) ou 'B' (defesa
  procedimental predominante). Em caso de mistura com leve predomínio do
  mérito, retorne 'A'. Null somente se realmente não der para decidir.
- quality_score: 0 a 5, default 3.0.

Em qualquer dúvida, retorne null no campo opcional. Nunca invente dados."""


class ImpugnacaoReferenceMetadataAgent:
    """Extrai metadados de uma peça-modelo via LLM, com fallback determinístico."""

    def __init__(self, model_name: Optional[str] = None, temperature: float = 0.0):
        self.model_name = model_name or os.getenv(
            "IMPUGNACAO_METADATA_MODEL",
            os.getenv("QUERY_MODEL", "gpt-4o-mini"),
        )
        self.temperature = temperature

    # ── API pública ──────────────────────────────────────────────────

    def extract(
        self,
        text: str,
        *,
        original_filename: Optional[str] = None,
    ) -> ImpugnacaoReferenceMetadata:
        snippet = (text or "")[:6000].strip()
        if not snippet:
            return self._fallback(original_filename, text)

        try:
            llm = ChatOpenAI(
                model=self.model_name, temperature=self.temperature
            ).with_structured_output(ImpugnacaoReferenceMetadata)
            messages = [
                ("system", _SYSTEM_PROMPT),
                (
                    "user",
                    f"Nome do arquivo: {original_filename or '(desconhecido)'}\n\n"
                    f"TRECHO INICIAL DA PEÇA:\n\n{snippet}",
                ),
            ]
            result = llm.invoke(messages)
            return self._sanitize(result, original_filename, text)
        except Exception as error:
            print(f"[ImpugnacaoReferenceMetadataAgent] erro: {error}")
            return self._fallback(original_filename, text)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _sanitize(
        meta: ImpugnacaoReferenceMetadata,
        original_filename: Optional[str],
        full_text: Optional[str],
    ) -> ImpugnacaoReferenceMetadata:
        title = (meta.title or "").strip()
        if not title:
            title = (
                ImpugnacaoReferenceMetadataAgent._title_from_filename(original_filename)
                or "Peça-Modelo de Impugnação"
            )
        meta.title = title[:250]

        if meta.case_name is not None:
            cleaned = meta.case_name.strip()
            meta.case_name = cleaned[:250] if cleaned else None

        if meta.trf_region:
            v = meta.trf_region.strip().upper()
            meta.trf_region = v if v in _VALID_TRF else None
        if not meta.trf_region:
            meta.trf_region = ImpugnacaoReferenceMetadataAgent._detect_trf_by_regex(full_text)

        if meta.generation_mode:
            v = meta.generation_mode.strip().upper()
            meta.generation_mode = v if v in _VALID_MODE else None

        try:
            q = float(meta.quality_score)
            meta.quality_score = max(0.0, min(5.0, q))
        except (TypeError, ValueError):
            meta.quality_score = 3.0

        return meta

    @staticmethod
    def _fallback(
        original_filename: Optional[str],
        full_text: Optional[str],
    ) -> ImpugnacaoReferenceMetadata:
        return ImpugnacaoReferenceMetadata(
            title=(
                ImpugnacaoReferenceMetadataAgent._title_from_filename(original_filename)
                or "Peça-Modelo de Impugnação"
            ),
            case_name=None,
            trf_region=ImpugnacaoReferenceMetadataAgent._detect_trf_by_regex(full_text),
            generation_mode=None,
            quality_score=3.0,
        )

    @staticmethod
    def _title_from_filename(filename: Optional[str]) -> Optional[str]:
        if not filename:
            return None
        base = os.path.basename(filename)
        stem = os.path.splitext(base)[0]
        cleaned = stem.replace("_", " ").replace("-", " ").strip()
        return cleaned[:250] if cleaned else None

    @staticmethod
    def _detect_trf_by_regex(full_text: Optional[str]) -> Optional[str]:
        if not full_text:
            return None
        sample = full_text[:8000].lower()
        for trf, pattern in _TRF_REGEX_HINTS:
            if re.search(pattern, sample):
                return trf
        return None
