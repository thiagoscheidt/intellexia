"""Teste da sanitização de metadados de peças-modelo (sem chamada LLM).

Rodar: uv run python scripts/tests/test_impugnacao_reference_metadata.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.legal_drafting.impugnacao_reference_metadata_agent import (
    ImpugnacaoReferenceMetadata,
    ImpugnacaoReferenceMetadataAgent,
)

FAILS = []


def check(label, got, expected):
    if got != expected:
        FAILS.append(label)
        print(f"  ✗ {label}: esperado {expected!r}, obtido {got!r}")
    else:
        print(f"  ✓ {label}")


san = ImpugnacaoReferenceMetadataAgent._sanitize

# CNJ válido deriva TRF e sobrepõe o palpite do LLM
meta = san(
    ImpugnacaoReferenceMetadata(
        title="Peça X", process_number="5001234-56.2024.4.04.7200",
        trf_region="TRF1", orgao_julgador="  3ª Vara Federal de Florianópolis  ",
        judge_name=" João da Silva ", quality_score=3.0,
    ),
    "peca.pdf", "texto qualquer",
)
check("CNJ mantido", meta.process_number, "5001234-56.2024.4.04.7200")
check("TRF derivado do CNJ vence o LLM", meta.trf_region, "TRF4")
check("vara com trim", meta.orgao_julgador, "3ª Vara Federal de Florianópolis")
check("juiz com trim", meta.judge_name, "João da Silva")

# CNJ inválido é descartado; TRF do LLM permanece
meta2 = san(
    ImpugnacaoReferenceMetadata(
        title="Peça Y", process_number="12345", trf_region="TRF2",
        quality_score=3.0,
    ),
    "peca.pdf", "texto",
)
check("CNJ inválido -> None", meta2.process_number, None)
check("TRF do LLM mantido sem CNJ", meta2.trf_region, "TRF2")

# Campos ausentes seguem None; fallback não quebra
fb = ImpugnacaoReferenceMetadataAgent._fallback("minha_peca.pdf", "")
check("fallback process_number", fb.process_number, None)
check("fallback orgao_julgador", fb.orgao_julgador, None)
check("fallback judge_name", fb.judge_name, None)

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
