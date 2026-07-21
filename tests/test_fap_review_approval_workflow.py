"""
Teste das regras do workflow de aprovação do Revisor FAP.

Cobre (funções puras do fap_review_service):
1. Status novo 'awaiting_approval' registrado com rótulo.
2. derive: revisão concluída → 'in_review' (aguardando ajustes virou decisão humana).
3. Transições que exigem admin (entrar em ready_for_filing; sair de
   awaiting_approval ou ready_for_filing).
4. Gate de triagem: todos os pontos checados ou descartados.
5. Mapeamento dos desfechos de triagem e estados que bloqueiam nova revisão.

Uso: uv run python tests/test_fap_review_approval_workflow.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')

from app.models import FapReviewExecution, FapReviewPetition  # noqa: E402
from app.services.fap_review_service import (  # noqa: E402
    NEW_REVISION_BLOCKED_STATUSES,
    PETITION_WORKFLOW_STATUSES,
    TRIAGE_OUTCOME_STATUSES,
    derive_petition_workflow_status,
    is_execution_superseded,
    is_triage_complete,
    status_transition_requires_admin,
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


def run():
    print("[1] Status novo registrado")
    check("awaiting_approval no dicionário", PETITION_WORKFLOW_STATUSES.get('awaiting_approval') == 'Aguardando aprovação')

    print("[2] derive_petition_workflow_status")
    check("completed → in_review", derive_petition_workflow_status('completed') == 'in_review')
    check("processing → in_review", derive_petition_workflow_status('processing') == 'in_review')
    check("failed → awaiting_adjustments", derive_petition_workflow_status('failed') == 'awaiting_adjustments')

    print("[3] Transições que exigem admin")
    for old, new in (
        ('awaiting_approval', 'ready_for_filing'),   # aprovar
        ('awaiting_approval', 'awaiting_adjustments'),  # devolver para ajustes
        ('ready_for_filing', 'awaiting_adjustments'),   # reabrir petição
        ('in_review', 'ready_for_filing'),           # aprovação direta também é admin
    ):
        check(f"{old} → {new} exige admin", status_transition_requires_admin(old, new) is True)
    for old, new in (
        ('awaiting_adjustments', 'in_review'),
        ('new', 'in_review'),
        ('in_review', 'awaiting_approval'),          # usuário envia para aprovação
        ('in_review', 'awaiting_adjustments'),       # usuário conclui triagem
    ):
        check(f"{old} → {new} não exige admin", status_transition_requires_admin(old, new) is False)

    print("[4] Gate de triagem")
    check("zero achados = completa", is_triage_complete(0, set(), set()) is True)
    check("todos checados = completa", is_triage_complete(3, {1, 2, 3}, set()) is True)
    check("mix checado/descartado = completa", is_triage_complete(3, {1, 3}, {2}) is True)
    check("sobreposição conta uma vez", is_triage_complete(3, {1, 2}, {2, 3}) is True)
    check("faltando um = incompleta", is_triage_complete(3, {1}, {2}) is False)
    check("índice fora do range não conta", is_triage_complete(3, {1, 2, 9}, set()) is False)

    print("[4b] Revisão substituída (derivada de latest_revision_id)")

    def execution_with(status='completed', exec_id=1, latest_id=1, exec_type='revision'):
        execution = FapReviewExecution()
        execution.id = exec_id
        execution.execution_type = exec_type
        execution.status = status
        petition = FapReviewPetition()
        petition.latest_revision_id = latest_id
        execution.petition = petition
        return execution

    check("concluída e não-corrente → substituída",
          is_execution_superseded(execution_with(exec_id=1, latest_id=2)) is True)
    check("concluída e corrente → não substituída",
          is_execution_superseded(execution_with(exec_id=2, latest_id=2)) is False)
    check("falha antiga não é substituída",
          is_execution_superseded(execution_with(status='failed', exec_id=1, latest_id=2)) is False)
    check("treinamento nunca é substituído",
          is_execution_superseded(execution_with(exec_type='training', exec_id=1, latest_id=2)) is False)
    no_petition = FapReviewExecution()
    no_petition.id = 1
    no_petition.execution_type = 'revision'
    no_petition.status = 'completed'
    check("sem petição → não substituída", is_execution_superseded(no_petition) is False)

    print("[5] Desfechos e bloqueio de nova revisão")
    check("new_version → awaiting_adjustments", TRIAGE_OUTCOME_STATUSES.get('new_version') == 'awaiting_adjustments')
    check("final_version → awaiting_approval", TRIAGE_OUTCOME_STATUSES.get('final_version') == 'awaiting_approval')
    check("bloqueio pós-aprovação", NEW_REVISION_BLOCKED_STATUSES == {'ready_for_filing', 'filed', 'archived'})


if __name__ == '__main__':
    run()
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
