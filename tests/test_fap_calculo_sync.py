#!/usr/bin/env python3
"""Busca e gravação de um estabelecimento da Consulta do FAP. Sem rede.

    uv run python tests/test_fap_calculo_sync.py
"""

import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, LawFirm, FapCalculoEstabelecimento, FapCalculoItem
from app.services import fap_calculo_client as client
from app.services import fap_calculo_sync_service as sync
from app.services.fap_web_service import FapWebResult

TEST_CNPJ = '00000000000999'
ESTAB = '07718633008163'
ANO = 2026

_falhas = []


def check(nome, condicao, detalhe=''):
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _calc(id_, tipo, data, b91=0, cat=0):
    return {'id': id_, 'tipoProcessamento': tipo, 'dataProcessamento': data,
            'quantidadeB91': b91, 'quantidadeB92': 0, 'quantidadeB93': 0,
            'quantidadeB94': 0, 'quantidadeCat': cat}


def _ben(nb, estado):
    return {'nb': nb, 'especie': 'B91', 'nit': '12455224092', 'cpf': 1234567890,
            'dataNascimento': '1976-05-14', 'cnpj': int(ESTAB), 'valorMensal': '1598.72',
            'totalPago': '2991.15', 'bloqueio': False, 'estado': estado}


CAT = {'numeroCat': 2024000123, 'nit': '12455224092', 'cpf': 1234567890,
       'cnpjOriginal': int(ESTAB), 'cnpjAtribuido': int(ESTAB), 'dataAcidente': '2024-07-04',
       'bloqueio': False, 'estado': 'ORIGINAL'}

CALCULOS = [
    {'anoVigencia': ANO, 'tipoProcessamento': 'EVENTO', 'dataProcessamento': '2026-10-20'},
    _calc(200, 'RECALCULO', '2026-10-20', b91=2, cat=1),
    _calc(100, 'CALCULO_ORIGINAL', '2025-09-30', b91=2, cat=1),
]


class Dublê:
    def __init__(self, calculos, beneficios, cats=None, calculos_status=None):
        self.calculos, self.beneficios, self.cats = calculos, beneficios, cats or {}
        self.calculos_status = calculos_status
        self.chamadas_beneficios = []

    def listar_calculos(self, svc, ano, cnpj):
        if self.calculos_status:
            return FapWebResult(ok=False, status_code=self.calculos_status, message='x',
                                expired=self.calculos_status == 401)
        return FapWebResult(ok=True, data=self.calculos)

    def listar_beneficios(self, svc, ano, cnpj, cid):
        self.chamadas_beneficios.append(cid)
        return FapWebResult(ok=True, data=self.beneficios.get(cid, []))

    def listar_cats(self, svc, ano, cnpj, cid):
        return FapWebResult(ok=True, data=self.cats.get(cid, []))


def _limpar(firm_id):
    FapCalculoItem.query.filter_by(law_firm_id=firm_id).delete()
    FapCalculoEstabelecimento.query.filter_by(law_firm_id=firm_id).delete()
    db.session.commit()


def _rodar(firm_id, d, gravado=None):
    orig = (client.listar_calculos, client.listar_beneficios, client.listar_cats)
    client.listar_calculos, client.listar_beneficios, client.listar_cats = (
        d.listar_calculos, d.listar_beneficios, d.listar_cats)
    try:
        busca = sync.buscar_estabelecimento(None, ANO, ESTAB, gravado)
    finally:
        client.listar_calculos, client.listar_beneficios, client.listar_cats = orig
    return busca, sync.gravar_estabelecimento(firm_id, busca)


def _itens(firm_id):
    return {(i.tipo, i.identificador): i
            for i in FapCalculoItem.query.filter_by(law_firm_id=firm_id)}


def test_primeira_busca_grava_itens(fid):
    print('primeira busca grava itens')
    d = Dublê(CALCULOS,
              {200: [_ben(6505977833, 'ORIGINAL'), _ben(6505977834, 'EXCLUIDO')],
               100: [_ben(6505977833, 'ORIGINAL'), _ben(6505977834, 'ORIGINAL')]},
              {200: [CAT], 100: [CAT]})
    _, cont = _rodar(fid, d)
    itens = _itens(fid)
    check('3 itens novos', cont == {'itens_novos': 3, 'itens_atualizados': 0}, str(cont))
    check('B91 + CAT', ('B91', '6505977833') in itens and ('CAT', '2024000123') in itens)
    check('estado_original ORIGINAL', itens[('B91', '6505977833')].estado_original == 'ORIGINAL')
    check('estado_atual EXCLUIDO', itens[('B91', '6505977834')].estado_atual == 'EXCLUIDO')
    check('cnpj do estabelecimento na CAT', itens[('CAT', '2024000123')].cnpj == ESTAB
          and itens[('CAT', '2024000123')].cnpj_raiz == ESTAB[:8])
    check('calculo_id atual', itens[('B91', '6505977833')].calculo_id == 200)
    e = FapCalculoEstabelecimento.query.filter_by(law_firm_id=fid).one()
    check('estab gravado', e.calculo_atual_id == 200 and e.calculo_original_id == 100
          and e.situacao == 'ok' and e.tem_itens and e.synced_at is not None)


