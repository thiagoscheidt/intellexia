#!/usr/bin/env python3
"""
Uso do MCP por usuário na tela de Atividade de Usuários.

O middleware do servidor MCP soma cada chamada (ferramenta ou comando pronto)
em user_mcp_calls, por usuário e dia, sem os argumentos. A tela mostra se o
usuário está conectado (token de renovação válido), o cliente, o uso de hoje e,
no botão MCP, as funções usadas. Escritório descartável, removido no fim.

    uv run python tests/test_mcp_uso.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp.exceptions import ToolError

from main import app
from app.models import (
    db, LawFirm, McpOAuthClient, McpOAuthToken, User, UserMcpCall, UserPageVisit,
)
from app.services import access_audit_service as svc

CNPJ = '00000000001099'
CLIENTE = 'cliente-teste-uso-mcp'
_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _setup():
    f = LawFirm.query.filter_by(cnpj=CNPJ).first()
    if f:
        _cleanup(f)
    firm = LawFirm(name='Escritório Teste Uso MCP', cnpj=CNPJ)
    db.session.add(firm)
    db.session.flush()
    users = []
    for i, role in enumerate(('admin', 'lawyer', 'lawyer')):
        u = User(law_firm_id=firm.id, name=f'usuario {i}', email=f'u{i}__test_uso_mcp@example.com',
                 role=role, is_active=True)
        u.set_password('x')
        db.session.add(u)
        users.append(u)
    db.session.flush()
    if not McpOAuthClient.query.filter_by(client_id=CLIENTE).first():
        db.session.add(McpOAuthClient(client_id=CLIENTE, client_info_json=json.dumps({'client_name': 'Claude'})))
    agora = int(time.time())
    conectado, antigo, _nunca = users
    db.session.add_all([
        # usuário 0: refresh válido → conectado
        McpOAuthToken(token='tk-uso-1', token_type='refresh', client_id=CLIENTE, user_id=conectado.id,
                      law_firm_id=firm.id, expires_at=agora + 86400, revoked=False),
        # usuário 1: só token revogado → desconectado
        McpOAuthToken(token='tk-uso-2', token_type='refresh', client_id=CLIENTE, user_id=antigo.id,
                      law_firm_id=firm.id, expires_at=agora + 86400, revoked=True),
    ])
    db.session.commit()
    return firm, users


def _cleanup(firm):
    McpOAuthToken.query.filter_by(law_firm_id=firm.id).delete()
    UserMcpCall.query.filter_by(law_firm_id=firm.id).delete()
    for u in User.query.filter_by(law_firm_id=firm.id).all():
        UserPageVisit.query.filter_by(user_id=u.id).delete()
        db.session.delete(u)
    McpOAuthClient.query.filter_by(client_id=CLIENTE).delete()
    db.session.delete(firm)
    db.session.commit()


def test_registro(firm, users):
    print('\n1. Registro agregado por dia')
    u = users[0]
    svc.record_mcp_call(u.id, firm.id, 'tool', 'resumo_fap', True, 120)
    svc.record_mcp_call(u.id, firm.id, 'tool', 'resumo_fap', True, 80)
    svc.record_mcp_call(u.id, firm.id, 'tool', 'resumo_fap', False, 10, 'ToolError: ' + 'x' * 400)
    svc.record_mcp_call(u.id, firm.id, 'prompt', 'dou_do_dia', True, 5)
    linhas = UserMcpCall.query.filter_by(user_id=u.id).all()
    check('uma linha por função e dia', len(linhas) == 2, str(len(linhas)))
    r = next(l for l in linhas if l.name == 'resumo_fap')
    check('soma chamadas, erros e tempo', (r.calls, r.errors, r.total_ms) == (3, 1, 210),
          str((r.calls, r.errors, r.total_ms)))
    check('erro guardado curto', r.last_error and len(r.last_error) == 255)
    check('comando pronto separado da ferramenta',
          any(l.kind == 'prompt' and l.name == 'dou_do_dia' for l in linhas))

    funcoes = svc.get_user_mcp_functions(firm.id, u.id)
    f = next(x for x in funcoes if x['name'] == 'resumo_fap')
    check('detalhe: chamadas, erros e tempo médio', (f['calls'], f['errors'], f['avg_ms']) == (3, 1, 70), str(f))


def test_conexao(firm, users):
    print('\n2. Conectado / desconectado / nunca')
    info = svc.get_users_mcp(firm.id)
    c, d, n = users
    check('refresh válido = conectado', info[c.id]['connected'] and info[c.id]['clients'] == ['Claude'])
    check('só token revogado = desconectado', not info[d.id]['connected'])
    check('quem nunca conectou não aparece', n.id not in info)
    check('chamadas de hoje', info[c.id]['calls_today'] == 4, str(info[c.id]))
    stats = svc.get_overview_stats(firm.id)
    check('topo: 1 conectado, 1 usou hoje', stats['mcp_connected'] == 1 and stats['mcp_active_today'] == 1, str(stats))


def test_middleware(firm, users):
    print('\n3. Middleware do servidor MCP')
    from mcp_server import usage_log

    u = users[1]
    claims = {'user_id': u.id, 'law_firm_id': firm.id}
    original = usage_log.get_access_token
    usage_log.get_access_token = lambda: SimpleNamespace(claims=claims)
    try:
        mw = usage_log.UsoMcpMiddleware(app)
        ctx = SimpleNamespace(message=SimpleNamespace(name='listar_beneficios_fap', arguments={'cpf': '12345678909'}))

        async def ok(_):
            return 'resultado'

        async def falha(_):
            raise ToolError('Acesso negado')

        res = asyncio.run(mw.on_call_tool(ctx, ok))
        check('devolve o resultado da ferramenta', res == 'resultado')
        try:
            asyncio.run(mw.on_call_tool(ctx, falha))
            check('erro da ferramenta continua subindo', False)
        except ToolError:
            check('erro da ferramenta continua subindo', True)
        # A gravação é de outra thread/sessão: sair do snapshot desta transação.
        db.session.rollback()
        linha = UserMcpCall.query.filter_by(user_id=u.id, name='listar_beneficios_fap').one()
        check('registrou 2 chamadas, 1 erro', (linha.calls, linha.errors) == (2, 1), str((linha.calls, linha.errors)))
        check('não guarda argumentos', '12345678909' not in json.dumps(
            {k: str(getattr(linha, k)) for k in ('name', 'last_error', 'kind')}))

        usage_log.get_access_token = lambda: (_ for _ in ()).throw(RuntimeError('sem token'))
        res = asyncio.run(mw.on_call_tool(ctx, ok))
        check('sem identidade: não registra e não quebra', res == 'resultado')

        def explode(*a, **k):
            raise RuntimeError('banco fora')
        usage_log.get_access_token = lambda: SimpleNamespace(claims=claims)
        original_gravar = usage_log._gravar
        usage_log._gravar = explode
        try:
            check('falha no registro não derruba a ferramenta', asyncio.run(mw.on_call_tool(ctx, ok)) == 'resultado')
        finally:
            usage_log._gravar = original_gravar
    finally:
        usage_log.get_access_token = original


def test_tela(firm, users):
    print('\n4. Tela de Atividade de Usuários')
    admin = users[0]
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(user_id=admin.id, law_firm_id=firm.id, user_role='admin',
                 user_module_permissions=admin.get_module_permissions())
    html = c.get('/admin/access-audit/').get_data(as_text=True)
    check('coluna MCP', '<th>MCP</th>' in html)
    check('conectado / desconectado / nunca', 'Conectado' in html and 'Desconectado' in html and 'Nunca conectou' in html)
    check('linha do topo', '1 de 3 conectados ao MCP' in html, html[html.find('conectados ao MCP') - 40:][:80])
    check('botão MCP só para quem usou ou conectou', html.count('btn-user-mcp"') == 2, str(html.count('btn-user-mcp"')))
    j = c.get(f'/admin/access-audit/users/{admin.id}/mcp?days=30').get_json()
    nomes = {f['name']: f for f in j['functions']}
    check('detalhe por JSON', nomes['resumo_fap']['calls'] == 3 and nomes['dou_do_dia']['kind'] == 'prompt', str(j)[:300])
    outro = LawFirm.query.filter(LawFirm.id != firm.id).first()
    if outro:
        alheio = User.query.filter_by(law_firm_id=outro.id).first()
        if alheio:
            r = c.get(f'/admin/access-audit/users/{alheio.id}/mcp')
            check('usuário de outro escritório: 404', r.status_code == 404)


def main() -> int:
    with app.app_context():
        firm, users = _setup()
        try:
            test_registro(firm, users)
            test_conexao(firm, users)
            test_middleware(firm, users)
            test_tela(firm, users)
        finally:
            db.session.rollback()
            _cleanup(firm)

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
