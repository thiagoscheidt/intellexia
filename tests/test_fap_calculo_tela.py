#!/usr/bin/env python3
"""Tela "Benefícios do cálculo FAP" (/fap-panel/calculo/) — Task 8.

Escritório e usuários descartáveis, removidos no fim.

    uv run python tests/test_fap_calculo_tela.py
"""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import (
    Benefit, FapCalculoEstabelecimento, FapCalculoItem, FapContestationCat,
    FapContestationJudgmentReport, FapVigenciaCnpj, LawFirm, User, UserPageVisit, db,
)
from app.utils.cnpj import formatar_cpf

TEST_CNPJ = '00000000001499'
EMAILS = ('admin__test_calculo_tela@example.com', 'semmodulo__test_calculo_tela@example.com')
URL = '/fap-panel/calculo/'

_falhas = []


def check(nome, condicao, detalhe=''):
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def cleanup(firm):
    FapContestationCat.query.filter_by(law_firm_id=firm.id).delete()
    FapContestationJudgmentReport.query.filter_by(law_firm_id=firm.id).delete()
    users = User.query.filter_by(law_firm_id=firm.id).all()
    ids = [u.id for u in users]
    if ids:
        UserPageVisit.query.filter(UserPageVisit.user_id.in_(ids)).delete(synchronize_session=False)
    for u in users:
        db.session.delete(u)
    Benefit.query.filter_by(law_firm_id=firm.id).delete()
    FapVigenciaCnpj.query.filter_by(law_firm_id=firm.id).delete()
    FapCalculoItem.query.filter_by(law_firm_id=firm.id).delete()
    FapCalculoEstabelecimento.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def setup():
    firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
    if firm:
        cleanup(firm)
    firm = LawFirm(name='Escritório Teste Cálculo Tela', cnpj=TEST_CNPJ)
    db.session.add(firm)
    db.session.flush()
    admin = User(law_firm_id=firm.id, name='admin', email=EMAILS[0], role='admin', is_active=True)
    admin.set_password('x')
    comum = User(law_firm_id=firm.id, name='comum', email=EMAILS[1], role='user', is_active=True)
    comum.set_password('x')
    comum.set_module_permissions(['dashboard'])
    db.session.add_all([admin, comum])
    db.session.flush()

    def item(tipo, ident, **kw):
        base = dict(law_firm_id=firm.id, ano_vigencia=2026, cnpj='07718633008163',
                    cnpj_raiz='07718633', tipo=tipo, identificador=ident,
                    estado_atual='ORIGINAL', data_inicio=date(2024, 7, 4))
        base.update(kw)
        db.session.add(FapCalculoItem(**base))

    item('B91', '6505977833', cpf='12455224092', nit='12455224092',
         data_nascimento=date(1976, 5, 14), calculo_id=804, last_seen_at=datetime(2026, 9, 3))
    item('CAT', '20230000099', cpf='98765432100', data_acidente=date(2023, 4, 5), calculo_id=804)
    item('B92', '6000000001', estado_atual='EXCLUIDO', calculo_id=700,
         last_seen_at=datetime(2026, 9, 3))
    db.session.add(FapCalculoEstabelecimento(
        law_firm_id=firm.id, ano_vigencia=2026, cnpj='07718633008163', cnpj_raiz='07718633',
        calculo_atual_id=804, calculo_atual_tipo='RECALCULO_ELETRONICO_SEGUNDA_INSTANCIA',
        calculo_atual_data=date(2026, 10, 20), protocolo='10128.048333/2025-01',
        historico_json='[{"id": 804, "tipo": "RECALCULO_ELETRONICO_SEGUNDA_INSTANCIA", "data": "2026-10-20"},'
                       ' {"id": 700, "tipo": "RECALCULO_ELETRONICO_PRIMEIRA_INSTANCIA", "data": "2026-06-01"},'
                       ' {"id": 600, "tipo": "CALCULO_ORIGINAL", "data": "2026-01-10"}]'))
    report = FapContestationJudgmentReport(user_id=admin.id, law_firm_id=firm.id,
                                           original_filename='r.pdf', file_path='/dev/null')
    db.session.add(report)
    db.session.flush()
    cat = FapContestationCat(law_firm_id=firm.id, report_id=report.id,
                             cat_number='20230000099', vigencia_year='2026')
    db.session.add(cat)

    vig = FapVigenciaCnpj(law_firm_id=firm.id, employer_cnpj='07718633008163', vigencia_year='2026')
    db.session.add(vig)
    db.session.flush()
    benef = Benefit(law_firm_id=firm.id, benefit_number='6505977833',
                    fap_vigencia_cnpj_id=vig.id)
    db.session.add(benef)
    db.session.commit()
    return firm, admin, comum, benef, cat.id


