#!/usr/bin/env python3
"""
MCP: benefícios e CATs do cálculo FAP (fap_calculo_itens) e CPF/NIT no
buscar_por_segurado. Escritório descartável, criado e removido no fim.

    uv run python tests/test_mcp_fap_calculo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp.exceptions import ToolError

from main import app
from app.models import db, LawFirm, FapCalculoItem
from mcp_server.tools.fap_calculo import (
    listar_beneficios_calculo_fap_handler as listar,
    resumo_beneficios_calculo_fap_handler as resumo,
)
from mcp_server.tools.insights import buscar_por_segurado_handler

TEST_CNPJ = '00000000001599'
CNPJ_EMP = '11222333000181'

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _item(firm, **kw):
    base = dict(law_firm_id=firm.id, ano_vigencia=2023, cnpj=CNPJ_EMP,
                cnpj_raiz=CNPJ_EMP[:8], tipo='B91', estado_atual='ORIGINAL')
    base.update(kw)
    return FapCalculoItem(**base)


def setup():
    firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
    if firm:
        cleanup(firm)
    firm = LawFirm(name='Escritório Teste MCP Cálculo', cnpj=TEST_CNPJ)
    db.session.add(firm)
    db.session.flush()
    db.session.add_all([
        _item(firm, identificador='6111111111', nit='12345678901', cpf='01234567890'),
        _item(firm, identificador='6222222222', tipo='B94', nit='22222222222',
              cpf='98765432100', estado_atual='EXCLUIDO'),
        _item(firm, identificador='9990001', tipo='CAT', nit='12345678901', cpf='01234567890'),
    ])
    db.session.commit()
    return firm


def cleanup(firm):
    FapCalculoItem.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def main() -> int:
    with app.app_context():
        firm = setup()
        try:
            print('\n1. lista')
            r = listar(firm.id, cpf='012.345.678-90')
            ids = sorted(i['identificador'] for i in r['itens'])
            check('CPF acha só-base-nova (benefício e CAT)', ids == ['6111111111', '9990001'], str(ids))
            check('CPF vem inteiro', r['itens'][0]['cpf'] == '01234567890')
            r = listar(firm.id, cnpj=CNPJ_EMP[:8])
            check('cnpj com raiz de 8 dígitos acha', r['total_encontrado'] == 3, str(r['total_encontrado']))
            r = listar(firm.id, cnpj=CNPJ_EMP)
            check('cnpj de 14 dígitos acha', r['total_encontrado'] == 3, str(r['total_encontrado']))
            r = listar(firm.id, situacao='excluido')
            check('situacao=excluido', r['total_encontrado'] == 1)
            r = listar(firm.id, tipo='CAT', contestado=False)
            check('tipo CAT não contestado', r['total_encontrado'] == 1)
            r = listar(firm.id, limite=2, deslocamento=1)
            check('paginação por deslocamento', r['total_encontrado'] == 3 and r['retornados'] == 2
                  and not r['tem_mais'], str(r['retornados']))
            for kw in ({'tipo': 'B99'}, {'situacao': 'xx'}):
                try:
                    listar(firm.id, **kw)
                    check(f'ToolError {kw}', False)
                except ToolError as e:
                    check(f'ToolError {kw} lista aceitos', 'B91' in str(e) or 'conta' in str(e), str(e))

            print('\n2. resumo')
            s = resumo(firm.id)
            check('total', s['total'] == 3, str(s['total']))
            check('cruzamento presente', s['cruzamento']['B94']['excluido']['nao_contestado'] == 1)
            check('resumo bate com a lista', s['total'] == listar(firm.id)['total_encontrado'])
            s = resumo(firm.id, tipo='B91')
            check('resumo filtra tipo', s['total'] == 1)

            print('\n3. buscar_por_segurado')
            r = buscar_por_segurado_handler(firm.id, ['fap_panel'], cpf='01234567890')
            check('beneficios_calculo_fap com 2 itens (benefício + CAT)',
                  r['beneficios_calculo_fap']['total'] == 2, str(r.get('beneficios_calculo_fap')))
            r = buscar_por_segurado_handler(firm.id, ['fap_panel'], nit='22222222222')
            check('por NIT', r['beneficios_calculo_fap']['total'] == 1)
            r = buscar_por_segurado_handler(firm.id, ['fap_panel'], nome='maria')
            check('só nome: sem a chave', 'beneficios_calculo_fap' not in r)
        finally:
            db.session.rollback()
            cleanup(firm)

    print('\n' + '=' * 62)
    if _falhas:
        print(f'❌ {len(_falhas)} verificação(ões) falharam:')
        for n in _falhas:
            print(f'   - {n}')
        return 1
    print('✅ Tudo verde')
    return 0


if __name__ == '__main__':
    sys.exit(main())