def test_mesmo_calculo_nao_busca_itens(fid):
    print('mesmo cálculo não busca itens')
    d = Dublê(CALCULOS, {200: [_ben(1, 'ORIGINAL')]})
    busca, cont = _rodar(fid, d, gravado=200)
    check('itens_atual None', busca.itens_atual is None)
    check('benefícios não chamado', d.chamadas_beneficios == [])
    check('itens intactos', len(_itens(fid)) == 3)
    check('contagem zero', cont == {'itens_novos': 0, 'itens_atualizados': 0})


def test_item_que_sumiu_fica(fid):
    print('item que sumiu fica')
    for i in _itens(fid).values():  # envelhece, para a comparação não depender do relógio do banco
        i.last_seen_at = i.last_seen_at - timedelta(hours=1)
    db.session.commit()
    antes = _itens(fid)[('B91', '6505977834')].last_seen_at
    calculos = [_calc(300, 'RECALCULO', '2026-10-21', b91=1)] + CALCULOS[1:]
    d = Dublê(calculos, {300: [_ben(6505977833, 'ORIGINAL')],
                         100: [_ben(6505977833, 'ORIGINAL')]})
    _, cont = _rodar(fid, d, gravado=200)
    itens = _itens(fid)
    check('linha continua', ('B91', '6505977834') in itens)
    check('last_seen_at antigo', itens[('B91', '6505977834')].last_seen_at == antes)
    check('visto atualizado', itens[('B91', '6505977833')].last_seen_at > antes)
    check('atualizado 1', cont['itens_atualizados'] == 1 and cont['itens_novos'] == 0, str(cont))


def test_sem_calculo(fid):
    print('sem cálculo')
    d = Dublê([{'tipoProcessamento': 'EVENTO', 'dataProcessamento': '2026-10-20'}], {})
    busca, _ = _rodar(fid, d)
    check('sem_calculo', busca.situacao == 'sem_calculo')
    check('sem chamadas', d.chamadas_beneficios == [])
    e = FapCalculoEstabelecimento.query.filter_by(law_firm_id=fid).one()
    check('situação gravada', e.situacao == 'sem_calculo')


def test_403_nao_apaga(fid):
    print('403 não apaga')
    e = FapCalculoEstabelecimento.query.filter_by(law_firm_id=fid).one()
    e.calculo_atual_id = 300
    db.session.commit()
    d = Dublê([], {}, calculos_status=403)
    busca, _ = _rodar(fid, d, gravado=300)
    e = FapCalculoEstabelecimento.query.filter_by(law_firm_id=fid).one()
    check('sem_acesso', busca.situacao == 'sem_acesso' and e.situacao == 'sem_acesso')
    check('itens intactos', len(_itens(fid)) == 3)
    check('calculo_atual_id preservado', e.calculo_atual_id == 300, str(e.calculo_atual_id))


def test_tem_itens_false_nao_chama_beneficios(fid):
    print('tem_itens False')
    _limpar(fid)
    d = Dublê([_calc(400, 'CALCULO_ORIGINAL', '2025-09-30')], {})
    busca, _ = _rodar(fid, d)
    check('ok com lista vazia', busca.situacao == 'ok' and busca.itens_atual == [])
    check('benefícios não chamado', d.chamadas_beneficios == [])
    e = FapCalculoEstabelecimento.query.filter_by(law_firm_id=fid).one()
    check('estab gravado sem itens', e.calculo_atual_id == 400 and not e.tem_itens
          and len(_itens(fid)) == 0)


ESTAB_B1, ESTAB_B2 = '11111111000191', '11111111000272'


