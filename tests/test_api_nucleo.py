#!/usr/bin/env python3
"""
Núcleo da API (/api/v1): autenticação só por Bearer, CORS, erros, limite e registro de uso.

Cookie de sessão e token na URL não autenticam; o preflight do navegador passa
sem token; exceção inesperada vira 500 sem traceback e conta como erro no uso;
as permissões são as atuais do usuário. Escritório descartável, removido no fim.

    uv run python tests/test_api_nucleo.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.blueprints import public_api
from app.models import db, ApiToken, LawFirm, User, UserMcpCall
from app.services import api_token_service

CNPJ = '00000000001342'
_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _cleanup():
    firm = LawFirm.query.filter_by(cnpj=CNPJ).first()
    if not firm:
        return
    ApiToken.query.filter_by(law_firm_id=firm.id).delete()
    UserMcpCall.query.filter_by(law_firm_id=firm.id).delete()
    User.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def _setup():
    _cleanup()
    firm = LawFirm(name='Escritório Teste API Núcleo', cnpj=CNPJ)
    db.session.add(firm)
    db.session.flush()
    u = User(law_firm_id=firm.id, name='Advogada API', role='lawyer', is_active=True,
             email='lawyer__test_api_nucleo@example.com')
    u.set_password('x')
    db.session.add(u)
    db.session.commit()
    _, texto = api_token_service.criar(u, 'Teste núcleo')
    return firm, u, texto


def _auth(texto):
    return {'Authorization': f'Bearer {texto}'}


def test_autenticacao(c, u, texto):
    print('\n1. Autenticação só pelo header')
    r = c.get('/api/v1/eu')
    check('sem header: 401', r.status_code == 401, str(r.status_code))
    check('erro no formato {"erro": ...}', 'erro' in (r.get_json() or {}), r.get_data(as_text=True)[:200])
    r = c.get(f'/api/v1/eu?token={texto}')
    check('token na URL: 401', r.status_code == 401, str(r.status_code))
    r = c.get('/api/v1/eu', headers={'Authorization': f'bearer   {texto}  '})
    check('"bearer" minúsculo com espaços: 200', r.status_code == 200, str(r.status_code))
    r = c.get('/api/v1/eu', headers={'Authorization': 'Basic abc'})
    check('outro esquema: 401', r.status_code == 401)

    with c.session_transaction() as s:
        s['user_id'] = u.id
        s['law_firm_id'] = u.law_firm_id
    r = c.get('/api/v1/eu')
    check('sessão logada sem header: 401', r.status_code == 401, str(r.status_code))
    with c.session_transaction() as s:
        s.clear()


def test_eu(c, u, texto):
    print('\n2. /eu com as permissões atuais')
    r = c.get('/api/v1/eu', headers=_auth(texto))
    d = r.get_json()
    check('usuário e escritório', d['usuario']['id'] == u.id and d['escritorio']['id'] == u.law_firm_id, str(d))
    check('token sem segredo', d['token']['final'] == texto[-4:] and texto not in json.dumps(d))
    check('fap_panel nos módulos', 'fap_panel' in d['modulos'])
    check('cota de nome com fap_panel', 'consultas_nome_restantes_hoje' in d)

    u.set_module_permissions([m for m in u.get_module_permissions() if m != 'fap_panel'])
    db.session.commit()
    d = c.get('/api/v1/eu', headers=_auth(texto)).get_json()
    check('módulo retirado some na hora', 'fap_panel' not in d['modulos'], str(d['modulos']))
    check('sem fap_panel, sem cota de nome', 'consultas_nome_restantes_hoje' not in d)

    u.set_module_permissions([m for m in u.get_module_permissions() if m != 'api'])
    db.session.commit()
    r = c.get('/api/v1/eu', headers=_auth(texto))
    check('sem o módulo api: 403', r.status_code == 403, str(r.status_code))
    u.set_module_permissions(None)
    u.module_permissions = None
    db.session.commit()


def test_cors(c, texto):
    print('\n3. CORS')
    r = c.options('/api/v1/eu', headers={'Origin': 'http://localhost:5173',
                                        'Access-Control-Request-Method': 'GET',
                                        'Access-Control-Request-Headers': 'authorization'})
    check('preflight sem token: 204', r.status_code == 204, str(r.status_code))
    check('preflight com Allow-Origin *', r.headers.get('Access-Control-Allow-Origin') == '*')
    check('preflight libera Authorization',
          'authorization' in (r.headers.get('Access-Control-Allow-Headers') or '').lower())
    r = c.get('/api/v1/eu', headers=_auth(texto))
    check('resposta 200 com Allow-Origin *', r.headers.get('Access-Control-Allow-Origin') == '*')
    check('sem Allow-Credentials', 'Access-Control-Allow-Credentials' not in r.headers)
    check('resposta da API não vai para cache', 'no-store' in (r.headers.get('Cache-Control') or ''))
    r = c.get('/api/v1/nao-existe', headers=_auth(texto))
    check('rota inexistente: 404 em JSON', r.status_code == 404 and 'erro' in (r.get_json() or {}))
    r = c.get('/api/v1/eu')
    check('401 também com Allow-Origin', r.headers.get('Access-Control-Allow-Origin') == '*')


def test_erro_inesperado(u, texto):
    print('\n4. Exceção inesperada')

    def explode(ctx):
        raise RuntimeError('detalhe interno que não pode vazar')

    with app.test_request_context('/api/v1/eu', headers=_auth(texto)):
        resp = public_api.executar('GET /_teste_erro', None, explode)
    corpo = resp.get_data(as_text=True)
    check('500', resp.status_code == 500, str(resp.status_code))
    check('sem traceback nem detalhe', 'Traceback' not in corpo and 'detalhe interno' not in corpo, corpo)
    linha = UserMcpCall.query.filter_by(user_id=u.id, kind='api', name='GET /_teste_erro').first()
    check('uso registrado com erro', linha is not None and linha.errors == 1)
    check('erro registrado só com o tipo (sem texto que pode trazer argumento)',
          linha is not None and linha.last_error == 'RuntimeError', linha.last_error if linha else '')


def test_uso_e_atividade(c, u, texto):
    print('\n5. Registro de uso e last_activity')
    antes = u.last_activity
    c.get('/api/v1/eu', headers=_auth(texto))
    linha = UserMcpCall.query.filter_by(user_id=u.id, kind='api', name='GET /eu').first()
    check('uso registrado como kind=api', linha is not None and linha.calls >= 1)
    db.session.refresh(u)
    check('last_activity intocado', u.last_activity == antes, f'{antes} → {u.last_activity}')


def test_limite(c, texto):
    print('\n6. Limite por minuto')
    os.environ['API_LIMITE_POR_MINUTO'] = '3'
    public_api._janelas.clear()
    try:
        codigos = [c.get('/api/v1/eu', headers=_auth(texto)).status_code for _ in range(4)]
        check('4ª chamada: 429', codigos == [200, 200, 200, 429], str(codigos))
        r = c.get('/api/v1/eu', headers=_auth(texto))
        check('429 com Retry-After', r.headers.get('Retry-After') is not None)
    finally:
        del os.environ['API_LIMITE_POR_MINUTO']
        public_api._janelas.clear()


def main() -> int:
    with app.app_context():
        firm, u, texto = _setup()
        try:
            c = app.test_client()
            test_autenticacao(c, u, texto)
            test_eu(c, u, texto)
            test_cors(c, texto)
            test_erro_inesperado(u, texto)
            test_uso_e_atividade(c, u, texto)
            test_limite(c, texto)
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
