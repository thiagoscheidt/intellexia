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
               orgao_julgador_norm="3A VARA FEDERAL", trf_region="TRF4", reference_id=1),
    make_point("p-vara", "trecho da mesma vara", judge_name_norm=None,
               orgao_julgador_norm="3A VARA FEDERAL", trf_region="TRF4", reference_id=1),
    make_point("p-trf", "trecho do mesmo trf", judge_name_norm=None,
               orgao_julgador_norm="OUTRA VARA", trf_region="TRF4", reference_id=2),
    make_point("p-geral", "trecho geral", judge_name_norm=None,
               orgao_julgador_norm=None, trf_region="TRF1", reference_id=2),
]

# Pontos de jurisprudência: para esse section_kind, a camada de "vara" usa
# orgao_julgador_origem_norm (vara de ORIGEM da peça), não orgao_julgador_norm
# (que no payload de jurisprudência é o órgão do precedente, não da origem).
JURIS_POINTS = [
    make_point("j-origem", "trecho juris da mesma origem", section_kind="jurisprudence",
               judge_name_norm=None, orgao_julgador_norm="OUTRO ORGAO (PRECEDENTE)",
               orgao_julgador_origem_norm="3A VARA FEDERAL", trf_region="TRF4", reference_id=3),
    make_point("j-decoy", "trecho juris de outra origem", section_kind="jurisprudence",
               judge_name_norm=None, orgao_julgador_norm="3A VARA FEDERAL",
               orgao_julgador_origem_norm="OUTRA ORIGEM QUALQUER", trf_region="TRF4", reference_id=3),
]


class StubQdrant:
    """Aplica as FieldConditions `must` do filtro sobre POINTS em memória."""

    def collection_exists(self, name):
        return True

    def query_points(self, collection_name, query, query_filter, limit, with_payload):
        conditions = []
        for cond in (query_filter.must or []):
            match = cond.match
            values = getattr(match, "any", None)
            if values is not None:
                conditions.append((cond.key, lambda v, values=values: v in values))
            else:
                value = match.value
                conditions.append((cond.key, lambda v, value=value: v == value))
        hits = []
        for point in POINTS + JURIS_POINTS:
            payload = dict(point.payload)
            payload.setdefault("law_firm_id", 1)
            payload.setdefault("status", "active")
            if all(check(payload.get(k)) for k, check in conditions):
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

# ── allowed_reference_ids ────────────────────────────────────────────
result_allowed = retriever.fetch_style_references(
    law_firm_id=1, query_text="tese", context=CTX,
    kind_plan=[("merit_by_thesis", 4)], max_chunks=4, max_chars=50_000,
    allowed_reference_ids=[2],
)
allowed_texts = [r["text"] for r in result_allowed]
check("filtro por reference_id", all(
    r.get("reference_id") == 2 for r in result_allowed) and len(result_allowed) > 0,
    f"(veio {allowed_texts})")

result_empty = retriever.fetch_style_references(
    law_firm_id=1, query_text="tese", context=CTX,
    kind_plan=[("merit_by_thesis", 4)], max_chunks=4, max_chars=50_000,
    allowed_reference_ids=[],
)
check("lista vazia -> sem consulta", result_empty == [])

check("item expõe reference_id", all("reference_id" in r for r in result_allowed))

# ── min_distinct_references ─────────────────────────────────────────
# Pontos isolados por camada: cada filtro de camada (juiz/vara/trf) bate
# com exatamente 1 ponto, e o 4º só aparece na camada geral (catch-all).
# Ordem proposital (d4 primeiro) para exercitar o truncamento por `limit`
# do stub também na camada geral.
MIN_DISTINCT_CTX = {
    "judge_name_norm": "X", "orgao_julgador_norm": "Y", "trf_region": "Z",
}
MIN_DISTINCT_POINTS = [
    make_point("d4", "trecho d4 (só geral)", judge_name_norm=None,
               orgao_julgador_norm="OTHER4", trf_region="OTHERZ4", reference_id=204),
    make_point("d1", "trecho d1 (juiz)", judge_name_norm="X",
               orgao_julgador_norm="OTHER1", trf_region="OTHERZ1", reference_id=201),
    make_point("d2", "trecho d2 (vara)", judge_name_norm=None,
               orgao_julgador_norm="Y", trf_region="OTHERZ2", reference_id=202),
    make_point("d3", "trecho d3 (trf)", judge_name_norm=None,
               orgao_julgador_norm="OTHER3", trf_region="Z", reference_id=203),
]


class StubQdrantMinDistinct:
    """Mesma mecânica de StubQdrant, mas sobre um acervo isolado (4 peças,
    1 por camada) para testar `min_distinct_references` sem interferência
    dos pontos usados nos checks acima."""

    def collection_exists(self, name):
        return True

    def query_points(self, collection_name, query, query_filter, limit, with_payload):
        conditions = []
        for cond in (query_filter.must or []):
            match = cond.match
            values = getattr(match, "any", None)
            if values is not None:
                conditions.append((cond.key, lambda v, values=values: v in values))
            else:
                value = match.value
                conditions.append((cond.key, lambda v, value=value: v == value))
        hits = []
        for point in MIN_DISTINCT_POINTS:
            payload = dict(point.payload)
            payload.setdefault("law_firm_id", 1)
            payload.setdefault("status", "active")
            if all(check(payload.get(k)) for k, check in conditions):
                hits.append(point)
        return SimpleNamespace(points=hits[:limit])


retriever_min_distinct = ImpugnacaoReferenceRetriever.__new__(ImpugnacaoReferenceRetriever)
retriever_min_distinct.collection = "stub-min-distinct"
retriever_min_distinct.qdrant = StubQdrantMinDistinct()
retriever_min_distinct._embed = lambda text: [0.0]

# 1) top_k=1 não basta (camada mais específica só tem 1 peça) — com
#    min_distinct_references=2, desce até achar uma 2ª peça distinta.
result_min2 = retriever_min_distinct.fetch_style_references(
    law_firm_id=1, query_text="tese", context=MIN_DISTINCT_CTX,
    kind_plan=[("merit_by_thesis", 1)], max_chunks=10, max_chars=50_000,
    min_distinct_references=2,
)
refs_min2 = sorted(r["reference_id"] for r in result_min2)
check("min_distinct_references=2 traz 2 peças distintas", refs_min2 == [201, 202],
      f"(veio {refs_min2})")

# 2) Sem o parâmetro, comportamento de hoje: para no top_k da 1ª camada.
result_no_min = retriever_min_distinct.fetch_style_references(
    law_firm_id=1, query_text="tese", context=MIN_DISTINCT_CTX,
    kind_plan=[("merit_by_thesis", 1)], max_chunks=10, max_chars=50_000,
)
refs_no_min = [r["reference_id"] for r in result_no_min]
check("sem min_distinct_references -> só 1 item (compat)", refs_no_min == [201],
      f"(veio {refs_no_min})")

# 3) Pedir mais peças distintas do que existem no acervo não trava em loop
#    infinito: as camadas se esgotam e devolve o que houver.
result_min5 = retriever_min_distinct.fetch_style_references(
    law_firm_id=1, query_text="tese", context=MIN_DISTINCT_CTX,
    kind_plan=[("merit_by_thesis", 1)], max_chunks=10, max_chars=50_000,
    min_distinct_references=5,
)
refs_min5 = sorted(r["reference_id"] for r in result_min5)
check("min_distinct_references=5 com acervo menor -> sem travar, devolve o que há",
      refs_min5 == [201, 202, 203, 204], f"(veio {refs_min5})")

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