class Portal:
    """Dublê do portal inteiro, para ``sincronizar``: ``estabs`` por raiz (int = status de falha)."""

    def __init__(self, estabs, expira_em=None):
        self.estabs, self.expira_em = estabs, expira_em
        self.chamadas_calculos = []

    def anos(self, svc):
        return FapWebResult(ok=True, data=[ANO])

    def estabelecimentos(self, svc, ano, raiz):
        v = self.estabs[raiz]
        if isinstance(v, int):
            return FapWebResult(ok=False, status_code=v, message='x', expired=v == 401)
        return FapWebResult(ok=True, data=v)

    def calculos(self, svc, ano, cnpj):
        self.chamadas_calculos.append(cnpj)
        if self.expira_em and cnpj == self.expira_em:
            return FapWebResult(ok=False, status_code=401, message='x', expired=True)
        return FapWebResult(ok=True, data=[_calc(500, 'CALCULO_ORIGINAL', '2025-09-30', b91=1)])

    def beneficios(self, svc, ano, cnpj, cid):
        return FapWebResult(ok=True, data=[{**_ben(int(cnpj[-4:]) + 7000000000, 'ORIGINAL'),
                                            'cnpj': int(cnpj)}])

    def cats(self, svc, ano, cnpj, cid):
        return FapWebResult(ok=True, data=[])


def _com_portal(p, fn):
    nomes = ('listar_anos', 'listar_estabelecimentos', 'listar_calculos', 'listar_beneficios', 'listar_cats')
    orig = [getattr(client, n) for n in nomes]
    for n, f in zip(nomes, (p.anos, p.estabelecimentos, p.calculos, p.beneficios, p.cats)):
        setattr(client, n, f)
    try:
        return fn()
    finally:
        for n, f in zip(nomes, orig):
            setattr(client, n, f)


def test_sincronizar_duas_raizes_uma_sem_acesso(fid):
    print('sincronizar: uma raiz sem acesso')
    _limpar(fid)
    p = Portal({'22222222': 403, '11111111': [ESTAB_B1, ESTAB_B2]})
    r = _com_portal(p, lambda: sync.sincronizar(
        fid, None, anos=[ANO], raizes=['22222222', '11111111'], workers=2, log=lambda *_: None))
    check('sem_acesso 1', r['sem_acesso'] == 1, str(r))
    check('2 estabelecimentos', r['estabelecimentos'] == 2 and r['com_itens'] == 2, str(r))
    check('2 itens novos', r['itens_novos'] == 2 and r['erros'] == 0 and not r['expirada'], str(r))
    check('itens de B gravados', len(_itens(fid)) == 2)
    check('nada de A', FapCalculoEstabelecimento.query.filter_by(
        law_firm_id=fid, cnpj_raiz='22222222').count() == 0)


def test_somente_novos_pula_gravados(fid):
    print('somente_novos pula gravados')
    p = Portal({'11111111': [ESTAB_B1, ESTAB_B2, '11111111000353']})
    r = _com_portal(p, lambda: sync.sincronizar(
        fid, None, anos=[ANO], raizes=['11111111'], workers=2, somente_novos=True,
        log=lambda *_: None))
    check('só o novo consultado', p.chamadas_calculos == ['11111111000353'], str(p.chamadas_calculos))
    check('1 estabelecimento', r['estabelecimentos'] == 1, str(r))


def test_expirada_interrompe(fid):
    print('expirada interrompe')
    _limpar(fid)
    p = Portal({'11111111': [ESTAB_B1, ESTAB_B2]}, expira_em=ESTAB_B2)
    r = _com_portal(p, lambda: sync.sincronizar(
        fid, None, anos=[ANO], raizes=['11111111'], workers=1, log=lambda *_: None))
    check('expirada True', r['expirada'] is True, str(r))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'fap_calculo_sync_script', Path(__file__).resolve().parent.parent / 'scripts' / 'fap_calculo_sync.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    codigo = _com_portal(p, lambda: mod.main(
        ['--vigencia', str(ANO), '--empresa', '11111111', '--sem-completar',
         '--escritorio', str(fid), '--workers', '1'], svc=object()))
    check('saída 2', codigo == 2, str(codigo))


