"""
Teste da transição de status "Em revisão" ao triar achados no Revisor FAP.

Quando o usuário clica em "Não pertinente" ou "Marcar como revisado" num ponto
de atenção, a petição deve passar para 'in_review' — mas apenas a partir de
estados pré-triagem ('new', 'awaiting_adjustments'), sem rebaixar petições
aprovadas, protocoladas ou arquivadas.

Uso: uv run python tests/test_fap_review_user_review_status.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')

from app.models import FapReviewPetition  # noqa: E402
from app.services.fap_review_service import mark_petition_in_user_review  # noqa: E402

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


def petition_with(status):
    petition = FapReviewPetition()
    petition.workflow_status = status
    return petition


def run():
    print("[1] Estados que promovem para 'in_review'")
    for status in ('new', 'awaiting_adjustments'):
        petition = petition_with(status)
        changed = mark_petition_in_user_review(petition)
        check(f"{status} → in_review (retorna True)", changed is True and petition.workflow_status == 'in_review')
        check(f"{status}: status_changed_at preenchido", petition.status_changed_at is not None)

    print("[2] Estados que NÃO mudam")
    for status in ('in_review', 'ready_for_filing', 'filed', 'archived'):
        petition = petition_with(status)
        changed = mark_petition_in_user_review(petition)
        check(f"{status} permanece (retorna False)", changed is False and petition.workflow_status == status)

    print("[3] Petição inexistente")
    check("None retorna False sem erro", mark_petition_in_user_review(None) is False)


if __name__ == '__main__':
    run()
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
