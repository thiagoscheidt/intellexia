"""Teste de sincronização do índice Meilisearch das peças-modelo.

Requer Meilisearch rodando (docker compose -f docker/docker-compose.yml up -d).
Usa reference_id sintético 999999 e limpa ao final.

Rodar: uv run python scripts/tests/test_impugnacao_meilisearch_sync.py
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import impugnacao_reference_search as search

FAILS = []


def check(label, cond, detail=""):
    if not cond:
        FAILS.append(label)
        print(f"  ✗ {label} {detail}")
    else:
        print(f"  ✓ {label}")


REF = SimpleNamespace(
    id=999999, law_firm_id=888888, title="Peça teste sync",
    trf_region="TRF4", orgao_julgador="3ª Vara Federal de Florianópolis",
    judge_name="João da Silva", process_number="5001234-56.2024.4.04.7200",
    status="active",
)
RECORDS = [
    {"qdrant_point_id": "11111111-1111-1111-1111-111111111111",
     "heading": "6. AUXÍLIO-ACIDENTE (B94)", "section": "6. AUXÍLIO-ACIDENTE (B94)",
     "section_kind": "merit_by_thesis", "thesis_catalog_id": "apuracao_indice_custo",
     "order_in_doc": 0, "full_text": "Texto sobre apuração do índice de custo xyzsync."},
    {"qdrant_point_id": "22222222-2222-2222-2222-222222222222",
     "heading": "PEDIDOS", "section": "PEDIDOS", "section_kind": "requests",
     "thesis_catalog_id": None, "order_in_doc": 1,
     "full_text": "Requer a procedência total xyzsync."},
]

check("indexação", search.index_reference_chunks(REF, RECORDS))
time.sleep(0.5)

hits = search.search_chunks(REF.law_firm_id, "xyzsync")
check("busca acha os 2 chunks", len(hits) == 2, f"(veio {len(hits)})")

hits_outro_tenant = search.search_chunks(777777, "xyzsync")
check("filtro de tenant", len(hits_outro_tenant) == 0, f"(veio {len(hits_outro_tenant)})")

hits_secao = search.search_chunks(REF.law_firm_id, "auxílio-acidente")
check("busca por título de seção", len(hits_secao) >= 1, f"(veio {len(hits_secao)})")

check("exclusão", search.delete_reference(REF.id))
time.sleep(0.5)
hits_after = search.search_chunks(REF.law_firm_id, "xyzsync")
check("índice limpo após exclusão", len(hits_after) == 0, f"(veio {len(hits_after)})")

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