def test_falha_na_lista_de_anos_e_incompleta(fid):
    print('falha em /vigencias/anos: incompleta, saída 3')
    p = Portal({'11111111': [ESTAB_B1]})
    p.anos = lambda svc: FapWebResult(ok=False, status_code=502, message='HTTP 502')
    logs = []
    r = _com_portal(p, lambda: sync.sincronizar(fid, None, raizes=['11111111'], log=logs.append))
    check('incompleta', r['incompleta'] is True and r['erros'] == 1 and not r['expirada'], str(r))
    check('motivo no log', any('502' in str(m) for m in logs), str(logs))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'fap_calculo_sync_script3', Path(__file__).resolve().parent.parent / 'scripts' / 'fap_calculo_sync.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    codigo = _com_portal(p, lambda: mod.main(
        ['--empresa', '11111111', '--escritorio', str(fid), '--workers', '1'], svc=object()))
    check('saída 3', codigo == 3, str(codigo))
    p2 = Portal({'11111111': 502})
    r = _com_portal(p2, lambda: sync.sincronizar(
        fid, None, anos=[ANO], raizes=['11111111'], log=logs.append))
    check('listagem 502 incompleta', r['incompleta'] is True, str(r))
    p3 = Portal({'11111111': 403})
    r = _com_portal(p3, lambda: sync.sincronizar(
        fid, None, anos=[ANO], raizes=['11111111'], log=logs.append))
    check('403 não é incompleta', r['incompleta'] is False, str(r))


def test_empresas_pequenas_em_paralelo(fid):
    print('empresas de 1 estabelecimento rodam em paralelo')
    import threading
    _limpar(fid)
    raizes = [f'{n:08d}' for n in range(33333331, 33333339)]
    p = Portal({r: [r + '000191'] for r in raizes})
    trava, ativos, pico = threading.Lock(), [0], [0]
    calculos_orig = p.calculos

    def calculos_lentos(svc, ano, cnpj):
        with trava:
            ativos[0] += 1
            pico[0] = max(pico[0], ativos[0])
        time.sleep(0.2)
        with trava:
            ativos[0] -= 1
        return calculos_orig(svc, ano, cnpj)

    p.calculos = calculos_lentos
    t0 = time.time()
    r = _com_portal(p, lambda: sync.sincronizar(
        fid, None, anos=[ANO], raizes=raizes, workers=4, log=lambda *_: None))
    check('8 estabelecimentos', r['estabelecimentos'] == 8 and r['erros'] == 0, str(r))
    check('mais de uma empresa ao mesmo tempo', pico[0] >= 3, f'pico {pico[0]}')
    check('tempo de lotes, não de fila', time.time() - t0 < 1.2, f'{time.time() - t0:.2f}s')


def test_erro_de_estabelecimento_vai_ao_log(fid):
    print('erro de estabelecimento: motivo no log e no resultado')
    _limpar(fid)
    p = Portal({'11111111': [ESTAB_B1, ESTAB_B2]})
    p.calculos = lambda svc, ano, cnpj: FapWebResult(
        ok=False, message='Falha de rede no portal FAP: TimeoutError')
    logs = []
    r = _com_portal(p, lambda: sync.sincronizar(
        fid, None, anos=[ANO], raizes=['11111111'], workers=2, log=logs.append))
    check('2 erros', r['erros'] == 2 and r['incompleta'] is True, str(r))
    check('motivo agregado', r['motivos_erro'] == {'Falha de rede no portal FAP: TimeoutError': 2},
          str(r.get('motivos_erro')))
    check('CNPJ e motivo no log', any(ESTAB_B1 in str(m) and 'TimeoutError' in str(m) for m in logs),
          str(logs))


def main():
    with app.app_context():
        firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
        if firm:
            _limpar(firm.id)
            db.session.delete(firm)
            db.session.commit()
        firm = LawFirm(name='Escritório Teste Sync Cálculo', cnpj=TEST_CNPJ)
        db.session.add(firm)
        db.session.commit()
        fid = firm.id
        try:
            for t in (test_primeira_busca_grava_itens, test_mesmo_calculo_nao_busca_itens,
                      test_item_que_sumiu_fica, test_sem_calculo, test_403_nao_apaga,
                      test_tem_itens_false_nao_chama_beneficios,
                      test_sincronizar_duas_raizes_uma_sem_acesso, test_somente_novos_pula_gravados,
                      test_expirada_interrompe, test_falha_na_lista_de_anos_e_incompleta,
                      test_empresas_pequenas_em_paralelo, test_erro_de_estabelecimento_vai_ao_log):
                t(fid)
        finally:
            db.session.rollback()
            _limpar(fid)
            db.session.delete(db.session.get(LawFirm, fid))
            db.session.commit()
    if _falhas:
        print(f'\n❌ {len(_falhas)} falha(s): {_falhas}')
        sys.exit(1)
    print('\n✅ Tudo verde')


if __name__ == '__main__':
    main()
