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
from app.models import db, User, DouEdition, DouArticle
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
                     'dou.reprocessar', 'dou.baixar_pdf', 'dou.leitor',
                     'dou.pagina_da_edicao_pdf'):
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
    """O chip do DOU fica sempre visível e serve de atalho para o módulo.

    Nunca mostra contagem de matérias: o acervo só cresce, e um número que
    nunca desce ao lado de badges de pendência ensina a ignorar a área. Os
    badges aparecem só quando há o que fazer, e o destino do clique muda com o
    estado — Captura quando há pendência, acervo quando não há.
    """
    print('\n7. Chip do Diário Oficial na header')
    from datetime import date

    def render(saude, permissao=lambda k: k == 'dou'):
        with app.test_request_context('/dou/'):
            html = render_template('partials/header.html',
                                   can_view_module=permissao, dou_health=saude,
                                   fap_review_pending_counts=None,
                                   process_deadline_counts=None)
        return re.search(
            r'<a class="module-counter-chip"\s+href="(/dou/[^"]*)"(.*?)</a>',
            html, re.S)

    def badges(saude, **kw):
        achado = render(saude, **kw)
        return re.findall(r'text-bg-(\w+)', achado.group(2)) if achado else None

    def destino(saude):
        achado = render(saude)
        return achado.group(1) if achado else None

    em_dia = {'com_erro': 0, 'parada': False, 'ultima_data': date(2026, 8, 10), 'badge': False}
    com_falha = {'com_erro': 3, 'parada': False, 'ultima_data': date(2026, 8, 10), 'badge': True}
    parada = {'com_erro': 0, 'parada': True, 'ultima_data': date(2026, 7, 1), 'badge': True}
    ambos = {'com_erro': 2, 'parada': True, 'ultima_data': date(2026, 7, 1), 'badge': True}

    check('tudo em dia: o chip aparece, sem badge', badges(em_dia) == [], str(badges(em_dia)))
    check('edição com falha: badge âmbar', badges(com_falha) == ['warning'], str(badges(com_falha)))
    check('captura parada: badge vermelho', badges(parada) == ['danger'], str(badges(parada)))
    check('os dois problemas: dois badges', badges(ambos) == ['warning', 'danger'], str(badges(ambos)))

    check('sem pendência o clique vai para o acervo',
          destino(em_dia) == '/dou/', destino(em_dia))
    check('com pendência o clique vai para a Captura',
          destino(com_falha) == '/dou/captura', destino(com_falha))

    check('nunca mostra contagem de matérias',
          all(str(n) not in (render(em_dia).group(2) or '') for n in (20682, 24000)),
          render(em_dia).group(2)[:80])

    check('sem a permissão do módulo, não aparece',
          badges(ambos, permissao=lambda k: False) is None)
    check('sem dados de saúde ainda assim renderiza (não quebra a header)',
          badges(None) == [], str(badges(None)))


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


