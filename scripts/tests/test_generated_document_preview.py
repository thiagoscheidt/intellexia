"""Agregação do preview de documentos (retriever stubado — sem serviços).

Rodar: uv run python scripts/tests/test_generated_document_preview.py

Cobre `aggregate_reference_candidates` (função pura) e, para o payload
`cobertura_teses` consumido pelo wizard (passo Documentos), o CONTRATO DE
FORMATO devolvido por `search_thesis_references` (mesma função usada por
`build_documents_preview` no laço por tese) — via retriever stubado, no
mesmo estilo de `test_thesis_coverage.py`. A orquestração completa de
`build_documents_preview` depende de app/models + Flask app context e não é
stubada aqui — cobertura é manual (ver checklist do wizard Documentos).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.generated_document_preview_service import (
    aggregate_reference_candidates,
)
from app.agents.legal_drafting.impugnacao_thesis_coverage import (
    THESIS_BLOCK_FOOTER_TEXT,
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

CHUNKS = [
    {"reference_id": 1, "section_kind": "merit_by_thesis", "thesis_catalog_id": "tese_a",
     "judge_name_norm": "JOAO DA SILVA", "orgao_julgador_norm": "3A VARA FEDERAL",
     "orgao_julgador_origem_norm": "", "trf_region": "TRF4", "text": "x"},
    {"reference_id": 1, "section_kind": "requests", "thesis_catalog_id": "tese_b",
     "judge_name_norm": "", "orgao_julgador_norm": "3A VARA FEDERAL",
     "orgao_julgador_origem_norm": "", "trf_region": "TRF4", "text": "y"},
    {"reference_id": 2, "section_kind": "jurisprudence", "thesis_catalog_id": "tese_a",
     "judge_name_norm": "", "orgao_julgador_norm": "OUTRA VARA DO PRECEDENTE",
     "orgao_julgador_origem_norm": "3A VARA FEDERAL", "trf_region": "TRF4", "text": "z"},
    {"reference_id": 3, "section_kind": "merit_by_thesis", "thesis_catalog_id": None,
     "judge_name_norm": "", "orgao_julgador_norm": "", "orgao_julgador_origem_norm": "",
     "trf_region": "TRF1", "text": "w"},
]

agg = aggregate_reference_candidates(CHUNKS, CTX)
by_id = {item["reference_id"]: item for item in agg}

check("3 peças agregadas", len(agg) == 3, f"(veio {len(agg)})")
check("peça 1 camada juiz", by_id[1]["camada"] == "juiz", f"(veio {by_id.get(1)})")
check("peça 1 teses únicas", sorted(by_id[1]["teses"]) == ["tese_a", "tese_b"])
check("peça 1 conta trechos", by_id[1]["trechos"] == 2)
check("juris usa vara de origem", by_id[2]["camada"] == "vara", f"(veio {by_id.get(2)})")
check("sem match -> geral", by_id[3]["camada"] == "geral")
check("ordem por camada", [i["reference_id"] for i in agg] == [1, 2, 3], f"(veio {[i['reference_id'] for i in agg]})")

# ── Dedup por point_id (múltiplas chamadas ao retriever podem trazer o
#    mesmo chunk mais de uma vez — não deve inflar a contagem de trechos) ──
DUP_CHUNKS = [
    {"reference_id": 10, "section_kind": "jurisprudence", "thesis_catalog_id": "tese_a",
     "judge_name_norm": "", "orgao_julgador_norm": "", "orgao_julgador_origem_norm": "",
     "trf_region": "TRF4", "text": "mesmo trecho", "point_id": "abc-123"},
    {"reference_id": 10, "section_kind": "jurisprudence", "thesis_catalog_id": "tese_a",
     "judge_name_norm": "", "orgao_julgador_norm": "", "orgao_julgador_origem_norm": "",
     "trf_region": "TRF4", "text": "mesmo trecho", "point_id": "abc-123"},
]
dup_agg = aggregate_reference_candidates(DUP_CHUNKS, CTX)
dup_by_id = {item["reference_id"]: item for item in dup_agg}
check("dedup por point_id -> 1 trecho", dup_by_id[10]["trechos"] == 1, f"(veio {dup_by_id.get(10)})")


# ── cobertura_teses: contrato de formato consumido pelo wizard ─────────────
# `build_documents_preview` monta `cobertura_teses` chamando
# `search_thesis_references` uma vez por tese e colecionando o `coverage` de
# cada chamada, na ordem em que as teses são iteradas. Aqui simulamos esse
# laço com um retriever stubado (mesmo padrão de test_thesis_coverage.py)
# para travar o formato que o passo Documentos vai consumir.
class StubRetriever:
    """Substitui ImpugnacaoReferenceRetriever: devolve chunks fixos por tese."""

    def __init__(self, chunks_by_query):
        self._chunks_by_query = chunks_by_query

    def fetch_style_references(self, **kwargs):
        return list(self._chunks_by_query.get(kwargs["query_text"], []))


THESIS_A_QUERY = "Tese principal do caso: Apuração do Índice de Custo"
THESIS_B_QUERY = "Tese principal do caso: Erro de Estabelecimento"

STUB = StubRetriever({
    THESIS_A_QUERY: [
        {"reference_id": 21, "section_kind": "merit_by_thesis",
         "judge_name_norm": "JOAO DA SILVA", "orgao_julgador_norm": "3A VARA FEDERAL",
         "orgao_julgador_origem_norm": "", "trf_region": "TRF4", "text": "trecho a"},
    ],
    THESIS_B_QUERY: [],  # tese sem nenhum modelo no acervo -> sem_modelo
})

cobertura_teses = []
for label, key, query in [
    ("Apuração do Índice de Custo", "apuracao_do_indice_de_custo", THESIS_A_QUERY),
    ("Erro de Estabelecimento", "erro_de_estabelecimento", THESIS_B_QUERY),
]:
    _, coverage = search_thesis_references(
        STUB,
        law_firm_id=1,
        thesis_label=label,
        thesis_key=key,
        query_text=query,
        context=CTX,
        kind_plan=[("merit_by_thesis", 6), ("jurisprudence", 15), ("requests", 2)],
        max_chunks=20,
        max_chars=60_000,
        min_distinct=2,
    )
    cobertura_teses.append(coverage)

check("cobertura_teses tem 1 entrada por tese", len(cobertura_teses) == 2, f"(veio {len(cobertura_teses)})")
check(
    "ordem preservada (mesma ordem de iteração das teses)",
    [c["tese"] for c in cobertura_teses] == ["Apuração do Índice de Custo", "Erro de Estabelecimento"],
    f"(veio {[c['tese'] for c in cobertura_teses]})",
)

_EXPECTED_KEYS = {"tese", "tese_key", "exemplos", "camada", "qtd_exemplos", "sem_modelo"}
for _cov in cobertura_teses:
    check(
        f"cobertura de '{_cov['tese']}' tem as chaves do contrato",
        _EXPECTED_KEYS.issubset(_cov.keys()),
        f"(veio {sorted(_cov.keys())})",
    )

check("tese com modelo -> sem_modelo is False", cobertura_teses[0]["sem_modelo"] is False)
check("tese com modelo -> qtd_exemplos == 1", cobertura_teses[0]["qtd_exemplos"] == 1)
check(
    "exemplos[i]['reference_id'] é int",
    all(isinstance(e["reference_id"], int) for c in cobertura_teses for e in c["exemplos"]),
    f"(veio {[c['exemplos'] for c in cobertura_teses]})",
)
check("tese sem modelo -> sem_modelo is True", cobertura_teses[1]["sem_modelo"] is True)
check("tese sem modelo -> exemplos == []", cobertura_teses[1]["exemplos"] == [])


# ── Regressão do item B: rodapé do bloco <TESE> tem fonte única ────────────
# `_build_budgeted_thesis_reference_block` (agent_generated_document.py)
# anexa THESIS_BLOCK_FOOTER_TEXT (importado de impugnacao_thesis_coverage,
# fonte única) em vez de manter uma cópia inline — se voltar a divergir, o
# orçamento reservado por THESIS_BLOCK_FOOTER_RESERVE_CHARS fica errado
# silenciosamente.
_agent = AgentGeneratedDocument()
_footer_block = _agent._build_budgeted_thesis_reference_block(
    thesis_label="Apuração do Índice de Custo",
    chunks=[{
        "section_kind": "merit_by_thesis",
        "text": "Fundamento principal da tese, com argumentação extensa. " * 10,
        "heading": "Estrutura da tese",
        "trf_region": "TRF4",
        "quality_score": 0.9,
    }],
    trf_region="TRF4",
    max_chars=4500,
)
check(
    "bloco <TESE> termina com THESIS_BLOCK_FOOTER_TEXT + </TESE>",
    _footer_block.endswith(THESIS_BLOCK_FOOTER_TEXT + "\n</TESE>"),
    f"(final do bloco: {_footer_block[-120:]!r})",
)

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
