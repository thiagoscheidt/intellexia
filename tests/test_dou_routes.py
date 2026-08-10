#!/usr/bin/env python3
"""
Testes das rotas do módulo Diário Oficial.

Usa app.test_client() no padrão dos demais testes de rota do projeto.

    uv run python tests/test_dou_routes.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import render_template

from main import app
from app.models import User, DouEdition, DouArticle
from app.utils.permissions import (MODULE_PERMISSIONS, ENDPOINT_MODULE_MAP,
                                   ROLE_DEFAULT_MODULE_PERMISSIONS)

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def test_registro_do_modulo():
    print('\n1. Registro do módulo nas permissões')
    check("'dou' está em MODULE_PERMISSIONS", 'dou' in MODULE_PERMISSIONS)
    check("rótulo é 'Diario Oficial'", MODULE_PERMISSIONS.get('dou') == 'Diario Oficial',
          repr(MODULE_PERMISSIONS.get('dou')))
    check("prefixo 'dou.' mapeado", ENDPOINT_MODULE_MAP.get('dou.') == 'dou',
          repr(ENDPOINT_MODULE_MAP.get('dou.')))
    check('admin tem o módulo por padrão', 'dou' in ROLE_DEFAULT_MODULE_PERMISSIONS['admin'])
    check('não-admin NÃO tem por padrão (concedível)',
          'dou' not in ROLE_DEFAULT_MODULE_PERMISSIONS['lawyer'])


def test_rotas_registradas():
    print('\n2. Rotas registradas')
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    for esperado in ('dou.edicoes', 'dou.edicao', 'dou.materia', 'dou.captura',
                     'dou.reprocessar', 'dou.baixar_pdf'):
        check(f'{esperado} existe', esperado in endpoints)


def test_exige_login():
    print('\n3. Acesso sem login')
    with app.test_client() as c:
        resposta = c.get('/dou/', follow_redirects=False)
        check('redireciona para o login', resposta.status_code in (301, 302),
              str(resposta.status_code))


def test_navegacao_em_tres_niveis():
    """A entrada é a lista de edições; a matéria fica dois cliques adiante."""
    print('\n4. Navegação em três níveis (sessão de admin)')
    with app.app_context():
        usuario = User.query.filter_by(role='admin').first()
        if usuario is None:
            print('  ⏭️  nenhum usuário admin no banco — pulando')
            return
        user_id, firm_id = usuario.id, usuario.law_firm_id
        edicao = (DouEdition.query
                  .filter_by(status=DouEdition.STATUS_PARSED)
                  .filter(DouEdition.qtd_materias > 0).first())
        artigo = (DouArticle.query.filter_by(edition_id=edicao.id).first()
                  if edicao else None)

    with app.test_client() as c:
        with c.session_transaction() as sessao:
            sessao['user_id'] = user_id
            sessao['law_firm_id'] = firm_id
            sessao['user_role'] = 'admin'

        # Nível 1
        resposta = c.get('/dou/')
        check('nível 1 (edições) responde 200', resposta.status_code == 200,
              str(resposta.status_code))
        html = resposta.get_data(as_text=True)
        check('nível 1 traz o título do módulo', 'Diário Oficial' in html)

        resposta = c.get('/dou/captura')
        check('captura responde 200', resposta.status_code == 200, str(resposta.status_code))

        if edicao is None:
            print('  ⏭️  sem edição capturada — pulando níveis 2 e 3')
            return

        dia = edicao.data_publicacao.isoformat()
        check('nível 1 lista a data capturada',
              edicao.data_publicacao.strftime('%d/%m/%Y') in html)

        # Nível 2
        resposta = c.get(f'/dou/edicao/{dia}')
        check('nível 2 (edição do dia) responde 200', resposta.status_code == 200,
              str(resposta.status_code))
        html = resposta.get_data(as_text=True)
        check('nível 2 mostra as abas de seção', edicao.secao_label in html)
        check('nível 2 lista matérias', '/dou/materia/' in html)

        check('data inexistente no acervo dá 404',
              c.get('/dou/edicao/1900-01-01').status_code == 404)
        check('data mal formatada dá 404',
              c.get('/dou/edicao/10-08-2026').status_code == 404)

        # Nível 3
        if artigo is not None:
            resposta = c.get(f'/dou/materia/{artigo.id}')
            check('nível 3 (matéria) responde 200', resposta.status_code == 200,
                  str(resposta.status_code))
            check('nível 3 volta para a edição',
                  f'/dou/edicao/{dia}' in resposta.get_data(as_text=True))

        check('matéria inexistente dá 404', c.get('/dou/materia/999999').status_code == 404)


def test_link_no_menu_lateral():
    """O item do menu tem de aparecer para quem tem SÓ a permissão 'dou'.

    O módulo é concedido individualmente, então esse é o caso mais provável em
    produção. Na primeira versão o item foi aninhado dentro do submenu do
    Painel de Processos, cujo bloco só renderiza com process_panel ou
    communications — um usuário só com 'dou' não via link nenhum.

    O sidebar é renderizado direto, com can_view_module controlado, em vez de
    forjar a sessão: o middleware check_session recarrega o usuário do banco a
    cada request e sobrescreve user_role/user_module_permissions, então sessão
    forjada nunca vence.
    """
    print('\n5. Link no menu lateral (usuário só com a permissão dou)')

    with app.test_request_context('/dou/'):
        html = render_template('partials/sidebar.html',
                               can_view_module=lambda k: k == 'dou')

    check('o link das edições aparece', '/dou/' in html, html[:200])
    check('o link da captura aparece', '/dou/captura' in html)
    check('o rótulo do módulo aparece', 'Diário Oficial' in html)
    check('é item de primeiro nível, não filho do Painel de Processos',
          'Painel de Processos' not in html and '/process-panel' not in html,
          'o item ainda depende do grupo de process_panel')
    check('não depende do Monitoramento', '/comunicacoes' not in html)


def main():
    print('=' * 60)
    print('TESTES DAS ROTAS DO DIÁRIO OFICIAL')
    print('=' * 60)

    test_registro_do_modulo()
    test_rotas_registradas()
    test_exige_login()
    test_navegacao_em_tres_niveis()
    test_link_no_menu_lateral()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