def test_edicao_do_dia():
    """Navegação entre dias, filtros e atalhos da tela da edição."""
    print('\n9. Tela da edição do dia')
    from app.blueprints import dou as tela

    # --- funções puras, sem banco
    class Fake:
        def __init__(self, h): self.orgao_hierarquia = h

    raiz, unidade = tela._orgao_da_linha(
        Fake('Presidência da República/Casa Civil/Agência Brasileira de Inteligência'),
        agrupado=False)
    check('fora do agrupamento: raiz + unidade que assinou',
          (raiz, unidade) == ('Presidência da República',
                              'Agência Brasileira de Inteligência'),
          f'{raiz!r} / {unidade!r}')

    raiz, unidade = tela._orgao_da_linha(
        Fake('Presidência da República/Casa Civil/Agência Brasileira de Inteligência'),
        agrupado=True)
    check('agrupado: a raiz sai da linha (já está no cabeçalho)', raiz is None, repr(raiz))
    check('agrupado: a linha leva o caminho abaixo da raiz',
          unidade == 'Casa Civil/Agência Brasileira de Inteligência', repr(unidade))

    check('hierarquia vazia não quebra',
          tela._orgao_da_linha(Fake(None), agrupado=False) == (None, None),
          str(tela._orgao_da_linha(Fake(None), agrupado=False)))

    check('sem agrupar, um bloco só e sem cabeçalho',
          tela._blocos_de_materias([Fake('A/B')], agrupar=False)[0][0] is None)

    blocos = tela._blocos_de_materias(
        [Fake('Ministério X/Unidade 1'), Fake('Ministério X/Unidade 2'),
         Fake('Ministério Y/Unidade 3')], agrupar=True)
    check('agrupa pela raiz, não pela hierarquia completa',
          [(rotulo, len(itens)) for rotulo, itens in blocos]
          == [('Ministério X', 2), ('Ministério Y', 1)],
          str([(r, len(i)) for r, i in blocos]))

    # --- tela
    with app.app_context():
        usuario = User.query.filter_by(role='admin').first()
        edicao = (DouEdition.query.filter_by(status=DouEdition.STATUS_PARSED)
                  .filter(DouEdition.qtd_materias > 0)
                  .order_by(DouEdition.data_publicacao.desc()).first())
        if usuario is None or edicao is None:
            print('  ⏭️  sem usuário admin ou sem edição capturada — pulando')
            return
        user_id, firm_id = usuario.id, usuario.law_firm_id
        dia, secao = edicao.data_publicacao.isoformat(), edicao.secao
        tem_pdf = edicao.pdf_disponivel
        anteriores = [
            d for (d,) in db.session.query(DouEdition.data_publicacao)
            .filter(DouEdition.status == DouEdition.STATUS_PARSED,
                    DouEdition.data_publicacao < edicao.data_publicacao)
            .distinct().order_by(DouEdition.data_publicacao.desc()).limit(1)]

    with app.test_client() as c:
        with c.session_transaction() as sessao:
            sessao['user_id'] = user_id
            sessao['law_firm_id'] = firm_id
            sessao['user_role'] = 'admin'

        base = f'/dou/edicao/{dia}?secao={secao}'
        html = c.get(base).get_data(as_text=True)

        check('a edição mais recente não oferece "próxima"',
              'mais recente' in html, 'botão de dia seguinte apareceu na ponta')
        if anteriores:
            check('o salto para o dia anterior vem do acervo, não de data-1',
                  f'/dou/edicao/{anteriores[0].isoformat()}' in html,
                  f'esperava link para {anteriores[0]}')

        check('o filtro de órgão é select, não campo livre',
              'Todos os órgãos' in html and 'name="orgao"' in html)
        check('a busca dentro do dia existe', 'name="q"' in html)
        check('na ordem de página a coluna Órgão fica e não há grupos',
              '>Órgão</th>' in html and 'class="dou-grupo"' not in html)

        agrupado = c.get(base + '&ordem=orgao').get_data(as_text=True)
        check('ordenando por órgão, aparecem cabeçalhos de grupo',
              'class="dou-grupo"' in agrupado)
        check('agrupado, a coluna Órgão sai (viraria repetição do cabeçalho)',
              '>Órgão</th>' not in agrupado)

        vazio = c.get(base + '&q=' + 'z' * 25).get_data(as_text=True)
        check('busca sem resultado não dá 500 e aponta a busca global',
              '/dou/busca?q=' in vazio, 'faltou a saída para o acervo inteiro')

        # Os atalhos de PDF exigem uma seção com o assinado baixado — a edição
        # mais recente costuma ainda não ter o dela.
        if not tem_pdf:
            with app.app_context():
                com_pdf = (DouEdition.query
                           .filter_by(status=DouEdition.STATUS_PARSED)
                           .filter(DouEdition.pdf_path.isnot(None),
                                   DouEdition.qtd_materias > 0)
                           .order_by(DouEdition.data_publicacao.desc()).first())
                alvo = ((com_pdf.data_publicacao.isoformat(), com_pdf.secao)
                        if com_pdf and com_pdf.pdf_disponivel else None)
            if alvo is None:
                print('  ⏭️  nenhuma edição com PDF assinado no acervo — atalhos não '
                      'verificados')
                return
            html = c.get(f'/dou/edicao/{alvo[0]}?secao={alvo[1]}').get_data(as_text=True)

        check('o PDF assinado está na linha das abas, não no fim do filtro',
              'PDF assinado da seção' in html and 'nav-item ms-auto' in html)
        check('a linha das abas leva ao leitor da edição',
              'Folhear a edição' in html and '/pagina/1?' in html)
        check('cada linha tem atalho para a folha daquela página',
              'dou-pag-pdf' in html and re.search(r'/dou/edicao/[\d-]+/pagina/\d+', html))


