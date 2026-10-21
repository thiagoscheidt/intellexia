#!/usr/bin/env python3
"""
Link para a consulta de situação cadastral do CPF na Receita Federal, já
preenchido com CPF e data de nascimento.

A página da Receita aceita ``?CPF=<11 dígitos>&NASCIMENTO=<ddmmaaaa>`` e abre
com os dois campos preenchidos (conferido em 21/10/2026 com CPF fictício); a
pessoa ainda resolve o captcha. É de lá que sai o nome do segurado, que nem o
relatório nem a Consulta do FAP trazem.

Função pura + a coluna Segurado da tela de Benefícios + o MCP. Escritório
descartável, removido no fim.

    uv run python tests/test_link_receita_cpf.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, LawFirm, Benefit
from app.utils.cnpj import link_consulta_cpf_receita

BASE = 'https://servicos.receita.fazenda.gov.br/Servicos/CPF/ConsultaSituacao/ConsultaPublica.asp'
TEST_CNPJ = '00000000000699'
CPF_FICTICIO = '12345678909'  # exemplo clássico de documentação, DV válido

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def test_funcao():
    print('\n1. link_consulta_cpf_receita')
    esperado = f'{BASE}?CPF=12345678909&NASCIMENTO=01011990'
    check('CPF cru + date', link_consulta_cpf_receita('12345678909', date(1990, 1, 1)) == esperado,
          str(link_consulta_cpf_receita('12345678909', date(1990, 1, 1))))
    check('CPF formatado + dd/mm/aaaa', link_consulta_cpf_receita('123.456.789-09', '01/01/1990') == esperado)
    check('data ISO', link_consulta_cpf_receita('12345678909', '1990-01-01') == esperado)
    check('CPF numérico (int) aceito', link_consulta_cpf_receita(12345678909, '1990-01-01') == esperado)
    check('sem nascimento → None', link_consulta_cpf_receita('12345678909', None) is None)
    check('sem CPF → None', link_consulta_cpf_receita(None, date(1990, 1, 1)) is None)
    check('CPF com DV errado → None', link_consulta_cpf_receita('12345678900', date(1990, 1, 1)) is None)
    check('CPF repetido → None', link_consulta_cpf_receita('11111111111', date(1990, 1, 1)) is None)
    check('data inválida → None', link_consulta_cpf_receita('12345678909', '31/02/1990') is None)
    check('"Não informado" → None', link_consulta_cpf_receita('Não informado', '01/01/1990') is None)


def _setup():
    firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
    if firm:
        _cleanup(firm)
    firm = LawFirm(name='Escritório Teste Link Receita', cnpj=TEST_CNPJ)
    db.session.add(firm)
    db.session.flush()
    com = Benefit(law_firm_id=firm.id, benefit_number='9911000001', benefit_type='B91',
                  insured_cpf=CPF_FICTICIO, insured_date_of_birth=date(1990, 1, 1))
    sem = Benefit(law_firm_id=firm.id, benefit_number='9911000002', benefit_type='B91',
                  insured_nit='12345678901')
    db.session.add_all([com, sem])
    db.session.commit()
    return firm, com, sem


def _cleanup(firm):
    Benefit.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def test_tela_e_mcp():
    print('\n2. Tela de Benefícios e MCP')
    from app.blueprints.disputes_center import _serialize_benefit_row
    from mcp_server.tools.fap import get_benefit_detail_handler, list_fap_benefits_handler
    from mcp_server.tools.insights import buscar_por_segurado_handler

    firm, com, sem = _setup()
    try:
        link = f'{BASE}?CPF=12345678909&NASCIMENTO=01011990'
        check('linha da tela traz o link', _serialize_benefit_row(com, '').get('consulta_cpf_receita') == link)
        check('linha sem CPF não traz', not _serialize_benefit_row(sem, '').get('consulta_cpf_receita'))

        itens = {i['numero_beneficio']: i for i in list_fap_benefits_handler(firm.id, limit=50)['itens']}
        check('listar_beneficios_fap', itens['9911000001'].get('consulta_cpf_receita') == link,
              str(itens['9911000001'].get('consulta_cpf_receita')))
        check('… None sem CPF', itens['9911000002'].get('consulta_cpf_receita') is None)
        check('detalhar_beneficio', get_benefit_detail_handler(com.id, firm.id).get('consulta_cpf_receita') == link)
        r = buscar_por_segurado_handler(firm.id, ['fap_panel'], cpf=CPF_FICTICIO)
        bens = r['beneficios']['itens']
        check('buscar_por_segurado', bens and bens[0].get('consulta_cpf_receita') == link, str(bens)[:200])
    finally:
        db.session.rollback()
        _cleanup(firm)

    html = (Path(__file__).resolve().parent.parent / 'templates' / 'disputes_center' / 'list.html').read_text()
    check('coluna Segurado usa o link', 'row.consulta_cpf_receita' in html)


def main() -> int:
    test_funcao()
    with app.app_context(), app.test_request_context():
        test_tela_e_mcp()

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
