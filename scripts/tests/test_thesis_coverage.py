"""Teste de cobertura de referências por tese (retriever stubado — sem serviços).

Rodar: uv run python scripts/tests/test_thesis_coverage.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.legal_drafting.impugnacao_thesis_coverage import (
    compute_reference_budgets,
    search_thesis_references,
)
from app.agents.legal_drafting.agent_generated_document import AgentGeneratedDocument

FAILS = []


def check(label, cond, detail=""):
    if not cond:
        FAILS.append(label)
        print(f"  ✗ {label} {detail}")
    else:
        print(f"  ✓ {label}")


CTX = {
    "trf_region": "TRF4",
    "orgao_julgador_norm": "3A VARA FEDERAL",
    "judge_name_norm": "JOAO DA SILVA",
}


class StubRetriever:
    """Substitui ImpugnacaoReferenceRetriever: devolve uma lista fixa de
    chunks (ou levanta) e registra os kwargs recebidos por fetch_style_references."""

    def __init__(self, chunks=None, raise_error=False):
        self._chunks = chunks or []
        self._raise_error = raise_error
        self.last_kwargs = None

    def fetch_style_references(self, **kwargs):
        self.last_kwargs = kwargs
        if self._raise_error:
            raise RuntimeError("qdrant indisponível")
        return list(self._chunks)


def _search(retriever, **overrides):
    kwargs = dict(
        law_firm_id=1,
        thesis_label="Apuração do Índice de Custo",
        thesis_key="apuracao_do_indice_de_custo",
        query_text="tese",
        context=CTX,
        kind_plan=[("merit_by_thesis", 5), ("jurisprudence", 2), ("requests", 1)],
        max_chunks=8,
        max_chars=4500,
        min_distinct=2,
    )
    kwargs.update(overrides)
    return search_thesis_references(retriever, **kwargs)


# ── 2 peças distintas ────────────────────────────────────────────────────
chunk_vara = {
    "reference_id": 12, "section_kind": "merit_by_thesis",
    "judge_name_norm": "", "orgao_julgador_norm": "3A VARA FEDERAL",
    "orgao_julgador_origem_norm": "", "trf_region": "TRF1", "text": "trecho vara",
}
chunk_trf = {
    "reference_id": 7, "section_kind": "merit_by_thesis",
    "judge_name_norm": "", "orgao_julgador_norm": "OUTRA VARA",
    "orgao_julgador_origem_norm": "", "trf_region": "TRF4", "text": "trecho trf",
}
retriever_2 = StubRetriever(chunks=[chunk_trf, chunk_vara])  # ordem proposital: pior camada primeiro
chunks_2, coverage_2 = _search(retriever_2)

check("2 peças distintas -> qtd_exemplos == 2", coverage_2["qtd_exemplos"] == 2, f"(veio {coverage_2})")
check("melhor camada == 'vara'", coverage_2["camada"] == "vara", f"(veio {coverage_2['camada']})")
check(
    "exemplos ordenados por camada (vara antes de trf)",
    [e["camada"] for e in coverage_2["exemplos"]] == ["vara", "trf"],
    f"(veio {coverage_2['exemplos']})",
)
check(
    "exemplos trazem os reference_id certos",
    {e["reference_id"] for e in coverage_2["exemplos"]} == {12, 7},
    f"(veio {coverage_2['exemplos']})",
)
check("sem_modelo is False", coverage_2["sem_modelo"] is False)
check("tese/tese_key propagados", coverage_2["tese"] == "Apuração do Índice de Custo"
      and coverage_2["tese_key"] == "apuracao_do_indice_de_custo")
check(
    "retriever recebeu min_distinct_references=2",
    retriever_2.last_kwargs.get("min_distinct_references") == 2,
    f"(veio {retriever_2.last_kwargs})",
)

# ── mesma peça em duas camadas diferentes -> uma entrada, melhor camada ──
chunk_ref9_trf = {
    "reference_id": 9, "section_kind": "merit_by_thesis",
    "judge_name_norm": "", "orgao_julgador_norm": "OUTRA VARA",
    "orgao_julgador_origem_norm": "", "trf_region": "TRF4", "text": "trecho 1 (trf)",
}
chunk_ref9_juiz = {
    "reference_id": 9, "section_kind": "merit_by_thesis",
    "judge_name_norm": "JOAO DA SILVA", "orgao_julgador_norm": "OUTRA VARA",
    "orgao_julgador_origem_norm": "", "trf_region": "TRF1", "text": "trecho 2 (juiz)",
}
retriever_dup = StubRetriever(chunks=[chunk_ref9_trf, chunk_ref9_juiz])
chunks_dup, coverage_dup = _search(retriever_dup)

check("peça em 2 camadas -> aparece 1 vez só", coverage_dup["qtd_exemplos"] == 1, f"(veio {coverage_dup})")
check(
    "aparece com a melhor camada ('juiz')",
    coverage_dup["exemplos"] == [{"reference_id": 9, "camada": "juiz"}],
    f"(veio {coverage_dup['exemplos']})",
)
check("camada agregada == 'juiz'", coverage_dup["camada"] == "juiz")

# ── retriever devolvendo [] -> sem_modelo ────────────────────────────────
retriever_empty = StubRetriever(chunks=[])
chunks_empty, coverage_empty = _search(retriever_empty)

check("chunks vazio", chunks_empty == [])
check("sem_modelo is True (lista vazia)", coverage_empty["sem_modelo"] is True)
check("camada is None (lista vazia)", coverage_empty["camada"] is None)
check("qtd_exemplos == 0 (lista vazia)", coverage_empty["qtd_exemplos"] == 0)
check("exemplos == [] (lista vazia)", coverage_empty["exemplos"] == [])

# ── retriever lançando exceção -> mesma coisa, sem propagar ─────────────
retriever_error = StubRetriever(raise_error=True)
try:
    chunks_error, coverage_error = _search(retriever_error)
    raised = False
except Exception:
    chunks_error, coverage_error = [], None
    raised = True

check("exceção do retriever não propaga", raised is False)
check("chunks == [] (exceção)", chunks_error == [])
check("sem_modelo is True (exceção)", coverage_error is not None and coverage_error["sem_modelo"] is True)
check("camada is None (exceção)", coverage_error is not None and coverage_error["camada"] is None)
check("qtd_exemplos == 0 (exceção)", coverage_error is not None and coverage_error["qtd_exemplos"] == 0)
check(
    "tese/tese_key preservados mesmo na falha",
    coverage_error is not None
    and coverage_error["tese"] == "Apuração do Índice de Custo"
    and coverage_error["tese_key"] == "apuracao_do_indice_de_custo",
)

# ── F1/F2 — _build_budgeted_thesis_reference_block: categorias escalam com
#    max_chars (F1) e o rodapé fixo não estoura o orçamento (F2) ──────────
_agent = AgentGeneratedDocument()

_MERIT_CHUNK = {
    "section_kind": "merit_by_thesis",
    "text": "Fundamento principal da tese, com argumentação extensa sobre o tema. " * 20,
    "heading": "Estrutura da tese",
    "trf_region": "TRF4",
    "quality_score": 0.9,
}

for _max_chars in (4500, 2200, 1500, 1200):
    _block = _agent._build_budgeted_thesis_reference_block(
        thesis_label="Apuração do Índice de Custo",
        chunks=[_MERIT_CHUNK],
        trf_region="TRF4",
        max_chars=_max_chars,
    )
    check(
        f"max_chars={_max_chars}: bloco contém EXEMPLO_ESTRUTURA_TESE",
        "EXEMPLO_ESTRUTURA_TESE" in _block,
        f"(len={len(_block)})",
    )
    check(
        f"max_chars={_max_chars}: len(bloco) <= max_chars (rodapé não estoura)",
        len(_block) <= _max_chars,
        f"(len={len(_block)}, max={_max_chars})",
    )

# ── F3 — _assemble_style_references_block: poda por prioridade ───────────
_header_blocks = ["HEADER1", "HEADER2", "HEADER3", "HEADER4"]
_section_blocks = [f'<SECAO nome="S{i}">' + ("x" * 500) + "</SECAO>" for i in range(4)]
_thesis_blocks = [f'<TESE nome="T{i}">' + ("y" * 800) + "</TESE>" for i in range(5)]

# Orçamento maior que header+teses (sem nenhuma seção), mas menor que o
# agregado completo (header+seções+teses) — força a poda a derrubar seções
# e comprova que nenhuma tese é sacrificada nesse cenário.
_header_and_theses_len = len("\n".join(_header_blocks + _thesis_blocks))
_full_len = len("\n".join(_header_blocks + _section_blocks + _thesis_blocks))
_prune_budget = _header_and_theses_len + 50
assert _prune_budget < _full_len, "cenário de teste não força poda"

_pruned_block = AgentGeneratedDocument._assemble_style_references_block(
    header_blocks=_header_blocks,
    section_blocks=_section_blocks,
    thesis_blocks=_thesis_blocks,
    max_total_chars=_prune_budget,
)
check(
    "poda por prioridade: derruba TODAS as seções",
    "<SECAO" not in _pruned_block,
    f"(veio {_pruned_block.count('<SECAO')} seção(ões))",
)
check(
    "poda por prioridade: preserva TODAS as teses",
    _pruned_block.count("<TESE") == len(_thesis_blocks),
    f"(veio {_pruned_block.count('<TESE')} de {len(_thesis_blocks)})",
)
check(
    "poda por prioridade: respeita max_total_chars sem precisar de corte bruto",
    len(_pruned_block) <= _prune_budget,
    f"(len={len(_pruned_block)}, max={_prune_budget})",
)

# ── compute_reference_budgets ────────────────────────────────────────────
MAX_TOTAL = 22000
MAX_SECTION = 2200
MAX_THESIS = 4500
N_SECTIONS = 4

for n in (1, 3, 12, 25):
    budgets = compute_reference_budgets(
        n, max_total_chars=MAX_TOTAL, max_section_chars=MAX_SECTION, max_thesis_chars=MAX_THESIS,
    )
    check(
        f"n={n}: per_thesis respeita o teto de 4500",
        budgets["per_thesis"] <= MAX_THESIS,
        f"(veio {budgets})",
    )
    check(
        f"n={n}: per_thesis*n + per_section*4 <= max_total_chars",
        budgets["per_thesis"] * n + budgets["per_section"] * N_SECTIONS <= MAX_TOTAL,
        f"(veio {budgets})",
    )

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