def test_leitor_da_edicao():
    """A folha do Diário em tela própria: barra de páginas e sumário."""
    print('\n10. Leitor da edição (a folha sozinha)')
    from app.blueprints import dou as tela

    # --- função pura: a janela do recorte encosta nas bordas sem estourar
    check('recorte no meio pega a anterior e a seguinte',
          tela._janela_do_recorte(50, 117) == (48, 50),
          str(tela._janela_do_recorte(50, 117)))
    check('na primeira página não existe anterior',
          tela._janela_do_recorte(1, 117) == (0, 1),
          str(tela._janela_do_recorte(1, 117)))
    check('na última página não existe seguinte',
          tela._janela_do_recorte(117, 117) == (115, 116),
          str(tela._janela_do_recorte(117, 117)))

    with app.app_context():
        usuario = User.query.filter_by(role='admin').first()
        edicao = (DouEdition.query.filter_by(status=DouEdition.STATUS_PARSED)
                  .filter(DouEdition.pdf_path.isnot(None),
                          DouEdition.qtd_materias > 0)
                  .order_by(DouEdition.data_publicacao.desc()).first())
        if usuario is None or edicao is None or not edicao.pdf_disponivel:
            print('  ⏭️  sem usuário admin ou sem edição com PDF assinado — pulando')
            return
        artigo = (DouArticle.query.filter_by(edition_id=edicao.id)
                  .filter(DouArticle.pagina_num.isnot(None)).first())
        if artigo is None:
            print('  ⏭️  nenhuma matéria com página registrada — pulando')
            return

        user_id, firm_id = usuario.id, usuario.law_firm_id
        edicao_id, secao = edicao.id, edicao.secao
        dia = edicao.data_publicacao.isoformat()
        artigo_id, pagina = artigo.id, artigo.pagina_num
        total = tela._total_paginas(edicao)
        sumario = tela._sumario_da_edicao(edicao_id)

    check('o total de páginas sai do PDF assinado', total > 0, f'total={total}')
    check('o sumário traz órgão e página', bool(sumario) and
          all(isinstance(o, str) and isinstance(p, int) for o, p in sumario),
          str(sumario[:2]))
    check('o sumário vem na ordem das páginas',
          [p for _, p in sumario] == sorted(p for _, p in sumario),
          str([p for _, p in sumario][:8]))
    check('o sumário agrupa pela raiz, não pela hierarquia completa',
          len(sumario) < 60, f'{len(sumario)} entradas — hierarquia inteira?')

    with app.test_client() as c:
        with c.session_transaction() as sessao:
            sessao['user_id'] = user_id
            sessao['law_firm_id'] = firm_id
            sessao['user_role'] = 'admin'

        base = f'/dou/edicao/{dia}/pagina'
        recorte = f'/dou/edicao/{edicao_id}/pagina/'
        html = c.get(f'{base}/{pagina}?secao={secao}').get_data(as_text=True)

        check('o leitor abre', 'dou-pdf-quadro--leitor' in html)
        check('a barra diz em que página está e quantas há',
              f'de {total}' in html and 'dou-leitor-barra' in html)
        check('a folha da página pedida está no quadro',
              f'{recorte}{pagina}.pdf' in html)
        check('o sumário da edição está na barra',
              'Sumário da edição' in html and f'{sumario[0][0]} — pág.' in html)
        check('nenhum órgão vem pré-selecionado no sumário',
              html.count('<option value="" selected>') == 1,
              'marcar um órgão anunciaria um que não é o desta folha')
        check('a barra oferece a folha e a edição inteira',
              'Esta página' in html and 'Edição completa' in html
              and f'/dou/edicao/{edicao_id}/pdf' in html)
        check('o botão da edição inteira avisa o peso antes do clique',
              re.search(r'\d+ MB', html) is not None,
              'a Seção 3 passa de 40 MB e o aviso tem de vir antes')
        check('o leitor não traz o texto do ato', 'dou-texto' not in html)
        check('a folha tem a volta para o inteiro teor',
              f'/dou/materia/{artigo_id}' in html or 'Nenhuma matéria indexada' in html)

        # --- folhear
        outra = total if total != pagina else max(1, total - 1)
        andou = c.get(f'{base}/{outra}?secao={secao}').get_data(as_text=True)
        check('folhear troca a folha', f'{recorte}{outra}.pdf' in andou)

        # "Ir para" é um GET sem JavaScript e cai no endereço canônico
        pulo = c.get(f'{base}/{pagina}?secao={secao}&pagina={outra}')
        check('"ir para" redireciona para o endereço da página',
              pulo.status_code == 302
              and pulo.headers.get('Location', '').endswith(f'/pagina/{outra}?secao={secao}'),
              f'{pulo.status_code} {pulo.headers.get("Location")}')
        check('"ir para" na página em que já se está não entra em laço',
              c.get(f'{base}/{pagina}?secao={secao}&pagina={pagina}').status_code == 200)

        # Número inválido prende na borda em vez de dar 404
        check('página acima do fim cai na última',
              f'{recorte}{total}.pdf' in c.get(f'{base}/99999?secao={secao}').get_data(as_text=True))
        check('página zero cai na primeira',
              f'{recorte}1.pdf' in c.get(f'{base}/0?secao={secao}').get_data(as_text=True))
        check('data que não é data dá 404',
              c.get('/dou/edicao/nao-e-data/pagina/1').status_code == 404)

        # --- a rota do recorte não pode ser engolida pela rota do leitor
        pdf = c.get(f'{recorte}{outra}.pdf')
        check('o recorte continua sendo servido como PDF',
              pdf.status_code == 200 and pdf.content_type == 'application/pdf',
              f'{pdf.status_code} {pdf.content_type}')
        check('o recorte não carrega a seção inteira',
              len(pdf.data) < 5 * 1024 * 1024, f'{len(pdf.data) // 1024} KB')
        check('página inexistente no PDF dá 404, não 500',
              c.get(f'{recorte}99999.pdf').status_code == 404)

        # No leitor a folha vem sozinha; na matéria, com as vizinhas, porque um
        # ato começa numa página e termina na outra.
        import fitz
        with fitz.open(stream=pdf.data, filetype='pdf') as doc:
            paginas_leitor = doc.page_count
            rotulo = doc[0].get_label()
        check('o leitor entrega uma página só', paginas_leitor == 1,
              f'{paginas_leitor} páginas')
        check('a página recortada mantém o número do Diário',
              rotulo == str(outra), f'rótulo {rotulo!r}, esperado {outra!r}')

        with app.app_context():
            adiante = (DouArticle.query.filter_by(edition_id=edicao_id)
                       .filter(DouArticle.pagina_num > 1).first())
        if adiante is not None:
            bruto = c.get(f'/dou/materia/{adiante.id}/pagina.pdf').data
            with fitz.open(stream=bruto, filetype='pdf') as doc:
                paginas_materia = doc.page_count
            check('a matéria continua com a página e as vizinhas',
                  paginas_materia > 1, f'{paginas_materia} página(s)')

        # --- a matéria continua sendo a tela do texto, e leva ao leitor
        materia = c.get(f'/dou/materia/{artigo_id}').get_data(as_text=True)
        check('a matéria voltou a ser texto com aba, não duas colunas',
              'dou-materia--com-pagina' not in materia
              and 'data-bs-toggle="tab"' in materia)
        check('a matéria aponta para o leitor',
              f'{base}/{pagina}?secao={secao}' in materia
              or f'/pagina/{pagina}?' in materia)


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
    test_edicao_do_dia()
    test_leitor_da_edicao()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
