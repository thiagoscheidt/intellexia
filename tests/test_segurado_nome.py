#!/usr/bin/env python3
"""
"Revelar nome" do segurado: consulta de nome por CPF, guardada por escritório.

O FAP não informa nome. O botão das telas de Benefícios (Central e cálculo FAP)
consulta o fornecedor uma vez por CPF e guarda só o nome em segurado_nomes; as
telas e o MCP reaproveitam. Sem rede: o GET do fornecedor é um dublê. CPFs
fictícios (DV válido), escritórios descartáveis removidos no fim.

    uv run python tests/test_segurado_nome.py
"""

import os
import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import (
    db, Benefit, FapCalculoItem, LawFirm, SeguradoNome, User, UserPageVisit,
)
from app.services import cpf_nome_client, segurado_nome_service as svc

CNPJ_A, CNPJ_B = '00000000000799', '00000000000899'
CPF_BEN = '12345678909'        # benefício da Central
CPF_CALC = '11144477735'       # item do cálculo FAP
CPF_SUMIDO = '52998224725'     # não encontrado no fornecedor
CPF_ALHEIO = '39053344705'     # não está na base do escritório
CPF_MCP_1 = '86288366757'      # para o limite diário do MCP
CPF_MCP_2 = '71428793860'
CPF_MCP_3 = '26541728054'

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


class Resp:
    def __init__(self, status, corpo):
        self.status_code, self._corpo = status, corpo
        self.ok = 200 <= status < 300

    def json(self):
        return self._corpo


chamadas = []
FORNECEDOR = {
    CPF_BEN: Resp(200, {'success': True, 'data': {
        'CPF': CPF_BEN, 'NOME': 'MARIA DE TESTE', 'SEXO': 'Feminino',
        'NASC': '01/01/1990', 'NOME_MAE': 'MAE DE TESTE'}}),
    CPF_CALC: Resp(200, {'success': True, 'data': {
        'CPF': CPF_CALC, 'NOME': 'JOAO DE TESTE', 'SEXO': 'Masculino',
        'NASC': '05/05/1985', 'NOME_MAE': 'OUTRA MAE'}}),
    CPF_SUMIDO: Resp(404, {'error': 'CPF não encontrado', 'code': 'CPF_NOT_FOUND'}),
    **{c: Resp(200, {'success': True, 'data': {'CPF': c, 'NOME': f'PESSOA {c[:3]}', 'NASC': '01/01/1980'}})
       for c in (CPF_MCP_1, CPF_MCP_2, CPF_MCP_3)},
}


def falso_get(url, headers=None, timeout=None):
    cpf = url.rsplit('/', 1)[-1]
    chamadas.append(cpf)
    if cpf == 'cota':
        return Resp(401, {'code': 'QUOTA_EXCEEDED'})
    return FORNECEDOR[cpf]


def _setup():
    for cnpj in (CNPJ_A, CNPJ_B):
        f = LawFirm.query.filter_by(cnpj=cnpj).first()
        if f:
            _cleanup(f)
    a = LawFirm(name='Escritório Teste Nome A', cnpj=CNPJ_A)
    b = LawFirm(name='Escritório Teste Nome B', cnpj=CNPJ_B)
    db.session.add_all([a, b])
    db.session.flush()
    db.session.add_all([
        Benefit(law_firm_id=a.id, benefit_number='9922000001', benefit_type='B91',
                insured_cpf='123.456.789-09', insured_date_of_birth=date(1990, 1, 1)),
        Benefit(law_firm_id=a.id, benefit_number='9922000002', benefit_type='B91',
                insured_cpf=CPF_SUMIDO, insured_date_of_birth=date(1970, 1, 1)),
        FapCalculoItem(law_firm_id=a.id, ano_vigencia=2026, cnpj='07718633008163',
                       cnpj_raiz='07718633', tipo='B91', identificador='9922000003',
                       cpf=CPF_CALC, data_nascimento=date(1985, 6, 6)),  # nasc. diverge
        Benefit(law_firm_id=b.id, benefit_number='9922000004', benefit_type='B91',
                insured_cpf=CPF_BEN, insured_date_of_birth=date(1990, 1, 1)),
        *[Benefit(law_firm_id=a.id, benefit_number=f'99220001{i}', benefit_type='B91',
                  insured_cpf=c, insured_date_of_birth=date(1980, 1, 1))
          for i, c in enumerate((CPF_MCP_1, CPF_MCP_2, CPF_MCP_3))],
    ])
    user = User(law_firm_id=a.id, name='teste', email='user__test_nome@example.com', role='admin', is_active=True)
    user.set_password('x')
    db.session.add(user)
    db.session.commit()
    return a, b, user


