"""
Teste das regras de reprocessamento de revisão do Revisor FAP.

Contexto: as execuções 52 e 53 falharam por bugs já corrigidos (estouro do
orçamento de saída do modelo e decimal.ConversionSyntax na contabilidade de
custo). Reexecutá-las exigia reupload de petição, anexos e planilha, porque o
botão "Tentar Novamente" apenas levava ao formulário vazio.

O reprocessamento reaproveita a MESMA execução: `revision_number` representa a
versão da petição revisada, não a tentativa de processamento — uma falha técnica
não é uma revisão nova. Criar outra execução inflaria `revision_count`, o Kanban
e as estatísticas por advogado.

Verifica (funções puras, sem tocar no banco):
1. Só revisão em 'failed' é reprocessável.
2. 'completed' é barrado (sobrescreveria achados já triados).
3. 'processing'/'pending' são barrados (duplo disparo custa uma chamada de modelo).
4. execution_type 'training' é barrado.
5. O reset devolve a execução a 'processing' limpando o erro.
6. O reset NÃO mexe em revision_number — a garantia central da decisão de design.
7. O reset NÃO apaga result_json (a execução 52 pode ter resultado recuperável).

Uso: uv run python tests/test_fap_review_reprocess.py
"""

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')

from app.models import FapReviewExecution  # noqa: E402
from app.services.fap_review_service import (  # noqa: E402
    REPROCESSABLE_EXECUTION_STATUSES,
    describe_reprocess_block,
    reset_execution_for_reprocess,
)

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


def build_execution(**overrides) -> FapReviewExecution:
    """Instância não persistida — o teste nunca toca o banco."""
    defaults = {
        'execution_type': 'revision',
        'status': 'failed',
        'revision_number': 3,
        'error_message': 'A resposta do modelo não contém JSON válido para a revisão.',
        'completed_at': datetime(2026, 8, 4, 12, 21, 30),
    }
    defaults.update(overrides)
    return FapReviewExecution(**defaults)


def test_failed_revision_is_reprocessable():
    print("[1] Revisão em 'failed' é reprocessável")
    block = describe_reprocess_block(build_execution())
    check("sem bloqueio", block is None, f"(obteve {block!r})")
    check("'failed' está no conjunto permitido", 'failed' in REPROCESSABLE_EXECUTION_STATUSES)


def test_other_statuses_are_blocked():
    print("[2] Demais status são barrados")
    for status in ('completed', 'processing', 'pending'):
        block = describe_reprocess_block(build_execution(status=status))
        check(f"'{status}' bloqueado", isinstance(block, str) and bool(block),
              f"(obteve {block!r})")


def test_training_is_blocked():
    print("[3] Execução de treinamento é barrada")
    block = describe_reprocess_block(build_execution(execution_type='training'))
    check("training bloqueado", isinstance(block, str) and bool(block),
          f"(obteve {block!r})")


def test_reset_returns_to_processing():
    print("[4] Reset devolve a execução a 'processing'")
    execution = build_execution()
    reset_execution_for_reprocess(execution)
    check("status vira 'processing'", execution.status == 'processing',
          f"(obteve {execution.status!r})")
    check("error_message limpa", execution.error_message is None,
          f"(obteve {execution.error_message!r})")
    check("completed_at limpa", execution.completed_at is None,
          f"(obteve {execution.completed_at!r})")


def test_reset_preserves_revision_number():
    print("[5] Reset preserva a numeração da revisão (decisão central do design)")
    execution = build_execution(revision_number=3)
    reset_execution_for_reprocess(execution)
    check("revision_number intacto", execution.revision_number == 3,
          f"(obteve {execution.revision_number!r})")


def test_reset_preserves_result_json():
    print("[6] Reset não apaga result_json (execução 52 pode ter resultado recuperável)")
    execution = build_execution(result_json='{"findings": []}')
    reset_execution_for_reprocess(execution)
    check("result_json preservado", execution.result_json == '{"findings": []}',
          f"(obteve {execution.result_json!r})")


if __name__ == '__main__':
    test_failed_revision_is_reprocessable()
    test_other_statuses_are_blocked()
    test_training_is_blocked()
    test_reset_returns_to_processing()
    test_reset_preserves_revision_number()
    test_reset_preserves_result_json()
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
