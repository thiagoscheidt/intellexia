"""Teste da busca em camadas do retriever, com Qdrant e embedding stubados.

Rodar: uv run python scripts/tests/test_impugnacao_layered_retrieval.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.legal_drafting.impugnacao_reference_retriever import (
    ImpugnacaoReferenceRetriever,
)

FAILS = []


def check(label, cond, detail=""):
    if not cond:
        FAILS.append(label)
        print(f"  ✗ {label} {detail}")
    else:
        print(f"  ✓ {label}")


def make_point(pid, text, **payload):
    payload.setdefault("section_kind", "merit_by_thesis")
    payload["text"] = text
    return SimpleNamespace(id=pid, score=0.9, payload=payload)


POINTS = [
    make_point("p-judge", "trecho do mesmo juiz", judge_name_norm="JOAO DA SILVA",
               orgao_julgador_norm="3A VARA FEDERAL", trf_region="TRF4"),
    make_point("p-vara", "trecho da mesma vara", judge_name_norm=None,
               orgao_julgador_norm="3A VARA FEDERAL", trf_region="TRF4"),
    make_point("p-trf", "trecho do mesmo trf", judge_name_norm=None,
               orgao_julgador_norm="OUTRA VARA", trf_region="TRF4"),
    make_point("p-geral", "trecho geral", judge_name_norm=None,
               orgao_julgador_norm=None, trf_region="TRF1"),
]

# Pontos de jurisprudência: para esse section_kind, a camada de "vara" usa
# orgao_julgador_origem_norm (vara de ORIGEM da peça), não orgao_julgador_norm
# (que no payload de jurisprudência é o órgão do precedente, não da origem).
JURIS_POINTS = [
    make_point("j-origem", "trecho juris da mesma origem", section_kind="jurisprudence",
               judge_name_norm=None, orgao_julgador_norm="OUTRO ORGAO (PRECEDENTE)",
               orgao_julgador_origem_norm="3A VARA FEDERAL", trf_region="TRF4"),
    make_point("j-decoy", "trecho juris de outra origem", section_kind="jurisprudence",
               judge_name_norm=None, orgao_julgador_norm="3A VARA FEDERAL",
               orgao_julgador_origem_norm="OUTRA ORIGEM QUALQUER", trf_region="TRF4"),
]


class StubQdrant:
    """Aplica as FieldConditions `must` do filtro sobre POINTS em memória."""

    def collection_exists(self, name):
        return True

    def query_points(self, collection_name, query, query_filter, limit, with_payload):
        conditions = []
        for cond in (query_filter.must or []):
            conditions.append((cond.key, cond.match.value))
        hits = []
        for point in POINTS + JURIS_POINTS:
            payload = dict(point.payload)
            payload.setdefault("law_firm_id", 1)
            payload.setdefault("status", "active")
            if all(payload.get(k) == v for k, v in conditions):
                hits.append(point)
        return SimpleNamespace(points=hits[:limit])


retriever = ImpugnacaoReferenceRetriever.__new__(ImpugnacaoReferenceRetriever)
retriever.collection = "stub"
retriever.qdrant = StubQdrant()
retriever._embed = lambda text: [0.0]

CTX = {
    "trf_region": "TRF4",
    "orgao_julgador": "3ª Vara Federal", "orgao_julgador_norm": "3A VARA FEDERAL",
    "judge_name": "João da Silva", "judge_name_norm": "JOAO DA SILVA",
}

# Com contexto completo: mesmo juiz vem primeiro, depois vara, depois TRF.
result = retriever.fetch_style_references(
    law_firm_id=1, query_text="tese", context=CTX,
    kind_plan=[("merit_by_thesis", 3)], max_chunks=3, max_chars=50_000,
)
texts = [r["text"] for r in result]
check("3 resultados", len(result) == 3, f"(veio {len(result)})")
check("juiz primeiro", texts and texts[0] == "trecho do mesmo juiz", f"(ordem: {texts})")
check("vara em segundo", len(texts) > 1 and texts[1] == "trecho da mesma vara", f"(ordem: {texts})")
check("trf em terceiro", len(texts) > 2 and texts[2] == "trecho do mesmo trf", f"(ordem: {texts})")
check("sem duplicatas", len(set(texts)) == len(texts))

# Sem contexto algum: ainda retorna (camada geral).
result_geral = retriever.fetch_style_references(
    law_firm_id=1, query_text="tese",
    kind_plan=[("merit_by_thesis", 4)], max_chunks=4, max_chars=50_000,
)
check("fallback geral nunca vazio", len(result_geral) == 4, f"(veio {len(result_geral)})")

# Contexto só com TRF (compat: kwarg trf_region antigo).
result_trf = retriever.fetch_style_references(
    law_firm_id=1, query_text="tese", trf_region="TRF4",
    kind_plan=[("merit_by_thesis", 2)], max_chunks=2, max_chars=50_000,
)
trf_texts = [r["text"] for r in result_trf]
check("kwarg trf_region prioriza TRF4", all("geral" not in t for t in trf_texts), f"(ordem: {trf_texts})")

# Jurisprudência: a camada de "vara" deve usar orgao_julgador_origem_norm
# (vara de origem da peça), não orgao_julgador_norm (órgão do precedente).
result_juris = retriever.fetch_style_references(
    law_firm_id=1, query_text="tese", context=CTX,
    kind_plan=[("jurisprudence", 1)], max_chunks=1, max_chars=50_000,
)
juris_texts = [r["text"] for r in result_juris]
check("juris usa vara de origem (swap de chave)", juris_texts == ["trecho juris da mesma origem"],
      f"(ordem: {juris_texts})")

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
