#!/usr/bin/env python3
"""
Filtro de benefícios por status na 1ª e na 2ª instância no MCP — E03 da
Remessa R09 ("Perguntas que cruzam dois filtros demoram minutos").

"B91 da Vale indeferidos na 1ª instância" obrigava o Claude a ler os 759 B91
página por página: listar_beneficios_fap não filtrava por instância e o
resumo_fap contava tipo e status separados. Agora há os dois filtros e o
cruzamento tipo × status, com a mesma normalização e a mesma regra de
"pendente" dos contadores da tela.

Escritório descartável, criado e removido no fim.

    uv run python tests/test_mcp_fap_status_instancia.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp.exceptions import ToolError

from main import app
from app.models import db, LawFirm, Benefit
from mcp_server.tools.fap import (
    fap_filter_values_handler, fap_summary_handler, list_fap_benefits_handler,
    resolver_status_instancia,
)

TEST_CNPJ = '00000000000599'

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


# (tipo, 1ª instância como gravada, 2ª instância como gravada)
BENEFICIOS = [
    ('B91', 'indeferido', ''),            # 1ª indeferida, 2ª pendente
    ('B91', 'Indeferido', 'deferido'),    # grafia antiga; ganhou no recurso
    ('B91', 'rejected', 'Indeferido'),    # legado em inglês
    ('B91', 'Deferido', ''),              # 2ª não se aplica
    ('B91', 'Em análise', ''),            # 2ª não se aplica
    ('B91', '', ''),                      # sem decisão
    ('B94', 'indeferido', ''),
    ('B94', 'deferido', ''),
    ('B94', 'Em análise', 'indeferido'),  # a tela ignora a 2ª quando a 1ª não acabou
]


def setup():
    firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
    if firm:
        cleanup(firm)
    firm = LawFirm(name='Escritório Teste Status Instância', cnpj=TEST_CNPJ)
    db.session.add(firm)
    db.session.flush()
    for i, (tipo, s1, s2) in enumerate(BENEFICIOS):
        db.session.add(Benefit(
            law_firm_id=firm.id, benefit_number=f'99000{i:05d}', benefit_type=tipo,
            employer_cnpj='33.592.510/0001-54', first_instance_status=s1 or None,
            second_instance_status=s2 or None,
        ))
    db.session.commit()
    return firm


def cleanup(firm):
    Benefit.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def test_resolver():
    print('\n1. Texto livre → valor do filtro')
    casos = {
        'indeferido': 'indeferido', 'Indeferidos': 'indeferido', 'rejected': 'indeferido',
        'deferido': 'deferido', 'DEFERIDOS': 'deferido', 'approved': 'deferido',
        'em análise': 'em_analise', 'em_analise': 'em_analise', 'in_review': 'em_analise',
        'pendente': 'pendente', 'aguardando': 'pendente',
    }
    for entrada, esperado in casos.items():
        got = resolver_status_instancia(entrada, 'status_1a_instancia')
        check(f'"{entrada}" → {esperado}', got == esperado, got)
    try:
        resolver_status_instancia('talvez', 'status_1a_instancia')
        check('valor desconhecido vira ToolError', False)
    except ToolError as e:
        check('valor desconhecido vira ToolError com os valores aceitos',
              'deferido, indeferido, em_analise ou pendente' in str(e), str(e))


def _total(firm, **kw):
    return list_fap_benefits_handler(firm.id, limit=200, **kw)['total_encontrado']


def test_listagem(firm):
    print('\n2. listar_beneficios_fap filtra por instância numa chamada')
    check('B91 indeferidos na 1ª (todas as grafias): 3',
          _total(firm, benefit_type='B91', status_1a_instancia='indeferidos') == 3,
          str(_total(firm, benefit_type='B91', status_1a_instancia='indeferidos')))
    check('deferidos na 1ª: 2', _total(firm, status_1a_instancia='deferido') == 2)
    check('em análise na 1ª: 2', _total(firm, status_1a_instancia='em análise') == 2)
    check('pendentes na 1ª: 1', _total(firm, status_1a_instancia='pendente') == 1)
    check('pendentes na 2ª: só quem pode recorrer (3)',
          _total(firm, status_2a_instancia='pendente') == 3,
          str(_total(firm, status_2a_instancia='pendente')))
    check('B91 indeferido na 1ª e deferido na 2ª: 1',
          _total(firm, benefit_type='B91', status_1a_instancia='indeferido',
                 status_2a_instancia='deferido') == 1)
    itens = list_fap_benefits_handler(firm.id, status_1a_instancia='indeferido', limit=200)['itens']
    check('itens trazem o status por instância', all('status_primeira_instancia' in i for i in itens))
    check('itens trazem os tópicos (colunas da listagem carregadas)',
          all('topicos_contestacao' in i for i in itens))


def test_resumo(firm):
    print('\n3. resumo_fap cruza tipo × status')
    r = fap_summary_handler(firm.id)
    x1 = r['beneficios']['por_tipo_x_status_primeira_instancia']
    x2 = r['beneficios']['por_tipo_x_status_segunda_instancia']
    check('B91 × 1ª', x1.get('B91') == {'indeferido': 3, 'deferido': 1, 'em_analise': 1, 'pendente': 1},
          str(x1.get('B91')))
    check('B91 × 2ª', x2.get('B91') == {'pendente': 2, 'deferido': 1, 'indeferido': 1, 'nao_se_aplica': 2},
          str(x2.get('B91')))
    check('a célula bate com a listagem filtrada',
          x1['B91']['indeferido'] == _total(firm, benefit_type='B91', status_1a_instancia='indeferido'))
    check('2ª da tela: 1ª em análise não conta como indeferido na 2ª',
          x2.get('B94') == {'pendente': 1, 'nao_se_aplica': 2}, str(x2.get('B94')))
    check('… e o filtro concorda', _total(firm, status_2a_instancia='indeferido') == 1,
          str(_total(firm, status_2a_instancia='indeferido')))
    check('2ª pendente do cruzamento bate com o filtro',
          sum(v.get('pendente', 0) for v in x2.values()) == _total(firm, status_2a_instancia='pendente'))

    r = fap_summary_handler(firm.id, tipo_beneficio='B91', status_1a_instancia='indeferido')
    check('filtros restringem o bloco de benefícios', r['beneficios']['total'] == 3,
          str(r['beneficios']['total']))
    check('filtros aparecem na resposta, com aviso sobre contestações',
          r['filtros'].get('status_1a_instancia') == 'indeferido' and 'aviso_filtros' in r)
    check('chamada posicional antiga continua funcionando',
          fap_summary_handler(firm.id, None, None, None)['beneficios']['total'] == len(BENEFICIOS))


def test_valores_de_filtro(firm):
    print('\n4. valores_de_filtro_fap lista os valores do filtro')
    v = fap_filter_values_handler(firm.id)
    check('status_instancia_filtro', v['beneficios'].get('status_instancia_filtro') ==
          ['deferido', 'indeferido', 'em_analise', 'pendente'], str(v['beneficios'].get('status_instancia_filtro')))


def main() -> int:
    test_resolver()
    with app.app_context():
        firm = setup()
        try:
            test_listagem(firm)
            test_resumo(firm)
            test_valores_de_filtro(firm)
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
