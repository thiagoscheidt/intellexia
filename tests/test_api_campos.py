#!/usr/bin/env python3
"""
Campos de resposta da API (/api/v1): a resposta real de cada rota confere com
o que public_api_campos declara (e que a documentação e o OpenAPI mostram).

Campo que o handler do MCP passou a devolver sem estar declarado, campo
declarado que sumiu ou tipo trocado = falha aqui — é o que impede a
documentação de envelhecer. Também cobre o que é só da API: teto de página por
rota (acima dele é 400), a janela exata do cálculo FAP e a saída dos textos
escritos para a IA (``dica``).

Duas amostras:
  1. escritório descartável do test_api_rotas, pela API (token, test_client);
  2. o escritório com mais benefícios do banco local, só leitura e direto no
     handler — é onde as listas internas (decisões, histórico, notas) têm item
     para conferir por dentro. Sem dados locais, a parte 2 só avisa.

    uv run python tests/test_api_campos.py
"""

import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_api_rotas as base  # noqa: E402  (fixture das rotas)

from main import app  # noqa: E402
from app.blueprints import public_api  # noqa: E402
from app.blueprints.public_api import Contexto  # noqa: E402
from app.models import (  # noqa: E402
    db, Benefit, BenefitContestationDecision, FapCalculoItem, FapWebContestacao, JudicialProcess,
    JurisprudenceDecision, KnowledgeBase, SeguradoNome, User,
)
from app.services import cpf_nome_client  # noqa: E402
from app.services import public_api_campos as C  # noqa: E402
from app.services.public_api_catalogo import ROTAS, TETO_PAGINA, para_api, ler_parametros  # noqa: E402
from mcp_server.tools import pagination  # noqa: E402

check = base.check
_falhas = base._falhas
ROTA = {(r.metodo, r.caminho): r for r in ROTAS}


def _conferir(nome, corpo, campos):
    problemas = C.conferir(corpo, campos)
    check(f'{nome} confere com os campos declarados', not problemas, '; '.join(problemas[:6]))


def _vazias(valor, campos, caminho=''):
    """Listas declaradas com campos que vieram vazias (não conferidas por dentro)."""
    out = []
    if not isinstance(valor, dict):
        return out
    for c in campos:
        v = valor.get(c.nome)
        onde = f'{caminho}.{c.nome}'.lstrip('.')
        if c.tipo == 'lista' and c.campos:
            if not v:
                out.append(onde)
            else:
                out += _vazias(v[0], c.campos, onde + '[]')
        elif c.tipo == 'objeto' and c.campos and isinstance(v, dict):
            out += _vazias(v, c.campos, onde)
    return out


def test_declaracao():
    print('\n1. Toda rota tem resposta declarada e schema no OpenAPI')
    from app.services.public_api_catalogo import openapi

    sem = [f'{r.metodo} {r.caminho}' for r in ROTAS if not r.resposta]
    check('toda rota declara a resposta', not sem, ', '.join(sem))
    doc = openapi('http://localhost')
    for r in ROTAS:
        op = doc['paths'][r.caminho][r.metodo.lower()]
        s = op['responses']['200'].get('content', {}).get('application/json', {}).get('schema', {})
        if not s.get('properties'):
            check(f'{r.metodo} {r.caminho}: schema da resposta no OpenAPI', False)
    check('OpenAPI traz o schema de toda resposta 200', True)
    for r in ROTAS:
        nomes = [c.nome for c in r.resposta]
        if len(nomes) != len(set(nomes)):
            check(f'{r.caminho}: campo declarado duas vezes', False)


