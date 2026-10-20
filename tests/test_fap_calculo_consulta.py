#!/usr/bin/env python3
"""
Consulta dos itens do cálculo FAP (fap_calculo_query_service).

Escritórios descartáveis, criados e removidos no fim.

    uv run python tests/test_fap_calculo_consulta.py
"""

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import (
    db, LawFirm, User, Benefit, FapVigenciaCnpj, FapContestationCat,
    FapContestationJudgmentReport, FapCalculoItem, FapCompany,
    FapCalculoEstabelecimento,
)
from app.services import fap_calculo_query_service as svc

CNPJ_A = '00000000001299'
CNPJ_B = '00000000001399'
EMPRESA = '12345678000199'
RAIZ = '12345678'

_falhas = []


def check(nome, condicao, detalhe=''):
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _item(firm_id, ano, tipo, ident, **kw):
    return FapCalculoItem(law_firm_id=firm_id, ano_vigencia=ano, cnpj=EMPRESA,
                          cnpj_raiz=RAIZ, tipo=tipo, identificador=ident,
                          estado_atual=kw.pop('estado_atual', 'ORIGINAL'), **kw)


def _firm(nome, cnpj, email):
    firm = LawFirm.query.filter_by(cnpj=cnpj).first()
    if firm:
        cleanup(firm)
    firm = LawFirm(name=nome, cnpj=cnpj)
    db.session.add(firm)
    db.session.flush()
    user = User(law_firm_id=firm.id, name='t', email=email, role='admin', is_active=True)
    user.set_password('x')
    db.session.add(user)
    db.session.flush()
    return firm, user


def setup():
    firm, user = _firm('Teste Consulta Cálculo A', CNPJ_A, 'user__consulta_calc_a@example.com')
    outra, _ = _firm('Teste Consulta Cálculo B', CNPJ_B, 'user__consulta_calc_b@example.com')
    report = FapContestationJudgmentReport(user_id=user.id, law_firm_id=firm.id,
                                           original_filename='r.pdf', file_path='/dev/null')
    db.session.add(report)
    vig25 = FapVigenciaCnpj(law_firm_id=firm.id, employer_cnpj=EMPRESA, vigencia_year='2025')
    db.session.add(vig25)
    db.session.flush()
    db.session.add_all([
        FapCompany(law_firm_id=firm.id, cnpj=RAIZ, nome='Empresa Teste SA', synced_at=datetime.now()),
        # NB contestado só na vigência 2025
        Benefit(law_firm_id=firm.id, benefit_number='6111111111', benefit_type='B91',
                fap_vigencia_cnpj_id=vig25.id),
        FapContestationCat(law_firm_id=firm.id, report_id=report.id, cat_number='2025000001',
                           vigencia_year='2025'),
        _item(firm.id, 2025, 'B91', '6111111111', cpf='01234567890', nit='12455224092'),
        _item(firm.id, 2026, 'B91', '6111111111'),
        _item(firm.id, 2025, 'CAT', '2025000001'),
        _item(firm.id, 2026, 'CAT', '2025000001'),
        _item(firm.id, 2026, 'B94', '6222222222', estado_atual='EXCLUIDO'),
        # mesmo NB no outro escritório
        _item(outra.id, 2025, 'B91', '6111111111'),
    ])
    db.session.commit()
    return firm, outra


def cleanup(firm):
    FapCalculoItem.query.filter_by(law_firm_id=firm.id).delete()
    FapCompany.query.filter_by(law_firm_id=firm.id).delete()
    FapCalculoEstabelecimento.query.filter_by(law_firm_id=firm.id).delete()
    FapContestationCat.query.filter_by(law_firm_id=firm.id).delete()
    Benefit.query.filter_by(law_firm_id=firm.id).delete()
    FapVigenciaCnpj.query.filter_by(law_firm_id=firm.id).delete()
    FapContestationJudgmentReport.query.filter_by(law_firm_id=firm.id).delete()
    User.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def test_filtro_tipo_e_cat(f):
    print('\n1. filtro por tipo')
    r = svc.filtrar(f.id, tipos=['CAT']).all()
    check('só CATs', len(r) == 2 and all(i.tipo == 'CAT' for i in r), str(len(r)))
    r = svc.filtrar(f.id, tipos=['B91', 'B94']).all()
    check('B91 e B94', len(r) == 3, str(len(r)))


