#!/usr/bin/env python3
"""
Testa o login com Google: só entra quem já existe na base, nunca cria usuário.

O retorno do Google é simulado (substituímos `google_client` no blueprint auth),
então o teste não faz rede nem precisa de credenciais reais.

Uso: uv run python tests/test_google_login.py
Cria dados temporários (escritório/usuários com sufixo __test_google) e remove ao final.
"""
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import redirect

from main import app
from app.models import db, LawFirm, User
from app.blueprints import auth as auth_module
from app.services import access_audit_service

TEST_CNPJ = '00000000000188'
TEST_CNPJ_INATIVO = '00000000000177'
# E-mail com maiúsculas de propósito: o Google devolve minúsculo e a busca
# precisa casar mesmo assim.
EMAIL_OK = 'Usuario__test_google@Example.com'
EMAIL_INATIVO = 'inativo__test_google@example.com'
EMAIL_FIRMA_INATIVA = 'firma__test_google@example.com'
EMAIL_DESCONHECIDO = 'ninguem__test_google@example.com'

SUB_ORIGINAL = 'sub-test-google-1'
SUB_NOVO = 'sub-test-google-2'


class FakeGoogleClient:
    """Substituto do cliente Authlib: devolve claims prontas do id_token."""

    def __init__(self, claims=None, falhar=False):
        self.claims = claims or {}
        self.falhar = falhar

    def authorize_redirect(self, redirect_uri):
        self.redirect_uri = redirect_uri
        return redirect('https://accounts.google.com/o/oauth2/v2/auth?fake=1')

    def authorize_access_token(self):
        if self.falhar:
            raise RuntimeError('falha simulada na troca do code')
        return {'userinfo': self.claims}


def claims(email, sub=SUB_ORIGINAL, verified=True):
    return {'email': email, 'sub': sub, 'email_verified': verified, 'name': 'Teste Google'}


def use_client(client_obj):
    """Aponta o blueprint para um cliente Google simulado (ou None)."""
    auth_module.google_client = lambda: client_obj


def erro_do_redirect(response):
    """Código de erro (?erro=) do redirect devolvido pelo callback."""
    assert response.status_code == 302, f'esperava redirect, veio {response.status_code}'
    query = parse_qs(urlparse(response.headers['Location']).query)
    return (query.get('erro') or [None])[0]


def setup_data():
    firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
    if not firm:
        firm = LawFirm(name='Escritório Teste Google', cnpj=TEST_CNPJ, is_active=True)
        db.session.add(firm)
        db.session.flush()
    firm.is_active = True

    firm_inativa = LawFirm.query.filter_by(cnpj=TEST_CNPJ_INATIVO).first()
    if not firm_inativa:
        firm_inativa = LawFirm(name='Escritório Inativo Google', cnpj=TEST_CNPJ_INATIVO)
        db.session.add(firm_inativa)
        db.session.flush()
    firm_inativa.is_active = False

    def get_or_create_user(email, law_firm_id, is_active=True):
        user = User.query.filter(db.func.lower(User.email) == email.lower()).first()
        if not user:
            user = User(
                law_firm_id=law_firm_id,
                name=email.split('@')[0],
                email=email,
                role='admin',
                is_active=is_active,
            )
            user.set_password('x')
            user.set_module_permissions(None)
            db.session.add(user)
            db.session.flush()
        user.law_firm_id = law_firm_id
        user.is_active = is_active
        user.google_sub = None
        user.google_linked_at = None
        return user

    ok = get_or_create_user(EMAIL_OK, firm.id)
    inativo = get_or_create_user(EMAIL_INATIVO, firm.id, is_active=False)
    firma_inativa = get_or_create_user(EMAIL_FIRMA_INATIVA, firm_inativa.id)
    db.session.commit()
    return [firm, firm_inativa], [ok, inativo, firma_inativa]


def cleanup(firms, users):
    for user in users:
        db.session.delete(user)
    db.session.commit()
    for firm in firms:
        db.session.delete(firm)
    db.session.commit()


