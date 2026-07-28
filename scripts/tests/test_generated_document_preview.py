"""Agregação do preview de documentos (retriever stubado — sem serviços).

Rodar: uv run python scripts/tests/test_generated_document_preview.py

Cobre apenas `aggregate_reference_candidates` (função pura). A orquestração
completa (`build_documents_preview`) depende de app/models + Flask app context
e não é stubada aqui — cobertura é manual (ver checklist do wizard Documentos).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.generated_document_preview_service import (
    aggregate_reference_candidates,
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

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
