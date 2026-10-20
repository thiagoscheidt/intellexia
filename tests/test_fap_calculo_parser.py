#!/usr/bin/env python3
"""
Parser puro da Consulta do FAP (cálculos, benefícios e CATs). Sem banco, sem rede.

    uv run python tests/test_fap_calculo_parser.py
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import fap_calculo_parser as parser

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _calc(id_, tipo, data, b91=0, b92=0, b93=0, b94=0, cat=0, **extra):
    return {'id': id_, 'tipoProcessamento': tipo, 'dataProcessamento': data,
            'quantidadeB91': b91, 'quantidadeB92': b92, 'quantidadeB93': b93,
            'quantidadeB94': b94, 'quantidadeCat': cat, **extra}


# Recon de 20/10/2026, UNIDASUL 0081-63: 5 eventos, 3 com cálculo.
UNIDASUL = [
    {'anoVigencia': 2026, 'cnpj': 7718633008163, 'tipoProcessamento': 'FIM_EFEITO_SUSPENSIVO_SEGUNDA_INSTANCIA',
     'dataProcessamento': '2026-10-20'},
    _calc(804038558, 'RECALCULO_ELETRONICO_SEGUNDA_INSTANCIA', '2026-10-20', b91=1,
          protocolo='10128.048333/2025-01'),
    {'tipoProcessamento': 'INICIO_EFEITO_SUSPENSIVO_SEGUNDA_INSTANCIA', 'dataProcessamento': '2026-03-10'},
    _calc(700000002, 'RECALCULO_ELETRONICO_PRIMEIRA_INSTANCIA', '2025-12-01', b91=1),
    _calc(625000001, 'CALCULO_ORIGINAL', '2025-09-30', b91=2),
]


def test_resumo_unidasul():
    print('\nresumo UNIDASUL')
    r = parser.resumir_calculos(UNIDASUL)
    check('atual_id', r['atual_id'] == 804038558, str(r['atual_id']))
    check('atual_tipo', r['atual_tipo'] == 'RECALCULO_ELETRONICO_SEGUNDA_INSTANCIA')
    check('atual_data', r['atual_data'] == date(2026, 10, 20), str(r['atual_data']))
    check('original_id', r['original_id'] == 625000001, str(r['original_id']))
    check('tem_itens', r['tem_itens'] is True)
    check('histórico só dos com id, na ordem',
          [h['id'] for h in r['historico']] == [804038558, 700000002, 625000001], str(r['historico']))
    check('protocolo', r['protocolo'] == '10128.048333/2025-01')


def test_sem_calculo():
    print('\nsem cálculo')
    eventos = [{'tipoProcessamento': 'INICIO_EFEITO_SUSPENSIVO_SEGUNDA_INSTANCIA', 'dataProcessamento': '2026-03-10'}]
    for entrada in (eventos, []):
        r = parser.resumir_calculos(entrada)
        check('atual_id None', r['atual_id'] is None)
        check('tem_itens False', r['tem_itens'] is False)
        check('histórico vazio', r['historico'] == [])


def test_tem_itens_pelo_original():
    print('\ntem_itens pelo original')
    r = parser.resumir_calculos([
        _calc(2, 'RECALCULO_ELETRONICO_SEGUNDA_INSTANCIA', '2026-10-20'),
        _calc(1, 'CALCULO_ORIGINAL', '2025-09-30', b94=1),
    ])
    check('atual zerado, original com B94 → True', r['tem_itens'] is True)
    r = parser.resumir_calculos([_calc(1, 'CALCULO_ORIGINAL', '2025-09-30')])
    check('todos zerados → False', r['tem_itens'] is False)


def test_beneficio():
    print('\nbenefício')
    d = {'nb': 6505977833, 'especie': 'B91', 'nit': '12455224092', 'cpf': 1234567890,
         'dataNascimento': '1976-05-14', 'cnpj': 7718633008163, 'valorMensal': '1598.72',
         'totalPago': '2991.15', 'dataDespacho': '2024-07-13', 'dataInicio': '2024-07-04',
         'dataCessacao': '2024-08-31', 'mesesContabilizacao': '1.8710', 'bloqueio': False,
         'estado': 'ORIGINAL'}
    b = parser.normalizar_beneficio(d)
    check('tipo', b['tipo'] == 'B91')
    check('identificador', b['identificador'] == '6505977833', str(b['identificador']))
    check('valor_mensal', b['valor_mensal'] == Decimal('1598.72'))
    check('total_pago', b['total_pago'] == Decimal('2991.15'))
    check('data_nascimento', b['data_nascimento'] == date(1976, 5, 14))
    check('meses_contabilizacao', b['meses_contabilizacao'] == Decimal('1.8710'))
    check('estado_atual', b['estado_atual'] == 'ORIGINAL')
    check('cnpj 14 dígitos', b['cnpj'] == '07718633008163', str(b['cnpj']))
    check('data_cessacao', b['data_cessacao'] == date(2024, 8, 31))
    check('raw_json presente', '6505977833' in b['raw_json'])


def test_cpf_com_zero():
    print('\nCPF com zero à esquerda')
    b = parser.normalizar_beneficio({'nb': 1, 'especie': 'B91', 'cpf': 1234567890})
    check('cpf completado', b['cpf'] == '01234567890', str(b['cpf']))


def test_cat():
    print('\nCAT')
    d = {'numeroCat': 2023123456789, 'nit': '12455224092', 'cpf': 1234567890,
         'dataNascimento': '1980-01-02', 'cnpjOriginal': 7718633008163,
         'cnpjAtribuido': 33592510007590, 'dataAcidente': '2023-05-01',
         'dataCadastroCat': '2023-05-03', 'dataObito': None, 'reciboEsocial': '1.2.3',
         'bloqueio': True, 'estado': 'ORIGINAL'}
    c = parser.normalizar_cat(d)
    check('tipo CAT', c['tipo'] == 'CAT')
    check('identificador', c['identificador'] == '2023123456789', str(c['identificador']))
    check('cnpj_atribuido 14', c['cnpj_atribuido'] == '33592510007590', str(c['cnpj_atribuido']))
    check('cnpj_original completado', c['cnpj_original'] == '07718633008163', str(c['cnpj_original']))
    check('dataObito None', c['data_obito'] is None)
    check('data_acidente', c['data_acidente'] == date(2023, 5, 1))
    check('bloqueio', c['bloqueio'] is True)
    check('cpf completado', c['cpf'] == '01234567890')


def main() -> int:
    test_resumo_unidasul()
    test_sem_calculo()
    test_tem_itens_pelo_original()
    test_beneficio()
    test_cpf_com_zero()
    test_cat()
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
