"""Cobertura de referências por tese.

A unidade de cobertura de peças-modelo é a TESE, não a peça: toda tese dos
benefícios selecionados precisa de um bloco de referência, e o advogado
precisa ser avisado nominalmente quando isso não acontece. Este módulo é a
fonte única de:

- `compute_reference_budgets`: cota de caracteres por tese e por seção,
  calculada ANTES de qualquer extra, para que nenhuma tese fique sem bloco
  só porque o orçamento global (`max_total_chars`) foi consumido por ordem
  de chegada.
- `search_thesis_references`: busca por tese com escada de local (juiz >
  vara > TRF > geral) e parada por peças distintas, retornando também a
  cobertura agregada (`coverage`) consumida pelo gerador, pelo worker, pelo
  preview e pela tela.

Falha na busca de uma tese NUNCA deve interromper a geração — ver
`search_thesis_references`.
"""
from __future__ import annotations

from typing import Optional

from app.agents.legal_drafting.impugnacao_process_context import (
    LAYER_ORDER,
    chunk_match_layer,
)

# Rodapé fixo de todo bloco <TESE>...</TESE> (ver
# agent_generated_document._build_budgeted_thesis_reference_block): o texto
# de <INSTRUCAO_DE_USO> + a tag de fechamento </TESE> são anexados DEPOIS de
# preencher as categorias, fora do orçamento por categoria. Fonte única do
# tamanho desse rodapé, usada tanto para reservar espaço antes de preencher
# categorias quanto para compute_reference_budgets devolver um per_thesis
# que já reflete o que sobra para conteúdo de fato (não o rodapé fixo).
THESIS_BLOCK_FOOTER_TEXT = (
    "<INSTRUCAO_DE_USO>"
    "Priorize EXEMPLO_ESTRUTURA_TESE para estrutura argumentativa. "
    "Para JURISPRUDENCIA_REGIONAL e JURISPRUDENCIA_COMPLEMENTAR: "
    "incorpore cada decisao como citacao inline real na tese — "
    "mencione o tribunal, o numero do processo e o relator exatamente como estao no bloco. "
    "Formato sugerido: 'Conforme [Tribunal], [tipo] n. [numero], Rel. [Relator]: [trecho da ementa]'. "
    "Nao apenas mencione que existe jurisprudencia — transcreva a essencia da decisao."
    "</INSTRUCAO_DE_USO>"
)
# +2 pelas quebras de linha que "\n".join(parts) insere antes deste bloco e
# antes do "</TESE>" final.
THESIS_BLOCK_FOOTER_RESERVE_CHARS = len(THESIS_BLOCK_FOOTER_TEXT) + len("</TESE>") + 2


def compute_reference_budgets(
    n_theses: int,
    *,
    max_total_chars: int,
    max_section_chars: int,
    max_thesis_chars: int,
    n_sections: int = 4,
    min_thesis_chars: int = 1200,
    footer_reserve_chars: int = THESIS_BLOCK_FOOTER_RESERVE_CHARS,
) -> dict:
    """Cota por tese ANTES de qualquer extra — nenhuma tese fica sem bloco.

    Retorna {'per_thesis': int, 'per_section': int}. `per_thesis` já desconta
    `footer_reserve_chars` (o rodapé fixo de cada bloco de tese, ver
    THESIS_BLOCK_FOOTER_RESERVE_CHARS) para refletir o que sobra para
    conteúdo de fato.
    """
    n = max(1, n_theses)
    if n * min_thesis_chars > max_total_chars:
        # O piso multiplicado por n não cabe no orçamento total: cede o piso
        # (em vez de estourar max_total_chars) e nada sobra para seções.
        per_thesis = max(0, max_total_chars // n)
        per_section = 0
    else:
        sections_reserve = min(n_sections * max_section_chars, int(max_total_chars * 0.4))
        thesis_pool = max_total_chars - sections_reserve
        per_thesis = max(min_thesis_chars, min(max_thesis_chars, thesis_pool // n))
        sections_pool = max(0, max_total_chars - per_thesis * n)
        per_section = min(max_section_chars, sections_pool // max(1, n_sections))

    per_thesis = max(0, per_thesis - footer_reserve_chars)
    return {"per_thesis": int(per_thesis), "per_section": int(per_section)}


def search_thesis_references(
    retriever,
    *,
    law_firm_id: int,
    thesis_label: str,
    thesis_key: Optional[str],
    query_text: str,
    context: Optional[dict],
    kind_plan: list[tuple[str, int]],
    max_chunks: int,
    max_chars: int,
    allowed_reference_ids: Optional[list[int]] = None,
    min_distinct: int = 2,
) -> tuple[list[dict], dict]:
    """Busca por tese com escada de local e parada por peças distintas.

    Retorna (chunks, coverage). Falha do retriever -> ([], coverage sem_modelo).
    """
    try:
        chunks = retriever.fetch_style_references(
            law_firm_id=law_firm_id,
            query_text=query_text,
            context=context,
            thesis_catalog_id=(thesis_key or None),
            kind_plan=kind_plan,
            max_chunks=max_chunks,
            max_chars=max_chars,
            allowed_reference_ids=allowed_reference_ids,
            min_distinct_references=min_distinct,
        )
    except Exception as error:
        print(
            f"[impugnacao_thesis_coverage] Falha na busca da tese "
            f"'{thesis_label}': {error}"
        )
        return [], _build_coverage(thesis_label, thesis_key, [], context)

    return chunks, _build_coverage(thesis_label, thesis_key, chunks, context)


def _build_coverage(
    thesis_label: str,
    thesis_key: Optional[str],
    chunks: list[dict],
    context: Optional[dict],
) -> dict:
    """Agrega chunks recuperados numa peça: melhor camada por reference_id."""
    context = context or {}
    best_layer_by_ref: dict[int, str] = {}
    for chunk in chunks or []:
        ref_id = chunk.get("reference_id")
        if ref_id is None:
            continue
        ref_id = int(ref_id)
        layer = chunk_match_layer(chunk, context)
        current = best_layer_by_ref.get(ref_id)
        if current is None or LAYER_ORDER[layer] < LAYER_ORDER[current]:
            best_layer_by_ref[ref_id] = layer

    exemplos = [
        {"reference_id": ref_id, "camada": layer}
        for ref_id, layer in sorted(
            best_layer_by_ref.items(),
            key=lambda item: (LAYER_ORDER[item[1]], item[0]),
        )
    ]

    melhor_camada = exemplos[0]["camada"] if exemplos else None

    return {
        "tese": thesis_label,
        "tese_key": thesis_key or None,
        "exemplos": exemplos,
        "camada": melhor_camada,
        "qtd_exemplos": len(exemplos),
        "sem_modelo": not exemplos,
    }
