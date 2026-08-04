"""
Teste da persistência de custo/tokens da execução do Revisor FAP.

Cobre a falha de produção de 03/08/2026 (execução 52, "Unimed Recife"), que
morreu com [<class 'decimal.ConversionSyntax'>]:

    if hasattr(result, 'cost_usd'):
        execution.cost_usd = Decimal(str(result.cost_usd))

`hasattr` é sempre True — o campo existe no modelo Pydantic —, mas o VALOR é
opcional: o agente devolve `cost_usd=float(total_cost) if total_cost else None`.
Com custo zerado o valor vira None e `Decimal("None")` estoura InvalidOperation,
derrubando uma revisão que já havia sido concluída com sucesso pelo modelo.

O custo zera quando o TokenUsageService não resolve o preço do modelo — e
`anthropic/claude-sonnet-5` não consta de `_DEFAULT_PRICING_PER_1K`, então basta
a consulta de preços ao OpenRouter falhar (rede, cache frio, timeout) para o
custo cair a zero. Daí o caráter intermitente da falha.

Verifica:
1. None não estoura e não grava valor.
2. Zero é preservado como Decimal('0') e não confundido com ausência.
3. Valores válidos (float, int, str, Decimal) convertem corretamente.
4. Lixo não numérico é descartado em vez de derrubar a execução.

Uso: uv run python tests/test_fap_review_cost_persistence.py
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')

from app.blueprints.fap_review import _to_decimal_or_none  # noqa: E402

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label} {detail}")


def test_none_does_not_raise():
    print("[1] None não estoura (regressão da execução 52)")
    try:
        result = _to_decimal_or_none(None)
        check("None retorna None", result is None, f"(obteve {result!r})")
    except Exception as exc:
        check("None não levanta exceção", False, f"({type(exc).__name__}: {exc})")


def test_zero_is_preserved():
    print("[2] Zero é custo válido, não ausência de custo")
    result = _to_decimal_or_none(0)
    check("0 vira Decimal('0')", result == Decimal('0'), f"(obteve {result!r})")
    check("0 não vira None", result is not None)
    result_float = _to_decimal_or_none(0.0)
    check("0.0 vira Decimal('0')", result_float == Decimal('0'), f"(obteve {result_float!r})")


def test_valid_values_convert():
    print("[3] Valores válidos convertem preservando precisão")
    check("float converte", _to_decimal_or_none(0.93382938) == Decimal('0.93382938'),
          f"(obteve {_to_decimal_or_none(0.93382938)!r})")
    check("int converte", _to_decimal_or_none(2) == Decimal('2'))
    check("str converte", _to_decimal_or_none('1.25') == Decimal('1.25'))
    check("Decimal passa direto", _to_decimal_or_none(Decimal('3.5')) == Decimal('3.5'))


def test_garbage_is_discarded():
    print("[4] Lixo não numérico é descartado, não derruba a revisão")
    for garbage in ('', 'N/A', 'abc', '1,25', [], {}):
        try:
            result = _to_decimal_or_none(garbage)
            check(f"{garbage!r} retorna None", result is None, f"(obteve {result!r})")
        except Exception as exc:
            check(f"{garbage!r} não levanta exceção", False, f"({type(exc).__name__}: {exc})")


if __name__ == '__main__':
    test_none_does_not_raise()
    test_zero_is_preserved()
    test_valid_values_convert()
    test_garbage_is_discarded()
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
