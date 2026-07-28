"""Preview dos documentos que alimentam a geração (passo "Documentos" do wizard).

Fonte única do endpoint preview-documentos: contestação, anexos por benefício e
peças-modelo candidatas (agregadas dos trechos do retriever em camadas). A
geração NÃO usa este módulo — ela re-executa a busca restrita aos ids
confirmados.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from app.agents.legal_drafting.impugnacao_process_context import (
    LAYER_ORDER,
    chunk_match_layer,
)
from app.agents.legal_drafting.impugnacao_thesis_coverage import (
    search_thesis_references,
)

# Planos de busca do preview: mesmos kinds da geração, caps generosos para
# enumerar candidatos (o preview define o conjunto permitido, não os trechos).
_PREVIEW_SECTION_PLANS = [
    ("INTRODUCAO", [("introduction", 4), ("general", 2), ("preliminary", 2)]),
    ("PRELIMINARES", [("preliminary", 4), ("jurisprudence", 3), ("general", 2)]),
    ("MERITO", [("merit_by_thesis", 6), ("jurisprudence", 4), ("general", 2)]),
    ("PEDIDOS", [("requests", 4), ("general", 2), ("jurisprudence", 2)]),
]
_PREVIEW_THESIS_PLAN = [("merit_by_thesis", 6), ("jurisprudence", 15), ("requests", 2)]
_PREVIEW_GENERAL_JURISPRUDENCE_QUERY = (
    "jurisprudência FAP impugnação contestação preliminar prescrição"
)
_PREVIEW_MAX_CHUNKS = 20
_PREVIEW_MAX_CHARS = 60_000


def aggregate_reference_candidates(chunks: list[dict], context: dict) -> list[dict]:
    """Agrega trechos por peça: melhor camada, teses únicas, contagem.

    Retorna ordenado por camada (juiz primeiro) e, dentro dela, por nº de
    trechos. Metadados de exibição (título, vara, ★) vêm do banco depois.
    """
    by_ref: dict[int, dict] = {}
    seen: set = set()
    for chunk in chunks or []:
        ref_id = chunk.get("reference_id")
        if ref_id is None:
            continue
        point_id = chunk.get("point_id")
        if point_id is not None:
            if point_id in seen:
                continue
            seen.add(point_id)
        ref_id = int(ref_id)
        entry = by_ref.setdefault(ref_id, {
            "reference_id": ref_id,
            "camada": "geral",
            "teses": [],
            "trechos": 0,
        })
        entry["trechos"] += 1
        layer = chunk_match_layer(chunk, context or {})
        if LAYER_ORDER[layer] < LAYER_ORDER[entry["camada"]]:
            entry["camada"] = layer
        thesis = chunk.get("thesis_catalog_id")
        if thesis and thesis not in entry["teses"]:
            entry["teses"].append(thesis)

    return sorted(
        by_ref.values(),
        key=lambda item: (LAYER_ORDER[item["camada"]], -item["trechos"], item["reference_id"]),
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
            .order_by(JudicialProcessBenefit.id.asc())
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
    cobertura_teses: list[dict] = []
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

            # Probe explícito de disponibilidade: fetch_style_references() engole
            # falhas de Qdrant/embedding internamente e devolve [] tanto para
            # "coleção vazia" quanto para "indisponível" — sem isto, o except
            # abaixo nunca dispara para falhas reais (o usuário vê "nenhuma
            # referência encontrada" numa indisponibilidade, e reference_ids=[]
            # fica persistido travando a geração sem referências mesmo depois
            # do Qdrant voltar). Nota: coleção genuinamente inexistente ainda
            # (acervo vazio) também cai aqui como erro — aceitável e mais
            # seguro do que confirmar silenciosamente "sem referências".
            if not retriever._collection_exists():
                raise RuntimeError('coleção de referências indisponível')
            retriever._embed('impugnação à contestação FAP')

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
                thesis_chunks, thesis_coverage = search_thesis_references(
                    retriever,
                    law_firm_id=law_firm_id,
                    thesis_label=thesis.name,
                    thesis_key=(thesis.key or None),
                    query_text=f"Tese principal do caso: {thesis.name}",
                    context=context,
                    kind_plan=_PREVIEW_THESIS_PLAN,
                    max_chunks=_PREVIEW_MAX_CHUNKS,
                    max_chars=_PREVIEW_MAX_CHARS,
                    min_distinct=2,
                )
                all_chunks.extend(thesis_chunks)
                cobertura_teses.append(thesis_coverage)

            # Espelha a busca geral de jurisprudência do enriquecimento — sem
            # ela, peças ricas em jurisprudência ficavam com menos trechos no
            # preview do que na geração e podiam não bater o mínimo de
            # confirmação, sendo excluídas mesmo com o usuário confirmando tudo.
            all_chunks.extend(retriever.fetch_style_references(
                law_firm_id=law_firm_id,
                query_text=_PREVIEW_GENERAL_JURISPRUDENCE_QUERY,
                context=context,
                kind_plan=[("jurisprudence", 20)],
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

            # Badges legíveis: os chunks carregam a key do catálogo
            # (ex.: 'apuracao_do_indice_de_custo') — exibir o NOME da tese.
            thesis_name_by_key = {
                key: name
                for key, name in JudicialLegalThesis.query
                .filter(JudicialLegalThesis.law_firm_id == law_firm_id)
                .with_entities(JudicialLegalThesis.key, JudicialLegalThesis.name)
                .all()
                if key and name
            }

            referencias = []
            for item in aggregated:
                ref = refs_by_id.get(item["reference_id"])
                if ref is None:
                    continue  # peça de outro tenant/apagada — nunca expor
                referencias.append({
                    **item,
                    "teses": [
                        thesis_name_by_key.get(key, key) for key in item["teses"]
                    ],
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
            cobertura_teses = []

    return {
        "contestacao": contestacao,
        "beneficios": beneficios,
        "referencias": referencias,
        "referencias_erro": referencias_erro,
        "cobertura_teses": cobertura_teses,
    }
