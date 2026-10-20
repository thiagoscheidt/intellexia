#!/usr/bin/env python3
"""
Segurado no MCP — o que faltava do E02 da Remessa R09.

- nascimento nas listagens (listar_beneficios_fap e buscar_por_segurado), não
  só no detalhar_beneficio;
- busca pelo nome avisa que o sistema não tem o nome do segurado e pede o CPF
  (relatório e portal do FAP não trazem nome);
- CPF aceito com ou sem pontuação, e sem o zero à esquerda;
- buscar_por_segurado só por CPF trazia 30 CATs quaisquer do escritório: a
  consulta de CAT só filtrava por NIT. Agora as CATs vêm pelos NITs dos
  benefícios daquele CPF.

Escritório descartável, criado e removido no fim.

    uv run python tests/test_mcp_segurado.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, LawFirm, User, Benefit, FapContestationCat, FapContestationJudgmentReport
from mcp_server.tools.fap import AVISO_SEM_NOME, list_fap_benefits_handler
from mcp_server.tools.insights import buscar_por_segurado_handler

TEST_CNPJ = '00000000000799'
EMAIL = 'user__test_mcp_segurado@example.com'

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def setup():
    firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
    if firm:
        cleanup(firm)
    firm = LawFirm(name='Escritório Teste MCP Segurado', cnpj=TEST_CNPJ)
    db.session.add(firm)
    db.session.flush()
    user = User(law_firm_id=firm.id, name='t', email=EMAIL, role='admin', is_active=True)
    user.set_password('x')
    db.session.add(user)
    db.session.flush()
    report = FapContestationJudgmentReport(user_id=user.id, law_firm_id=firm.id,
                                           original_filename='r.pdf', file_path='/dev/null')
    db.session.add(report)
    db.session.flush()
    db.session.add_all([
        # CPF gravado pelo script novo (só dígitos, com o zero)
        Benefit(law_firm_id=firm.id, benefit_number='6505977833', benefit_type='B91',
                insured_nit='12455224092', insured_cpf='01234567890',
                insured_date_of_birth=date(1976, 5, 14)),
        # CPF digitado à mão, formatado
        Benefit(law_firm_id=firm.id, benefit_number='6400000001', benefit_type='B91',
                insured_nit='20000000001', insured_cpf='987.654.321-00'),
        FapContestationCat(law_firm_id=firm.id, report_id=report.id, cat_number='CAT-DO-SEGURADO',
                           insured_nit='12455224092'),
        FapContestationCat(law_firm_id=firm.id, report_id=report.id, cat_number='CAT-DE-OUTRO',
                           insured_nit='99999999999'),
    ])
    db.session.commit()
    return firm


def cleanup(firm):
    FapContestationCat.query.filter_by(law_firm_id=firm.id).delete()
    Benefit.query.filter_by(law_firm_id=firm.id).delete()
    FapContestationJudgmentReport.query.filter_by(law_firm_id=firm.id).delete()
    User.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def test_listar(firm):
    print('\n1. listar_beneficios_fap')
    for cpf in ('01234567890', '012.345.678-90', '1234567890'):
        r = list_fap_benefits_handler(firm.id, cpf=cpf)
        check(f'CPF "{cpf}" acha o benefício', r['total_encontrado'] == 1, str(r['total_encontrado']))
    r = list_fap_benefits_handler(firm.id, cpf='98765432100')
    check('CPF só dígitos acha o gravado com pontuação', r['total_encontrado'] == 1, str(r['total_encontrado']))
    item = list_fap_benefits_handler(firm.id, cpf='01234567890')['itens'][0]
    check('item traz a data de nascimento', item.get('segurado_data_nascimento') == '1976-05-14',
          str(item.get('segurado_data_nascimento')))
    r = list_fap_benefits_handler(firm.id, segurado='maria')
    check('busca por nome avisa que não há nome e pede o CPF', r.get('aviso') == AVISO_SEM_NOME, str(r.get('aviso')))
    check('sem nome na busca, sem aviso', 'aviso' not in list_fap_benefits_handler(firm.id, cpf='01234567890'))


def test_buscar_por_segurado(firm):
    print('\n2. buscar_por_segurado')
    modulos = ['fap_panel', 'disputes_center']
    r = buscar_por_segurado_handler(firm.id, modulos, cpf='012.345.678-90')
    check('CPF formatado acha o benefício', r['beneficios']['total'] == 1, str(r['beneficios']['total']))
    b = r['beneficios']['itens'][0]
    check('item traz NIT, CPF e nascimento',
          b.get('segurado_nit') == '12455224092' and b.get('segurado_cpf') == '01234567890'
          and b.get('segurado_data_nascimento') == '1976-05-14', str(b))
    numeros = [c['numero_cat'] for c in r['cats']['itens']]
    check('só por CPF: só as CATs do NIT desse segurado', numeros == ['CAT-DO-SEGURADO'], str(numeros))

    r = buscar_por_segurado_handler(firm.id, modulos, cpf='11122233344')
    check('CPF sem benefício: nenhuma CAT (antes vinham 30 quaisquer)', r['cats']['total'] == 0, str(r['cats']))

    r = buscar_por_segurado_handler(firm.id, modulos, nome='maria')
    check('nome: aviso de que não há nome do segurado', r.get('aviso') == AVISO_SEM_NOME, str(r.get('aviso')))


def main() -> int:
    with app.app_context():
        firm = setup()
        try:
            test_listar(firm)
            test_buscar_por_segurado(firm)
        finally:
            db.session.rollback()
            cleanup(firm)

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
