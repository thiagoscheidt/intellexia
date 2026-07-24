#!/usr/bin/env python3
"""Testa a derivação de tribunal a partir do número CNJ (app/utils/cnj.py)
e o fallback de exibição em JudicialProcess.tribunal_name.

Uso: uv run python tests/test_cnj_tribunal.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import JudicialProcess
from app.utils.cnj import tribunal_sigla_from_cnj, ensure_tribunal_sigla

CASOS = [
    ('5012523-40.2025.4.04.7208', 'TRF4'),    # Justiça Federal, 4ª Região
    ('5014876-48.2021.4.03.6100', 'TRF3'),    # Justiça Federal, 3ª Região
    ('1048931-17.2026.4.01.3500', 'TRF1'),    # Justiça Federal, 1ª Região
    ('0001234-56.2024.8.24.0008', 'TJSC'),    # Justiça Estadual, SC
    ('0001234-56.2024.8.26.0100', 'TJSP'),    # Justiça Estadual, SP
    ('0001234-56.2024.5.12.0001', 'TRT12'),   # Justiça do Trabalho, 12ª Região
    ('0001234-56.2024.3.00.0000', 'STJ'),     # STJ
    ('TEMP-42', None),                        # número provisório do pipeline
    ('', None),
    (None, None),
]

falhas = 0
for numero, esperado in CASOS:
    obtido = tribunal_sigla_from_cnj(numero)
    ok = obtido == esperado
    falhas += 0 if ok else 1
    print(f"{'✓' if ok else '✗'} {numero!r} → {obtido!r} (esperado {esperado!r})")

with app.app_context():
    # Fallback de exibição: sem court e sem tribunal gravado, deriva do número
    p = JudicialProcess(process_number='5012523-40.2025.4.04.7208', tribunal=None)
    ok = p.tribunal_name == 'TRF4'
    falhas += 0 if ok else 1
    print(f"{'✓' if ok else '✗'} tribunal_name sem tribunal gravado → {p.tribunal_name!r} (esperado 'TRF4')")

    # Lixo 'None' como string também cai no fallback
    p = JudicialProcess(process_number='5012523-40.2025.4.04.7208', tribunal='None')
    ok = p.tribunal_name == 'TRF4'
    falhas += 0 if ok else 1
    print(f"{'✓' if ok else '✗'} tribunal_name com lixo 'None' → {p.tribunal_name!r} (esperado 'TRF4')")

    # Valor gravado legítimo continua vencendo a derivação
    p = JudicialProcess(process_number='5012523-40.2025.4.04.7208', tribunal='TRF da 4ª Região')
    ok = p.tribunal_name == 'TRF da 4ª Região'
    falhas += 0 if ok else 1
    print(f"{'✓' if ok else '✗'} tribunal_name com valor gravado → {p.tribunal_name!r} (mantido)")

    # ensure_tribunal_sigla preenche vazio e respeita preenchido
    p = JudicialProcess(process_number='5012523-40.2025.4.04.7208', tribunal='')
    ensure_tribunal_sigla(p)
    ok = p.tribunal == 'TRF4'
    falhas += 0 if ok else 1
    print(f"{'✓' if ok else '✗'} ensure_tribunal_sigla em vazio → {p.tribunal!r} (esperado 'TRF4')")

    p = JudicialProcess(process_number='5012523-40.2025.4.04.7208', tribunal='TJSC')
    ensure_tribunal_sigla(p)
    ok = p.tribunal == 'TJSC'
    falhas += 0 if ok else 1
    print(f"{'✓' if ok else '✗'} ensure_tribunal_sigla não sobrescreve → {p.tribunal!r} (mantido 'TJSC')")

print(f"\n{'✓ Todos os testes passaram' if falhas == 0 else f'✗ {falhas} falha(s)'}")
sys.exit(0 if falhas == 0 else 1)
