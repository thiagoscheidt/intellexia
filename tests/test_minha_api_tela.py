#!/usr/bin/env python3
"""
Tela Minha API: criar (token mostrado uma vez), listar, revogar e a aba do admin.

O token aparece só na resposta da criação, nunca na lista nem na URL; cada um
vê os próprios tokens; a aba "Tokens do escritório" é só de admin e só do
escritório dele. Escritórios descartáveis, removidos no fim.

    uv run python tests/test_minha_api_tela.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, ApiToken, LawFirm, User, UserPageVisit
from app.services import api_token_service

CNPJS = ('00000000001776', '00000000001857')
_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _cleanup():
    for cnpj in CNPJS:
        firm = LawFirm.query.filter_by(cnpj=cnpj).first()
        if not firm:
            continue
        ApiToken.query.filter_by(law_firm_id=firm.id).delete()
        for u in User.query.filter_by(law_firm_id=firm.id).all():
            UserPageVisit.query.filter_by(user_id=u.id).delete()
            db.session.delete(u)
        db.session.delete(firm)
    db.session.commit()


def _setup():
    _cleanup()
    usuarios = {}
    for i, cnpj in enumerate(CNPJS):
        firm = LawFirm(name=f'Escritório Teste Minha API {i}', cnpj=cnpj)
        db.session.add(firm)
        db.session.flush()
        for papel in ('admin', 'lawyer'):
            u = User(law_firm_id=firm.id, name=f'{papel} {i}', role=papel, is_active=True,
                     email=f'{papel}{i}__test_minha_api@example.com')
            u.set_password('x')
            db.session.add(u)
            usuarios[(i, papel)] = u
    db.session.commit()
    return usuarios


def _logar(c, u):
    with c.session_transaction() as s:
        s.clear()
        s['user_id'] = u.id
        s['law_firm_id'] = u.law_firm_id
        s['user_role'] = u.role


def test_criar_e_listar(c, usuarios):
    print('\n1. Criar e listar')
    u = usuarios[(0, 'lawyer')]
    _logar(c, u)
    r = c.get('/minha-api/')
    check('lista abre', r.status_code == 200, str(r.status_code))
    check('botão Criar token', 'Criar token' in r.get_data(as_text=True))

    r = c.post('/minha-api/tokens', data={'nome': 'Claude Code do notebook', 'validade': '30'})
    html = r.get_data(as_text=True)
    achados = re.findall(r'itx_[A-Za-z0-9_\-]{30,}', html)
    check('resposta da criação traz o token', r.status_code == 200 and achados, str(r.status_code))
    check('token aparece uma vez só (um valor)', len(set(achados)) == 1, str(set(achados)))
    check('aviso de que não aparece de novo', 'não aparece de novo' in html)
    check('página com o token não vai para cache', 'no-store' in (r.headers.get('Cache-Control') or ''))
    texto = achados[0] if achados else ''
    check('token criado autentica', texto and api_token_service.autenticar(texto).id == u.id)
    reg = ApiToken.query.filter_by(user_id=u.id).one()
    check('validade escolhida', (reg.expires_at - reg.created_at).days == 30)

    r = c.get('/minha-api/')
    html = r.get_data(as_text=True)
    check('lista sem o token', texto not in html)
    check('lista com o nome e o final', 'Claude Code do notebook' in html and texto[-4:] in html)

    r = c.post('/minha-api/tokens', data={'nome': 'x', 'validade': '7'})
    check('validade fora da lista recusada', r.status_code in (302, 400) and
          ApiToken.query.filter_by(user_id=u.id).count() == 1)
    return reg


def test_revogar(c, usuarios, reg):
    print('\n2. Revogar')
    outro = usuarios[(0, 'admin')]
    _logar(c, usuarios[(0, 'lawyer')])
    r = c.post(f'/minha-api/tokens/{reg.id}/revogar')
    check('dono revoga', r.status_code == 302)
    db.session.refresh(reg)
    check('situação revogado', api_token_service.situacao(reg) == 'revogado')
    html = c.get('/minha-api/').get_data(as_text=True)
    check('lista mostra revogado', 'Revogado' in html)

    alvo, _ = api_token_service.criar(outro, 'do admin')
    r = c.post(f'/minha-api/tokens/{alvo.id}/revogar')
    db.session.refresh(alvo)
    check('lawyer não revoga token de outro', alvo.revoked_at is None)


def test_admin(c, usuarios):
    print('\n3. Tokens do escritório (admin)')
    _logar(c, usuarios[(0, 'lawyer')])
    r = c.get('/minha-api/escritorio')
    check('lawyer não entra', r.status_code == 302, str(r.status_code))

    api_token_service.criar(usuarios[(1, 'lawyer')], 'Token de outro escritório')
    _logar(c, usuarios[(0, 'admin')])
    r = c.get('/minha-api/escritorio')
    html = r.get_data(as_text=True)
    check('admin entra', r.status_code == 200, str(r.status_code))
    check('vê token de outro usuário do escritório', 'Claude Code do notebook' in html and 'lawyer 0' in html)
    check('não vê de outro escritório', 'Token de outro escritório' not in html)

    api_token_service.criar(usuarios[(0, 'lawyer')], "x');alert(document.cookie);//")
    html = c.get('/minha-api/escritorio').get_data(as_text=True)
    check('nome de token nunca dentro de JavaScript inline',
          'onsubmit' not in html and 'alert(document.cookie)' not in html.split('<script')[-1],
          html[html.find('alert(') - 120:][:200] if 'alert(' in html else '')

    alvo, _ = api_token_service.criar(usuarios[(0, 'lawyer')], 'Para o admin revogar')
    r = c.post(f'/minha-api/tokens/{alvo.id}/revogar', data={'voltar': 'escritorio'})
    db.session.refresh(alvo)
    check('admin revoga token de outro', alvo.revoked_at is not None)
    check('volta para a aba do escritório', r.headers.get('Location', '').endswith('/minha-api/escritorio'))


def test_modal_header(c, usuarios):
    print('\n5. Botão e modal da API no cabeçalho')
    u = usuarios[(1, 'admin')]
    _logar(c, u)
    html = c.get('/minha-api/documentacao').get_data(as_text=True)
    check('botão da API ao lado do Claude', 'data-bs-target="#apiModal"' in html
          and html.find('#claudeMcpModal') < html.find('#apiModal'))
    check('modal com endereço base e mini documentação',
          'id="apiModal"' in html and 'http://localhost/api/v1' in html and '/fap/beneficios' in html)

    r = c.get('/minha-api/tokens.json')
    check('lista JSON vazia', r.status_code == 200 and r.get_json()['tokens'] == [], r.get_data(as_text=True)[:200])
    r = c.post('/minha-api/tokens.json', json={'nome': 'Pelo modal', 'validade': 180})
    d = r.get_json() or {}
    check('cria pelo modal: 201 com o token', r.status_code == 201 and d.get('token', '').startswith('itx_'),
          r.get_data(as_text=True)[:200])
    check('resposta da criação sem cache', 'no-store' in (r.headers.get('Cache-Control') or ''))
    check('validade escolhida', d.get('expira_em') and api_token_service.autenticar(d['token']).id == u.id)
    lista = c.get('/minha-api/tokens.json').get_json()['tokens']
    check('lista traz o token sem o texto', len(lista) == 1 and d['token'] not in str(lista) and lista[0]['final'] == d['token'][-4:])
    r = c.post('/minha-api/tokens.json', json={'nome': 'x', 'validade': 7})
    check('validade inválida: 400', r.status_code == 400 and 'erro' in r.get_json())
    r = c.post('/minha-api/tokens.json', json={'nome': 'sem validade', 'validade': None})
    check('sem validade aceita', r.status_code == 201 and r.get_json()['expira_em'] is None)

    r = c.post(f'/minha-api/tokens/{lista[0]["id"]}/revogar.json')
    check('revoga pelo modal', r.status_code == 200 and r.get_json()['token']['situacao'] == 'revogado')
    alheio = ApiToken.query.filter(ApiToken.user_id != u.id).first()
    r = c.post(f'/minha-api/tokens/{alheio.id}/revogar.json')
    check('token de outro escritório: 403', r.status_code == 403, str(r.status_code))

    sem = User(law_firm_id=u.law_firm_id, name='sem api', role='lawyer', is_active=True,
               email='semapi__test_minha_api@example.com')
    sem.set_password('x')
    sem.set_module_permissions(['dashboard'])
    db.session.add(sem)
    db.session.commit()
    _logar(c, sem)
    html = c.get('/').get_data(as_text=True)
    check('sem o módulo api: sem botão nem modal', 'apiModal' not in html)
    r = c.get('/minha-api/tokens.json')
    check('sem o módulo api: JSON negado', r.status_code in (302, 403), str(r.status_code))


def test_sem_sessao(c):
    print('\n4. Sem sessão')
    with c.session_transaction() as s:
        s.clear()
    r = c.post('/minha-api/tokens', data={'nome': 'x', 'validade': '30'})
    check('POST sem sessão vai para o login', r.status_code == 302 and 'login' in r.headers.get('Location', ''))


def main() -> int:
    with app.app_context():
        usuarios = _setup()
        try:
            c = app.test_client()
            reg = test_criar_e_listar(c, usuarios)
            test_revogar(c, usuarios, reg)
            test_admin(c, usuarios)
            test_modal_header(c, usuarios)
            test_sem_sessao(c)
        finally:
            db.session.rollback()
            _cleanup()

    print('\n' + '=' * 62)
    if _falhas:
        print(f'❌ {len(_falhas)} verificação(ões) falharam:')
        for nome in _falhas:
            print(f'   - {nome}')
        return 1
    print('✅ Tudo verde')
    return 0


if __name__ == '__main__':
    sys.exit(main())