def test_amostra_da_api(c, a, tokens):
    print('\n2. Amostra descartável, pela API')
    h = base._h(tokens['lawyer'])
    b0 = Benefit.query.filter_by(law_firm_id=a.id).order_by(Benefit.id).first()
    p = JudicialProcess.query.filter_by(law_firm_id=a.id).first()
    d = JurisprudenceDecision.query.filter_by(law_firm_id=a.id).first()
    urls = {
        '/fap/empresas': '', '/fap/contestacoes': '', '/fap/beneficios': '?limite=1',
        '/fap/beneficios/{id}': b0.id, '/fap/resumo': '?empresa=teste', '/fap/filtros': '',
        '/fap/procuracoes': '', '/fap/calculo/beneficios': '', '/fap/calculo/resumo': '',
        '/fap/calculo/ranking': '?agrupar_por=estabelecimento', '/fap/calculo/cruzamento-vigencias': '',
        '/fap/calculo/estabelecimento': '?cnpj=33592510000154',
        '/segurados': '?cpf=12345678909', '/jurisprudencia': '?limite=1', '/jurisprudencia/panorama': '',
        '/jurisprudencia/filtros': '', '/jurisprudencia/{id}': d.id, '/processos': '',
        '/processos/{id}': p.id, '/numero-processo/{numero}': '5001234-56.2024.4.04.7000',
    }
    for caminho, extra in urls.items():
        if '{' in caminho:
            url = '/api/v1' + caminho.replace('{id}', str(extra)).replace('{numero}', str(extra))
        else:
            url = '/api/v1' + caminho + str(extra)
        r = c.get(url, headers=h)
        if r.status_code != 200:
            check(f'{caminho}: 200', False, f'{r.status_code} {r.get_data(as_text=True)[:200]}')
            continue
        _conferir(caminho, r.get_json(), ROTA[('GET', caminho)].resposta)

    r = c.get('/api/v1/fap/beneficios?limite=1', headers=h)
    corpo = r.get_json()
    check('lista paginada sem "dica" (texto para a IA) e com proximo_deslocamento',
          'dica' not in corpo and corpo.get('tem_mais') and corpo.get('proximo_deslocamento') == 1,
          str({k: v for k, v in corpo.items() if k != 'itens'}))

    # Revelar nome com o fornecedor substituído: nunca consulta CPF de verdade.
    original = cpf_nome_client.consultar_nome
    cpf_nome_client.consultar_nome = lambda cpf: cpf_nome_client.ResultadoNome(
        True, 'SEGURADO DE TESTE', date(1990, 1, 1))
    os.environ['CPF_NOME_API_KEY'] = 'teste'
    try:
        r = c.post('/api/v1/segurados/revelar-nome', json={'cpf': '12345678909'}, headers=h)
        check('revelar nome: 200', r.status_code == 200, f'{r.status_code} {r.get_data(as_text=True)[:200]}')
        if r.status_code == 200:
            _conferir('/segurados/revelar-nome', r.get_json(), ROTA[('POST', '/segurados/revelar-nome')].resposta)
        completo = cpf_nome_client.consultar_completo
        cpf_nome_client.consultar_completo = lambda cpf: cpf_nome_client.ResultadoCompleto(
            True, {'NOME': 'FULANO DE FORA', 'NASC': '10/10/1975', 'SEXO': 'Masculino', 'NOME_MAE': 'MAE DE FORA'})
        try:
            r = c.post('/api/v1/segurados/consultar-cpf', json={'cpf': '390.533.447-05'}, headers=h)
            check('consultar CPF (fora da base): 200', r.status_code == 200,
                  f'{r.status_code} {r.get_data(as_text=True)[:200]}')
            if r.status_code == 200:
                _conferir('/segurados/consultar-cpf', r.get_json(), ROTA[('POST', '/segurados/consultar-cpf')].resposta)
                check('consultar CPF devolve a resposta inteira do serviço', r.get_json()['dados'].get('NOME_MAE') == 'MAE DE FORA')
            r = c.post('/api/v1/segurados/consultar-cpf', json={'cpf': '123.456.789-00'}, headers=h)
            check('consultar CPF com DV inválido: 400', r.status_code == 400, str(r.status_code))
        finally:
            cpf_nome_client.consultar_completo = completo
    finally:
        cpf_nome_client.consultar_nome = original
        os.environ.pop('CPF_NOME_API_KEY', None)

    r = c.get('/api/v1/eu', headers=h)
    _conferir('/eu', r.get_json(), C.EU)


