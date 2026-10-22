#!/usr/bin/env python3
"""
Documentação da API: OpenAPI e página gerados do mesmo registro de rotas, e o manual.

Uma operação por rota do registro, parâmetro de caminho sempre declarado, o
endereço base da instalação, a página logada com todas as rotas e o manual
da API na lista de manuais. Escritório descartável, removido no fim.

    uv run python tests/test_api_documentacao.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.blueprints import public_api
from app.models import db, ApiToken, LawFirm, User, UserMcpCall, UserPageVisit
from app.services import api_token_service
from app.services.public_api_catalogo import ROTAS, openapi, resumo_markdown

CNPJ = '00000000001695'
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
    for u in User.query.filter_by(law_firm_id=firm.id).all():
        UserPageVisit.query.filter_by(user_id=u.id).delete()
        db.session.delete(u)
    db.session.delete(firm)
    db.session.commit()


def _setup():
    _cleanup()
    firm = LawFirm(name='Escritório Teste API Docs', cnpj=CNPJ)
    db.session.add(firm)
    db.session.flush()
    usuarios = {}
    for nome, modulos in (('com_api', None), ('sem_api', ['dashboard', 'fap_panel'])):
        u = User(law_firm_id=firm.id, name=nome, role='lawyer', is_active=True,
                 email=f'{nome}__test_api_docs@example.com')
        u.set_password('x')
        if modulos:
            u.set_module_permissions(modulos)
        db.session.add(u)
        usuarios[nome] = u
    db.session.commit()
    _, texto = api_token_service.criar(usuarios['com_api'], 'docs')
    return usuarios, texto


def _logar(c, u):
    with c.session_transaction() as s:
        s['user_id'] = u.id
        s['law_firm_id'] = u.law_firm_id
        s['user_role'] = u.role


def test_openapi():
    print('\n1. OpenAPI do registro')
    spec = openapi('https://exemplo.test')
    check('versão 3.1', spec['openapi'].startswith('3.1'))
    check('servers com /api/v1', spec['servers'][0]['url'] == 'https://exemplo.test/api/v1')
    check('esquema bearer', spec['components']['securitySchemes']['bearer']['scheme'] == 'bearer')
    operacoes = [(m.upper(), caminho) for caminho, ops in spec['paths'].items() for m in ops]
    check('uma operação por rota (+ /eu)',
          sorted(operacoes) == sorted([(r.metodo, r.caminho) for r in ROTAS] + [('GET', '/eu')]),
          f'{len(operacoes)} × {len(ROTAS) + 1}')
    for caminho, ops in spec['paths'].items():
        for op in ops.values():
            declarados = {p['name'] for p in op.get('parameters', []) if p['in'] == 'path'}
            no_caminho = {s.strip('{}') for s in caminho.split('/') if s.startswith('{')}
            if declarados != no_caminho:
                check(f'parâmetros de caminho de {caminho}', False, f'{declarados} × {no_caminho}')
    check('todo parâmetro de caminho declarado', True)
    post = spec['paths']['/segurados/revelar-nome']['post']
    check('POST com corpo JSON e cpf obrigatório',
          'cpf' in post['requestBody']['content']['application/json']['schema']['required'])
    check('x-modulo informado', spec['paths']['/fap/beneficios']['get']['x-modulo'] == 'fap_panel')
    resumo = resumo_markdown()
    check('resumo com uma linha por rota', all(r.caminho in resumo for r in ROTAS))
    check('resumo diz o que cada rota devolve', resumo.count('Devolve:') == len(ROTAS) + 1)
    item = (spec['paths']['/fap/beneficios']['get']['responses']['200']['content']['application/json']
            ['schema']['properties']['itens']['items']['properties'])
    check('OpenAPI descreve os campos de cada item da lista', 'numero_beneficio' in item and 'segurado_cpf' in item)
    limite = next(p for p in spec['paths']['/fap/beneficios']['get']['parameters'] if p['name'] == 'limite')
    check('OpenAPI diz o teto do limite', limite['schema'].get('maximum') == 1000, str(limite['schema']))


def test_rota_openapi(c, texto):
    print('\n2. /api/v1/openapi.json')
    r = c.get('/api/v1/openapi.json', headers={'Authorization': f'Bearer {texto}'})
    check('com token: 200', r.status_code == 200, str(r.status_code))
    check('servers do host acessado', r.get_json()['servers'][0]['url'].endswith('/api/v1'))
    check('sem token: 401', c.get('/api/v1/openapi.json').status_code == 401)


def test_pagina(c, usuarios):
    print('\n3. Página de documentação')
    _logar(c, usuarios['com_api'])
    r = c.get('/minha-api/documentacao')
    html = r.get_data(as_text=True)
    check('logado com o módulo: 200', r.status_code == 200, str(r.status_code))
    faltando = [rota.caminho for rota in ROTAS if rota.caminho not in html]
    check('todas as rotas na página', not faltando, str(faltando))
    check('endereço base da instalação', 'http://localhost/api/v1' in html)
    check('exemplo com $INTELLEXIA_TOKEN', 'INTELLEXIA_TOKEN' in html)
    check('seção do Claude Code', 'Claude Code' in html)
    check('cada rota mostra os campos da resposta', html.count('Resposta:') == len(ROTAS) + 1,
          str(html.count('Resposta:')))
    check('campos aninhados com o caminho (itens[].campo)', 'itens[].' in html and 'segurado_cpf' in html)
    check('exemplo de resposta em JSON', html.count('Exemplo de resposta') == len(ROTAS) + 1)
    _logar(c, usuarios['sem_api'])
    r = c.get('/minha-api/documentacao')
    check('sem o módulo api: redireciona', r.status_code == 302, str(r.status_code))
    with c.session_transaction() as s:
        s.clear()


def test_manual(c, usuarios):
    print('\n4. Manual')
    _logar(c, usuarios['com_api'])
    html = c.get('/docs/manuais').get_data(as_text=True)
    check('manual da API listado', 'API do IntellexIA' in html)
    with c.session_transaction() as s:
        s.clear()


def main() -> int:
    with app.app_context():
        usuarios, texto = _setup()
        public_api._janelas.clear()
        try:
            c = app.test_client()
            test_openapi()
            test_rota_openapi(c, texto)
            test_pagina(c, usuarios)
            test_manual(c, usuarios)
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
