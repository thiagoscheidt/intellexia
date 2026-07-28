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

# ── compute_reference_budgets ────────────────────────────────────────────
MAX_TOTAL = 22000
MAX_SECTION = 2200
MAX_THESIS = 4500
N_SECTIONS = 4

budgets_3 = compute_reference_budgets(
    3, max_total_chars=MAX_TOTAL, max_section_chars=MAX_SECTION, max_thesis_chars=MAX_THESIS,
)
check(
    "3 teses: per_thesis respeita o teto de 4500",
    budgets_3["per_thesis"] <= MAX_THESIS,
    f"(veio {budgets_3})",
)
check(
    "3 teses: orçamento total não estoura max_total_chars",
    budgets_3["per_thesis"] * 3 + budgets_3["per_section"] * N_SECTIONS <= MAX_TOTAL,
    f"(veio {budgets_3})",
)

budgets_12 = compute_reference_budgets(
    12, max_total_chars=MAX_TOTAL, max_section_chars=MAX_SECTION, max_thesis_chars=MAX_THESIS,
)
check(
    "12 teses: per_thesis cai abaixo do teto 4500",
    budgets_12["per_thesis"] < budgets_3["per_thesis"],
    f"(veio {budgets_12} vs {budgets_3})",
)
check(
    "12 teses: per_thesis nunca abaixo do piso 1200",
    budgets_12["per_thesis"] >= 1200,
    f"(veio {budgets_12})",
)
check(
    "12 teses: orçamento total não estoura max_total_chars",
    budgets_12["per_thesis"] * 12 + budgets_12["per_section"] * N_SECTIONS <= MAX_TOTAL,
    f"(veio {budgets_12})",
)

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