def login(client, user):
    with client.session_transaction() as sess:
        sess['user_id'] = user.id
        sess['law_firm_id'] = user.law_firm_id
        sess['user_role'] = user.role
        sess['user_module_permissions'] = user.get_module_permissions()


def main():
    with app.app_context():
        firm, admin, comum, benef, cat_id = setup()
        try:
            client = app.test_client()
            login(client, admin)

            print('test_tela_abre')
            r = client.get(URL)
            html = r.get_data(as_text=True)
            check('200', r.status_code == 200, str(r.status_code))
            check('título', 'Benefícios do cálculo FAP' in html)
            check('3 itens na tela', '6505977833' in html and '20230000099' in html
                  and '6000000001' in html)

            print('test_vigencia_invalida_ignorada')
            r = client.get(URL + '?vigencia=abc')
            check('vigência não numérica não quebra', r.status_code == 200, str(r.status_code))

            print('test_filtro_tipo_cat')
            html = client.get(URL + '?tipo=CAT').get_data(as_text=True)
            check('mostra a CAT', '20230000099' in html)
            check('esconde os benefícios', '6505977833' not in html and '6000000001' not in html)

            print('test_cpf_inteiro')
            html = client.get(URL + '?q=12455224092').get_data(as_text=True)
            check('CPF formatado inteiro', formatar_cpf('12455224092') in html)
            check('CPF não mascarado', '***' not in html)

            print('test_link_contestado')
            html = client.get(URL + '?tipo=B91').get_data(as_text=True)
            check('link para o benefício da Central', f'/disputes-center/{benef.id}/edit' in html)

            print('test_link_cat_contestada')
            html = client.get(URL + '?tipo=CAT').get_data(as_text=True)
            check('link para a CAT da Central', f'/disputes-center/cats/{cat_id}/edit' in html)

            print('test_detalhe_do_calculo')
            html = client.get(URL + '?tipo=B91').get_data(as_text=True)
            check('protocolo', '10128.048333/2025-01' in html)
            check('tipo e data do cálculo', 'Recálculo 2ª instância de 20/10/2026' in html)
            check('histórico do estabelecimento', 'Cálculo original (10/01/2026) → '
                  'Recálculo 1ª instância (01/06/2026) → Recálculo 2ª instância (20/10/2026)' in html)

            print('test_ausente_no_calculo_atual')
            html = client.get(URL + '?tipo=B92').get_data(as_text=True)
            check('selo de ausente com data', 'Ausente no cálculo atual' in html
                  and 'visto em 03/09/2026' in html)
            check('sem selo Excluído', 'text-bg-danger">Excluído' not in html)
            check('item do cálculo atual sem selo', 'Ausente no cálculo atual' not in
                  client.get(URL + '?tipo=B91').get_data(as_text=True))

            print('test_sem_modulo_fap_panel')
            outro = app.test_client()
            login(outro, comum)
            r = outro.get(URL)
            check('sem fap_panel não acessa', r.status_code in (302, 403)
                  and '6505977833' not in r.get_data(as_text=True), str(r.status_code))
        finally:
            db.session.rollback()
            cleanup(db.session.get(LawFirm, firm.id))

    if _falhas:
        print(f'\n❌ {len(_falhas)} falha(s): {_falhas}')
        sys.exit(1)
    print('\n✅ Tudo verde')


if __name__ == '__main__':
    main()
