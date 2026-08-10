#!/usr/bin/env python3
"""
Testes da busca do DOU (app/services/dou_search_service.py).

As partes 1 a 5 são função pura: sem rede, sem banco, sem Flask.

    uv run python tests/test_dou_search.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import dou_search_service as busca

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def test_so_digitos():
    print('\n1. Normalização para dígitos')
    check('tira pontuação do CNPJ',
          busca.so_digitos('19.630.496/0001-05') == '19630496000105',
          busca.so_digitos('19.630.496/0001-05'))
    check('tira pontuação do processo',
          busca.so_digitos('15414.630210/2026-80') == '15414630210202680',
          busca.so_digitos('15414.630210/2026-80'))
    check('None vira string vazia', busca.so_digitos(None) == '')
    check('texto sem dígito vira vazio', busca.so_digitos('Previdência') == '')


def test_extrair_cnpjs():
    print('\n2. Extração de CNPJ do texto')
    texto = ('Autoriza o funcionamento de BESSO RE BRASIL CORRETORA LTDA, '
             'CNPJ nº 19.630.496/0001-05, com sede na cidade do Rio.')
    check('acha o CNPJ formatado e normaliza',
          busca.extrair_cnpjs(texto) == ['19630496000105'],
          str(busca.extrair_cnpjs(texto)))

    dois = 'CNPJ: 04.898.857/0002-02 e também 05.917.351/0001-85.'
    check('acha os dois', busca.extrair_cnpjs(dois) == ['04898857000202', '05917351000185'],
          str(busca.extrair_cnpjs(dois)))

    check('acha CNPJ já em dígitos',
          busca.extrair_cnpjs('inscrito sob 19630496000105 nesta data') == ['19630496000105'],
          str(busca.extrair_cnpjs('inscrito sob 19630496000105 nesta data')))

    check('não inventa CNPJ onde não há',
          busca.extrair_cnpjs('Portaria nº 1.234, de 8 de agosto') == [],
          str(busca.extrair_cnpjs('Portaria nº 1.234, de 8 de agosto')))

    check('não duplica o mesmo CNPJ',
          busca.extrair_cnpjs('19.630.496/0001-05 e de novo 19.630.496/0001-05') ==
          ['19630496000105'],
          str(busca.extrair_cnpjs('19.630.496/0001-05 e de novo 19.630.496/0001-05')))

    check('texto vazio devolve lista vazia', busca.extrair_cnpjs(None) == [])


def test_extrair_processos():
    print('\n3. Extração de número de processo')
    texto = 'Processo nº 15414.630210/2026-80, referente à contestação.'
    check('acha e normaliza',
          busca.extrair_processos(texto) == ['15414630210202680'],
          str(busca.extrair_processos(texto)))
    check('17 dígitos, não 14',
          len(busca.extrair_processos(texto)[0]) == 17,
          str(len(busca.extrair_processos(texto)[0])))
    check('não confunde CNPJ com processo',
          busca.extrair_processos('CNPJ nº 19.630.496/0001-05') == [],
          str(busca.extrair_processos('CNPJ nº 19.630.496/0001-05')))


def test_classificar_consulta():
    print('\n4. Roteamento da consulta')
    for entrada in ('19.630.496/0001-05', '19630496000105', ' 19.630.496/0001-05 '):
        tipo, termo = busca.classificar_consulta(entrada)
        check(f'{entrada!r} vai para o campo de CNPJ',
              (tipo, termo) == ('cnpj', '19630496000105'), f'{tipo}/{termo}')

    tipo, termo = busca.classificar_consulta('15414.630210/2026-80')
    check('processo vai para o campo de processo',
          (tipo, termo) == ('processo', '15414630210202680'), f'{tipo}/{termo}')

    tipo, termo = busca.classificar_consulta('Fator Acidentário de Prevenção')
    check('texto livre continua texto', tipo == 'texto', tipo)

    # O guarda que evita falso positivo: número embutido numa frase é texto
    tipo, _ = busca.classificar_consulta('portaria 19630496000105 de agosto')
    check('número dentro de frase NÃO vira busca de CNPJ', tipo == 'texto', tipo)

    tipo, _ = busca.classificar_consulta('12345')
    check('número curto continua texto', tipo == 'texto', tipo)

    tipo, termo = busca.classificar_consulta('   ')
    check('termo em branco é texto vazio', (tipo, termo) == ('texto', ''), f'{tipo}/{termo}')


def test_orgao_raiz():
    print('\n5. Raiz da hierarquia do órgão')
    h = 'Ministério da Previdência Social/Instituto Nacional do Seguro Social/Diretoria'
    check('pega o primeiro nível',
          busca.orgao_raiz(h) == 'Ministério da Previdência Social', busca.orgao_raiz(h))
    check('sem barra devolve o próprio',
          busca.orgao_raiz('Presidência da República') == 'Presidência da República')
    check('None devolve None', busca.orgao_raiz(None) is None)
    check('vazio devolve None', busca.orgao_raiz('   ') is None)


def test_documento_indexado():
    """O documento carrega o que a tela precisa e o que a busca filtra."""
    print('\n6. Montagem do documento')
    from main import app
    from app.models import DouArticle

    with app.app_context():
        artigo = (DouArticle.query
                  .filter(DouArticle.orgao_hierarquia.isnot(None)).first())
        if artigo is None:
            print('  ⏭️  acervo vazio — pulando')
            return

        doc = busca.montar_documento(artigo)
        esperado_data = artigo.pub_date.strftime('%d/%m/%Y')
        esperado_raiz = busca.orgao_raiz(artigo.orgao_hierarquia)
        esperado_texto = artigo.texto or ''
        artigo_id = artigo.id

    check('id é o id da matéria', doc['id'] == artigo_id, str(doc.get('id')))
    check('pub_date_num é AAAAMMDD inteiro',
          isinstance(doc['pub_date_num'], int) and 20000000 < doc['pub_date_num'] < 21000000,
          str(doc.get('pub_date_num')))
    check('data_br pronta para exibir', doc['data_br'] == esperado_data, doc.get('data_br'))
    check('orgao_raiz é o primeiro nível', doc['orgao_raiz'] == esperado_raiz,
          doc.get('orgao_raiz'))
    check('cnpjs é lista', isinstance(doc['cnpjs'], list))
    check('processos é lista', isinstance(doc['processos'], list))
    check('texto vai inteiro para o índice', doc['texto'] == esperado_texto,
          '(texto divergente)')


def test_indexar_e_buscar():
    """Ponta a ponta contra o Meilisearch local, em índice de teste próprio."""
    print('\n7. Indexação e busca (Meilisearch local)')

    if not busca.is_available():
        print('  ⏭️  Meilisearch não responde — pulando')
        return

    from main import app
    from app.models import DouArticle

    # NUNCA o índice de produção: neste módulo já houve teste que destruiu
    # dado real por usar a mesma chave que o dado verdadeiro.
    nome_teste = 'dou_articles_test'
    indice = busca.get_index(nome_teste)

    try:
        with app.app_context():
            artigos = DouArticle.query.limit(300).all()
            if not artigos:
                print('  ⏭️  acervo vazio — pulando')
                return
            enviados = busca.index_articles(artigos, indice=indice)
            com_cnpj = next((a for a in artigos if busca.extrair_cnpjs(a.texto)), None)
            cnpj = busca.extrair_cnpjs(com_cnpj.texto)[0] if com_cnpj else None
            cnpj_id = com_cnpj.id if com_cnpj else None

        check('indexou o lote', enviados == len(artigos), f'{enviados}/{len(artigos)}')
        busca.aguardar_indexacao(indice)

        if cnpj:
            r = busca.search(cnpj, indice=indice)
            check('acha pelo CNPJ só em dígitos',
                  any(h['id'] == cnpj_id for h in r['hits']),
                  f'{cnpj}: {r["total"]} resultado(s)')

            formatado = f'{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}'
            r2 = busca.search(formatado, indice=indice)
            check('acha pelo CNPJ formatado, mesmo resultado',
                  any(h['id'] == cnpj_id for h in r2['hits']), formatado)

        r3 = busca.search('portaria', indice=indice)
        check('busca por texto devolve resultados', r3['total'] > 0, str(r3['total']))
        check('traz facetas com contagem',
              isinstance(r3['facetas'], dict) and 'pub_name' in r3['facetas'],
              str(list(r3['facetas'].keys()) if r3['facetas'] else None))
        check('traz trecho destacado',
              any('<mark>' in (h.get('trecho') or '') for h in r3['hits']),
              '(nenhum destaque)')

        r4 = busca.search('zzzznaoexisteestetermo', indice=indice)
        check('termo sem resultado devolve zero, sem erro', r4['total'] == 0, str(r4['total']))

    finally:
        busca.drop_index(nome_teste)
        print('  (índice de teste removido)')


def test_montar_filtro():
    print('\n8. Montagem do filtro do Meilisearch')
    from datetime import date

    check('sem filtro devolve None', busca.montar_filtro({}) is None,
          repr(busca.montar_filtro({})))

    f = busca.montar_filtro({'pub_name': ['DO1']})
    check('um valor vira igualdade', f == '(pub_name = "DO1")', repr(f))

    f = busca.montar_filtro({'pub_name': ['DO1', 'DO3']})
    check('dois valores do mesmo campo viram OR',
          f == '(pub_name = "DO1" OR pub_name = "DO3")', repr(f))

    f = busca.montar_filtro({'pub_name': ['DO1'], 'art_type': ['Portaria']})
    check('campos diferentes viram AND',
          ' AND ' in f and 'pub_name' in f and 'art_type' in f, repr(f))

    f = busca.montar_filtro({'de': date(2026, 8, 1), 'ate': date(2026, 8, 10)})
    check('período vira faixa em AAAAMMDD',
          'pub_date_num >= 20260801' in f and 'pub_date_num <= 20260810' in f, repr(f))

    f = busca.montar_filtro({'orgao_raiz': ['Ministério "X"']})
    check('aspas no valor são escapadas', '\\"' in f, repr(f))

    check('valores vazios são ignorados',
          busca.montar_filtro({'pub_name': ['', None]}) is None,
          repr(busca.montar_filtro({'pub_name': ['', None]})))


def test_busca_com_filtro():
    print('\n9. Busca filtrada (Meilisearch local)')
    if not busca.is_available():
        print('  ⏭️  Meilisearch não responde — pulando')
        return

    from main import app
    from app.models import DouArticle

    nome_teste = 'dou_articles_test'
    indice = busca.get_index(nome_teste)
    try:
        with app.app_context():
            artigos = DouArticle.query.filter_by(pub_name='DO1').limit(300).all()
            if not artigos:
                print('  ⏭️  sem matérias da Seção 1 — pulando')
                return
            busca.index_articles(artigos, indice=indice)
        busca.aguardar_indexacao(indice)

        sem = busca.search('portaria', indice=indice)
        check('busca sem filtro acha algo', sem['total'] > 0, str(sem['total']))

        so_do1 = busca.search('portaria', filtros={'pub_name': ['DO1']}, indice=indice)
        check('filtro pela seção presente mantém os resultados',
              so_do1['total'] == sem['total'], f"{sem['total']} -> {so_do1['total']}")

        so_do2 = busca.search('portaria', filtros={'pub_name': ['DO2']}, indice=indice)
        check('filtro por seção ausente no lote zera', so_do2['total'] == 0,
              str(so_do2['total']))

        from datetime import date
        futuro = busca.search('portaria', filtros={'de': date(2099, 1, 1)}, indice=indice)
        check('período no futuro zera', futuro['total'] == 0, str(futuro['total']))

        por_data = busca.search('portaria', ordem='data', indice=indice)
        chave = lambda d: d.split('/')[::-1]  # noqa: E731 — DD/MM/AAAA -> AAAA,MM,DD
        datas = [h['data_br'] for h in por_data['hits'] if h['data_br']]
        check('ordem por data é decrescente',
              datas == sorted(datas, key=chave, reverse=True), str(datas[:4]))
    finally:
        busca.drop_index(nome_teste)
        print('  (índice de teste removido)')


def main():
    print('=' * 60)
    print('TESTES DA BUSCA DO DOU')
    print('=' * 60)

    test_so_digitos()
    test_extrair_cnpjs()
    test_extrair_processos()
    test_classificar_consulta()
    test_orgao_raiz()
    test_documento_indexado()
    test_indexar_e_buscar()
    test_montar_filtro()
    test_busca_com_filtro()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