def test_contestado_por_vigencia(f):
    print('\n2. contestado por vigência')
    itens, _ = svc.pagina(svc.filtrar(f.id, tipos=['B91']), 1)
    por_ano = {i['ano_vigencia']: i for i in itens}
    check('NB contestado em 2025', por_ano[2025]['contestado'] is True)
    check('mesmo NB não contestado em 2026', por_ano[2026]['contestado'] is False)
    check('link da Central só onde contestado',
          por_ano[2025]['beneficio_central_id'] is not None
          and por_ano[2026]['beneficio_central_id'] is None)
    check('nome da empresa', por_ano[2025]['empresa_nome'] == 'Empresa Teste SA')
    nao = svc.filtrar(f.id, vigencia=2026, contestado=False).all()
    check('contestado=False em 2026 traz o NB', any(i.identificador == '6111111111' for i in nao))
    sim = svc.filtrar(f.id, vigencia=2026, contestado=True).all()
    check('contestado=True em 2026 vazio', sim == [], str(sim))
    cats, _ = svc.pagina(svc.filtrar(f.id, tipos=['CAT']), 1)
    c = {i['ano_vigencia']: i for i in cats}
    check('CAT por número + vigência', c[2025]['contestado'] and not c[2026]['contestado'])
    check('CAT sem beneficio_central_id', c[2025]['beneficio_central_id'] is None)


def test_identificador_cpf_com_pontuacao(f):
    print('\n3. identificador')
    r = svc.filtrar(f.id, identificador='012.345.678-90').all()
    check('CPF formatado', len(r) == 1 and r[0].cpf == '01234567890', str(r))
    check('CPF sem zero à esquerda', len(svc.filtrar(f.id, identificador='1234567890').all()) == 1)
    check('NIT', len(svc.filtrar(f.id, identificador='12455224092').all()) == 1)
    check('NB', len(svc.filtrar(f.id, identificador='6111111111').all()) == 2)


def test_situacao_excluido(f):
    print('\n4. situação')
    check('excluido', [i.identificador for i in svc.filtrar(f.id, situacao='excluido').all()] == ['6222222222'])
    check('conta', len(svc.filtrar(f.id, situacao='conta').all()) == 4)


def test_contadores_batem_com_filtro(f):
    print('\n5. contadores')
    q = svc.filtrar(f.id)
    c = svc.contadores(q)
    check('total', c['total'] == q.count() == 5, str(c))
    check('por tipo', c['por_tipo'] == {'B91': 2, 'B92': 0, 'B93': 0, 'B94': 1, 'CAT': 2}, str(c['por_tipo']))
    check('excluídos', c['excluidos'] == 1)
    check('não contestados', c['nao_contestados'] == svc.filtrar(f.id, contestado=False).count() == 3,
          str(c['nao_contestados']))
    c26 = svc.contadores(svc.filtrar(f.id, vigencia=2026))
    cr = c['cruzamento']
    soma = sum(v['contestado'] + v['nao_contestado'] for t in cr.values() for v in t.values())
    check('cruzamento soma o total', soma == c['total'], str(cr))
    check('cruzamento: B91 conta 1 contestado + 1 não', cr['B91']['conta'] == {'contestado': 1, 'nao_contestado': 1}, str(cr['B91']))
    check('cruzamento: B94 excluído não contestado', cr['B94']['excluido'] == {'contestado': 0, 'nao_contestado': 1})
    check('cruzamento bate com nao_contestados',
          sum(v['nao_contestado'] for t in cr.values() for v in t.values()) == c['nao_contestados'])
    check('contadores respeitam o filtro', c26['total'] == 3 and c26['nao_contestados'] == 3, str(c26))


def test_tenant(f, outra):
    print('\n6. tenant')
    check('A só vê os seus', svc.filtrar(f.id, vigencia=2025, tipos=['B91']).count() == 1)
    itens, total = svc.pagina(svc.filtrar(outra.id), 1)
    check('B vê o seu item, sem contestado nem nome',
          total == 1 and not itens[0]['contestado'] and itens[0]['empresa_nome'] is None, str(itens))


