"""Reproduz a corrida do registro de visitas de tela (user_page_visits).

Cenário real: duas requests quase simultâneas do mesmo usuário/endpoint/dia.
Com REPEATABLE READ (MySQL), o SELECT da segunda request não enxerga a linha
que a primeira acabou de comitar; o INSERT então estoura 1062 (Duplicate entry)
no commit do middleware — fora do try/except do serviço — e derruba a tela.

O teste simula o "snapshot cego" forçando a busca de linha existente a
retornar None, com uma linha conflitante já comitada no banco.

Uso:
    uv run python scripts/tests/test_record_page_visit_race.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from main import app
from app.models import db, User, UserPageVisit
from app.services import access_audit_service
from app.utils.timezone import now_sp

ENDPOINT = '__teste__.corrida_visita'


def _cleanup(user_id, today):
    UserPageVisit.query.filter_by(
        user_id=user_id, endpoint=ENDPOINT, visit_date=today).delete()
    db.session.commit()


def main():
    with app.app_context():
        user = User.query.order_by(User.id.asc()).first()
        if not user:
            print('ERRO: nenhum usuário no banco para o teste.')
            return 1

        today = now_sp().date()
        _cleanup(user.id, today)

        # "Outra request" já comitou a linha do dia
        db.session.add(UserPageVisit(
            law_firm_id=user.law_firm_id,
            user_id=user.id,
            endpoint=ENDPOINT,
            visit_date=today,
            hits=5,
        ))
        db.session.commit()

        fake_request = SimpleNamespace(endpoint=ENDPOINT)
        try:
            with mock.patch.object(access_audit_service, '_is_page_navigation',
                                   return_value=True), \
                 mock.patch.object(access_audit_service, 'request', fake_request), \
                 mock.patch.object(access_audit_service, '_find_visit',
                                   return_value=None):
                access_audit_service.record_page_visit(user)

            # É aqui que o bug explodia: IntegrityError no commit do middleware
            db.session.commit()

            row = UserPageVisit.query.filter_by(
                user_id=user.id, endpoint=ENDPOINT, visit_date=today).first()
            if row is None:
                print('FALHOU: linha da visita sumiu.')
                return 1
            if row.hits != 6:
                print(f'FALHOU: hits={row.hits}, esperado 6 '
                      '(fallback deveria incrementar a linha existente).')
                return 1
            print('OK: corrida tratada — commit não estourou e hits foi de 5 para 6.')
            return 0
        except Exception as exc:  # noqa: BLE001 — teste standalone
            db.session.rollback()
            print(f'FALHOU: exceção vazou para o commit do chamador: {exc!r}')
            return 1
        finally:
            db.session.rollback()
            _cleanup(user.id, today)


if __name__ == '__main__':
    sys.exit(main())
