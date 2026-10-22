#!/usr/bin/env python3
"""
Ferramentas MCP da API: minha_api, criar_token_api, revogar_token_api e documentacao_api.

O token criado pelo Claude aparece só na resposta da criação; a listagem nunca
traz o texto; revogar pelo MCP só alcança os tokens do próprio usuário; a
documentação filtra por grupo. Escritório descartável, removido no fim.

    uv run python tests/test_mcp_api_tokens.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp.exceptions import ToolError

from main import app
from app.models import db, ApiToken, LawFirm, User
from app.services import api_token_service
from mcp_server.tools.api_tokens import (
    criar_token_api_handler, documentacao_api_handler, minha_api_handler, revogar_token_api_handler,
)

CNPJ = '00000000002080'
BASE = 'https://exemplo.test'
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
    User.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def _setup():
    _cleanup()
    firm = LawFirm(name='Escritório Teste MCP API', cnpj=CNPJ)
    db.session.add(firm)
    db.session.flush()
    usuarios = []
    for i in range(2):
        u = User(law_firm_id=firm.id, name=f'usuario {i}', role='lawyer', is_active=True,
                 email=f'u{i}__test_mcp_api_tokens@example.com')
        u.set_password('x')
        db.session.add(u)
        usuarios.append(u)
    db.session.commit()
    return firm, usuarios


def test_criar_e_listar(firm, u):
    print('\n1. Criar e listar')
    r = criar_token_api_handler(firm.id, u.id, 'Claude Code', 30)
    check('devolve o token itx_', r['token'].startswith('itx_'), str(r)[:120])
    check('com final, validade e orientação', r['final'] == r['token'][-4:] and r['expira_em'] and r['orientacao'])
    check('autentica', api_token_service.autenticar(r['token']).id == u.id)
    m = minha_api_handler(firm.id, u.id, BASE)
    check('minha_api traz endereço e documentação',
          m['endereco'] == BASE + '/api/v1' and m['openapi'].endswith('/api/v1/openapi.json')
          and m['documentacao'].endswith('/minha-api/documentacao'), str(m)[:300])
    check('lista o token sem o texto', len(m['tokens']) == 1 and r['token'] not in json.dumps(m))
    try:
        criar_token_api_handler(firm.id, u.id, 'x', 7)
        check('validade inválida recusada', False)
    except ToolError as e:
        check('validade inválida recusada', '30' in str(e), str(e))
    return r


def test_revogar(firm, dono, outro, criado):
    print('\n2. Revogar')
    tid = ApiToken.query.filter_by(user_id=dono.id).first().id
    try:
        revogar_token_api_handler(firm.id, outro.id, tid)
        check('token de outro usuário não é revogado', False)
    except ToolError:
        check('token de outro usuário não é revogado', db.session.get(ApiToken, tid).revoked_at is None)
    r = revogar_token_api_handler(firm.id, dono.id, tid)
    check('dono revoga', r['situacao'] == 'revogado', str(r))
    try:
        revogar_token_api_handler(firm.id, dono.id, 999999999)
        check('token inexistente: erro claro', False)
    except ToolError:
        check('token inexistente: erro claro', True)


def test_documentacao():
    print('\n3. Documentação')
    d = documentacao_api_handler(BASE)
    check('endereço e openapi', d['endereco'] == BASE + '/api/v1' and d['openapi'].endswith('openapi.json'))
    check('todas as rotas', '/fap/beneficios' in d['rotas'] and '/jurisprudencia' in d['rotas'])
    d = documentacao_api_handler(BASE, grupo='fap')
    linhas = [l for l in d['rotas'].splitlines() if l.strip()]
    check('grupo fap só traz /fap', linhas and all(' /fap/' in l for l in linhas), d['rotas'][:300])
    try:
        documentacao_api_handler(BASE, grupo='inexistente')
        check('grupo inexistente: erro com os válidos', False)
    except ToolError as e:
        check('grupo inexistente: erro com os válidos', 'fap' in str(e), str(e))


def main() -> int:
    with app.app_context():
        firm, (dono, outro) = _setup()
        try:
            criado = test_criar_e_listar(firm, dono)
            test_revogar(firm, dono, outro, criado)
            test_documentacao()
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
