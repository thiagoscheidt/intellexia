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

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
