#!/usr/bin/env python3
"""
Completar CPF, nascimento, RMI e total pago dos benefícios da Central pela
Consulta do FAP — E02 e E04 da Remessa R09.

Cada benefício da Central está ligado a uma vigência (CNPJ do estabelecimento +
ano). Com isso a rota do portal se monta sozinha: ``/calculos`` dá o id do
cálculo atual e ``/calculos/{id}/beneficios/`` traz todos os benefícios dele,
com CPF, nascimento, RMI (``valorMensal``) e total pago.

Sem rede: ``FapWebService._get`` é trocado por um dublê. Escritório
descartável, criado e removido no fim.

    uv run python tests/test_fap_completar_beneficios.py
"""

import json
import sys
import urllib.error
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, LawFirm, Benefit, FapVigenciaCnpj
from app.services import fap_calculo_client as client
from app.services import fap_calculo_parser as parser
from app.services import fap_beneficio_portal_service as portal

TEST_CNPJ = '00000000000699'
ESTAB = '07718633008163'

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


# ── Dados no formato do portal (recon de 20/10/2026, UNIDASUL 0081-63) ──────

CALCULOS = [
    {'anoVigencia': 2026, 'cnpj': 7718633008163, 'tipoProcessamento': 'FIM_EFEITO_SUSPENSIVO_SEGUNDA_INSTANCIA',
     'dataProcessamento': '2026-10-20'},
    {'id': 804038558, 'tipoProcessamento': 'RECALCULO_ELETRONICO_SEGUNDA_INSTANCIA',
     'dataProcessamento': '2026-10-20', 'quantidadeB91': 1, 'quantidadeB92': 0, 'quantidadeB93': 0,
     'quantidadeB94': 0, 'quantidadeCat': 0, 'protocolo': '10128.048333/2025-01'},
    {'id': 625000001, 'tipoProcessamento': 'CALCULO_ORIGINAL', 'dataProcessamento': '2025-09-30',
     'quantidadeB91': 2, 'quantidadeB92': 0, 'quantidadeB93': 0, 'quantidadeB94': 0, 'quantidadeCat': 0},
]
ITEM = {'nb': 6505977833, 'especie': 'B91', 'nit': '12455224092', 'cpf': 1234567890,
        'dataNascimento': '1976-05-14', 'cnpj': 7718633008163, 'valorMensal': '1598.72',
        'dataDespacho': '2024-07-13', 'dataInicio': '2024-07-04', 'dataCessacao': '2024-08-31',
        'dataInicioContabilizacao': '2024-07-04', 'dataFimContabilizacao': '2024-08-31',
        'mesesContabilizacao': '1.8710', 'totalPago': '2991.15', 'bloqueio': False, 'estado': 'ORIGINAL'}
SO_NO_ORIGINAL = dict(ITEM, nb=6400000001, cpf=98765432100, valorMensal='1000.00', totalPago='500.00',
                      dataNascimento='1980-01-02')


class Dublê:
    """Troca ``svc._get``: responde por sufixo da URL e registra as chamadas."""

    def __init__(self, respostas):
        self.respostas = respostas
        self.urls = []
        self.referers = []

    def __call__(self, url, timeout=30, referer=''):
        self.urls.append(url)
        self.referers.append(referer)
        for sufixo, resposta in self.respostas.items():
            if url.endswith(sufixo):
                if isinstance(resposta, int):
                    raise urllib.error.HTTPError(url, resposta, 'erro', {}, BytesIO(b''))
                return json.dumps(resposta).encode(), 200
        raise urllib.error.HTTPError(url, 404, 'nao achou', {}, BytesIO(b''))


class Svc:
    def __init__(self, respostas):
        self._get = Dublê(respostas)


def svc_padrao():
    base = f'/vigencias/2026/empresa/{ESTAB}'
    return Svc({
        f'{base}/calculos': CALCULOS,
        f'{base}/calculos/804038558/beneficios/': [ITEM],
        f'{base}/calculos/625000001/beneficios/': [ITEM, SO_NO_ORIGINAL],
    })


def test_cliente():
    print('\n1. Cliente da Consulta do FAP')
    svc = svc_padrao()
    r = client.listar_beneficios(svc, 2026, ESTAB, 804038558)
    check('benefícios: URL com a barra final (todas as espécies)',
          svc._get.urls[-1].endswith('/calculos/804038558/beneficios/'), svc._get.urls[-1])
    check('referer da Consulta do FAP', svc._get.referers[-1].endswith('/consultar-fap'))
    check('devolve a lista', r.ok and r.data == [ITEM])

    r = client.listar_calculos(Svc({}), 2026, ESTAB)
    check('404 vira lista vazia', r.ok and r.data == [], str(r))
    r = client.listar_calculos(Svc({'/calculos': 403}), 2026, ESTAB)
    check('403 é sem acesso, não sessão expirada', not r.ok and r.status_code == 403 and not r.expired)
    r = client.listar_calculos(Svc({'/calculos': 401}), 2026, ESTAB)
    check('401 é sessão expirada', not r.ok and r.expired)