def _cleanup(firm):
    SeguradoNome.query.filter_by(law_firm_id=firm.id).delete()
    for u in User.query.filter_by(law_firm_id=firm.id).all():
        UserPageVisit.query.filter_by(user_id=u.id).delete()
        db.session.delete(u)
    FapCalculoItem.query.filter_by(law_firm_id=firm.id).delete()
    Benefit.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def test_cliente():
    print('\n1. Cliente: só nome e nascimento saem dele')
    r = cpf_nome_client.consultar_nome(CPF_BEN)
    check('encontrado', r.encontrado and r.nome == 'MARIA DE TESTE' and r.nascimento == date(1990, 1, 1))
    check('nome da mãe e sexo não existem no resultado',
          not hasattr(r, 'nome_mae') and not hasattr(r, 'sexo') and set(vars(r)) == {'encontrado', 'nome', 'nascimento'})
    check('404 = não encontrado', cpf_nome_client.consultar_nome(CPF_SUMIDO).encontrado is False)
    try:
        cpf_nome_client.consultar_nome('cota')
        check('cota esgotada vira indisponível', False)
    except cpf_nome_client.CpfNomeIndisponivel as e:
        check('cota esgotada vira indisponível, com mensagem para a tela', 'cota' in e.mensagem, e.mensagem)


def test_servico(a, b, user):
    print('\n2. Serviço: uma consulta por CPF, só CPF do escritório')
    chamadas.clear()
    r = svc.revelar(a.id, '123.456.789-09', user.id)
    check('revela e guarda', r['nome'] == 'MARIA DE TESTE' and not r['ja_revelado'])
    reg = SeguradoNome.query.filter_by(law_firm_id=a.id, cpf=CPF_BEN).one()
    check('guarda quem consultou e a fonte', reg.consultado_por_id == user.id and reg.fonte == 'cpf_brasil')
    r = svc.revelar(a.id, CPF_BEN, user.id)
    check('segunda vez não consulta de novo', r['ja_revelado'] and chamadas == [CPF_BEN], str(chamadas))

    r = svc.revelar(a.id, CPF_SUMIDO, user.id)
    svc.revelar(a.id, CPF_SUMIDO, user.id)
    check('não encontrado também é guardado (paga uma vez)',
          r['status'] == 'nao_encontrado' and chamadas.count(CPF_SUMIDO) == 1)

    r = svc.revelar(a.id, CPF_CALC, user.id)
    check('CPF do cálculo FAP também vale', r['nome'] == 'JOAO DE TESTE')
    check('nascimento diferente do FAP fica marcado', r['nascimento_diverge'] is True)

    for cpf, esperado in ((CPF_ALHEIO, 404), ('12345678900', 400)):
        try:
            svc.revelar(a.id, cpf, user.id)
            check(f'{cpf} recusado', False)
        except svc.NomeNaoRevelavel as e:
            check(f'{"CPF fora da base" if esperado == 404 else "DV inválido"} recusado sem consultar',
                  e.status_http == esperado and cpf not in chamadas)

    check('outro escritório não vê o nome revelado', svc.nome_conhecido(b.id, CPF_BEN) is None)
    check('busca por nome acha o CPF', svc.cpfs_por_nome(a.id, 'maria') == [CPF_BEN])


def test_falha_nao_grava(a, user):
    print('\n3. Falha do fornecedor não é guardada')
    antigo = FORNECEDOR[CPF_BEN]
    SeguradoNome.query.filter_by(law_firm_id=a.id, cpf=CPF_BEN).delete()
    db.session.commit()
    FORNECEDOR[CPF_BEN] = Resp(401, {'code': 'TOKEN_EXPIRED'})
    corpo, status = svc.resposta_revelar(a.id, CPF_BEN, user.id)
    FORNECEDOR[CPF_BEN] = antigo
    check('token vencido: 503 com mensagem', status == 503 and 'token' in corpo['message'].lower(), str(corpo))
    check('nada gravado', SeguradoNome.query.filter_by(law_firm_id=a.id, cpf=CPF_BEN).count() == 0)
    svc.revelar(a.id, CPF_BEN, user.id)


