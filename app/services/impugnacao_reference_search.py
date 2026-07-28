"""Busca textual das peças-modelo de impugnação (Meilisearch).

Índice dedicado, sincronizado nos mesmos pontos que o Qdrant (ingestão,
reindexação, arquivar/reativar, exclusão). Papel: busca por termo exato /
texto livre na TELA — a geração continua 100% Qdrant. Falhas aqui nunca
abortam o fluxo principal (a fonte crítica é o Qdrant).
"""
from __future__ import annotations

import os
import re

from dotenv import load_dotenv
from meilisearch_python_sdk import Client as MeilisearchClient

load_dotenv()

MEILISEARCH_HOST = os.getenv("MEILISEARCH_HOST", "http://localhost:7700")
MEILISEARCH_API_KEY = os.getenv("MEILISEARCH_API_KEY")
IMPUGNACAO_REFERENCES_MEILI_INDEX = os.getenv(
    "IMPUGNACAO_REFERENCES_MEILI_INDEX", "impugnacao_references"
)

_FILTERABLE = ["law_firm_id", "status", "trf_region", "section_kind",
               "thesis_catalog_id", "reference_id"]
_SEARCHABLE = ["text", "section", "heading", "reference_title",
               "judge_name", "orgao_julgador", "process_number"]
_VALID_TRF_REGIONS = {f"TRF{n}" for n in range(1, 7)}
_VALID_THESIS_KEY_RE = re.compile(r"^[a-z0-9_\-]+$")


def _get_index():
    client = MeilisearchClient(MEILISEARCH_HOST, MEILISEARCH_API_KEY)
    index = client.get_or_create_index(uid=IMPUGNACAO_REFERENCES_MEILI_INDEX, primary_key="id")

    current_filterable = index.get_filterable_attributes() or []
    if set(current_filterable) != set(_FILTERABLE):
        task = index.update_filterable_attributes(_FILTERABLE)
        client.wait_for_task(task.task_uid, timeout_in_ms=10000)

    current_searchable = index.get_searchable_attributes() or []
    if list(current_searchable) != list(_SEARCHABLE):
        task = index.update_searchable_attributes(_SEARCHABLE)
        client.wait_for_task(task.task_uid, timeout_in_ms=10000)

    return client, index


def _build_documents(reference, chunk_records) -> list[dict]:
    documents = []
    for record in chunk_records or []:
        point_id = record.get("qdrant_point_id")
        if not point_id:
            continue
        documents.append({
            "id": str(point_id).replace("-", ""),
            "law_firm_id": int(reference.law_firm_id),
            "reference_id": int(reference.id),
            "reference_title": reference.title or "",
            "trf_region": reference.trf_region or None,
            "orgao_julgador": reference.orgao_julgador or None,
            "judge_name": reference.judge_name or None,
            "process_number": reference.process_number or None,
            "status": reference.status or "active",
            "heading": record.get("heading") or "",
            "section": record.get("section") or "",
            "section_kind": record.get("section_kind") or "general",
            "thesis_catalog_id": record.get("thesis_catalog_id"),
            "order_in_doc": record.get("order_in_doc", 0),
            "text": record.get("full_text") or record.get("preview_text") or "",
        })
    return documents


def index_reference_chunks(reference, chunk_records) -> bool:
    try:
        client, index = _get_index()
        task = index.delete_documents_by_filter(f"reference_id = {int(reference.id)}")
        client.wait_for_task(task.task_uid, timeout_in_ms=10000)
        documents = _build_documents(reference, chunk_records)
        if documents:
            task = index.add_documents(documents)
            client.wait_for_task(task.task_uid, timeout_in_ms=30000)
        return True
    except Exception as error:
        print(f"[impugnacao_reference_search] Falha ao indexar ref {reference.id}: {error}")
        return False


