#!/usr/bin/env python3
"""
Modelos das tabelas do cálculo FAP (estabelecimentos e itens da Consulta do FAP).

Escritório descartável, criado e removido no fim.

    uv run python tests/test_fap_calculo_modelos.py
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.exc import IntegrityError

from main import app
from app.models import db, LawFirm, FapCalculoEstabelecimento, FapCalculoItem

TEST_CNPJ = '00000000000899'
ESTAB = '07718633008163'

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _cleanup(firm):
    db.session.rollback()
    FapCalculoItem.query.filter_by(law_firm_id=firm.id).delete()
    FapCalculoEstabelecimento.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def _item(firm_id, ano):
    return FapCalculoItem(
        law_firm_id=firm_id, ano_vigencia=ano, cnpj=ESTAB, cnpj_raiz=ESTAB[:8],
        tipo='B91', identificador='6505977833', nit='12455224092',
        cpf='01234567890', data_nascimento=date(1976, 5, 14),
        valor_mensal=Decimal('1598.72'), meses_contabilizacao=Decimal('1.2345'),
        bloqueio=False, calculo_id=804038558,
    )


def test_cria_e_unique():
    print('\n1. Criar e unicidade')
    firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
    if firm:
        _cleanup(firm)
    firm = LawFirm(name='Escritório Teste Cálculo FAP', cnpj=TEST_CNPJ)
    db.session.add(firm)
    db.session.commit()
    try:
        db.session.add(FapCalculoEstabelecimento(
            law_firm_id=firm.id, ano_vigencia=2026, cnpj=ESTAB, cnpj_raiz=ESTAB[:8],
            calculo_atual_id=804038558, calculo_atual_tipo='RECALCULO_ELETRONICO_SEGUNDA_INSTANCIA',
            calculo_atual_data=date(2026, 10, 20), tem_itens=True, situacao='ok',
        ))
        db.session.add(_item(firm.id, 2026))
        db.session.commit()
        check('estabelecimento e item gravados',
              FapCalculoItem.query.filter_by(law_firm_id=firm.id).count() == 1)

        db.session.add(_item(firm.id, 2026))
        try:
            db.session.commit()
            check('chave repetida dá IntegrityError', False)
        except IntegrityError:
            db.session.rollback()
            check('chave repetida dá IntegrityError', True)

        db.session.add(_item(firm.id, 2025))
        db.session.commit()
        check('mesmo NB em outro ano grava',
              FapCalculoItem.query.filter_by(law_firm_id=firm.id).count() == 2)

        db.session.add(FapCalculoEstabelecimento(
            law_firm_id=firm.id, ano_vigencia=2026, cnpj=ESTAB, cnpj_raiz=ESTAB[:8]))
        try:
            db.session.commit()
            check('estabelecimento repetido dá IntegrityError', False)
        except IntegrityError:
            db.session.rollback()
            check('estabelecimento repetido dá IntegrityError', True)
    finally:
        _cleanup(firm)


def main() -> int:
    with app.app_context():
        test_cria_e_unique()

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