def test_parser():
    print('\n2. Leitura dos dados do portal')
    res = parser.resumir_calculos(CALCULOS)
    check('cálculo atual é o primeiro com id', res['atual_id'] == 804038558, str(res['atual_id']))
    check('original é o CALCULO_ORIGINAL', res['original_id'] == 625000001)
    check('tem itens', res['tem_itens'] is True)
    check('só eventos → sem cálculo', parser.resumir_calculos(CALCULOS[:1])['atual_id'] is None)

    b = parser.normalizar_beneficio(ITEM)
    check('NB em dígitos', b['identificador'] == '6505977833')
    check('CPF volta a ter 11 dígitos', b['cpf'] == '01234567890', b['cpf'])
    check('RMI e total pago em Decimal', b['valor_mensal'] == Decimal('1598.72') and b['total_pago'] == Decimal('2991.15'))
    check('nascimento em date', b['data_nascimento'] == date(1976, 5, 14))
    check('CNPJ com 14', b['cnpj'] == ESTAB)


def _setup():
    firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
    if firm:
        _cleanup(firm)
    firm = LawFirm(name='Escritório Teste Completar Benefícios', cnpj=TEST_CNPJ)
    db.session.add(firm)
    db.session.flush()
    vig = FapVigenciaCnpj(law_firm_id=firm.id, employer_cnpj=ESTAB, vigencia_year='2026')
    db.session.add(vig)
    db.session.flush()
    vazio = Benefit(law_firm_id=firm.id, benefit_number='6505977833', fap_vigencia_cnpj_id=vig.id)
    preenchido = Benefit(law_firm_id=firm.id, benefit_number='6400000001', fap_vigencia_cnpj_id=vig.id,
                         insured_cpf='11111111111', initial_monthly_benefit=Decimal('999.99'))
    fora = Benefit(law_firm_id=firm.id, benefit_number='6999999999', fap_vigencia_cnpj_id=vig.id)
    db.session.add_all([vazio, preenchido, fora])
    db.session.commit()
    return firm, vig, vazio.id, preenchido.id, fora.id


def _cleanup(firm):
    Benefit.query.filter_by(law_firm_id=firm.id).delete()
    FapVigenciaCnpj.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def test_completar():
    print('\n3. Completar os benefícios da Central')
    firm, vig, id_vazio, id_preenchido, id_fora = _setup()
    try:
        busca = portal.buscar_vigencia(svc_padrao(), 2026, ESTAB, {'6505977833', '6400000001', '6999999999'})
        check('achou no atual e buscou o original para quem faltou',
              set(busca.itens) == {'6505977833', '6400000001'}, str(sorted(busca.itens)))
        check('situação ok', busca.situacao == 'ok', busca.situacao)

        res = portal.aplicar(firm.id, vig.id, busca)
        db.session.commit()
        vazio, preenchido, fora = (db.session.get(Benefit, i) for i in (id_vazio, id_preenchido, id_fora))
        check('vazio recebe CPF, nascimento, RMI e total',
              vazio.insured_cpf == '01234567890' and vazio.insured_date_of_birth == date(1976, 5, 14)
              and vazio.initial_monthly_benefit == Decimal('1598.72') and vazio.total_paid == Decimal('2991.15'))
        check('CPF diferente é trocado pelo do portal', preenchido.insured_cpf == '98765432100',
              preenchido.insured_cpf)
        check('RMI já preenchida fica', preenchido.initial_monthly_benefit == Decimal('999.99'))
        check('total vazio é preenchido', preenchido.total_paid == Decimal('500.00'))
        check('NB que o portal não tem fica intacto', fora.insured_cpf is None)
        check('contagem por campo', res['cpf'] == 2 and res['rmi'] == 1 and res['total_pago'] == 2
              and res['nao_encontrados'] == 1, str(res))

        res2 = portal.aplicar(firm.id, vig.id, busca)
        check('rodar de novo não muda nada', res2['cpf'] == 0 and res2['rmi'] == 0 and res2['total_pago'] == 0,
              str(res2))

        sem = portal.buscar_vigencia(Svc({'/calculos': 403}), 2026, ESTAB, {'6505977833'})
        check('403 vira sem acesso, sem itens', sem.situacao == 'sem_acesso' and not sem.itens)
        exp = portal.buscar_vigencia(Svc({'/calculos': 401}), 2026, ESTAB, {'6505977833'})
        check('401 vira sessão expirada', exp.situacao == 'expirada')
    finally:
        db.session.rollback()
        _cleanup(firm)


def main() -> int:
    test_cliente()
    test_parser()
    with app.app_context():
        test_completar()

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