def test_sem_escritorio_e_filtros_invalidos(f):
    print('\n7. escritório explícito e filtros inutilizáveis')
    bruta = FapCalculoItem.query.filter_by(law_firm_id=f.id)
    for nome, fn in (('contadores', lambda: svc.contadores(bruta)),
                     ('pagina', lambda: svc.pagina(bruta, 1))):
        try:
            fn()
            check(f'{nome} sem escritório levanta', False)
        except ValueError:
            check(f'{nome} sem escritório levanta', True)
    c = svc.contadores(bruta, law_firm_id=f.id)
    itens, total = svc.pagina(bruta, 1, 500, law_firm_id=f.id)
    check('law_firm_id explícito funciona', c['total'] == 5 and total == 5 and len(itens) == 5)
    check('contestado correto com escritório explícito', sum(i['contestado'] for i in itens) == 2)
    for rotulo, kw in (('identificador sem dígitos', {'identificador': 'abc'}),
                       ('cnpj sem dígitos', {'cnpj': '--'}),
                       ('situação desconhecida', {'situacao': 'xyz'}),
                       ('tipo desconhecido', {'tipos': ['B99']})):
        check(f'{rotulo} filtra para vazio', svc.filtrar(f.id, **kw).count() == 0)


def test_raiz_no_filtro_cnpj_e_dados_do_estabelecimento(f):
    print('\n8. cnpj com raiz, cálculo de origem e item ausente')
    r = svc.filtrar(f.id, cnpj=RAIZ).all()
    check('raiz de 8 dígitos acha os estabelecimentos', len(r) == 5, str(len(r)))
    check('raiz com pontuação', len(svc.filtrar(f.id, cnpj='12.345.678').all()) == 5)
    check('14 dígitos continua exato', len(svc.filtrar(f.id, cnpj=EMPRESA).all()) == 5)
    check('outro estabelecimento não acha', svc.filtrar(f.id, cnpj='12345678000270').count() == 0)

    db.session.add(FapCalculoEstabelecimento(
        law_firm_id=f.id, ano_vigencia=2025, cnpj=EMPRESA, cnpj_raiz=RAIZ,
        calculo_atual_id=500, calculo_atual_tipo='RECALCULO_ELETRONICO_PRIMEIRA_INSTANCIA',
        calculo_atual_data=date(2025, 10, 1), protocolo='PROT-123',
        historico_json='[{"id": 500, "tipo": "RECALCULO_ELETRONICO_PRIMEIRA_INSTANCIA", "data": "2025-10-01"},'
                       ' {"id": 400, "tipo": "CALCULO_ORIGINAL", "data": "2025-09-01"}]'))
    FapCalculoItem.query.filter_by(law_firm_id=f.id, ano_vigencia=2025, tipo='B91').update(
        {'calculo_id': 400})
    FapCalculoItem.query.filter_by(law_firm_id=f.id, ano_vigencia=2025, tipo='CAT').update(
        {'calculo_id': 500})
    db.session.commit()
    itens, _ = svc.pagina(svc.filtrar(f.id, vigencia=2025), 1)
    por = {i['tipo']: i for i in itens}
    cat, b91 = por['CAT'], por['B91']
    check('protocolo exposto', cat['protocolo'] == 'PROT-123')
    check('tipo e data do cálculo', cat['calculo_tipo'] == 'Recálculo 1ª instância'
          and cat['calculo_data'] == date(2025, 10, 1), str(cat['calculo_tipo']))
    check('histórico com rótulos', [h['rotulo'] for h in cat['historico']]
          == ['Recálculo 1ª instância', 'Cálculo original'], str(cat['historico']))
    check('item do cálculo atual não é ausente', cat['ausente_no_calculo_atual'] is False)
    check('item de cálculo antigo é ausente', b91['ausente_no_calculo_atual'] is True)
    check('CAT contestada traz o id da Central', cat['cat_central_id'] is not None
          and b91['cat_central_id'] is None, str(cat['cat_central_id']))
    itens26, _ = svc.pagina(svc.filtrar(f.id, vigencia=2026), 1)
    check('sem estabelecimento gravado: sem ausência', all(
        not i['ausente_no_calculo_atual'] and i['historico'] == [] for i in itens26))


def main() -> int:
    with app.app_context():
        f, outra = setup()
        try:
            test_filtro_tipo_e_cat(f)
            test_contestado_por_vigencia(f)
            test_identificador_cpf_com_pontuacao(f)
            test_situacao_excluido(f)
            test_contadores_batem_com_filtro(f)
            test_tenant(f, outra)
            test_sem_escritorio_e_filtros_invalidos(f)
            test_raiz_no_filtro_cnpj_e_dados_do_estabelecimento(f)
        finally:
            db.session.rollback()
            for firm in (f, outra):
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