def delete_reference(reference_id: int) -> bool:
    try:
        client, index = _get_index()
        task = index.delete_documents_by_filter(f"reference_id = {int(reference_id)}")
        client.wait_for_task(task.task_uid, timeout_in_ms=10000)
        return True
    except Exception as error:
        print(f"[impugnacao_reference_search] Falha ao remover ref {reference_id}: {error}")
        return False


def update_reference_status(reference) -> bool:
    """Propaga o status atual (active/archived) para os documentos da peça."""
    try:
        from app.models import ImpugnacaoReferenceChunk
        client, index = _get_index()
        chunk_ids = [
            str(chunk.qdrant_point_id).replace("-", "")
            for chunk in ImpugnacaoReferenceChunk.query
            .filter_by(reference_id=reference.id).all()
            if chunk.qdrant_point_id
        ]
        if not chunk_ids:
            return True
        task = index.update_documents(
            [{"id": chunk_id, "status": reference.status} for chunk_id in chunk_ids]
        )
        client.wait_for_task(task.task_uid, timeout_in_ms=30000)
        return True
    except Exception as error:
        print(f"[impugnacao_reference_search] Falha ao atualizar status da ref {reference.id}: {error}")
        return False


def update_reference_metadata(reference) -> bool:
    """Propaga campos de metadados no nível da peça (título, TRF, vara, juiz,
    número do processo) para os documentos já indexados, sem tocar em
    texto/heading/section (partial update — mesmo padrão de
    `update_reference_status`)."""
    try:
        from app.models import ImpugnacaoReferenceChunk
        client, index = _get_index()
        chunk_ids = [
            str(chunk.qdrant_point_id).replace("-", "")
            for chunk in ImpugnacaoReferenceChunk.query
            .filter_by(reference_id=reference.id).all()
            if chunk.qdrant_point_id
        ]
        if not chunk_ids:
            return True
        task = index.update_documents([
            {
                "id": chunk_id,
                "reference_title": reference.title or "",
                "trf_region": reference.trf_region or None,
                "orgao_julgador": reference.orgao_julgador or None,
                "judge_name": reference.judge_name or None,
                "process_number": reference.process_number or None,
            }
            for chunk_id in chunk_ids
        ])
        client.wait_for_task(task.task_uid, timeout_in_ms=30000)
        return True
    except Exception as error:
        print(f"[impugnacao_reference_search] Falha ao atualizar metadados da ref {reference.id}: {error}")
        return False


def search_chunks(law_firm_id: int, query: str, *, status: str = "active",
                  trf_region: str | None = None,
                  thesis_catalog_id: str | None = None,
                  limit: int = 30) -> list[dict] | None:
    """Busca textual multi-tenant. Retorna hits crus do Meilisearch.

    [] = busca ok sem resultados; None = Meilisearch indisponível.
    """
    if not law_firm_id or not (query or "").strip():
        return []
    try:
        _, index = _get_index()
        filters = [f"law_firm_id = {int(law_firm_id)}"]
        if status in ("active", "archived"):
            filters.append(f"status = '{status}'")
        if trf_region and trf_region.strip().upper() in _VALID_TRF_REGIONS:
            filters.append(f"trf_region = '{trf_region.strip().upper()}'")
        if thesis_catalog_id and _VALID_THESIS_KEY_RE.match(thesis_catalog_id.strip()):
            filters.append(f"thesis_catalog_id = '{thesis_catalog_id.strip()}'")
        result = index.search(
            query.strip(),
            filter=" AND ".join(filters),
            limit=limit,
            attributes_to_highlight=["text", "section", "reference_title"],
            attributes_to_crop=["text"],
            crop_length=40,
            highlight_pre_tag="",
            highlight_post_tag="",
        )
        hits = result.hits or []
        for hit in hits:
            formatted = hit.get("_formatted") or {}
            cropped_text = formatted.get("text")
            if cropped_text is not None:
                hit["text"] = cropped_text
        return hits
    except Exception as error:
        print(f"[impugnacao_reference_search] Falha na busca: {error}")
        return None
