"""Verificação da visão kanban do Revisor FAP.

Script standalone (padrão do projeto): renderiza /fap-review/ com um usuário
real do banco de dev e confere os marcadores da visão kanban no HTML.

Uso: uv run python tests/test_fap_review_kanban.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import User

MARKERS = [
    'id="petitionListView"',
    'id="kanbanBoard"',
    'data-view="list"',
    'data-view="kanban"',
    "localStorage.getItem('fapReviewPetitionView')",
]


def run():
    with app.app_context():
        user = (User.query.filter_by(role='admin').first()
                or User.query.first())
        assert user is not None, 'Nenhum usuário no banco de dev'

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['law_firm_id'] = user.law_firm_id

        resp = client.get('/fap-review/')
        assert resp.status_code == 200, f'HTTP {resp.status_code}'
        html = resp.get_data(as_text=True)

        if 'Nenhuma petição registrada ainda' in html:
            print('AVISO: banco sem petições — só o toggle é verificável.')

        missing = [m for m in MARKERS if m not in html]
        assert not missing, f'Marcadores ausentes: {missing}'
        print(f'OK — {len(MARKERS)} marcadores encontrados em /fap-review/')


if __name__ == '__main__':
    run()
