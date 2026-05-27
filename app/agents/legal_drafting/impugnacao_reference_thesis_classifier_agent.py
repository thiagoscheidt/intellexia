"""Agente de IA para classificar teses jurídicas em peças-modelo de impugnação.

Objetivo:
- Ler o arquivo completo da peça (PDF/DOCX/TXT) via payload de arquivo.
- Classificar teses do documento conforme o catálogo do escritório.
- Classificar teses por chunk (order_in_doc) para indexação no RAG.
"""

from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from app.agents.config import DEFAULT_MODEL_MINI
from app.agents.core.file_agent import FileAgent


class ChunkThesisClassification(BaseModel):
    order_in_doc: int = Field(description="Índice do chunk no documento (order_in_doc).")
    thesis_catalog_ids: list[str] = Field(
        default_factory=list,
        description="Lista de keys de teses do catálogo aplicáveis ao chunk.",
    )


class ImpugnacaoReferenceThesisClassification(BaseModel):
    document_thesis_catalog_ids: list[str] = Field(
        default_factory=list,
        description="Lista de keys de teses aplicáveis ao documento inteiro.",
    )
    chunk_classifications: list[ChunkThesisClassification] = Field(
        default_factory=list,
        description="Classificação por chunk usando order_in_doc.",
    )


_SYSTEM_PROMPT = """Você é um classificador jurídico para peças de impugnação à contestação (FAP).

Sua tarefa é classificar teses SOMENTE usando as keys do catálogo fornecido.

Regras obrigatórias:
- Use apenas keys existentes no catálogo.
- Não invente tese nova.
- Se não houver evidência suficiente, retorne lista vazia para o item.
- Classifique no máximo 10 teses no documento e no máximo 5 teses por chunk.
- O campo order_in_doc deve corresponder exatamente aos chunks enviados.
"""


class ImpugnacaoReferenceThesisClassifierAgent:
    """Classifica teses por documento e por chunk usando LLM mini + arquivo completo."""

    def __init__(self, model_name: Optional[str] = None, temperature: float = 0.0):
        self.model_name = model_name or os.getenv(
            "IMPUGNACAO_THESIS_CLASSIFIER_MODEL",
            DEFAULT_MODEL_MINI,
        )
        self.temperature = temperature

    @staticmethod
    def _build_chunk_context(segments: list[dict]) -> str:
        lines: list[str] = []
        for order, seg in enumerate(segments):
            heading = str(seg.get('heading') or '').strip()
            section_kind = str(seg.get('section_kind') or '').strip()
            page = seg.get('page')
            chunk_text = str(seg.get('text') or '').strip()
            preview = chunk_text[:700]
            lines.append(
                f"[chunk order_in_doc={order}] page={page} section_kind={section_kind} heading={heading}\n"
                f"preview: {preview}"
            )
        return "\n\n".join(lines)

    @staticmethod
    def _build_catalog_context(thesis_catalog: list[dict]) -> str:
        lines = []
        for thesis in thesis_catalog:
            key = str(thesis.get('key') or '').strip()
            name = str(thesis.get('name') or '').strip()
            if not key or not name:
                continue
            lines.append(f"- key={key} | name={name}")
        return "\n".join(lines)

    def classify(
        self,
        *,
        file_path: str,
        thesis_catalog: list[dict],
        segments: list[dict],
    ) -> ImpugnacaoReferenceThesisClassification:
        if not file_path:
            return ImpugnacaoReferenceThesisClassification()
        if not thesis_catalog:
            return ImpugnacaoReferenceThesisClassification()
        if not segments:
            return ImpugnacaoReferenceThesisClassification()

        catalog_context = self._build_catalog_context(thesis_catalog)
        chunks_context = self._build_chunk_context(segments)
        if not catalog_context or not chunks_context:
            return ImpugnacaoReferenceThesisClassification()

        file_part = FileAgent().build_openrouter_file_part(file_path)

        user_prompt = (
            "CATÁLOGO DE TESES DISPONÍVEIS (use somente as keys):\n"
            f"{catalog_context}\n\n"
            "CHUNKS DA PEÇA PARA CLASSIFICAÇÃO:\n"
            f"{chunks_context}\n\n"
            "Retorne as teses do documento inteiro e também por chunk (order_in_doc)."
        )

        llm = ChatOpenAI(
            model=self.model_name,
            temperature=self.temperature,
        ).with_structured_output(ImpugnacaoReferenceThesisClassification)

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    file_part,
                ],
            },
        ]

        result = llm.invoke(messages)
        return self._sanitize(result, thesis_catalog, len(segments))

    @staticmethod
    def _sanitize(
        result: ImpugnacaoReferenceThesisClassification,
        thesis_catalog: list[dict],
        total_segments: int,
    ) -> ImpugnacaoReferenceThesisClassification:
        valid_keys = {
            str(item.get('key') or '').strip()
            for item in thesis_catalog
            if str(item.get('key') or '').strip()
        }

        def _clean_keys(values: list[str], limit: int) -> list[str]:
            cleaned: list[str] = []
            seen = set()
            for item in values or []:
                key = str(item or '').strip()
                if not key or key not in valid_keys or key in seen:
                    continue
                seen.add(key)
                cleaned.append(key)
                if len(cleaned) >= limit:
                    break
            return cleaned

        result.document_thesis_catalog_ids = _clean_keys(result.document_thesis_catalog_ids, limit=10)

        normalized_chunks: list[ChunkThesisClassification] = []
        seen_orders = set()
        for chunk in result.chunk_classifications or []:
            try:
                order = int(chunk.order_in_doc)
            except Exception:
                continue
            if order < 0 or order >= total_segments or order in seen_orders:
                continue
            seen_orders.add(order)
            normalized_chunks.append(
                ChunkThesisClassification(
                    order_in_doc=order,
                    thesis_catalog_ids=_clean_keys(chunk.thesis_catalog_ids, limit=5),
                )
            )

        result.chunk_classifications = normalized_chunks
        return result
