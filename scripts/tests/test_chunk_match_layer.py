"""Teste de `chunk_match_layer` (classificação de trecho por camada de
especificidade), sem serviços externos.

Rodar: uv run python scripts/tests/test_chunk_match_layer.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.legal_drafting.impugnacao_process_context import (
    LAYER_LABELS,
    LAYER_ORDER,
    chunk_match_layer,
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

# ── mesmo juiz ───────────────────────────────────────────────────────
chunk_juiz = {
    "section_kind": "merit_by_thesis",
    "judge_name_norm": "JOAO DA SILVA",
    "orgao_julgador_norm": "OUTRA VARA",
    "trf_region": "TRF1",
}
check("mesmo juiz -> 'juiz'", chunk_match_layer(chunk_juiz, CTX) == "juiz")

# ── mesma vara (kind normal usa orgao_julgador_norm) ────────────────
chunk_vara = {
    "section_kind": "merit_by_thesis",
    "judge_name_norm": "",
    "orgao_julgador_norm": "3A VARA FEDERAL",
    "trf_region": "TRF1",
}
check("mesma vara -> 'vara'", chunk_match_layer(chunk_vara, CTX) == "vara")

# ── jurisprudência: vara comparada é a de ORIGEM da peça ─────────────
chunk_juris_origem = {
    "section_kind": "jurisprudence",
    "judge_name_norm": "",
    "orgao_julgador_norm": "OUTRO ORGAO (PRECEDENTE)",
    "orgao_julgador_origem_norm": "3A VARA FEDERAL",
    "trf_region": "TRF1",
}
check("jurisprudência usa orgao_julgador_origem_norm -> 'vara'",
      chunk_match_layer(chunk_juris_origem, CTX) == "vara")

chunk_juris_nao_origem = {
    "section_kind": "jurisprudence",
    "judge_name_norm": "",
    "orgao_julgador_norm": "3A VARA FEDERAL",  # bateria se fosse usado, mas não é
    "orgao_julgador_origem_norm": "OUTRA ORIGEM QUALQUER",
    "trf_region": "TRF1",
}
check("jurisprudência ignora orgao_julgador_norm (usa origem) -> não 'vara'",
      chunk_match_layer(chunk_juris_nao_origem, CTX) != "vara")

# ── mesmo TRF ─────────────────────────────────────────────────────────
chunk_trf = {
    "section_kind": "merit_by_thesis",
    "judge_name_norm": "",
    "orgao_julgador_norm": "OUTRA VARA",
    "trf_region": "trf4",  # caixa baixa: comparação deve ser case-insensitive
}
check("mesmo trf (case-insensitive) -> 'trf'", chunk_match_layer(chunk_trf, CTX) == "trf")

# ── acervo geral (nenhum match) ───────────────────────────────────────
chunk_geral = {
    "section_kind": "merit_by_thesis",
    "judge_name_norm": "",
    "orgao_julgador_norm": "OUTRA VARA",
    "trf_region": "TRF1",
}
check("sem match -> 'geral'", chunk_match_layer(chunk_geral, CTX) == "geral")

# ── contexto vazio: nunca dá match, sempre 'geral' ────────────────────
check("contexto vazio -> 'geral'", chunk_match_layer(chunk_juiz, {}) == "geral")

# ── LAYER_ORDER / LAYER_LABELS: contrato mínimo usado pelos consumidores ──
check("LAYER_ORDER tem as 4 camadas", set(LAYER_ORDER) == {"juiz", "vara", "trf", "geral"})
check("LAYER_ORDER ordena por especificidade",
      LAYER_ORDER["juiz"] < LAYER_ORDER["vara"] < LAYER_ORDER["trf"] < LAYER_ORDER["geral"])
check("LAYER_LABELS cobre as mesmas chaves", set(LAYER_LABELS) == set(LAYER_ORDER))

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
