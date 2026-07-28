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
        thesis_catalog_id: Optional[str],
        extra_match: Optional[dict] = None,
        allowed_reference_ids: Optional[list[int]] = None,
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

        for key, value in (extra_match or {}).items():
            must.append(rest.FieldCondition(key=key, match=rest.MatchValue(value=value)))

        if allowed_reference_ids:
            must.append(rest.FieldCondition(
                key="reference_id",
                match=rest.MatchAny(any=[int(rid) for rid in allowed_reference_ids]),
            ))

        return rest.Filter(must=must)

    @staticmethod
    def _context_layers(context: Optional[dict], section_kind: Optional[str]) -> list[dict]:
        """Filtros extras em ordem de especificidade: juiz > vara > TRF > geral.

        Para chunks de jurisprudência, a vara de ORIGEM da peça fica em
        `orgao_julgador_origem_norm` (o `orgao_julgador` é do precedente).
        """
        context = context or {}
        vara_key = (
            "orgao_julgador_origem_norm"
            if section_kind == "jurisprudence"
            else "orgao_julgador_norm"
        )
        layers: list[dict] = []
        if context.get("judge_name_norm"):
            layers.append({"judge_name_norm": context["judge_name_norm"]})
        if context.get("orgao_julgador_norm"):
            layers.append({vara_key: context["orgao_julgador_norm"]})
        if context.get("trf_region"):
            layers.append({"trf_region": str(context["trf_region"]).upper()})
        layers.append({})
        return layers

    @staticmethod
    def _hit_to_item(payload: dict, default_kind: str) -> dict:
        return {
            "reference_id": payload.get("reference_id"),
            "judge_name_norm": payload.get("judge_name_norm") or "",
            "orgao_julgador_norm": payload.get("orgao_julgador_norm") or "",
            "orgao_julgador_origem_norm": payload.get("orgao_julgador_origem_norm") or "",
            "section_kind": payload.get("section_kind") or default_kind,
            "heading": payload.get("heading") or "",
            "section": payload.get("section") or "",
            "section_normalized": payload.get("section_normalized") or "",
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
            "secao_origem": payload.get("secao_origem") or "general",
            "fundamento_principal": payload.get("fundamento_principal") or "",
            "text": (payload.get("text") or "").strip(),
        }

    def fetch_style_references(
        self,
        *,
        law_firm_id: int,
        query_text: str,
        generation_mode: Optional[str] = None,
        trf_region: Optional[str] = None,
        context: Optional[dict] = None,
        thesis_catalog_id: Optional[str] = None,
        kind_plan: Optional[list[tuple[str, int]]] = None,
        max_chunks: Optional[int] = None,
        max_chars: Optional[int] = None,
        allowed_reference_ids: Optional[list[int]] = None,
        min_distinct_references: Optional[int] = None,
    ) -> list[dict]:
        """Retorna lista de chunks para compor bloco de referência.

        Busca em camadas de especificidade decrescente (juiz > vara > TRF >
        geral), conforme `context` (formato de `build_reference_search_context`).
        Sem `context`, o kwarg `trf_region` vira contexto mínimo (compat).

        `min_distinct_references`: quando informado, o laço de camadas de cada
        kind continua descendo mesmo após cumprir a cota `top_k`, aceitando
        apenas trechos de `reference_id` ainda não visto NESTA chamada, até
        juntar N peças distintas ou esgotar as camadas. Teto rígido de
        `top_k + min_distinct_references` trechos por kind. Sem o parâmetro,
        o comportamento é idêntico ao anterior (compat).

        Cada item: {section_kind, heading, reference_title, trf_region,
        quality_score, text}.
        """
        if not IMPUGNACAO_REFERENCES_ENABLED:
            return []
        if not law_firm_id:
            return []
        if allowed_reference_ids is not None and not allowed_reference_ids:
            return []
        if not self._collection_exists():
            return []

        plan = kind_plan or DEFAULT_KIND_PLAN
        cap_chunks = max_chunks or IMPUGNACAO_REFERENCES_MAX_CHUNKS
        cap_chars = max_chars or IMPUGNACAO_REFERENCES_MAX_CHARS

        if context is None and trf_region:
            context = {"trf_region": trf_region}

        try:
            vector = self._embed(query_text or "impugnacao a contestacao FAP")
        except Exception as error:
            print(f"[ImpugnacaoReferenceRetriever] Falha no embedding: {error}")
            return []

        collected: list[dict] = []
        total_chars = 0
        seen_ids: set = set()
        distinct_refs: set = set()

        def _needs_more_distinct() -> bool:
            return (
                min_distinct_references is not None
                and len(distinct_refs) < min_distinct_references
            )

        def _query(kind: Optional[str], extra_match: dict, limit: int):
            try:
                return self.qdrant.query_points(
                    collection_name=self.collection,
                    query=vector,
                    query_filter=self._build_filter(
                        law_firm_id=law_firm_id,
                        section_kind=kind,
                        generation_mode=generation_mode,
                        thesis_catalog_id=thesis_catalog_id,
                        extra_match=extra_match,
                        allowed_reference_ids=allowed_reference_ids,
                    ),
                    limit=limit,
                    with_payload=True,
                ).points
            except Exception as error:
                print(f"[ImpugnacaoReferenceRetriever] Falha kind={kind} camada={extra_match}: {error}")
                return []

        def _collect(kind: Optional[str], top_k: int) -> None:
            nonlocal total_chars
            taken_for_kind = 0
            hard_ceiling = top_k + (min_distinct_references or 0)
            for layer in self._context_layers(context, kind):
                if len(collected) >= cap_chunks or total_chars >= cap_chars:
                    return
                if taken_for_kind >= top_k and not _needs_more_distinct():
                    return
                hits = _query(kind, layer, top_k)
                # Dentro da camada, mantém a ordem de score do Qdrant;
                # quality_score desempata.
                hits = sorted(
                    hits,
                    key=lambda h: (
                        -(getattr(h, "score", 0) or 0),
                        -float((h.payload or {}).get("quality_score") or 0),
                    ),
                )
                for hit in hits:
                    if len(collected) >= cap_chunks or total_chars >= cap_chars:
                        return
                    quota_done = taken_for_kind >= top_k
                    if quota_done and not _needs_more_distinct():
                        return
                    if taken_for_kind >= hard_ceiling:
                        return
                    if hit.id in seen_ids:
                        continue
                    item = self._hit_to_item(hit.payload or {}, kind or "general")
                    item["point_id"] = str(hit.id)
                    if not item["text"]:
                        continue
                    ref_id = item.get("reference_id")
                    # Cota do kind já cumprida: só aceita peça (reference_id)
                    # ainda não vista nesta chamada — é isso que garante
                    # exemplos de peças distintas em vez de mais trechos da
                    # mesma peça.
                    if quota_done and (ref_id is None or ref_id in distinct_refs):
                        continue
                    if total_chars + len(item["text"]) > cap_chars and collected:
                        continue
                    collected.append(item)
                    seen_ids.add(hit.id)
                    total_chars += len(item["text"])
                    taken_for_kind += 1
                    if ref_id is not None:
                        distinct_refs.add(ref_id)

        for kind, top_k in plan:
            if len(collected) >= cap_chunks or total_chars >= cap_chars:
                break
            _collect(kind, top_k)

        # Fallback amplo apenas quando nada foi encontrado no plano principal.
        if not collected and cap_chunks > 0:
            _collect(None, cap_chunks)

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
