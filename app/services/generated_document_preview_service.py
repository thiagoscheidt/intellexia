"""Preview dos documentos que alimentam a geração (passo "Documentos" do wizard).

Fonte única do endpoint preview-documentos: contestação, anexos por benefício e
peças-modelo candidatas (agregadas dos trechos do retriever em camadas). A
geração NÃO usa este módulo — ela re-executa a busca restrita aos ids
confirmados.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

_LAYER_ORDER = {"juiz": 0, "vara": 1, "trf": 2, "geral": 3}

# Planos de busca do preview: mesmos kinds da geração, caps generosos para
# enumerar candidatos (o preview define o conjunto permitido, não os trechos).
_PREVIEW_SECTION_PLANS = [
    ("INTRODUCAO", [("introduction", 4), ("general", 2), ("preliminary", 2)]),
    ("PRELIMINARES", [("preliminary", 4), ("jurisprudence", 3), ("general", 2)]),
    ("MERITO", [("merit_by_thesis", 6), ("jurisprudence", 4), ("general", 2)]),
    ("PEDIDOS", [("requests", 4), ("general", 2), ("jurisprudence", 2)]),
]
_PREVIEW_THESIS_PLAN = [("merit_by_thesis", 6), ("jurisprudence", 4), ("requests", 2)]
_PREVIEW_MAX_CHUNKS = 20
_PREVIEW_MAX_CHARS = 60_000


def _chunk_layer(chunk: dict, context: dict) -> str:
    judge = (context.get("judge_name_norm") or "").strip()
    vara = (context.get("orgao_julgador_norm") or "").strip()
    trf = (context.get("trf_region") or "").strip().upper()

    if judge and (chunk.get("judge_name_norm") or "") == judge:
        return "juiz"
    vara_key = (
        "orgao_julgador_origem_norm"
        if (chunk.get("section_kind") or "") == "jurisprudence"
        else "orgao_julgador_norm"
    )
    if vara and (chunk.get(vara_key) or "") == vara:
        return "vara"
    if trf and (chunk.get("trf_region") or "").upper() == trf:
        return "trf"
    return "geral"


def aggregate_reference_candidates(chunks: list[dict], context: dict) -> list[dict]:
    """Agrega trechos por peça: melhor camada, teses únicas, contagem.

    Retorna ordenado por camada (juiz primeiro) e, dentro dela, por nº de
    trechos. Metadados de exibição (título, vara, ★) vêm do banco depois.
    """
    by_ref: dict[int, dict] = {}
    for chunk in chunks or []:
        ref_id = chunk.get("reference_id")
        if ref_id is None:
            continue
        ref_id = int(ref_id)
        entry = by_ref.setdefault(ref_id, {
            "reference_id": ref_id,
            "camada": "geral",
            "teses": [],
            "trechos": 0,
        })
        entry["trechos"] += 1
        layer = _chunk_layer(chunk, context or {})
        if _LAYER_ORDER[layer] < _LAYER_ORDER[entry["camada"]]:
            entry["camada"] = layer
        thesis = chunk.get("thesis_catalog_id")
        if thesis and thesis not in entry["teses"]:
            entry["teses"].append(thesis)

    return sorted(
        by_ref.values(),
        key=lambda item: (_LAYER_ORDER[item["camada"]], -item["trechos"], item["reference_id"]),
    )


def build_documents_preview(
    *,
    process,
    law_firm_id: int,
    document_type: str,
    parsed_selections: list[tuple[int, Optional[int]]],
    resolve_contestation_pdf: Callable,
    resolve_contestation_summary: Callable,
) -> dict:
    from app.models import (
        ImpugnacaoReferenceModel,
        JudicialLegalThesis,
        JudicialProcessBenefit,
    )
    from sqlalchemy.orm import selectinload

    is_impugnacao = document_type == "impugnacao_contestacao"

    # ── Contestação ──────────────────────────────────────────────────
    contestacao = {"aplicavel": is_impugnacao, "pdf_encontrado": False,
                   "pdf_nome": None, "resumo_encontrado": False}
    if is_impugnacao:
        try:
            pdf_path = resolve_contestation_pdf(process)
            if pdf_path:
                contestacao["pdf_encontrado"] = True
                contestacao["pdf_nome"] = os.path.basename(str(pdf_path))
            contestacao["resumo_encontrado"] = bool(
                resolve_contestation_summary(process, law_firm_id))
        except Exception as error:
            print(f"[generated_document_preview] contestação: {error}")

    # ── Anexos por benefício (mesmo filtro do worker) ────────────────
    benefit_ids = {b_id for b_id, _ in parsed_selections}
    beneficios = []
    if benefit_ids:
        benefits = (
            JudicialProcessBenefit.query
            .filter(JudicialProcessBenefit.id.in_(benefit_ids),
                    JudicialProcessBenefit.process_id == process.id)
            .options(selectinload(JudicialProcessBenefit.attachments))
            .all()
        )
        for benefit in benefits:
            anexos = [
                {"id": att.id,
                 "arquivo": att.original_filename or "",
                 "titulo": (att.description or att.original_filename or "").strip()}
                for att in (benefit.attachments or [])
                if att.is_active and (att.description or "").strip()
            ]
            beneficios.append({
                "benefit_id": benefit.id,
                "nb": benefit.benefit_number or "",
                "segurado": benefit.insured_name or "",
                "anexos": anexos,
            })

    # ── Peças-modelo candidatas (só impugnação) ──────────────────────
    referencias = None
    referencias_erro = False
    if is_impugnacao:
        try:
            from app.agents.legal_drafting.impugnacao_process_context import (
                build_reference_search_context,
            )
            from app.agents.legal_drafting.impugnacao_reference_retriever import (
                ImpugnacaoReferenceRetriever,
            )

            context = build_reference_search_context(process)
            retriever = ImpugnacaoReferenceRetriever()

            thesis_ids = {t_id for _, t_id in parsed_selections if t_id}
            theses = []
            if thesis_ids:
                theses = (
                    JudicialLegalThesis.query
                    .filter(JudicialLegalThesis.id.in_(thesis_ids),
                            JudicialLegalThesis.law_firm_id == law_firm_id)
                    .all()
                )

            all_chunks: list[dict] = []
            for section_label, kind_plan in _PREVIEW_SECTION_PLANS:
                all_chunks.extend(retriever.fetch_style_references(
                    law_firm_id=law_firm_id,
                    query_text=f"Seção da peça: {section_label} | impugnação à contestação FAP",
                    context=context,
                    kind_plan=kind_plan,
                    max_chunks=_PREVIEW_MAX_CHUNKS,
                    max_chars=_PREVIEW_MAX_CHARS,
                ))
            for thesis in theses:
                all_chunks.extend(retriever.fetch_style_references(
                    law_firm_id=law_firm_id,
                    query_text=f"Tese principal do caso: {thesis.name}",
                    context=context,
                    thesis_catalog_id=(thesis.key or None),
                    kind_plan=_PREVIEW_THESIS_PLAN,
                    max_chunks=_PREVIEW_MAX_CHUNKS,
                    max_chars=_PREVIEW_MAX_CHARS,
                ))

            aggregated = aggregate_reference_candidates(all_chunks, context)

            ref_ids = [item["reference_id"] for item in aggregated]
            refs_by_id = {}
            if ref_ids:
                refs_by_id = {
                    ref.id: ref
                    for ref in ImpugnacaoReferenceModel.query
                    .filter(ImpugnacaoReferenceModel.id.in_(ref_ids),
                            ImpugnacaoReferenceModel.law_firm_id == law_firm_id)
                    .all()
                }

            referencias = []
            for item in aggregated:
                ref = refs_by_id.get(item["reference_id"])
                if ref is None:
                    continue  # peça de outro tenant/apagada — nunca expor
                referencias.append({
                    **item,
                    "titulo": ref.title,
                    "trf_region": ref.trf_region,
                    "orgao_julgador": ref.orgao_julgador,
                    "judge_name": ref.judge_name,
                    "quality_score": float(ref.quality_score) if ref.quality_score is not None else None,
                })
        except Exception as error:
            print(f"[generated_document_preview] referências indisponíveis: {error}")
            referencias = None
            referencias_erro = True

    return {
        "contestacao": contestacao,
        "beneficios": beneficios,
        "referencias": referencias,
        "referencias_erro": referencias_erro,
    }
