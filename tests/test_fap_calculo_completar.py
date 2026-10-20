#!/usr/bin/env python3
"""
completar_central: preenche CPF, nascimento, RMI e total pago dos benefícios da
Central a partir de fap_calculo_itens (mesma vigência, nunca CAT, só o escritório).

    uv run python tests/test_fap_calculo_completar.py
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, LawFirm, Benefit, FapVigenciaCnpj, FapCalculoItem
from app.services import fap_calculo_sync_service as sync

CNPJ_A = '00000000001099'
CNPJ_B = '00000000001199'
ESTAB = '07718633008163'
NB = '6505977833'

_falhas = []


def check(nome, condicao, detalhe=''):
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _firm(cnpj):
    f = LawFirm.query.filter_by(cnpj=cnpj).first()
    if f:
        _cleanup(f)
    f = LawFirm(name=f'Escritório Teste Completar Cálculo {cnpj}', cnpj=cnpj)
    db.session.add(f)
    db.session.flush()
    return f


def _cleanup(firm):
    Benefit.query.filter_by(law_firm_id=firm.id).delete()
    FapCalculoItem.query.filter_by(law_firm_id=firm.id).delete()
    FapVigenciaCnpj.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def _item(firm, ano, nb=NB, cnpj=ESTAB, tipo='B91', **kw):
    campos = dict(cpf='01234567890', data_nascimento=date(1976, 5, 14),
                  valor_mensal=Decimal('1598.72'), total_pago=Decimal('2991.15'))
    campos.update(kw)
    db.session.add(FapCalculoItem(law_firm_id=firm.id, ano_vigencia=ano, cnpj=cnpj, cnpj_raiz=cnpj[:8],
                                  tipo=tipo, identificador=nb, **campos))


def _benefit(firm, ano, nb=NB, **kw):
    vig = FapVigenciaCnpj.query.filter_by(law_firm_id=firm.id, employer_cnpj=ESTAB,
                                          vigencia_year=str(ano)).first()
    if not vig:
        vig = FapVigenciaCnpj(law_firm_id=firm.id, employer_cnpj=ESTAB, vigencia_year=str(ano))
        db.session.add(vig)
        db.session.flush()
    b = Benefit(law_firm_id=firm.id, benefit_number=nb, fap_vigencia_cnpj_id=vig.id, **kw)
    db.session.add(b)
    db.session.flush()
    return b


def test_preenche_vazios():
    print('\n1. Preenche vazios')
    firm = _firm(CNPJ_A)
    try:
        _item(firm, 2026)
        b = _benefit(firm, 2026)
        db.session.commit()
        res = sync.completar_central(firm.id)
        db.session.refresh(b)
        check('campos gravados', b.insured_cpf == '01234567890' and b.insured_date_of_birth == date(1976, 5, 14)
              and b.initial_monthly_benefit == Decimal('1598.72') and b.total_paid == Decimal('2991.15'))
        check('contagem', res == {'beneficios_vistos': 1, 'cpf': 1, 'nascimento': 1, 'rmi': 1, 'total_pago': 1},
              str(res))
        res2 = sync.completar_central(firm.id)
        check('idempotente', res2['cpf'] == 0 and res2['rmi'] == 0 and res2['total_pago'] == 0
              and res2['nascimento'] == 0, str(res2))
    finally:
        db.session.rollback()
        _cleanup(firm)


def test_cpf_sobrescreve_rmi_nao():
    print('\n2. CPF sobrescreve, RMI não')
    firm = _firm(CNPJ_A)
    try:
        _item(firm, 2026)
        b = _benefit(firm, 2026, insured_cpf='11111111111', initial_monthly_benefit=Decimal('999.99'))
        db.session.commit()
        sync.completar_central(firm.id)
        db.session.refresh(b)
        check('CPF trocado', b.insured_cpf == '01234567890', str(b.insured_cpf))
        check('RMI mantida', b.initial_monthly_benefit == Decimal('999.99'))
        check('total vazio preenchido', b.total_paid == Decimal('2991.15'))
    finally:
        db.session.rollback()
        _cleanup(firm)


def test_mesma_vigencia():
    print('\n3. Mesma vigência')
    firm = _firm(CNPJ_A)
    try:
        _item(firm, 2025, total_pago=Decimal('100.00'))
        _item(firm, 2026, total_pago=Decimal('2991.15'))
        b = _benefit(firm, 2026)
        db.session.commit()
        sync.completar_central(firm.id)
        db.session.refresh(b)
        check('total da vigência 2026', b.total_paid == Decimal('2991.15'), str(b.total_paid))
        res = sync.completar_central(firm.id, ano=2025)
        check('filtro por ano não toca outra vigência', res['beneficios_vistos'] == 0, str(res))
    finally:
        db.session.rollback()
        _cleanup(firm)


def test_sem_item_nao_toca():
    print('\n4. Sem item não toca')
    firm = _firm(CNPJ_A)
    try:
        _item(firm, 2026, nb='6000000001', tipo='CAT')
        _item(firm, 2025)
        b = _benefit(firm, 2026, nb='6000000001')
        b2 = _benefit(firm, 2026, nb='6999999999')
        db.session.commit()
        res = sync.completar_central(firm.id)
        db.session.refresh(b)
        db.session.refresh(b2)
        check('CAT e outra vigência não completam',
              b.insured_cpf is None and b2.insured_cpf is None and b.total_paid is None, str(res))
        check('vistos contados', res['beneficios_vistos'] == 2, str(res))
    finally:
        db.session.rollback()
        _cleanup(firm)


def test_tenant():
    print('\n5. Tenant')
    a = _firm(CNPJ_A)
    o = _firm(CNPJ_B)
    try:
        _item(o, 2026)
        b = _benefit(a, 2026)
        db.session.commit()
        sync.completar_central(a.id)
        db.session.refresh(b)
        check('item de outro escritório não completa', b.insured_cpf is None and b.total_paid is None)
    finally:
        db.session.rollback()
        _cleanup(a)
        _cleanup(o)


def main() -> int:
    with app.app_context():
        test_preenche_vazios()
        test_cpf_sobrescreve_rmi_nao()
        test_mesma_vigencia()
        test_sem_item_nao_toca()
        test_tenant()
    if _falhas:
        print(f'\n❌ {len(_falhas)} falha(s): {_falhas}')
        return 1
    print('\n✅ Tudo verde')
    return 0


if __name__ == '__main__':
    sys.exit(main())
