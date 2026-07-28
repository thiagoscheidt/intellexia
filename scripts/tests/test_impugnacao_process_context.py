"""Teste do helper de contexto de busca de referências de impugnação.

Rodar: uv run python scripts/tests/test_impugnacao_process_context.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.legal_drafting.impugnacao_process_context import (
    normalize_context_value,
    normalize_section_title,
    trf_region_from_process,
    build_reference_search_context,
)
import app.services.datajud_snapshot_service as djs

FAILS = []


def check(label, got, expected):
    if got != expected:
        FAILS.append(f"{label}: esperado {expected!r}, obtido {got!r}")
        print(f"  ✗ {label}: esperado {expected!r}, obtido {got!r}")
    else:
        print(f"  ✓ {label}")


# ── normalização ─────────────────────────────────────────────────────
check("normalize vazio", normalize_context_value(None), "")
# NFKD decompõe 'ª' em 'a' -> caixa alta 'A'
check(
    "normalize vara",
    normalize_context_value("  3ª Vara   Federal de Florianópolis "),
    "3A VARA FEDERAL DE FLORIANOPOLIS",
)
check(
    "normalize_section_title remove numeração",
    normalize_section_title("6. AUXÍLIO-ACIDENTE POR ACIDENTE DE TRABALHO (B94)"),
    "AUXILIO-ACIDENTE POR ACIDENTE DE TRABALHO (B94)",
)
check("normalize_section_title vazio", normalize_section_title(""), "")

# ── TRF pelo CNJ ─────────────────────────────────────────────────────
proc_cnj = SimpleNamespace(
    id=1, law_firm_id=1,
    process_number="5001234-56.2024.4.04.7200",   # segmento 4 (JF), TR 04 -> TRF4
    court=None, tribunal=None, tribunal_name="", section=None, judge_name=None,
)
check("TRF derivado do CNJ", trf_region_from_process(proc_cnj), "TRF4")

# ── TRF por texto (fallback sem CNJ) ─────────────────────────────────
proc_texto = SimpleNamespace(
    id=2, law_firm_id=1, process_number=None,
    court=SimpleNamespace(tribunal="Tribunal Regional Federal da 4ª Região",
                          orgao_julgador=None),
    tribunal=None, tribunal_name="", section=None, judge_name=None,
)
check("TRF por texto do tribunal", trf_region_from_process(proc_texto), "TRF4")

# Regex não deve capturar "Região" fora de contexto federal (ex.: Justiça do
# Trabalho, que também usa "Tribunal Regional do Trabalho da Nª Região").
proc_trt = SimpleNamespace(
    id=5, law_firm_id=1, process_number=None,
    court=SimpleNamespace(tribunal="Tribunal Regional do Trabalho da 4ª Região",
                          orgao_julgador=None),
    tribunal=None, tribunal_name="", section=None, judge_name=None,
)
check("TRT não é confundido com TRF", trf_region_from_process(proc_trt), None)

# ── contexto completo com snapshot DataJud stubado ───────────────────
djs.get_snapshot = lambda process_id, law_firm_id: SimpleNamespace(
    payload_json={"instancias": [
        {"grau": "G2", "orgao_julgador": "Gab. Des. Fulano"},
        {"grau": "G1", "orgao_julgador": "3ª Vara Federal de Florianópolis"},
    ]}
)
proc = SimpleNamespace(
    id=3, law_firm_id=1,
    process_number="5001234-56.2024.4.04.7200",
    court=None, tribunal=None, tribunal_name="", section=None,
    judge_name="  João da Silva ",
)
ctx = build_reference_search_context(proc)
check("ctx trf", ctx["trf_region"], "TRF4")
check("ctx vara (menor grau primeiro)", ctx["orgao_julgador"], "3ª Vara Federal de Florianópolis")
check("ctx vara norm", ctx["orgao_julgador_norm"], "3A VARA FEDERAL DE FLORIANOPOLIS")
check("ctx juiz", ctx["judge_name"], "João da Silva")
check("ctx juiz norm", ctx["judge_name_norm"], "JOAO DA SILVA")

# ── snapshot indisponível não pode quebrar ───────────────────────────
def _boom(process_id, law_firm_id):
    raise RuntimeError("banco fora")
djs.get_snapshot = _boom
proc_sem = SimpleNamespace(
    id=4, law_firm_id=1, process_number=None, court=None, tribunal=None,
    tribunal_name="", section="12ª Vara Federal", judge_name=None,
)
ctx2 = build_reference_search_context(proc_sem)
check("fallback vara via process.section", ctx2["orgao_julgador"], "12ª Vara Federal")
check("juiz ausente -> None", ctx2["judge_name_norm"], None)

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