def test_teto(c, tokens):
    print('\n3. Teto da página')
    h = base._h(tokens['lawyer'])
    r = c.get(f'/api/v1/fap/beneficios?limite={TETO_PAGINA + 1}', headers=h)
    check(f'limite acima de {TETO_PAGINA}: 400 dizendo o máximo',
          r.status_code == 400 and str(TETO_PAGINA) in r.get_json()['erro'], r.get_data(as_text=True)[:200])
    r = c.get(f'/api/v1/fap/beneficios?limite={TETO_PAGINA}', headers=h)
    check(f'limite = {TETO_PAGINA}: aceito', r.status_code == 200, str(r.status_code))
    r = c.get('/api/v1/fap/beneficios?limite=0', headers=h)
    check('limite 0: 400', r.status_code == 400, str(r.status_code))
    r = c.get('/api/v1/fap/beneficios?deslocamento=-1', headers=h)
    check('deslocamento negativo: 400', r.status_code == 400, str(r.status_code))
    r = c.get('/api/v1/base-conhecimento/pesquisa?pergunta=x&limite=51', headers=base._h(tokens['so_kb']))
    check('pesquisa na base: teto próprio de 50 (a busca traz 50 trechos)',
          r.status_code == 400 and '50' in r.get_json()['erro'], r.get_data(as_text=True)[:200])
    check('decisões parecidas: teto próprio de 20', ROTA[('GET', '/jurisprudencia/{id}/parecidas')].teto == 20)

    check('MCP continua parando em 200', pagination.clamp_limit(500, 50) == 200)
    with pagination.teto_da_pagina(TETO_PAGINA):
        check('dentro do teto da API, o handler aceita 500', pagination.clamp_limit(500, 50) == 500)
    check('o teto volta ao do MCP depois', pagination.clamp_limit(500, 50) == 200)


def _amostra_local():
    """O escritório com mais benefícios do banco, se houver (só leitura)."""
    linha = (db.session.query(Benefit.law_firm_id, db.func.count(Benefit.id))
             .filter(~Benefit.law_firm_id.in_([f.id for f in base.LawFirm.query.filter(
                 base.LawFirm.cnpj.in_(base.CNPJS)).all()] or [-1]))
             .group_by(Benefit.law_firm_id).order_by(db.func.count(Benefit.id).desc()).first())
    if not linha:
        return None
    fid = linha[0]
    u = (User.query.filter_by(law_firm_id=fid, role='admin', is_active=True).first()
         or User.query.filter_by(law_firm_id=fid).first())
    if not u:
        return None
    return Contexto(u.id, fid, u.get_module_permissions(), 'admin', 'http://localhost', 0)


def _primeiro(query):
    r = query.first()
    return r.id if r else None