def run():
    falhas = []

    def check(nome, condicao, detalhe=''):
        if condicao:
            print(f'✓ {nome}')
        else:
            print(f'✗ {nome} {detalhe}')
            falhas.append(nome)

    with app.app_context():
        firms, users = setup_data()
        user_ok, user_inativo, user_firma_inativa = users
        id_ok = user_ok.id
        google_client_original = auth_module.google_client
        google_enabled_original = auth_module.google_login_enabled

        try:
            # --- Google não configurado ---
            use_client(None)
            with app.test_client() as client:
                resp = client.get('/login/google')
                check('sem configuração, /login/google recusa',
                      erro_do_redirect(resp) == 'google_indisponivel')
                resp = client.get('/login/google/callback')
                check('sem configuração, callback recusa',
                      erro_do_redirect(resp) == 'google_indisponivel')

            # --- Botão só aparece quando habilitado ---
            auth_module.google_login_enabled = lambda: False
            with app.test_client() as client:
                html = client.get('/login').get_data(as_text=True)
                check('botão ausente quando desabilitado', 'Continuar com Google' not in html)
            auth_module.google_login_enabled = lambda: True
            with app.test_client() as client:
                html = client.get('/login').get_data(as_text=True)
                check('botão presente quando habilitado', 'Continuar com Google' in html)
                check('login por senha preservado', 'id="login-form"' in html)

            # --- Falha na troca do code ---
            use_client(FakeGoogleClient(falhar=True))
            with app.test_client() as client:
                resp = client.get('/login/google/callback')
                check('erro na troca do code volta ao login',
                      erro_do_redirect(resp) == 'google_falhou')

            # --- E-mail não verificado pelo Google ---
            use_client(FakeGoogleClient(claims(EMAIL_OK, verified=False)))
            with app.test_client() as client:
                resp = client.get('/login/google/callback')
                check('e-mail não verificado é recusado',
                      erro_do_redirect(resp) == 'google_email_nao_verificado')
                with client.session_transaction() as sess:
                    check('sessão não criada para e-mail não verificado',
                          'user_id' not in sess)

            # --- E-mail sem usuário na base: nunca cria conta ---
            total_antes = User.query.count()
            use_client(FakeGoogleClient(claims(EMAIL_DESCONHECIDO)))
            with app.test_client() as client:
                resp = client.get('/login/google/callback')
                check('e-mail desconhecido é recusado',
                      erro_do_redirect(resp) == 'google_nao_autorizado')
            check('nenhum usuário criado pelo login com Google',
                  User.query.count() == total_antes)

            # --- Usuário inativo ---
            use_client(FakeGoogleClient(claims(EMAIL_INATIVO)))
            with app.test_client() as client:
                resp = client.get('/login/google/callback')
                check('usuário inativo é recusado', erro_do_redirect(resp) == 'conta_inativa')

            # --- Escritório inativo ---
            use_client(FakeGoogleClient(claims(EMAIL_FIRMA_INATIVA)))
            with app.test_client() as client:
                resp = client.get('/login/google/callback')
                check('escritório inativo é recusado',
                      erro_do_redirect(resp) == 'escritorio_inativo')

            # --- Primeiro login: grava o vínculo e abre a sessão ---
            fake = FakeGoogleClient(claims(EMAIL_OK.lower()))
            use_client(fake)
            with app.test_client() as client:
                resp = client.get('/login/google?next=/cases')
                check('/login/google redireciona ao Google',
                      resp.status_code == 302 and 'accounts.google.com' in resp.headers['Location'])
                check('redirect_uri aponta para o callback',
                      fake.redirect_uri.endswith('/login/google/callback'),
                      getattr(fake, 'redirect_uri', ''))

                resp = client.get('/login/google/callback')
                destino = resp.headers.get('Location', '')
                check('login bem-sucedido respeita o next', destino.endswith('/cases'), destino)
                with client.session_transaction() as sess:
                    check('sessão completa após login com Google',
                          sess.get('user_id') == id_ok and sess.get('law_firm_id') and sess.get('user_role'))

            user_ok = db.session.get(User, id_ok)
            check('sub gravado no primeiro login', user_ok.google_sub == SUB_ORIGINAL,
                  str(user_ok.google_sub))
            check('data do vínculo registrada', user_ok.google_linked_at is not None)
            check('último login registrado', user_ok.last_login is not None)
            check('login por Google contabilizado', user_ok.google_login_count == 1,
                  str(user_ok.google_login_count))
            check('data do login por Google registrada', user_ok.google_last_login_at is not None)

            # --- Auditoria de acesso mostra a adoção ---
            atividade = {u['id']: u for u in access_audit_service.get_users_activity(firms[0].id)}
            linha = atividade.get(id_ok, {})
            check('auditoria expõe contagem de logins por Google',
                  linha.get('google_login_count') == 1, str(linha.get('google_login_count')))
            check('auditoria expõe data do último login por Google',
                  linha.get('google_last_login') is not None)
            check('auditoria marca que o último login foi por Google',
                  linha.get('last_login_via_google') is True)
            stats = access_audit_service.get_overview_stats(firms[0].id)
            check('estatística de adoção conta o usuário', stats.get('google_users') == 1,
                  str(stats.get('google_users')))

            # --- Login por senha não conta como login por Google ---
            with app.test_client() as client:
                resp = client.post('/login', data={'email': EMAIL_OK, 'password': 'x'})
                check('login por senha continua funcionando',
                      resp.get_json().get('success') is True, resp.get_data(as_text=True)[:120])
            db.session.expire_all()
            user_ok = db.session.get(User, id_ok)
            check('login por senha não incrementa o contador do Google',
                  user_ok.google_login_count == 1, str(user_ok.google_login_count))
            atividade = {u['id']: u for u in access_audit_service.get_users_activity(firms[0].id)}
            check('após login por senha, último acesso não é marcado como Google',
                  atividade[id_ok].get('last_login_via_google') is False)

            # --- Conta Google trocada: revinculação automática ---
            use_client(FakeGoogleClient(claims(EMAIL_OK.lower(), sub=SUB_NOVO)))
            with app.test_client() as client:
                resp = client.get('/login/google/callback')
                check('login aceito com conta Google nova',
                      resp.status_code == 302 and 'erro=' not in resp.headers['Location'])
            db.session.expire_all()
            check('sub revinculado automaticamente',
                  db.session.get(User, id_ok).google_sub == SUB_NOVO)
            check('segundo login por Google somado ao contador',
                  db.session.get(User, id_ok).google_login_count == 2,
                  str(db.session.get(User, id_ok).google_login_count))

            # --- Mesmo sub em outro usuário: vínculo antigo é liberado ---
            # O índice é único, então o vínculo sai de um antes de entrar no outro.
            db.session.get(User, id_ok).google_sub = None
            db.session.flush()
            user_inativo.is_active = True
            user_inativo.google_sub = SUB_NOVO
            db.session.commit()
            id_outro = user_inativo.id
            use_client(FakeGoogleClient(claims(EMAIL_OK.lower(), sub=SUB_NOVO)))
            with app.test_client() as client:
                resp = client.get('/login/google/callback')
                check('login aceito quando o sub estava em outro usuário',
                      resp.status_code == 302 and 'erro=' not in resp.headers['Location'])
            db.session.expire_all()
            check('vínculo antigo liberado',
                  db.session.get(User, id_outro).google_sub is None)
            check('vínculo movido para o usuário correto',
                  db.session.get(User, id_ok).google_sub == SUB_NOVO)

        finally:
            auth_module.google_client = google_client_original
            auth_module.google_login_enabled = google_enabled_original
            db.session.rollback()
            cleanup(firms, [db.session.get(User, u.id) for u in users if db.session.get(User, u.id)])

    print()
    if falhas:
        print(f'{len(falhas)} verificação(ões) falharam: {", ".join(falhas)}')
        return 1
    print('Todas as verificações passaram.')
    return 0


if __name__ == '__main__':
    sys.exit(run())
