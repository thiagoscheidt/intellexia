#!/usr/bin/env python3
"""
Testes das rotas do módulo Diário Oficial.

Usa app.test_client() no padrão dos demais testes de rota do projeto.

    uv run python tests/test_dou_routes.py
"""

import re
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


def test_tela_de_busca():
    print('\n6. Tela de busca')
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    check('dou.busca existe', 'dou.busca' in endpoints)

    with app.app_context():
        usuario = User.query.filter_by(role='admin').first()
        if usuario is None:
            print('  ⏭️  nenhum usuário admin no banco — pulando')
            return
        user_id, firm_id = usuario.id, usuario.law_firm_id

    with app.test_client() as c:
        with c.session_transaction() as sessao:
            sessao['user_id'] = user_id
            sessao['law_firm_id'] = firm_id
            sessao['user_role'] = 'admin'

        resposta = c.get('/dou/busca')
        check('abre sem termo (estado inicial)', resposta.status_code == 200,
              str(resposta.status_code))
        html = resposta.get_data(as_text=True)
        check('estado inicial, sem resultados', 'dou-hit' not in html)
        check('convida a agir', 'O que você procura' in html)

        resposta = c.get('/dou/busca?q=portaria')
        check('busca por termo responde 200', resposta.status_code == 200,
              str(resposta.status_code))

        resposta = c.get('/dou/busca?q=' + 'z' * 30)
        check('termo sem resultado responde 200, não 500',
              resposta.status_code == 200, str(resposta.status_code))
        check('estado vazio explica o que foi buscado',
              'Nada encontrado' in resposta.get_data(as_text=True))


def test_chip_da_header():
    """O chip do DOU conta saúde da captura, e some quando está tudo em dia.

    Ao contrário dos outros dois chips, este não é fila de trabalho: o módulo
    não tem "não lidas". Um contador de matérias só cresceria e, ao lado de
    badges que significam "faça algo", ensinaria a ignorar a área inteira.
    """
    print('\n7. Chip de saúde na header')
    from datetime import date

    def chip(saude, permissao=lambda k: k == 'dou'):
        with app.test_request_context('/dou/'):
            html = render_template('partials/header.html',
                                   can_view_module=permissao, dou_health=saude,
                                   fap_review_pending_counts=None,
                                   process_deadline_counts=None)
        achado = re.search(
            r'<a class="module-counter-chip"[^>]*?/dou/captura[^>]*>(.*?)</a>',
            html, re.S)
        return re.findall(r'text-bg-(\w+)', achado.group(1)) if achado else None

    em_dia = {'com_erro': 0, 'parada': False, 'ultima_data': date(2026, 8, 10), 'badge': False}
    com_falha = {'com_erro': 3, 'parada': False, 'ultima_data': date(2026, 8, 10), 'badge': True}
    parada = {'com_erro': 0, 'parada': True, 'ultima_data': date(2026, 7, 1), 'badge': True}
    ambos = {'com_erro': 2, 'parada': True, 'ultima_data': date(2026, 7, 1), 'badge': True}
    vazio = {'com_erro': 0, 'parada': False, 'ultima_data': None, 'badge': False}

    check('tudo em dia: o chip não aparece', chip(em_dia) is None, str(chip(em_dia)))
    check('edição com falha: badge âmbar', chip(com_falha) == ['warning'], str(chip(com_falha)))
    check('captura parada: badge vermelho', chip(parada) == ['danger'], str(chip(parada)))
    check('os dois problemas: dois badges', chip(ambos) == ['warning', 'danger'], str(chip(ambos)))
    check('acervo vazio não alarma (instalação sem credencial)',
          chip(vazio) is None, str(chip(vazio)))
    check('sem a permissão do módulo, nunca aparece',
          chip(ambos, permissao=lambda k: False) is None)


def test_contadores_de_saude():
    """A regra de dias úteis não pode alarmar na segunda-feira."""
    print('\n8. Regra de "a captura parou"')
    from datetime import date
    from app.services import dou_ingestion_service as ing

    check('sexta -> segunda não alarma',
          ing._dias_uteis_entre(date(2026, 8, 7), date(2026, 8, 10)) < ing.TOLERANCIA_DIAS_UTEIS)
    check('sexta -> terça tolera (feriado na segunda)',
          ing._dias_uteis_entre(date(2026, 8, 7), date(2026, 8, 11)) < ing.TOLERANCIA_DIAS_UTEIS)
    check('sexta -> quarta alarma',
          ing._dias_uteis_entre(date(2026, 8, 7), date(2026, 8, 12)) >= ing.TOLERANCIA_DIAS_UTEIS)

    with app.app_context():
        saude = ing.health_counters()
    check('health_counters devolve as chaves da tela',
          set(saude) == {'com_erro', 'parada', 'ultima_data', 'badge'}, str(sorted(saude)))
    check('badge reflete os dois sinais',
          saude['badge'] == bool(saude['com_erro'] or saude['parada']), str(saude))


def main():
    print('=' * 60)
    print('TESTES DAS ROTAS DO DIÁRIO OFICIAL')
    print('=' * 60)

    test_registro_do_modulo()
    test_rotas_registradas()
    test_exige_login()
    test_navegacao_em_tres_niveis()
    test_link_no_menu_lateral()
    test_tela_de_busca()
    test_chip_da_header()
    test_contadores_de_saude()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
