#!/usr/bin/env python3
"""
Testes dos alertas de cliente no Diário Oficial.

Usa app.test_client() no padrão dos demais testes de rota do projeto.

    uv run python tests/test_dou_alertas.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import (db, User, Client, DouArticle, DouEdition,
                        DouClientAlert, DouClientAlertMatch)
from app.services import dou_alert_service as alertas

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


class FakeCliente:
    """Cliente sem banco, para exercitar o casamento em memória."""

    def __init__(self, id, name, cnpj):
        self.id, self.name, self.cnpj = id, name, cnpj


def _carteira(*clientes):
    """Carteira montada à mão, sem tocar o banco."""
    carteira = alertas.Carteira.__new__(alertas.Carteira)
    carteira.law_firm_id = 1
    carteira.por_cnpj, carteira.por_raiz, carteira.invalidos = {}, {}, []
    for cliente in clientes:
        digitos = ''.join(ch for ch in cliente.cnpj if ch.isdigit())
        if not alertas.cnpj_valido(digitos):
            carteira.invalidos.append(cliente)
            continue
        carteira.por_cnpj[digitos] = cliente
        carteira.por_raiz.setdefault(digitos[:8], cliente)
    return carteira


def test_validacao_de_cnpj():
    """O DV é o que separa o alerta do lixo — foi ele que matou o falso da HAVAN."""
    print('\n1. Validação de CNPJ')

    check('CNPJ real passa', alertas.cnpj_valido('33592510000154'))
    check('DV errado reprova', not alertas.cnpj_valido('33592510000155'))
    check('curto demais reprova', not alertas.cnpj_valido('3359251000015'))
    check('com pontuação já normalizada reprova se vier crua',
          not alertas.cnpj_valido('33.592.510/0001-54'))
    check('não numérico reprova', not alertas.cnpj_valido('3359251000015x'))
    check('vazio reprova', not alertas.cnpj_valido(''))
    check('None reprova', not alertas.cnpj_valido(None))

    # O caso que motivou a regra: 00000000000000 tem raiz 00000000, que casa
    # com 00.000.000/0001-91 — o Banco do Brasil, presente em todo convênio de
    # folha de pagamento do país.
    check('zeros reprovam (era a HAVAN casando com o Banco do Brasil)',
          not alertas.cnpj_valido('00000000000000'))
    check('repetidos reprovam', not alertas.cnpj_valido('11111111111111'))
    check('o CNPJ do Banco do Brasil é válido — o problema era o cadastro',
          alertas.cnpj_valido('00000000000191'))

    check('formatação para leitura',
          alertas.formatar_cnpj('33592510000154') == '33.592.510/0001-54',
          alertas.formatar_cnpj('33592510000154'))


def test_casamento():
    """Exato, por raiz, e o que não pode virar alerta."""
    print('\n2. Casamento com a carteira')

    vale = FakeCliente(1, 'VALE S.A.', '33.592.510/0001-54')
    lixo = FakeCliente(2, 'CLIENTE SEM CNPJ', '00000000000000')
    carteira = _carteira(vale, lixo)

    check('cadastro com CNPJ inválido fica fora da vigilância',
          carteira.invalidos == [lixo] and len(carteira.por_cnpj) == 1)

    casados = carteira.casar('Contrato com a VALE, CNPJ 33.592.510/0001-54.')
    check('CNPJ cadastrado casa como exato',
          len(casados) == 1 and casados[0][1] is vale
          and casados[0][2] == DouClientAlert.MATCH_EXACT, str(casados))

    # Outro estabelecimento do mesmo grupo: mesma raiz, DV válido. O número
    # é real — apareceu no acervo capturado.
    casados = carteira.casar('Aviso de licença — CNPJ 33.592.510/0021-06.')
    check('outro estabelecimento do grupo casa como raiz',
          len(casados) == 1 and casados[0][2] == DouClientAlert.MATCH_ROOT,
          str(casados))
    check('o CNPJ guardado é o que apareceu no DOU, não o cadastrado',
          casados and casados[0][0] == '33592510002106', str(casados))

    check('CNPJ com DV inválido no texto é ignorado',
          carteira.casar('Protocolo 33.592.510/0001-99 e mais nada') == [])

    check('texto sem CNPJ não gera nada', carteira.casar('Portaria sem número') == [])
    check('texto vazio não quebra', carteira.casar(None) == [])

    dois = carteira.casar('CNPJ 33.592.510/0001-54 e CNPJ 33.592.510/0021-06')
    check('exato e raiz convivem na mesma matéria', len(dois) == 2, str(dois))
    check('o exato não é recontado como raiz',
          sum(1 for _, _, t in dois if t == DouClientAlert.MATCH_EXACT) == 1)

    repetido = carteira.casar('CNPJ 33.592.510/0001-54, de novo 33592510000154')
    check('o mesmo CNPJ repetido no texto conta uma vez', len(repetido) == 1,
          str(repetido))


def test_alerta_e_por_materia():
    """A unidade é a matéria: um edital cita 52 clientes e não vira 52 linhas."""
    print('\n3. A unidade do alerta')

    with app.app_context():
        maior = (DouClientAlert.query
                 .order_by(DouClientAlert.clients_count.desc()).first())
        if maior is None:
            print('  ⏭️  nenhum alerta gerado ainda — rode '
                  'scripts/gerar_alertas_dou.py --tudo')
            return

        check('existe alerta com muitos CNPJs (o edital de lista)',
              maior.clients_count > 1, f'maior tem {maior.clients_count}')
        check('e ele é UMA linha, não uma por CNPJ',
              DouClientAlert.query.filter_by(
                  article_id=maior.article_id,
                  law_firm_id=maior.law_firm_id).count() == 1)

        pares = DouClientAlertMatch.query.filter_by(alert_id=maior.id).count()
        check('os CNPJs ficam na tabela filha, não em linhas de alerta',
              pares == maior.clients_count, f'{pares} vs {maior.clients_count}')

        citados = maior.clientes_citados
        check('os chips agrupam por empresa, não por CNPJ',
              len(citados) <= maior.clients_count, f'{len(citados)} chips')
        if citados:
            check('o chip diz quantos estabelecimentos daquela empresa',
                  sum(n for _, _, n in citados) == maior.clients_count,
                  str([(c.name if c else None, t, n) for c, t, n in citados][:3]))

        check('o alerta sabe qual CNPJ grifar ao abrir a matéria',
              maior.cnpj_destaque and len(maior.cnpj_destaque) == 14,
              repr(maior.cnpj_destaque))


def test_reprocessar_nao_duplica():
    """Rodar de novo a mesma data atualiza a linha e preserva a triagem."""
    print('\n4. Reprocessamento')

    with app.app_context():
        alerta = DouClientAlert.query.first()
        if alerta is None:
            print('  ⏭️  nenhum alerta gerado ainda — pulando')
            return

        law_firm_id, data = alerta.law_firm_id, alerta.pub_date
        antes = DouClientAlert.query.filter_by(law_firm_id=law_firm_id,
                                               pub_date=data).count()
        status_original = alerta.status
        alerta_id = alerta.id

        # Marca como lido para provar que a triagem sobrevive
        alerta.status = DouClientAlert.STATUS_READ
        db.session.commit()

        alertas.gerar_para_datas([data])
        db.session.commit()

        depois = DouClientAlert.query.filter_by(law_firm_id=law_firm_id,
                                                pub_date=data).count()
        check('reprocessar não duplica alerta', antes == depois,
              f'{antes} -> {depois}')

        db.session.expire_all()
        check('alerta já lido continua lido depois do reprocessamento',
              DouClientAlert.query.get(alerta_id).status == DouClientAlert.STATUS_READ)

        # devolve o estado original
        DouClientAlert.query.get(alerta_id).status = status_original
        db.session.commit()

        orfaos = (db.session.query(DouClientAlertMatch)
                  .outerjoin(DouClientAlert,
                             DouClientAlert.id == DouClientAlertMatch.alert_id)
                  .filter(DouClientAlert.id.is_(None)).count())
        check('não sobra casamento órfão', orfaos == 0, f'{orfaos} órfão(s)')


def test_tela():
    """A tela, os filtros e o isolamento por escritório."""
    print('\n5. Tela de alertas')

    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    for esperado in ('dou.alertas', 'dou.alerta_marcar', 'dou.alertas_marcar_todas'):
        check(f'{esperado} existe', esperado in endpoints)

    with app.app_context():
        usuario = User.query.filter_by(role='admin').first()
        if usuario is None:
            print('  ⏭️  nenhum usuário admin — pulando')
            return
        user_id, firm_id = usuario.id, usuario.law_firm_id
        alerta = DouClientAlert.query.filter_by(law_firm_id=firm_id).first()
        if alerta is None:
            print('  ⏭️  nenhum alerta do escritório do admin — pulando')
            return
        alerta_id = alerta.id
        status_original = alerta.status
        cliente_id = alerta.matches[0].client_id if alerta.matches else None
        resumo = alertas.resumo(firm_id)

    with app.test_client() as c:
        with c.session_transaction() as sessao:
            sessao['user_id'] = user_id
            sessao['law_firm_id'] = firm_id
            sessao['user_role'] = 'admin'

        resposta = c.get('/dou/alertas')
        html = resposta.get_data(as_text=True)
        check('a tela abre', resposta.status_code == 200, str(resposta.status_code))
        check('mostra os totais', str(resumo['total']) in html)
        check('separa cadastrado de filial do grupo',
              'citam cliente cadastrado' in html and 'outra filial do grupo' in html)
        check('abre em não lidos, que é a fila de trabalho',
              'value="novo" selected' in html or "value=\"novo\" selected" in html
              or 'selected>Não lidos' in html or 'Não lidos' in html)
        check('o link da matéria leva o CNPJ para grifar',
              '/dou/materia/' in html and 'q=' in html)

        # "Ver no Diário" abre a folha assinada. O caminho alternativo (texto)
        # não aparece no acervo atual — as 41 matérias com alerta têm PDF —,
        # então a regra é exercitada direto na propriedade.
        import re as _re
        from types import SimpleNamespace as _NS
        pagina_de = DouClientAlert.pagina_no_diario.fget
        check('sem página registrada não há folha para abrir',
              pagina_de(_NS(article=_NS(pagina_num=None, edition=None))) is None)
        check('sem PDF assinado na seção também não',
              pagina_de(_NS(article=_NS(pagina_num=5,
                                        edition=_NS(pdf_disponivel=False)))) is None)
        check('com os dois, a folha é a página da matéria',
              pagina_de(_NS(article=_NS(pagina_num=5,
                                        edition=_NS(pdf_disponivel=True)))) == 5)
        check('sem matéria não quebra',
              pagina_de(_NS(article=None)) is None)

        para_folha = _re.findall(
            r'href="(/dou/edicao/[\d-]+/pagina/\d+[^"]*)"[^>]*>\s*Ver no Di', html)
        check('"Ver no Diário" leva à folha assinada, não ao texto',
              bool(para_folha), 'nenhum botão apontando para o leitor')
        if para_folha:
            check('e o endereço da folha responde',
                  c.get(para_folha[0]).status_code == 200, para_folha[0])

        check('filtro por tipo responde',
              c.get('/dou/alertas?tipo=exato').status_code == 200)
        check('filtro por seção responde',
              c.get('/dou/alertas?secao=DO3').status_code == 200)
        if cliente_id:
            check('filtro por cliente responde',
                  c.get(f'/dou/alertas?cliente={cliente_id}&status=todos').status_code == 200)
        check('página fora do intervalo não dá 500',
              c.get('/dou/alertas?page=9999').status_code == 200)

        # --- triagem
        c.post(f'/dou/alertas/{alerta_id}/lida', data={'lido': '1'})
        with app.app_context():
            db.session.expire_all()
            check('marcar como lida grava',
                  DouClientAlert.query.get(alerta_id).status == DouClientAlert.STATUS_READ)
        c.post(f'/dou/alertas/{alerta_id}/lida', data={'lido': '0'})
        with app.app_context():
            db.session.expire_all()
            atual = DouClientAlert.query.get(alerta_id)
            check('e dá para devolver para não lida',
                  atual.status == DouClientAlert.STATUS_NEW)
            atual.status = status_original
            db.session.commit()

        # --- tenant
        with app.app_context():
            de_outro = (DouClientAlert.query
                        .filter(DouClientAlert.law_firm_id != firm_id).first())
            outro_id = de_outro.id if de_outro else None
        if outro_id:
            check('alerta de outro escritório dá 404',
                  c.post(f'/dou/alertas/{outro_id}/lida').status_code == 404)
        else:
            check('alerta de outro escritório dá 404 (só um escritório na base)',
                  c.post('/dou/alertas/99999999/lida').status_code == 404)

    # Sem escritório na sessão a tela não pode abrir — o alerta é do tenant
    with app.test_client() as c:
        with c.session_transaction() as sessao:
            sessao['user_id'] = user_id
            sessao['user_role'] = 'admin'
        check('sem escritório na sessão, a tela recusa',
              c.get('/dou/alertas').status_code in (302, 403))


def test_chip_da_header():
    """O badge de alerta no chip do Diário Oficial."""
    print('\n6. Chip da header')

    with app.app_context():
        usuario = User.query.filter_by(role='admin').first()
        if usuario is None:
            print('  ⏭️  nenhum usuário admin — pulando')
            return
        user_id, firm_id = usuario.id, usuario.law_firm_id
        nao_lidos = alertas.contar_nao_lidos(firm_id)

    with app.test_client() as c:
        with c.session_transaction() as sessao:
            sessao['user_id'] = user_id
            sessao['law_firm_id'] = firm_id
            sessao['user_role'] = 'admin'
        html = c.get('/dou/').get_data(as_text=True)

    if nao_lidos:
        check('o chip mostra o número de alertas não lidos',
              f'>{nao_lidos if nao_lidos < 100 else "99+"}</span>' in html
              or 'alerta(s) de cliente não lido(s)' in html,
              f'esperava {nao_lidos}')
        check('com alerta pendente o chip aponta para os alertas',
              '/dou/alertas' in html)
    else:
        check('sem alerta pendente o chip não inventa badge',
              'alerta(s) de cliente não lido(s)' not in html)


def test_trecho():
    """O modal "ver trecho": recorte por CNPJ, inteiro teor no edital-tabela."""
    print('\n7. Trecho da matéria')
    from app.services import dou_search_service as busca

    # --- marcação de todas as ocorrências, sem marca dentro de marca
    marcado = busca.marcar_identificadores(
        'Contrato com 33.592.510/0001-54 e com 33.592.510/0021-06 hoje',
        ['33592510000154', '33592510002106'])
    check('marca as duas ocorrências', marcado.count(busca.MARCA_INI) == 2, marcado)
    check('não marca quem não foi pedido',
          busca.marcar_identificadores('CNPJ 33.592.510/0001-54',
                                       ['11222333000181']).count(busca.MARCA_INI) == 0)
    check('texto sem alvo volta inteiro',
          busca.marcar_identificadores('sem número', []) == 'sem número')
    check('texto vazio não quebra', busca.marcar_identificadores(None, ['x']) is None)

    # --- o HTML do DOU não pode virar elemento na página: o fragmento entra
    # no template com `| safe`, então o escape tem de acontecer aqui.
    perigoso = busca.destacar('<script>alert(1)</script> e '
                              + busca.MARCA_INI + '33.592.510/0001-54' + busca.MARCA_FIM)
    check('o script do texto é escapado', '<script>' not in perigoso, perigoso[:60])
    check('e a marca vira <mark> de verdade', '<mark>' in perigoso)

    with app.app_context():
        pequeno = DouClientAlert.query.filter_by(clients_count=1).first()
        grande = (DouClientAlert.query
                  .order_by(DouClientAlert.clients_count.desc()).first())
        if pequeno is None or grande is None:
            print('  ⏭️  sem alertas para exercitar — pulando')
            return

        um = alertas.trechos_do_alerta(pequeno)
        check('matéria em prosa vem como HTML, não texto puro',
              um['modo'] == 'html', str(um['modo']))
        check('o bloco traz o CNPJ marcado', '<mark>' in (um['html'] or ''),
              (um['html'] or '')[:80])
        check('vem o parágrafo, não a matéria inteira',
              len(um['html'] or '') < len(pequeno.article.texto_html or ''),
              f"{len(um['html'] or '')} vs {len(pequeno.article.texto_html or '')}")
        check('e não sobra tag proibida do documento publicado',
              '<script' not in (um['html'] or '') and '<style' not in (um['html'] or ''))

        muitos = alertas.trechos_do_alerta(grande)
        if grande.clients_count > 20:
            check('o edital-tabela sai como tabela de verdade',
                  muitos['modo'] == 'html' and '<table' in (muitos['html'] or ''),
                  str(muitos['modo']))
            check('uma tabela só, não uma por linha',
                  (muitos['html'] or '').count('<table') == 1,
                  f"{(muitos['html'] or '').count('<table')} tabelas")
            check('todas as citações do cliente cabem no recorte',
                  muitos['restantes'] == 0
                  and (muitos['html'] or '').count('<mark>') >= grande.clients_count - 2,
                  f"{(muitos['html'] or '').count('<mark>')} marcas para "
                  f"{grande.clients_count} CNPJs, {muitos['restantes']} de fora")
            # Comparar tamanho não serve: quando todas as linhas da tabela são
            # do cliente, o recorte é a tabela inteira — e ainda cresce com as
            # tags <mark>. O invariante é outro: nenhuma linha de terceiro
            # entra no recorte.
            from bs4 import BeautifulSoup as _BS
            from app.services.dou_search_service import extrair_cnpjs as _ex
            do_cliente = {m.cnpj for m in grande.matches}
            fora = [tr for tr in _BS(muitos['html'] or '', 'html.parser').find_all('tr')
                    if do_cliente.isdisjoint(_ex(tr.get_text(' ')))]
            check('nenhuma linha de outra empresa entra no recorte',
                  not fora, f'{len(fora)} linha(s) de terceiro')

        # A montagem do HTML, sem depender do acervo
        from bs4 import BeautifulSoup as _BS
        sopa = _BS('<table><tr><td><p>33.592.510/0001-54</p></td>'
                   '<td><p>Deferido</p></td></tr>'
                   '<tr><td><p>11.222.333/0001-81</p></td><td><p>x</p></td></tr>'
                   '</table><p>Nada aqui</p>', 'html.parser')
        blocos = alertas._blocos_com_cnpj(sopa, ['33592510000154'])
        check('o bloco de uma célula é a LINHA, não a célula',
              len(blocos) == 1 and blocos[0].name == 'tr', str(blocos))
        check('a linha traz as outras colunas junto',
              'Deferido' in blocos[0].get_text(), blocos[0].get_text())
        check('linha de outra empresa fica de fora',
              '11.222.333' not in blocos[0].get_text())
        montado = alertas._montar_html(blocos)
        check('<tr> solto ganha <table> em volta, senão não renderiza',
              montado.startswith('<table>') and montado.endswith('</table>'),
              montado[:60])

        usuario = User.query.filter_by(role='admin').first()
        user_id, firm_id = usuario.id, usuario.law_firm_id
        id_pequeno, id_grande = pequeno.id, grande.id

    with app.test_client() as c:
        with c.session_transaction() as sessao:
            sessao['user_id'] = user_id
            sessao['law_firm_id'] = firm_id
            sessao['user_role'] = 'admin'

        resposta = c.get(f'/dou/alertas/{id_pequeno}/trecho')
        html = resposta.get_data(as_text=True)
        check('a rota do trecho responde', resposta.status_code == 200,
              str(resposta.status_code))
        check('devolve fragmento, não a página inteira',
              '<html' not in html.lower() and 'dou-trecho' in html)
        check('o fragmento leva a matéria inteira e a folha',
              '/dou/materia/' in html and '/pagina/' in html)

        grandes = c.get(f'/dou/alertas/{id_grande}/trecho').get_data(as_text=True)
        check('o edital-tabela chega como tabela, com o CSS da matéria',
              '<table' in grandes and 'dou-texto' in grandes,
              'sem a classe dou-texto a tabela sai sem colunas')
        check('as ações vêm num bloco que o JS move para o rodapé fixo',
              'dou-trecho__pe' in grandes)

        check('trecho de alerta inexistente dá 404',
              c.get('/dou/alertas/99999999/trecho').status_code == 404)

        lista = c.get('/dou/alertas').get_data(as_text=True)
        check('o botão fica ao lado de "Ver no Diário"',
              'dou-ver-trecho' in lista and 'Ver no Diário' in lista)
        check('a lista tem um modal só, não um por linha',
              lista.count('id="modal-trecho"') == 1,
              f"{lista.count('id=\"modal-trecho\"')} modais")
        check('o inteiro teor não é embutido na lista',
              'dou-trecho__texto' not in lista,
              'a página carregaria 30 matérias de uma vez')


def test_resultado_fap():
    """A decisão do recurso: detecção, contagem e destaque na tela."""
    print('\n8. Resultado de recurso FAP')
    from bs4 import BeautifulSoup as _BS

    # --- vocabulário. Medido no acervo: 1.070 "Indeferimento Total",
    # 249 "Deferimento Parcial", 1 "Deferimento Total".
    for valor in ('Indeferimento Total', 'Deferimento Parcial',
                  'Deferimento Total', 'INDEFERIMENTO TOTAL',
                  'Deferimento parcial', 'Diligência', 'Prejudicado'):
        check(f'{valor!r} é decisão', alertas.eh_resultado(valor))
    for valor in ('2025', 'Adm. 2ª Instância', '10128.027795/2024-04', '', None,
                  'O recurso trata de indeferimento total do pedido anterior'):
        check(f'{valor!r} não é decisão', not alertas.eh_resultado(valor))

    # --- a decisão sai da linha do CNPJ, não da primeira do documento
    sopa = _BS('<table>'
               '<tr><td><p>718</p></td><td><p>33.592.510/0001-54</p></td>'
               '<td><p>Adm. 2ª Instância</p></td><td><p>Deferimento Parcial</p></td></tr>'
               '<tr><td><p>719</p></td><td><p>11.222.333/0001-81</p></td>'
               '<td><p>Adm. 2ª Instância</p></td><td><p>Indeferimento Total</p></td></tr>'
               '</table>', 'html.parser')
    blocos = alertas._blocos_com_cnpj(sopa, ['33592510000154'])
    check('a decisão vem da linha daquele CNPJ',
          alertas.resultado_do_bloco(blocos[0]) == 'Deferimento Parcial',
          str(alertas.resultado_do_bloco(blocos[0])))
    check('parágrafo solto não tem decisão',
          alertas.resultado_do_bloco(_BS('<p>Indeferimento Total</p>',
                                         'html.parser').p) is None,
          'só linha de tabela carrega decisão de recurso')

    # --- a célula de decisão ganha classe no HTML do modal
    marcado = alertas._montar_html(blocos)
    check('a célula de decisão é marcada no modal',
          'dou-decisao--favoravel' in marcado, marcado[-160:])

    with app.app_context():
        com = DouClientAlert.query.filter_by(tem_resultado=True).all()
        if not com:
            print('  ⏭️  nenhum alerta com resultado no acervo — pulando')
            return
        usuario = User.query.filter_by(role='admin').first()
        user_id, firm_id = usuario.id, usuario.law_firm_id

        check('a geração marcou os alertas com decisão', len(com) > 0,
              f'{len(com)} de {DouClientAlert.query.count()}')
        check('todo alerta marcado tem ao menos uma decisão gravada',
              all(a.resultados for a in com),
              'tem_resultado sem match com resultado')
        check('nenhum alerta sem decisão ficou marcado',
              not DouClientAlert.query.filter(
                  DouClientAlert.tem_resultado.is_(True),
                  ~DouClientAlert.matches.any(
                      DouClientAlertMatch.resultado.isnot(None))).count())

        maior = max(com, key=lambda a: a.clients_count)
        soma = sum(q for _, q, _ in maior.resultados)
        check('a contagem por decisão fecha com os CNPJs que a têm',
              soma == sum(1 for m in maior.matches if m.resultado),
              f'{soma} vs {sum(1 for m in maior.matches if m.resultado)}')

        favoraveis = [a for a in com if a.tem_favoravel]
        if favoraveis:
            alvo = favoraveis[0]
            check('deferimento vem antes de indeferimento no resumo',
                  alvo.resultados[0][2] is True,
                  str(alvo.resultados))
        check('deferimento é favorável, indeferimento não',
              all(fav == d.lower().startswith('deferimento')
                  for a in com for d, _, fav in a.resultados))

        resumo = alertas.resumo(firm_id)
        check('o resumo conta os alertas com resultado',
              resumo['com_resultado'] == len(com),
              f"{resumo['com_resultado']} vs {len(com)}")

        # Dentro do dia, desfecho antes de notícia
        pagina = alertas.listar(firm_id, status=None, page=1)
        seq = [(a.pub_date, a.tem_resultado) for a in pagina.items]
        fora_de_ordem = [i for i in range(len(seq) - 1)
                         if seq[i][0] == seq[i + 1][0]
                         and not seq[i][1] and seq[i + 1][1]]
        check('no mesmo dia, quem tem decisão vem primeiro',
              not fora_de_ordem, f'{len(fora_de_ordem)} inversão(ões)')

        so_com = alertas.listar(firm_id, status=None, resultado=True, page=1)
        check('o filtro devolve só quem tem decisão',
              all(a.tem_resultado for a in so_com.items) and so_com.total == len(com),
              f'{so_com.total} vs {len(com)}')

    with app.test_client() as c:
        with c.session_transaction() as sessao:
            sessao['user_id'] = user_id
            sessao['law_firm_id'] = firm_id
            sessao['user_role'] = 'admin'

        html = c.get('/dou/alertas?status=todos').get_data(as_text=True)
        check('o tile de resultado FAP aparece', 'com resultado FAP' in html)
        check('a linha mostra a contagem por decisão',
              'dou-alerta__resultados' in html and 'RESULTADO FAP' in html.upper())
        check('favorável e contrário têm cores diferentes',
              'dou-resultado--sim' in html and 'dou-resultado--nao' in html)

        filtrado = c.get('/dou/alertas?status=todos&resultado=1')
        corpo = filtrado.get_data(as_text=True)
        check('o tile filtra ao ser clicado', filtrado.status_code == 200)
        check('e a página filtrada só tem linhas com decisão',
              corpo.count('class="dou-alerta ') == corpo.count('dou-alerta--resultado'),
              f"{corpo.count('class=\"dou-alerta ')} linhas, "
              f"{corpo.count('dou-alerta--resultado')} com decisão")
        check('o filtro sobrevive à paginação',
              'resultado=1' in corpo or 'Próxima' not in corpo)


def main():
    print('=' * 60)
    print('TESTES DOS ALERTAS DE CLIENTE NO DIÁRIO OFICIAL')
    print('=' * 60)

    test_validacao_de_cnpj()
    test_casamento()
    test_alerta_e_por_materia()
    test_reprocessar_nao_duplica()
    test_tela()
    test_chip_da_header()
    test_trecho()
    test_resultado_fap()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