def test_telas_e_mcp(a, user):
    print('\n4. Telas e MCP')
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(user_id=user.id, law_firm_id=a.id, user_role='admin',
                 user_module_permissions=user.get_module_permissions())

    r = c.post('/disputes-center/api/segurado/revelar-nome', json={'cpf': CPF_BEN})
    check('rota da Central', r.status_code == 200 and r.get_json()['nome'] == 'MARIA DE TESTE')
    r = c.post('/fap-panel/calculo/segurado/revelar-nome', json={'cpf': CPF_ALHEIO})
    check('rota do cálculo recusa CPF de fora', r.status_code == 404)

    linhas = c.get('/disputes-center/api/list?draw=1&start=0&length=50&quick_vigencia=__all__').get_json()['data']
    por_nb = {l['benefit_number']: l for l in linhas}
    check('lista da Central traz o nome revelado',
          (por_nb['9922000001'].get('nome_revelado') or {}).get('nome') == 'MARIA DE TESTE')
    check('… e não oferece o botão de novo', por_nb['9922000001']['pode_revelar_nome'] is False)

    html = c.get('/fap-panel/calculo/').get_data(as_text=True)
    check('tela do cálculo traz o nome para a célula', 'JOAO DE TESTE' in html and 'data-segurado-nome' in html)

    from mcp_server.tools.fap import list_fap_benefits_handler
    from mcp_server.tools.insights import buscar_por_segurado_handler
    from mcp_server.tools.fap_calculo import listar_beneficios_calculo_fap_handler

    itens = list_fap_benefits_handler(a.id, segurado='maria', limit=50)['itens']
    check('MCP: busca por nome revelado acha o benefício',
          [i['numero_beneficio'] for i in itens] == ['9922000001'], str(itens)[:200])
    check('MCP: segurado_nome preenchido', itens and itens[0]['segurado_nome'] == 'MARIA DE TESTE')
    r = buscar_por_segurado_handler(a.id, ['fap_panel'], nome='maria')
    check('MCP: buscar_por_segurado por nome', r['beneficios']['total'] == 1)
    calc = listar_beneficios_calculo_fap_handler(a.id)['itens']
    check('MCP: cálculo FAP traz segurado_nome', calc and calc[0]['segurado_nome'] == 'JOAO DE TESTE')


def test_mcp_revelar(a, user):
    print('\n5. MCP revelar_nome_segurado: limite diário por usuário')
    from fastmcp.exceptions import ToolError
    from mcp_server.tools.fap import revelar_nome_segurado_handler

    outro = User(law_firm_id=a.id, name='outro', email='outro__test_nome@example.com', role='lawyer', is_active=True)
    outro.set_password('x')
    db.session.add(outro)
    db.session.commit()
    os.environ['CPF_NOME_LIMITE_DIARIO_MCP'] = '2'
    try:
        r = revelar_nome_segurado_handler(a.id, user.id, CPF_BEN)
        check('nome já salvo (pela tela) volta sem gastar', r['ja_estava_salvo'] and r['consultas_restantes_hoje'] == 2,
              str(r))
        r = revelar_nome_segurado_handler(a.id, user.id, CPF_MCP_1)
        check('1ª consulta pelo MCP', r['nome'] == 'PESSOA 862' and r['consultas_restantes_hoje'] == 1, str(r))
        check('origem gravada como mcp',
              SeguradoNome.query.filter_by(law_firm_id=a.id, cpf=CPF_MCP_1).one().origem == 'mcp')
        revelar_nome_segurado_handler(a.id, user.id, CPF_MCP_2)
        try:
            revelar_nome_segurado_handler(a.id, user.id, CPF_MCP_3)
            check('3ª consulta passa do limite', False)
        except ToolError as e:
            check('3ª consulta passa do limite e explica', 'Limite diário de 2' in str(e), str(e))
        check('… sem chamar o fornecedor', CPF_MCP_3 not in chamadas)
        r = revelar_nome_segurado_handler(a.id, user.id, CPF_MCP_1)
        check('o que já foi revelado continua saindo depois do limite', r['ja_estava_salvo'])
        r = revelar_nome_segurado_handler(a.id, outro.id, CPF_MCP_3)
        check('outro usuário tem o próprio limite', r['nome'] == 'PESSOA 265')
        corpo, status = svc.resposta_revelar(a.id, CPF_SUMIDO, user.id)
        check('tela não entra no limite do MCP', status == 200)
        try:
            revelar_nome_segurado_handler(a.id, user.id, CPF_ALHEIO)
            check('CPF de fora recusado', False)
        except ToolError as e:
            check('CPF de fora recusado', 'não está entre os segurados' in str(e))
    finally:
        os.environ.pop('CPF_NOME_LIMITE_DIARIO_MCP', None)


def main() -> int:
    os.environ['CPF_NOME_API_KEY'] = 'teste'
    original = requests.get
    cpf_nome_client.requests.get = falso_get
    try:
        test_cliente()
        with app.app_context(), app.test_request_context():
            a, b, user = _setup()
            try:
                test_servico(a, b, user)
                test_falha_nao_grava(a, user)
                test_telas_e_mcp(a, user)
                test_mcp_revelar(a, user)
            finally:
                db.session.rollback()
                _cleanup(a)
                _cleanup(b)
    finally:
        cpf_nome_client.requests.get = original
        os.environ.pop('CPF_NOME_API_KEY', None)

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
