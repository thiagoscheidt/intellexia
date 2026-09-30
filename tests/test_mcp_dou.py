"""
Tools MCP do Diário Oficial (mcp_server/tools/dou.py).

Duas partes:
- regras puras (resolução de seção/órgão, grifo, linhas do "ver trecho",
  cabeçalho de tabela) — rodam sempre;
- contra o acervo e os alertas do banco — puladas se o dev não tiver DOU
  capturado ou se o Meilisearch estiver fora do ar.

Uso:
    uv run python tests/test_mcp_dou.py
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp.exceptions import ToolError  # noqa: E402

from main import app  # noqa: E402
from mcp_server.tools import dou as t  # noqa: E402

FALHAS = []


def ok(cond, msg):
    print(('  ✅ ' if cond else '  ❌ ') + msg)
    if not cond:
        FALHAS.append(msg)


def erro(fn, trecho, msg):
    try:
        fn()
    except ToolError as e:
        ok(trecho.lower() in str(e).lower(), f'{msg} ({str(e)[:70]}…)')
        return
    ok(False, f'{msg} — não levantou ToolError')


def puras():
    print('\n── regras puras')
    ok(t._resolver_secoes('1') == ['DO1'], 'seção "1" → DO1')
    ok(t._resolver_secoes('Seção 3') == ['DO3'], 'seção "Seção 3" → DO3')
    ok(t._resolver_secoes('seção 1 extra') == ['DO1E'], 'seção "seção 1 extra" → DO1E')
    ok(t._resolver_secoes('DO2E; 1') == ['DO2E', 'DO1'], 'várias seções com ";"')
    erro(lambda: t._resolver_secoes('5'), 'não reconhecida', 'seção 5 é recusada')

    orgaos = ['Ministério da Previdência Social', 'Ministério da Saúde', 'Poder Judiciário']
    ok(t._resolver('ministerio da previdencia social', orgaos, 'órgão', '') == orgaos[0],
       'órgão sem acento e minúsculo casa o exato')
    ok(t._resolver('previdencia', orgaos, 'órgão', '') == orgaos[0], 'trecho único resolve')
    erro(lambda: t._resolver('ministerio', orgaos, 'órgão', ''), 'mais de um',
         'trecho ambíguo lista as opções em vez de escolher')
    erro(lambda: t._resolver('xyz', orgaos, 'órgão', ''), 'não encontrado', 'valor inexistente')

    ok(t._texto_puro('A <mark>FAP</mark> &amp; B') == 'A «FAP» & B', 'trecho: <mark> vira «» e desescapa')
    ok(t._sem_grifo('<mark>DE</mark> 3 <mark>DE</mark> AGOSTO') == 'DE 3 DE AGOSTO', 'título sem grifo')

    html = ('<table><tr><td>718</td><td>10128.027795/2024-04</td><td>90.400.888/2079-10</td>'
            '<td><p>Indeferimento Total</p></td></tr></table><p>Parágrafo solto</p>')
    linhas = t._linhas_do_trecho({'modo': 'html', 'html': html})
    ok(linhas == ['718 | 10128.027795/2024-04 | 90.400.888/2079-10 | Indeferimento Total',
                  'Parágrafo solto'], 'linha de tabela vira uma linha, sem repetir o <p> da célula')

    dado = SimpleNamespace(texto_html=html)
    ok(t._cabecalho_da_tabela(dado) is None, 'linha de dados não vira cabeçalho')
    cab = SimpleNamespace(texto_html='<table><tr><td>Processo</td><td>CNPJ</td></tr>'
                                     '<tr><td>1</td><td>2</td></tr></table>')
    ok(t._cabecalho_da_tabela(cab) == 'Processo | CNPJ', 'cabeçalho de verdade é devolvido')


def acervo():
    from app.models import DouArticle
    from app.services import dou_search_service as busca

    print('\n── acervo (busca, leitura, edições, sumário)')
    if not DouArticle.query.first():
        print('  ⏭️  sem DOU capturado — pulado')
        return
    ultimas = t.latest_editions_handler(3)
    ok(bool(ultimas['ultimas_edicoes']), 'ultimas_edicoes_dou devolve datas')
    ok('captura' in ultimas and 'periodo_do_acervo' in ultimas, 'traz saúde da captura e período')

    s = t.edition_summary_handler()
    ok(s['secoes'] and s['secoes'][0]['sumario'], 'sumário da edição mais recente tem órgãos')
    pags = [i['primeira_pagina'] for i in s['secoes'][0]['sumario'] if i['primeira_pagina']]
    ok(pags == sorted(pags), 'sumário na ordem das páginas')
    erro(lambda: t.edition_summary_handler('1990-01-01'), 'não há edição', 'dia sem edição explica')

    if not busca.is_available():
        print('  ⏭️  Meilisearch fora do ar — busca pulada')
        return
    sem, com = (t.search_dou_handler(q, limit=1)['total_de_materias']
                for q in ('fator acidentário de prevenção', '"fator acidentário de prevenção"'))
    ok(com <= sem, f'aspas restringem à frase exata ({com} ≤ {sem})')
    r = t.search_dou_handler('fator acidentário de prevenção', limit=1)
    ok('dica' in r, 'termo de várias palavras sem aspas ganha a dica das aspas')
    erro(lambda: t.search_dou_handler(None), 'informe um termo', 'sem termo nem filtro é recusado')

    r = t.search_dou_handler(None, secao='1', limit=3)
    ok(r['filtros_aplicados']['secao'] == ['DO1'] and r['total_encontrado'] > 0,
       'sem termo, só filtro, lista o recorte')
    datas = [i['data'] for i in r['itens']]
    ok(datas == sorted(datas, reverse=True), 'sem termo, mais recentes primeiro')

    p1 = t.search_dou_handler(None, secao='3', limit=5, offset=0)
    p2 = t.search_dou_handler(None, secao='3', limit=5, offset=5)
    ok(not ({i['id'] for i in p1['itens']} & {i['id'] for i in p2['itens']}),
       'paginação por deslocamento não repete matéria')
    erro(lambda: t.search_dou_handler('fap', offset=1000), 'primeiros', 'além de 1.000 explica o teto')

    m = t.get_dou_article_handler(p1['itens'][0]['id'], law_firm_id=1, max_caracteres=1000)
    ok(len(m['texto']) <= 1000 and 'url' in m, 'ler_materia corta o texto e traz links')
    erro(lambda: t.get_dou_article_handler(-1, 1), 'não encontrada', 'matéria inexistente')


def escritorio():
    from app.models import DouClientAlert

    print('\n── alertas do escritório')
    alerta = DouClientAlert.query.filter_by(tem_resultado=True).first() or DouClientAlert.query.first()
    if alerta is None:
        print('  ⏭️  sem alertas no banco — pulado')
        return
    firma = alerta.law_firm_id

    r = t.list_alerts_handler(firma, limit=5)
    ok(r['total_encontrado'] >= 1 and 'resumo_do_escritorio' in r, 'alertas_dou lista e resume')
    fav = t.list_alerts_handler(firma, resultado_fap='deferimento', limit=200)['total_encontrado']
    contra = t.list_alerts_handler(firma, resultado_fap='indeferimento', limit=200)['total_encontrado']
    com = t.list_alerts_handler(firma, resultado_fap='com', limit=200)['total_encontrado']
    ok(fav <= com and contra <= com, 'recortes de resultado FAP cabem em "com decisão"')
    erro(lambda: t.list_alerts_handler(firma, status='xx'), 'status inválido', 'status inválido')
    erro(lambda: t.list_alerts_handler(firma, cliente='zzzz-nao-existe'), 'nenhum alerta',
         'cliente sem alerta lista os que têm')

    outra = firma + 9999
    ok(t.list_alerts_handler(outra, limit=5)['total_encontrado'] == 0,
       'outro escritório não vê os alertas')
    erro(lambda: t.alert_detail_handler(outra, alerta.id), 'não encontrado',
         'detalhe de alerta de outro escritório é recusado')

    d = t.alert_detail_handler(firma, alerta.id, max_linhas=10)
    ok(d['total_de_estabelecimentos'] == len(alerta.matches), 'detalhe conta todos os estabelecimentos')
    ok(len(d['estabelecimentos']) <= 10, 'detalhe respeita max_linhas')
    if alerta.tem_resultado:
        ok(d['como_ler_as_linhas'] and d['linhas_do_edital'], 'edital de julgamento traz as linhas e a legenda')

    dg = t.firm_digest_handler(firma, 3)
    total = t.list_alerts_handler(firma, limit=1)['total_encontrado']
    ok(dg['alertas'] <= total, 'resumo_dou_escritorio conta só alertas que existem na lista')
    ok(dg['recursos_fap']['clientes_com_algum_deferimento']
       <= dg['recursos_fap']['clientes_com_recurso_julgado'], 'deferidos ⊂ julgados')


def vigilancia():
    from app.models import DouArticle

    print('\n── vigilância')
    ok('regras' in t.rules_handler(1), 'regras_dou responde')
    erro(lambda: t.test_term_handler(None), 'palavra-chave', 'teste sem termo nem órgão é recusado')
    if DouArticle.query.first():
        r = t.test_term_handler('fator acidentário de prevenção')
        ok(r['avaliacao'] in ('vazio', 'ok', 'alto', 'ruidoso') and r['explicacao'],
           'testar_termo_dou avalia o volume')
        ok('como_criar' in r, 'teste aponta a tela para criar a regra (não cria)')


if __name__ == '__main__':
    with app.app_context():
        puras()
        acervo()
        escritorio()
        vigilancia()
    print('\n' + '=' * 60)
    if FALHAS:
        print(f'❌ {len(FALHAS)} falha(s)')
        sys.exit(1)
    print('✅ Todos os testes passaram')
