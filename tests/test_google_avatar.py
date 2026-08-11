#!/usr/bin/env python3
"""
Avatar do usuário na header a partir da foto do Google.

Cobre o sanitizador da URL (o valor vai direto para o src de um <img>),
a coluna no modelo, a macro do avatar e o uso dela na header.

    uv run python tests/test_google_avatar.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import render_template, render_template_string, session

from main import app
from app.blueprints import auth
from app.models import db, LawFirm, User
from app.services.google_oauth import sanitize_picture_url

FOTO = 'https://lh3.googleusercontent.com/a/ACg8ocKexemplo=s96-c'
CNPJ_TESTE = '00000000000188'
EMAIL_TESTE = 'avatar__test_google@example.com'

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def test_sanitizador():
    print('\n1. Sanitizador da URL da foto')
    check('URL do CDN do Google passa intacta', sanitize_picture_url(FOTO) == FOTO,
          repr(sanitize_picture_url(FOTO)))
    check('outro subdomínio do CDN passa',
          sanitize_picture_url('https://lh5.googleusercontent.com/a/x') ==
          'https://lh5.googleusercontent.com/a/x')
    check('espaços em volta são aparados', sanitize_picture_url(f'  {FOTO}  ') == FOTO)
    check('http:// é recusado',
          sanitize_picture_url('http://lh3.googleusercontent.com/a/x') is None)
    check('javascript: é recusado', sanitize_picture_url('javascript:alert(1)') is None)
    check('host de terceiro é recusado',
          sanitize_picture_url('https://exemplo.invalido/foto.png') is None)
    check('host que apenas termina parecido é recusado',
          sanitize_picture_url('https://malgoogleusercontent.com/foto.png') is None)
    check('string vazia vira None', sanitize_picture_url('') is None)
    check('None vira None', sanitize_picture_url(None) is None)


def test_coluna_no_modelo():
    print('\n2. Coluna no modelo')
    coluna = User.__table__.columns.get('google_picture_url')
    check('users.google_picture_url existe', coluna is not None)
    if coluna is None:
        return
    check('é nullable (login por senha não tem foto)', coluna.nullable)
    check('comporta a URL do CDN', getattr(coluna.type, 'length', 0) >= 512,
          repr(getattr(coluna.type, 'length', None)))


def _render_macro(picture):
    with app.test_request_context('/'):
        session['user_name'] = 'Thiago'
        if picture:
            session['user_picture'] = picture
        return render_template_string(
            "{% from 'partials/user_avatar.html' import user_avatar %}"
            "{{ user_avatar(32, 14) }}"
        )


def test_macro_com_foto():
    print('\n3. Macro do avatar — com foto')
    html = _render_macro(FOTO)
    check('renderiza <img> com a URL do Google', f'src="{FOTO}"' in html, html)
    check('não vaza o referer para o Google', 'referrerpolicy="no-referrer"' in html)
    check('a inicial continua no DOM como fallback',
          re.search(r'>\s*T\s*<', html) is not None, html)
    check('o fallback começa escondido', 'display:none' in html.replace(' ', ''), html)
    check('onerror troca a imagem pela inicial', 'onerror=' in html, html)


def test_macro_sem_foto():
    print('\n4. Macro do avatar — sem foto')
    html = _render_macro(None)
    check('não renderiza <img>', '<img' not in html, html)
    check('mostra a inicial', re.search(r'>\s*T\s*<', html) is not None, html)
    check('a inicial não fica escondida', 'display:none' not in html.replace(' ', ''), html)


def test_header_usa_a_macro():
    print('\n5. Header usa a macro nos dois avatares')
    with app.test_request_context('/'):
        session['user_name'] = 'Thiago'
        session['user_email'] = 'thiago@exemplo.invalido'
        session['user_picture'] = FOTO
        html = render_template(
            'partials/header.html',
            can_view_module=lambda chave: False,
            recent_case_comments_count=0,
            recent_case_comments=[],
        )
    check('a foto aparece no chip e no dropdown', html.count(f'src="{FOTO}"') == 2,
          f'ocorrências: {html.count(chr(34) + FOTO + chr(34))}')
    check('os dois avatares têm fallback', html.count('onerror=') == 2,
          f'ocorrências: {html.count("onerror=")}')

    raiz = Path(__file__).resolve().parent.parent
    fonte = raiz / 'templates' / 'partials' / 'header.html'
    origem = fonte.read_text(encoding='utf-8')
    check('a header importa a macro', 'user_avatar' in origem)
    check('não sobrou avatar de inicial montado à mão na header',
          "session.get('user_name', 'U')" not in origem)


class FakeGoogleClient:
    """Devolve claims prontas — nenhuma chamada de rede, nenhum token real."""

    def __init__(self, claims):
        self.claims = claims

    def authorize_access_token(self):
        return {'userinfo': self.claims}


def _setup_usuario():
    firm = LawFirm.query.filter_by(cnpj=CNPJ_TESTE).first()
    if not firm:
        firm = LawFirm(name='Escritório Teste Avatar', cnpj=CNPJ_TESTE)
        db.session.add(firm)
        db.session.flush()

    user = User.query.filter_by(email=EMAIL_TESTE).first()
    if not user:
        user = User(law_firm_id=firm.id, name='Thiago Teste', email=EMAIL_TESTE,
                    role='admin', is_active=True)
        user.set_password('x')
        db.session.add(user)
    db.session.commit()
    return firm, user


def _callback_com_claims(claims):
    """Roda o callback do Google com um client falso e devolve a sessão."""
    original = auth.google_client
    auth.google_client = lambda: FakeGoogleClient(claims)
    try:
        with app.test_client() as c:
            c.get('/login/google/callback')
            with c.session_transaction() as sessao:
                return dict(sessao)
    finally:
        auth.google_client = original


def test_callback_grava_a_foto():
    print('\n6. Callback do Google grava a foto e popula a sessão')
    with app.app_context():
        firm, user = _setup_usuario()
        try:
            claims = {'sub': 'sub-teste-avatar', 'email': EMAIL_TESTE,
                      'email_verified': True, 'picture': FOTO}
            sessao = _callback_com_claims(claims)

            db.session.expire_all()
            gravado = User.query.filter_by(email=EMAIL_TESTE).first()
            check('a foto fica gravada no usuário', gravado.google_picture_url == FOTO,
                  repr(gravado.google_picture_url))
            check('a sessão carrega a foto', sessao.get('user_picture') == FOTO,
                  repr(sessao.get('user_picture')))

            # Foto removida no Google: o campo é reescrito, não fica preso na antiga.
            claims_sem_foto = dict(claims, picture=None)
            sessao = _callback_com_claims(claims_sem_foto)
            db.session.expire_all()
            gravado = User.query.filter_by(email=EMAIL_TESTE).first()
            check('foto removida no Google limpa o campo',
                  gravado.google_picture_url is None, repr(gravado.google_picture_url))
            check('sessão sem foto cai no fallback',
                  sessao.get('user_picture') is None, repr(sessao.get('user_picture')))

            # URL fora do CDN do Google nunca chega ao src do <img>.
            claims_hostil = dict(claims, picture='https://exemplo.invalido/foto.png')
            _callback_com_claims(claims_hostil)
            db.session.expire_all()
            gravado = User.query.filter_by(email=EMAIL_TESTE).first()
            check('URL de host estranho é descartada',
                  gravado.google_picture_url is None, repr(gravado.google_picture_url))
        finally:
            db.session.delete(user)
            db.session.delete(firm)
            db.session.commit()


def test_login_por_senha_mantem_a_foto():
    print('\n7. Login por senha reaproveita a foto já gravada')
    with app.app_context():
        firm, user = _setup_usuario()
        user.google_picture_url = FOTO
        db.session.commit()
        try:
            with app.test_request_context('/'):
                auth._start_user_session(user)
                check('a sessão do login por senha também traz a foto',
                      session.get('user_picture') == FOTO, repr(session.get('user_picture')))
        finally:
            db.session.delete(user)
            db.session.delete(firm)
            db.session.commit()


def main():
    print('=' * 60)
    print('Avatar do Google na header')
    print('=' * 60)
    test_sanitizador()
    test_coluna_no_modelo()
    test_macro_com_foto()
    test_macro_sem_foto()
    test_header_usa_a_macro()
    test_callback_grava_a_foto()
    test_login_por_senha_mantem_a_foto()
    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): ' + ', '.join(_falhas))
        return 1
    print('✅ Tudo verde')
    return 0


if __name__ == '__main__':
    sys.exit(main())