def test_amostra_local():
    print('\n4. Escritório com mais dados no banco local (só leitura)')
    ctx = _amostra_local()
    if ctx is None:
        print('  ⚠️  sem escritório com benefícios no banco local — parte pulada')
        return
    fid = ctx.law_firm_id
    ids = {
        '/fap/beneficios/{id}': _primeiro(
            Benefit.query.filter_by(law_firm_id=fid)
            .join(BenefitContestationDecision, BenefitContestationDecision.benefit_id == Benefit.id)
            .order_by(Benefit.id.desc())) or _primeiro(Benefit.query.filter_by(law_firm_id=fid)),
        '/fap/contestacoes/{id}': _primeiro(
            FapWebContestacao.query.filter_by(law_firm_id=fid).order_by(FapWebContestacao.id.desc())),
        '/jurisprudencia/{id}': _primeiro(
            JurisprudenceDecision.query.filter_by(law_firm_id=fid).order_by(JurisprudenceDecision.id.desc())),
        '/processos/{id}': _primeiro(
            JudicialProcess.query.filter_by(law_firm_id=fid).filter(JudicialProcess.benefits.any())
            .order_by(JudicialProcess.id.desc())) or _primeiro(JudicialProcess.query.filter_by(law_firm_id=fid)),
        '/base-conhecimento/arquivos/{id}': _primeiro(
            KnowledgeBase.query.filter_by(law_firm_id=fid, is_active=True).order_by(KnowledgeBase.id.desc())),
    }
    ids['/jurisprudencia/{id}/parecidas'] = ids['/jurisprudencia/{id}']
    proc = db.session.get(JudicialProcess, ids['/processos/{id}']) if ids['/processos/{id}'] else None
    b = Benefit.query.filter_by(law_firm_id=fid).filter(Benefit.insured_nit.isnot(None)).first()
    est = FapCalculoItem.query.filter_by(law_firm_id=fid).order_by(FapCalculoItem.id).first()
    # Número de processo na pergunta = busca textual direta, sem a IA escolher o modo.
    kb_num = (KnowledgeBase.query.filter_by(law_firm_id=fid, is_active=True)
              .filter(KnowledgeBase.lawsuit_number.isnot(None)).first())
    extra = {
        '/segurados': {'nit': b.insured_nit} if b else None,
        '/base-conhecimento/pesquisa': ({'pergunta': kb_num.lawsuit_number, 'modo_busca': 'textual'}
                                        if kb_num else None),
        '/fap/calculo/estabelecimento': ({'cnpj': est.cnpj} if est else None),
        '/fap/beneficios': {'limite': '200'}, '/fap/calculo/beneficios': {'limite': '200'},
        '/fap/contestacoes': {'limite': '200'}, '/jurisprudencia': {'limite': '200'},
        '/processos': {'limite': '200'},
    }
    vazias = []
    from fastmcp.exceptions import ToolError
    from werkzeug.datastructures import MultiDict

    for rota in ROTAS:
        if rota.metodo != 'GET':
            continue
        if rota.caminho in extra and extra[rota.caminho] is None:
            print(f'  ⚠️  {rota.caminho}: sem dado local para a consulta — pulada')
            continue
        caminho = {}
        if '{id}' in rota.caminho:
            if not ids.get(rota.caminho):
                print(f'  ⚠️  {rota.caminho}: sem registro local — pulada')
                continue
            caminho['id'] = ids[rota.caminho]
        if '{numero}' in rota.caminho:
            if not proc:
                continue
            caminho['numero'] = proc.process_number
        try:
            params = ler_parametros(rota, MultiDict(extra.get(rota.caminho) or {}), None, caminho)
            with pagination.teto_da_pagina(rota.teto):
                corpo = app.json.loads(app.json.dumps(para_api(rota.chamar(ctx, params))))
        except ToolError as e:
            print(f'  ⚠️  {rota.caminho}: {str(e)[:110]} — pulada')
            continue
        finally:
            db.session.rollback()
        _conferir(f'{rota.caminho} (local)', corpo, rota.resposta)
        vazias += [f'{rota.caminho} → {v}' for v in _vazias(corpo, rota.resposta)]
    if vazias:
        print('  ℹ️  listas vazias nesta amostra (conferidas só por fora):')
        for v in vazias:
            print(f'       {v}')


def test_janela_calculo():
    print('\n5. Lista do cálculo FAP: a janela é a posição pedida')
    from app.services import fap_calculo_query_service as svc

    linha = (db.session.query(FapCalculoItem.law_firm_id, db.func.count(FapCalculoItem.id))
             .group_by(FapCalculoItem.law_firm_id).order_by(db.func.count(FapCalculoItem.id).desc()).first())
    if not linha or linha[1] < 30:
        print('  ⚠️  sem itens do cálculo FAP no banco local — parte pulada')
        return
    q = svc.filtrar(linha[0])
    todos, total = svc.janela(q, 0, 30, law_firm_id=linha[0])
    meio, total2 = svc.janela(q, 7, 11, law_firm_id=linha[0])
    check('janela(7, 11) = itens 7 a 17 da janela(0, 30)',
          [i['id'] for i in meio] == [i['id'] for i in todos[7:18]] and total == total2)
    if total > 450:
        with pagination.teto_da_pagina(TETO_PAGINA):
            from mcp_server.tools.fap_calculo import listar_beneficios_calculo_fap_handler
            grande = listar_beneficios_calculo_fap_handler(linha[0], limite=300, deslocamento=150)
        esperado, _ = svc.janela(q, 150, 300, law_firm_id=linha[0])
        check('limite 300 com deslocamento 150: as 300 linhas certas (sem o corte de 200 da tela)',
              [i['id'] for i in grande['itens']] == [i['id'] for i in esperado] and len(esperado) == 300)
    else:
        print(f'  ⚠️  só {total} itens no banco local: a página de 300 (acima do corte de 200) não foi conferida')


def main() -> int:
    with app.app_context():
        test_declaracao()
        a, b, usuarios, tokens = base._setup()
        public_api._janelas.clear()
        try:
            c = app.test_client()
            test_amostra_da_api(c, a, tokens)
            test_teto(c, tokens)
            test_amostra_local()
            test_janela_calculo()
        finally:
            db.session.rollback()
            SeguradoNome.query.filter_by(law_firm_id=a.id).delete()
            db.session.commit()
            base._cleanup()

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
