#!/usr/bin/env python3
"""
Testa a auditoria de acesso: registro de visitas, estatísticas e proteção
admin-only do dashboard de Atividade de Usuários.

Uso: uv run python tests/test_access_audit.py
Cria dados temporários (escritório/usuários com sufixo __test_audit) e remove ao final.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, LawFirm, User, UserPageVisit
from app.services import access_audit_service

TEST_CNPJ = '00000000000199'
TEST_EMAIL_ADMIN = 'admin__test_audit@example.com'
TEST_EMAIL_USER = 'user__test_audit@example.com'


def setup_data():
    firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
    if not firm:
        firm = LawFirm(name='Escritório Teste Auditoria', cnpj=TEST_CNPJ)
        db.session.add(firm)
        db.session.flush()

    def get_or_create_user(email, role):
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(law_firm_id=firm.id, name=email.split('@')[0], email=email, role=role, is_active=True)
            user.set_password('x')
            db.session.add(user)
            db.session.flush()
        user.last_login = datetime.now()
        user.last_activity = datetime.now()
        return user

    admin = get_or_create_user(TEST_EMAIL_ADMIN, 'admin')
    normal = get_or_create_user(TEST_EMAIL_USER, 'user')
    db.session.commit()
    return firm, admin, normal


def cleanup(firm, admin, normal):
    UserPageVisit.query.filter(UserPageVisit.user_id.in_([admin.id, normal.id])).delete(synchronize_session=False)
    db.session.delete(admin)
    db.session.delete(normal)
    db.session.delete(firm)
    db.session.commit()


def login_session(client, user):
    with client.session_transaction() as sess:
        sess['user_id'] = user.id
        sess['law_firm_id'] = user.law_firm_id
        sess['user_role'] = user.role
        sess['user_module_permissions'] = user.get_module_permissions()


def run_tests():
    failures = []

    def check(name, condition, detail=''):
        status = 'OK ' if condition else 'FAIL'
        print(f"[{status}] {name}" + (f" — {detail}" if detail and not condition else ''))
        if not condition:
            failures.append(name)

    with app.app_context():
        firm, admin, normal = setup_data()
        try:
            # 1. Upsert via middleware: mesma tela no mesmo dia incrementa hits
            with app.test_client() as client:
                login_session(client, normal)
                client.get('/dashboard', headers={'Accept': 'text/html'})
                client.get('/dashboard', headers={'Accept': 'text/html'})

            visits = UserPageVisit.query.filter_by(user_id=normal.id, endpoint='dashboard.dashboard').all()
            check('middleware registra visita de tela', len(visits) == 1,
                  f'esperava 1 linha agregada, obteve {len(visits)}')
            if visits:
                check('upsert incrementa hits (2 GETs → hits=2)', visits[0].hits == 2,
                      f'hits={visits[0].hits}')

            # 2. Chamada AJAX não registra visita
            with app.test_client() as client:
                login_session(client, normal)
                client.get('/dashboard', headers={'Accept': 'application/json',
                                                  'X-Requested-With': 'XMLHttpRequest'})
            visits_after_ajax = UserPageVisit.query.filter_by(user_id=normal.id, endpoint='dashboard.dashboard').first()
            check('AJAX/JSON não conta como tela', visits_after_ajax.hits == 2 if visits_after_ajax else False,
                  f'hits={visits_after_ajax.hits if visits_after_ajax else None}')

            # 3. Estatísticas
            stats = access_audit_service.get_overview_stats(firm.id)
            check('online_now conta usuários recentes', stats['online_now'] >= 2, str(stats))
            check('total_users do escritório', stats['total_users'] == 2, str(stats))

            # Usuário antigo não conta como online
            normal.last_activity = datetime.now() - timedelta(hours=2)
            db.session.commit()
            stats = access_audit_service.get_overview_stats(firm.id)
            check('usuário com atividade antiga fica offline', stats['online_now'] == 1, str(stats))

            activity = access_audit_service.get_users_activity(firm.id)
            check('get_users_activity retorna os 2 usuários', len(activity) == 2, str(len(activity)))
            by_id = {a['id']: a for a in activity}
            check('flag is_online correta', by_id[admin.id]['is_online'] and not by_id[normal.id]['is_online'])
            check('última tela registrada', by_id[normal.id]['last_screen'] is not None,
                  str(by_id[normal.id]['last_screen']))

            screens = access_audit_service.get_user_screens(firm.id, normal.id, days=7)
            check('get_user_screens agrega por endpoint', len(screens) == 1 and screens[0]['hits'] == 2,
                  str(screens))

            # 4. Proteção admin-only
            with app.test_client() as client:
                login_session(client, normal)
                resp = client.get('/admin/access-audit/')
                check('não-admin é redirecionado', resp.status_code == 302, f'status={resp.status_code}')
                resp = client.get(f'/admin/access-audit/users/{normal.id}/screens',
                                  headers={'Accept': 'application/json',
                                           'X-Requested-With': 'XMLHttpRequest',
                                           'Content-Type': 'application/json'})
                check('não-admin recebe 403/302 no JSON', resp.status_code in (302, 403),
                      f'status={resp.status_code}')

            with app.test_client() as client:
                login_session(client, admin)
                resp = client.get('/admin/access-audit/')
                check('admin acessa dashboard (200)', resp.status_code == 200, f'status={resp.status_code}')
                if resp.status_code == 200:
                    check('página contém título', 'Atividade de Usuários' in resp.data.decode('utf-8'))
                resp = client.get(f'/admin/access-audit/users/{normal.id}/screens')
                check('admin acessa JSON de telas (200)', resp.status_code == 200, f'status={resp.status_code}')
                if resp.status_code == 200:
                    payload = resp.get_json()
                    check('JSON traz telas com hits', payload['screens'] and payload['screens'][0]['hits'] == 2,
                          str(payload))

                # Usuário de outro escritório → 404
                resp = client.get('/admin/access-audit/users/999999/screens')
                check('usuário inexistente → 404', resp.status_code == 404, f'status={resp.status_code}')
        finally:
            cleanup(firm, admin, normal)

    return failures


if __name__ == '__main__':
    print('🧪 Testando auditoria de acesso...')
    failures = run_tests()
    if failures:
        print(f"\n❌ {len(failures)} teste(s) falharam: {failures}")
        sys.exit(1)
    print('\n✅ Todos os testes passaram!')
    sys.exit(0)
