"""Retriever de peças-modelo de impugnação.

Busca trechos relevantes na coleção Qdrant dedicada
(IMPUGNACAO_REFERENCES_COLLECTION) usando filtro hard por law_firm_id.
"""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest


load_dotenv()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
IMPUGNACAO_REFERENCES_COLLECTION = os.getenv(
    "IMPUGNACAO_REFERENCES_COLLECTION", "impugnacao_models"
)
IMPUGNACAO_REFERENCES_MAX_CHUNKS = int(os.getenv("IMPUGNACAO_REFERENCES_MAX_CHUNKS", "6"))
IMPUGNACAO_REFERENCES_MAX_CHARS = int(os.getenv("IMPUGNACAO_REFERENCES_MAX_CHARS", "9000"))
IMPUGNACAO_REFERENCES_ENABLED = os.getenv("IMPUGNACAO_REFERENCES_ENABLED", "true").lower() == "true"


# Ordem preferencial de seções a buscar — espelha a arquitetura argumentativa
# da peça (introdução → preliminares → mérito por tese → jurisprudência →
# pedidos → encerramento).
DEFAULT_KIND_PLAN = [
    ("introduction", 1),
    ("preliminary", 1),
    ("merit_by_thesis", 2),
    ("jurisprudence", 1),
    ("requests", 1),
    ("closing", 1),
    ("general", 2),
]


