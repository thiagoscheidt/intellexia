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


# Ordem preferencial de seções com foco prático para impugnação:
# primeiro mérito por tese e jurisprudência, depois apoio complementar.
DEFAULT_KIND_PLAN = [
    ("merit_by_thesis", 3),
    ("jurisprudence", 2),
    ("preliminary", 1),
    ("requests", 1),
    ("general", 1),
]


class ImpugnacaoReferenceRetriever:
    """Recupera blocos de inspiração do escritório para impugnação."""

    def __init__(self, collection_name: Optional[str] = None):
        self.collection = collection_name or IMPUGNACAO_REFERENCES_COLLECTION
        self.qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=30)
        self.openai = OpenAI()

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
        thesis_catalog_id: Optional[str],
    ) -> rest.Filter:
        must: list[rest.FieldCondition] = [
            rest.FieldCondition(key="law_firm_id", match=rest.MatchValue(value=int(law_firm_id))),
            rest.FieldCondition(key="status", match=rest.MatchValue(value="active")),
        ]

        if section_kind:
            must.append(
                rest.FieldCondition(
                    key="section_kind",
                    match=rest.MatchValue(value=section_kind),
                )
            )

        if generation_mode:
            must.append(
                rest.FieldCondition(
                    key="generation_mode",
                    match=rest.MatchValue(value=generation_mode.upper()),
                )
            )

        if thesis_catalog_id:
            must.append(
                rest.FieldCondition(
                    key="thesis_catalog_id",
                    match=rest.MatchValue(value=thesis_catalog_id),
                )
            )

        should = []
        if trf_region:
            should.append(
                rest.FieldCondition(
                    key="trf_region",
                    match=rest.MatchValue(value=trf_region.upper()),
                )
            )

        return rest.Filter(must=must, should=should or None)

    def fetch_style_references(
        self,
        *,
        law_firm_id: int,
        query_text: str,
        generation_mode: Optional[str] = None,
        trf_region: Optional[str] = None,
        thesis_catalog_id: Optional[str] = None,
        kind_plan: Optional[list[tuple[str, int]]] = None,
        max_chunks: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> list[dict]:
        """Retorna lista de chunks para compor bloco de referência.

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
            vector = self._embed(query_text or "impugnacao a contestacao FAP")
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
                response = self.qdrant.query_points(
                    collection_name=self.collection,
                    query=vector,
                    query_filter=self._build_filter(
                        law_firm_id=law_firm_id,
                        section_kind=kind,
                        generation_mode=generation_mode,
                        trf_region=trf_region,
                        thesis_catalog_id=thesis_catalog_id,
                    ),
                    limit=top_k,
                    with_payload=True,
                )
            except Exception as error:
                print(f"[ImpugnacaoReferenceRetriever] Falha ao buscar kind={kind}: {error}")
                continue

            for hit in response.points:
                if hit.id in seen_ids:
                    continue
                payload = hit.payload or {}
                text = (payload.get("text") or "").strip()
                if not text:
                    continue
                if total_chars + len(text) > cap_chars and collected:
                    continue
                collected.append(
                    {
                        "section_kind": payload.get("section_kind") or kind,
                        "heading": payload.get("heading") or "",
                        "reference_title": payload.get("reference_title") or "",
                        "trf_region": payload.get("trf_region") or "",
                        "thesis_catalog_id": payload.get("thesis_catalog_id") or "",
                        "thesis_catalog_ids": payload.get("thesis_catalog_ids") or [],
                        "quality_score": payload.get("quality_score"),
                        "tribunal": payload.get("tribunal") or "",
                        "case_number": payload.get("case_number") or "",
                        "relator": payload.get("relator") or "",
                        "orgao_julgador": payload.get("orgao_julgador") or "",
                        "data_julgamento": payload.get("data_julgamento") or "",
                        "tipo_juris": payload.get("tipo_juris") or "",
                        "fundamento_principal": payload.get("fundamento_principal") or "",
                        "text": text,
                    }
                )
                seen_ids.add(hit.id)
                total_chars += len(text)
                if len(collected) >= cap_chunks or total_chars >= cap_chars:
                    break

        # Fallback amplo apenas quando nada foi encontrado no plano principal.
        if not collected and cap_chunks > 0 and total_chars < cap_chars:
            try:
                broad_response = self.qdrant.query_points(
                    collection_name=self.collection,
                    query=vector,
                    query_filter=self._build_filter(
                        law_firm_id=law_firm_id,
                        section_kind=None,
                        generation_mode=generation_mode,
                        trf_region=trf_region,
                        thesis_catalog_id=thesis_catalog_id,
                    ),
                    limit=cap_chunks,
                    with_payload=True,
                )
            except Exception as error:
                print(f"[ImpugnacaoReferenceRetriever] Falha no fallback amplo: {error}")
                broad_response = None

            for hit in (broad_response.points if broad_response else []):
                if hit.id in seen_ids:
                    continue
                payload = hit.payload or {}
                text = (payload.get("text") or "").strip()
                if not text:
                    continue
                if total_chars + len(text) > cap_chars and collected:
                    continue
                collected.append(
                    {
                        "section_kind": payload.get("section_kind") or "general",
                        "heading": payload.get("heading") or "",
                        "reference_title": payload.get("reference_title") or "",
                        "trf_region": payload.get("trf_region") or "",
                        "thesis_catalog_id": payload.get("thesis_catalog_id") or "",
                        "thesis_catalog_ids": payload.get("thesis_catalog_ids") or [],
                        "quality_score": payload.get("quality_score"),
                        "text": text,
                    }
                )
                seen_ids.add(hit.id)
                total_chars += len(text)
                if len(collected) >= cap_chunks or total_chars >= cap_chars:
                    break

        return collected

    @staticmethod
    def format_block(chunks: list[dict], include_header: bool = True) -> str:
        """Formata bloco de referências em tags úteis ao prompt de geração."""
        if not chunks:
            return ""

        categories = {
            "EXEMPLO_ESTRUTURA_TESE": [],
            "JURISPRUDENCIA_REGIONAL": [],
            "JURISPRUDENCIA_COMPLEMENTAR": [],
            "PADRAO_PEDIDO_DA_TESE": [],
            "REFERENCIAS_COMPLEMENTARES": [],
        }

        for chunk in chunks:
            kind = (chunk.get("section_kind") or "").strip().lower()
            region = (chunk.get("trf_region") or "").strip().upper()

            if kind == "merit_by_thesis":
                categories["EXEMPLO_ESTRUTURA_TESE"].append(chunk)
            elif kind == "jurisprudence":
                if region.startswith("TRF"):
                    categories["JURISPRUDENCIA_REGIONAL"].append(chunk)
                else:
                    categories["JURISPRUDENCIA_COMPLEMENTAR"].append(chunk)
            elif kind == "requests":
                categories["PADRAO_PEDIDO_DA_TESE"].append(chunk)
            else:
                categories["REFERENCIAS_COMPLEMENTARES"].append(chunk)

        parts = []
        if include_header:
            parts.extend([
                "=== REFERENCIAS JURIDICAS RELEVANTES PARA A TESE DO CASO ===",
                "Use os trechos abaixo como orientacao de estrutura argumentativa e precedentes.",
                "NAO copiar literal e NAO reaproveitar fatos especificos de outros casos.",
            ])

        def _append_tag_block(tag_name: str, tag_chunks: list[dict]) -> None:
            if not tag_chunks:
                return
            parts.append(f"\n<{tag_name}>")
            for idx, chunk in enumerate(tag_chunks, start=1):
                meta = []
                section_kind = chunk.get("section_kind")
                trf_region = chunk.get("trf_region")
                quality = chunk.get("quality_score")
                heading = (chunk.get("heading") or "").strip()

                if section_kind:
                    meta.append(f"secao: {section_kind}")
                if trf_region:
                    meta.append(f"regiao: {trf_region}")
                if quality is not None:
                    meta.append(f"qualidade: {quality}")

                meta_str = " | ".join(meta) if meta else "sem metadados"
                parts.append(f"[item {idx} | {meta_str}]")
                if heading:
                    parts.append(f"[heading original: {heading}]")
                parts.append(chunk["text"])
                parts.append("")
            parts.append(f"</{tag_name}>")

        _append_tag_block("EXEMPLO_ESTRUTURA_TESE", categories["EXEMPLO_ESTRUTURA_TESE"])
        _append_tag_block("JURISPRUDENCIA_REGIONAL", categories["JURISPRUDENCIA_REGIONAL"])
        _append_tag_block("JURISPRUDENCIA_COMPLEMENTAR", categories["JURISPRUDENCIA_COMPLEMENTAR"])
        _append_tag_block("PADRAO_PEDIDO_DA_TESE", categories["PADRAO_PEDIDO_DA_TESE"])
        _append_tag_block("REFERENCIAS_COMPLEMENTARES", categories["REFERENCIAS_COMPLEMENTARES"])

        if not any(categories.values()):
            return ""

        parts.append(
            "\n<INSTRUCAO_DE_USO>"
            "Priorize EXEMPLO_ESTRUTURA_TESE e JURISPRUDENCIA_REGIONAL na redacao do merito. "
            "Use JURISPRUDENCIA_COMPLEMENTAR apenas como reforco. "
            "PADRAO_PEDIDO_DA_TESE deve orientar o fechamento dos pedidos."
            "</INSTRUCAO_DE_USO>"
        )

        return "\n".join(parts)
