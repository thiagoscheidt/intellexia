#!/usr/bin/env python3
"""
Rotas de dados da API (/api/v1): mesma resposta das ferramentas MCP, parâmetros
conferidos, módulo exigido e escritório isolado.

Cada rota do registro (public_api_catalogo.ROTAS) chama o handler do MCP; aqui
a resposta da API é comparada com a do handler chamado direto. Filtro com nome
errado ou tipo inválido dá 400 (nunca a base inteira nem 500). Escritórios
descartáveis, removidos no fim.

    uv run python tests/test_api_rotas.py
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.blueprints import public_api
from app.models import (
    db, ApiToken, Benefit, FapCompany, JudicialProcess, JurisprudenceDecision, LawFirm, User,
    UserMcpCall,
)
from app.services import api_token_service
from app.services.public_api_catalogo import ROTAS, para_api
from mcp_server.tools import fap, fap_calculo, insights, jurisprudence, process_panel

CNPJS = ('00000000001423', '00000000001504')
_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _cleanup():
    for cnpj in CNPJS:
        firm = LawFirm.query.filter_by(cnpj=cnpj).first()
        if not firm:
            continue
        for modelo in (ApiToken, UserMcpCall, Benefit, FapCompany, JurisprudenceDecision, JudicialProcess):
            modelo.query.filter_by(law_firm_id=firm.id).delete()
        User.query.filter_by(law_firm_id=firm.id).delete()
        db.session.delete(firm)
    db.session.commit()


def _setup():
    _cleanup()
    a = LawFirm(name='Escritório Teste API Rotas A', cnpj=CNPJS[0])
    b = LawFirm(name='Escritório Teste API Rotas B', cnpj=CNPJS[1])
    db.session.add_all([a, b])
    db.session.flush()
    db.session.add_all([
        FapCompany(law_firm_id=a.id, cnpj='33592510', nome='EMPRESA TESTE API S.A.', synced_at=datetime.utcnow()),
        *[Benefit(law_firm_id=a.id, benefit_number=f'99310000{i}', benefit_type=t,
                  employer_cnpj='33.592.510/0001-54', employer_name='EMPRESA TESTE API S.A.',
                  insured_cpf='123.456.789-09', insured_nit=f'1234567890{i}',
                  insured_date_of_birth=date(1990, 1, 1), first_instance_status=s)
          for i, (t, s) in enumerate((('B91', 'indeferido'), ('B91', 'deferido'), ('B94', None)))],
        Benefit(law_firm_id=b.id, benefit_number='993100009', benefit_type='B91',
                employer_cnpj='11.222.333/0001-81'),
    ])
    usuarios = {}
    for papel, modulos in (('lawyer', None), ('restrito', ['api', 'dashboard']),
                           ('so_kb', ['api', 'knowledge_base'])):
        u = User(law_firm_id=a.id, name=papel, role='lawyer', is_active=True,
                 email=f'{papel}__test_api_rotas@example.com')
        u.set_password('x')
        if modulos:
            u.set_module_permissions(modulos)
        db.session.add(u)
        usuarios[papel] = u
    db.session.flush()
    db.session.add(JudicialProcess(law_firm_id=a.id, user_id=usuarios['lawyer'].id,
                                   process_number='5001234-56.2024.4.04.7000'))
    db.session.add(JurisprudenceDecision(law_firm_id=a.id, processo='5001234-56.2024.4.04.7000',
                                         processo_digits='50012345620244047000'))
    db.session.commit()
    tokens = {k: api_token_service.criar(u, 'teste rotas')[1] for k, u in usuarios.items()}
    return a, b, usuarios, tokens


def _h(texto):
    return {'Authorization': f'Bearer {texto}'}


def _json(valor):
    # A API devolve o mesmo do handler, sem os textos escritos para a IA (dica).
    return json.loads(app.json.dumps(para_api(valor)))


def test_paridade(c, a, token):
    print('\n1. Mesma resposta do handler do MCP')
    casos = [
        ('/api/v1/fap/beneficios?limite=2&tipo_beneficio=B91',
         lambda: fap.list_fap_benefits_handler(a.id, None, None, None, 'B91', None, None, None, None, None,
                                               None, None, 2, 0)),
        ('/api/v1/fap/beneficios?status_1a_instancia=indeferido',
         lambda: fap.list_fap_benefits_handler(a.id, None, None, None, None, None, None, None, None, None,
                                               None, None, 50, 0, status_1a_instancia='indeferido')),
        ('/api/v1/fap/empresas?nome=teste',
         lambda: fap.list_fap_companies_handler(a.id, 'teste', None, None, 100, 0)),
        ('/api/v1/fap/contestacoes?limite=2',
         lambda: fap.list_fap_contestacoes_handler(a.id, None, None, None, None, None, 2, 0,
                                                   app_public_url='http://localhost', protocolo=None)),
        ('/api/v1/fap/procuracoes', lambda: fap.list_fap_procuracoes_handler(a.id, None, None, 100, 0)),
        ('/api/v1/fap/resumo?tipo_beneficio=B91',
         lambda: fap.fap_summary_handler(a.id, None, None, None, tipo_beneficio='B91')),
        ('/api/v1/fap/filtros', lambda: fap.fap_filter_values_handler(a.id)),
        ('/api/v1/fap/calculo/beneficios?limite=5',
         lambda: fap_calculo.listar_beneficios_calculo_fap_handler(a.id, None, None, None, None, None, None,
                                                                   None, None, None, None, 5, 0)),
        ('/api/v1/fap/calculo/resumo',
         lambda: fap_calculo.resumo_beneficios_calculo_fap_handler(a.id, None, None, None, None, None)),
        ('/api/v1/segurados?cpf=12345678909',
         lambda: insights.buscar_por_segurado_handler(
             a.id, User.query.filter_by(email='lawyer__test_api_rotas@example.com').one().get_module_permissions(),
             None, '12345678909', None)),
    ]
    for url, handler in casos:
        r = c.get(url, headers=_h(token))
        esperado = _json(handler())
        check(f'{url.split("?")[0]} igual ao handler', r.status_code == 200 and r.get_json() == esperado,
              f'{r.status_code} {r.get_data(as_text=True)[:200]}')
    b0 = Benefit.query.filter_by(law_firm_id=a.id).order_by(Benefit.id).first()
    r = c.get(f'/api/v1/fap/beneficios/{b0.id}', headers=_h(token))
    check('detalhe do benefício igual ao handler',
          r.status_code == 200 and r.get_json() == _json(fap.get_benefit_detail_handler(b0.id, a.id)))


def test_parametros(c, b, token):
    print('\n2. Parâmetros conferidos')
    r = c.get('/api/v1/fap/beneficios?tipo_benefico=B91', headers=_h(token))
    check('nome errado: 400 citando os válidos',
          r.status_code == 400 and 'tipo_beneficio' in r.get_json()['erro'], r.get_data(as_text=True)[:300])
    r = c.get('/api/v1/fap/beneficios?limite=abc', headers=_h(token))
    check('tipo inválido: 400 citando o parâmetro',
          r.status_code == 400 and 'limite' in r.get_json()['erro'], r.get_data(as_text=True)[:300])
    r = c.get('/api/v1/fap/calculo/beneficios?contestado=talvez', headers=_h(token))
    check('booleano inválido: 400', r.status_code == 400, str(r.status_code))
    r = c.get('/api/v1/fap/calculo/beneficios?contestado=false', headers=_h(token))
    check('booleano "false" aceito', r.status_code == 200, r.get_data(as_text=True)[:200])
    r = c.get('/api/v1/fap/beneficios/xyz', headers=_h(token))
    check('id não numérico: 404 em JSON, nunca 500', r.status_code == 404 and 'erro' in r.get_json())
    alheio = Benefit.query.filter_by(law_firm_id=b.id).first()
    r = c.get(f'/api/v1/fap/beneficios/{alheio.id}', headers=_h(token))
    check('benefício de outro escritório: 404', r.status_code == 404, str(r.status_code))
    r = c.get('/api/v1/fap/beneficios?limite=500', headers=_h(token))
    check('lista de outro escritório nunca aparece',
          all(i.get('numero_beneficio') != '993100009' for i in r.get_json()['itens']))
    r = c.get('/api/v1/segurados', headers=_h(token))
    check('/segurados sem filtro: 400', r.status_code == 400, str(r.status_code))
    r = c.get('/api/v1/fap/resumo?ano_vigencia=2023&ano_vigencia=2024', headers=_h(token))
    check('parâmetro simples repetido: 400', r.status_code == 400, str(r.status_code))


def test_modulo(c, token_restrito):
    print('\n3. Módulo exigido')
    for rota in ROTAS:
        if rota.modulo != 'fap_panel' or rota.metodo != 'GET' or '{' in rota.caminho:
            continue
        r = c.get(f'/api/v1{rota.caminho}', headers=_h(token_restrito))
        check(f'sem fap_panel: 403 em {rota.caminho}', r.status_code == 403, str(r.status_code))
    r = c.post('/api/v1/segurados/revelar-nome', json={'cpf': '12345678909'}, headers=_h(token_restrito))
    check('sem fap_panel: 403 em revelar-nome', r.status_code == 403, str(r.status_code))


def test_revelar(c, token):
    print('\n4. Revelar nome pela API')
    os.environ.pop('CPF_NOME_API_KEY', None)
    r = c.post('/api/v1/segurados/revelar-nome', json={'cpf': '12345678909'}, headers=_h(token))
    check('sem fornecedor configurado: 503 explicando',
          r.status_code == 503 and 'configurada' in r.get_json()['erro'], f'{r.status_code} {r.get_data(as_text=True)[:200]}')
    r = c.post('/api/v1/segurados/revelar-nome', json={}, headers=_h(token))
    check('sem cpf no corpo: 400', r.status_code == 400 and 'cpf' in r.get_json()['erro'])
    r = c.post('/api/v1/segurados/revelar-nome', data='nao é json', headers=_h(token))
    check('corpo que não é JSON: 400', r.status_code == 400, str(r.status_code))
    os.environ['CPF_NOME_API_KEY'] = 'teste'
    try:
        r = c.post('/api/v1/segurados/revelar-nome', json={'cpf': '39053344705'}, headers=_h(token))
        check('CPF fora da base do escritório: 404', r.status_code == 404, f'{r.status_code} {r.get_data(as_text=True)[:200]}')
        os.environ['CPF_NOME_LIMITE_DIARIO_MCP'] = '0'
        r = c.post('/api/v1/segurados/revelar-nome', json={'cpf': '12345678909'}, headers=_h(token))
        check('cota do dia esgotada: 429 com Retry-After',
              r.status_code == 429 and r.headers.get('Retry-After'), f'{r.status_code} {dict(r.headers)}')
    finally:
        os.environ.pop('CPF_NOME_API_KEY', None)
        os.environ.pop('CPF_NOME_LIMITE_DIARIO_MCP', None)


def test_bases(c, a, tokens):
    print('\n6. Base de conhecimento, jurisprudência e processos')
    t = tokens['lawyer']
    casos = [
        ('/api/v1/processos?limite=5', lambda: process_panel.list_processes_handler(a.id, None, None, 5, 0)),
        ('/api/v1/jurisprudencia?limite=5',
         lambda: jurisprudence.search_jurisprudence_handler(a.id, 'http://localhost', modo='campos', limite=5,
                                                            deslocamento=0, ordem='recentes')),
        ('/api/v1/jurisprudencia/filtros', lambda: jurisprudence.jurisprudence_filter_values_handler(a.id)),
    ]
    for url, handler in casos:
        r = c.get(url, headers=_h(t))
        check(f'{url.split("?")[0]} igual ao handler', r.status_code == 200 and r.get_json() == _json(handler()),
              f'{r.status_code} {r.get_data(as_text=True)[:300]}')
    r = c.get('/api/v1/jurisprudencia/panorama', headers=_h(t))
    check('/jurisprudencia/panorama não cai no detalhe', r.status_code == 200 and 'erro' not in r.get_json(),
          r.get_data(as_text=True)[:200])
    d = JurisprudenceDecision.query.filter_by(law_firm_id=a.id).first()
    r = c.get(f'/api/v1/jurisprudencia/{d.id}', headers=_h(t))
    check('detalhe da decisão', r.status_code == 200, str(r.status_code))
    r = c.get('/api/v1/jurisprudencia?tribunais=TRF4,TRF3', headers=_h(t))
    check('lista separada por vírgula aceita', r.status_code == 200, r.get_data(as_text=True)[:200])
    p = JudicialProcess.query.filter_by(law_firm_id=a.id).first()
    r = c.get(f'/api/v1/processos/{p.id}', headers=_h(t))
    check('detalhe do processo igual ao handler',
          r.status_code == 200 and r.get_json() == _json(process_panel.get_process_detail_handler(p.id, a.id)))

    for url in ('/api/v1/processos', '/api/v1/jurisprudencia', '/api/v1/base-conhecimento/pesquisa?pergunta=x'):
        r = c.get(url, headers=_h(tokens['restrito']))
        check(f'sem o módulo: 403 em {url.split("?")[0]}', r.status_code == 403, str(r.status_code))
    r = c.get('/api/v1/numero-processo/5001234-56.2024.4.04.7000', headers=_h(tokens['restrito']))
    check('número de processo sem nenhuma base: 403', r.status_code == 403, str(r.status_code))
    r = c.get('/api/v1/numero-processo/5001234-56.2024.4.04.7000', headers=_h(tokens['so_kb']))
    corpo = r.get_json()
    check('número de processo só nas bases permitidas',
          r.status_code == 200 and list(corpo['bases']) == ['base_conhecimento'] and corpo.get('sem_permissao'),
          r.get_data(as_text=True)[:300])

    r = c.post('/api/v1/base-conhecimento/perguntar', json={'pergunta': 'x'}, headers=_h(t))
    check('perguntar à base fora da API (busca do agente não filtra escritório)',
          r.status_code in (404, 405) and all(rr.caminho != '/base-conhecimento/perguntar' for rr in ROTAS),
          str(r.status_code))

    for url in ('/api/v1/jurisprudencia/999999999', '/api/v1/jurisprudencia/999999999/parecidas',
                '/api/v1/base-conhecimento/arquivos/999999999'):
        r = c.get(url, headers=_h(t))
        check(f'{url.replace("999999999", "{id}")} inexistente: 404', r.status_code == 404,
              f'{r.status_code} {r.get_data(as_text=True)[:150]}')


def test_registro_x_rotas():
    print('\n5. Registro × rotas montadas')
    montadas = {(m, str(rule.rule)) for rule in app.url_map.iter_rules()
                if rule.endpoint.startswith('public_api.') for m in rule.methods - {'HEAD', 'OPTIONS'}}
    for rota in ROTAS:
        caminho = '/api/v1' + rota.caminho.replace('{', '<').replace('}', '>')
        caminho = caminho.replace('<id>', '<int:id>')
        check(f'{rota.metodo} {rota.caminho} montada', (rota.metodo, caminho) in montadas)
    nomes = [(r.metodo, r.caminho) for r in ROTAS]
    check('sem rota duplicada no registro', len(nomes) == len(set(nomes)))


def main() -> int:
    with app.app_context():
        a, b, usuarios, tokens = _setup()
        public_api._janelas.clear()
        try:
            c = app.test_client()
            test_paridade(c, a, tokens['lawyer'])
            test_parametros(c, b, tokens['lawyer'])
            test_modulo(c, tokens['restrito'])
            test_revelar(c, tokens['lawyer'])
            test_bases(c, a, tokens)
            test_registro_x_rotas()
        finally:
            db.session.rollback()
            _cleanup()

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