class ImpugnacaoReferenceRetriever:
    """Recupera blocos de inspiração de estilo do escritório."""

    def __init__(self, collection_name: Optional[str] = None):
        self.collection = collection_name or IMPUGNACAO_REFERENCES_COLLECTION
        self.qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=30)
        self.openai = OpenAI()

    # ── Helpers ────────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        response = self.openai.embeddings.create(input=text, model=EMBEDDING_MODEL)
        return response.data[0].embedding

    def _collection_exists(self) -> bool:
        try:
            return self.qdrant.collection_exists(self.collection)
        except Exception:
            return False

    def _build_filter(
        self,
        *,
        law_firm_id: int,
        section_kind: Optional[str],
        generation_mode: Optional[str],
        trf_region: Optional[str],
    ) -> rest.Filter:
        must: list[rest.FieldCondition] = [
            rest.FieldCondition(key="law_firm_id", match=rest.MatchValue(value=int(law_firm_id))),
            rest.FieldCondition(key="status", match=rest.MatchValue(value="active")),
        ]
        if section_kind:
            must.append(rest.FieldCondition(
                key="section_kind", match=rest.MatchValue(value=section_kind)
            ))
        if generation_mode:
            must.append(rest.FieldCondition(
                key="generation_mode", match=rest.MatchValue(value=generation_mode.upper())
            ))

        should = []
        if trf_region:
            should.append(rest.FieldCondition(
                key="trf_region", match=rest.MatchValue(value=trf_region.upper())
            ))

        return rest.Filter(must=must, should=should or None)

    # ── API pública ────────────────────────────────────────────────────

    def fetch_style_references(
        self,
        *,
        law_firm_id: int,
        query_text: str,
        generation_mode: Optional[str] = None,
        trf_region: Optional[str] = None,
        kind_plan: Optional[list[tuple[str, int]]] = None,
        max_chunks: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> list[dict]:
        """Retorna lista de chunks (dicts) prontos para compor o bloco de
        inspiração no user_prompt.

        Cada item: {section_kind, heading, reference_title, trf_region,
                    quality_score, text}.
        """
        if not IMPUGNACAO_REFERENCES_ENABLED:
            return []
        if not law_firm_id:
            return []
        if not self._collection_exists():
            return []

        plan = kind_plan or DEFAULT_KIND_PLAN
        cap_chunks = max_chunks or IMPUGNACAO_REFERENCES_MAX_CHUNKS
        cap_chars = max_chars or IMPUGNACAO_REFERENCES_MAX_CHARS

        try:
            vector = self._embed(query_text or "impugnação à contestação FAP")
        except Exception as error:
            print(f"[ImpugnacaoReferenceRetriever] Falha no embedding: {error}")
            return []

        collected: list[dict] = []
        total_chars = 0
        seen_ids: set[str] = set()

        for kind, top_k in plan:
            if len(collected) >= cap_chunks or total_chars >= cap_chars:
                break
            try:
                results = self.qdrant.search(
                    collection_name=self.collection,
                    query_vector=vector,
                    query_filter=self._build_filter(
                        law_firm_id=law_firm_id,
                        section_kind=kind,
                        generation_mode=generation_mode,
                        trf_region=trf_region,
                    ),
                    limit=top_k,
                    with_payload=True,
                )
            except Exception as error:
                print(f"[ImpugnacaoReferenceRetriever] Falha ao buscar kind={kind}: {error}")
                continue

            for hit in results:
                if hit.id in seen_ids:
                    continue
                payload = hit.payload or {}
                text = (payload.get("text") or "").strip()
                if not text:
                    continue
                if total_chars + len(text) > cap_chars and collected:
                    continue
                collected.append({
                    "section_kind": payload.get("section_kind") or kind,
                    "heading": payload.get("heading") or "",
                    "reference_title": payload.get("reference_title") or "",
                    "trf_region": payload.get("trf_region") or "",
                    "quality_score": payload.get("quality_score"),
                    "text": text,
                })
                seen_ids.add(hit.id)
                total_chars += len(text)
                if len(collected) >= cap_chunks or total_chars >= cap_chars:
                    break

        # Fallback: se nenhum chunk foi encontrado por section_kind,
        # faz uma busca ampla sem filtrar seção para aproveitar bases que
        # ainda estejam majoritariamente classificadas como "general".
        if not collected and cap_chunks > 0 and total_chars < cap_chars:
            try:
                broad_results = self.qdrant.search(
                    collection_name=self.collection,
                    query_vector=vector,
                    query_filter=self._build_filter(
                        law_firm_id=law_firm_id,
                        section_kind=None,
                        generation_mode=generation_mode,
                        trf_region=trf_region,
                    ),
                    limit=cap_chunks,
                    with_payload=True,
                )
            except Exception as error:
                print(f"[ImpugnacaoReferenceRetriever] Falha no fallback amplo: {error}")
                broad_results = []

            for hit in broad_results:
                if hit.id in seen_ids:
                    continue
                payload = hit.payload or {}
                text = (payload.get("text") or "").strip()
                if not text:
                    continue
                if total_chars + len(text) > cap_chars and collected:
                    continue
                collected.append({
                    "section_kind": payload.get("section_kind") or "general",
                    "heading": payload.get("heading") or "",
                    "reference_title": payload.get("reference_title") or "",
                    "trf_region": payload.get("trf_region") or "",
                    "quality_score": payload.get("quality_score"),
                    "text": text,
                })
                seen_ids.add(hit.id)
                total_chars += len(text)
                if len(collected) >= cap_chunks or total_chars >= cap_chars:
                    break

        return collected

    @staticmethod
    def format_block(chunks: list[dict]) -> str:
        """Formata o bloco de referências para injetar no user_prompt."""
        if not chunks:
            return ""

        header = (
            "=== REFERÊNCIAS DE ESTILO DO ESCRITÓRIO ===\n"
            "Os trechos abaixo são EXEMPLOS de tom, estrutura e ritmo argumentativo "
            "de peças premium do escritório. Use APENAS como inspiração estilística.\n"
            "REGRAS ABSOLUTAS:\n"
            "  • NÃO copie literalmente nenhum trecho.\n"
            "  • NÃO reutilize fatos, nomes de empresas/segurados, CNPJs, NITs, "
            "números de processo, NB ou datas que apareçam nos exemplos.\n"
            "  • Os dados concretos da peça atual são APENAS os fornecidos nas "
            "seções 'DADOS DO PROCESSO' e 'BENEFÍCIOS E TESES'.\n"
            "  • Se um exemplo trouxer um fato que não está no caso atual, ignore-o.\n"
        )

        parts = [header]
        for idx, chunk in enumerate(chunks, start=1):
            meta = []
            if chunk.get("section_kind"):
                meta.append(f"seção: {chunk['section_kind']}")
            if chunk.get("trf_region"):
                meta.append(chunk["trf_region"])
            if chunk.get("quality_score") is not None:
                meta.append(f"qualidade {chunk['quality_score']}")
            meta_str = " | ".join(meta) if meta else "—"
            parts.append(f"\n--- Referência {idx} ({meta_str}) ---")
            heading = (chunk.get("heading") or "").strip()
            if heading:
                parts.append(f"[heading original: {heading}]")
            parts.append(chunk["text"])

        return "\n".join(parts)
