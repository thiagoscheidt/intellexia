#!/usr/bin/env python3
"""
conferir_dados_beneficios: o que a petição (ou a pessoa) diz de cada benefício
contra a Central de contestações e o cálculo FAP do escritório, sem IA.

Escritórios descartáveis, criados e removidos no fim. Confere:

  1. comparação campo a campo (CPF, NIT, espécie, DIB, DCB, nascimento, CNPJ,
     vigência, nome, CAT) com qualquer pontuação e formato de data;
  2. os alertas que só a base dá (já excluído do cálculo, fora do cálculo,
     não contestado, deferido, indeferido nas duas instâncias);
  3. número inexistente e número incompleto;
  4. escritório: nada de outro escritório aparece;
  5. MCP (handler, JSON em texto, limite) e API (POST /fap/beneficios/conferir).

    uv run python tests/test_conferir_dados_beneficios.py
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp.exceptions import ToolError  # noqa: E402

from main import app  # noqa: E402
from app.models import (  # noqa: E402
    ApiToken, Benefit, FapCalculoEstabelecimento, FapCalculoItem, FapVigenciaCnpj, LawFirm, SeguradoNome,
    User, UserMcpCall, db,
)
from app.services import api_token_service  # noqa: E402
from app.services import conferencia_beneficios_service as svc  # noqa: E402

CNPJS = ('00000000001681', '00000000001682')
CNPJ_EMP = '11222333000181'
CNPJ_EMP_FMT = '11.222.333/0001-81'

_falhas: list[str] = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}' + (f' — {detalhe}' if detalhe else ''))
        _falhas.append(nome)


def _cleanup():
    for cnpj in CNPJS:
        firm = LawFirm.query.filter_by(cnpj=cnpj).first()
        if not firm:
            continue
        for modelo in (ApiToken, UserMcpCall, Benefit, FapVigenciaCnpj, FapCalculoItem,
                       FapCalculoEstabelecimento, SeguradoNome):
            modelo.query.filter_by(law_firm_id=firm.id).delete()
        User.query.filter_by(law_firm_id=firm.id).delete()
        db.session.delete(firm)
    db.session.commit()


def _item(firm, **kw):
    base = dict(law_firm_id=firm.id, ano_vigencia=2026, cnpj=CNPJ_EMP, cnpj_raiz=CNPJ_EMP[:8],
                tipo='B91', estado_atual='ORIGINAL', estado_original='ORIGINAL', calculo_id=10)
    base.update(kw)
    return FapCalculoItem(**base)


def _setup():
    _cleanup()
    a = LawFirm(name='Escritório Teste Conferir Benefícios', cnpj=CNPJS[0])
    b = LawFirm(name='Escritório Teste Conferir Benefícios B', cnpj=CNPJS[1])
    db.session.add_all([a, b])
    db.session.flush()
    vig = FapVigenciaCnpj(law_firm_id=a.id, employer_cnpj=CNPJ_EMP_FMT, vigencia_year='2026')
    db.session.add(vig)
    db.session.flush()
    comum = dict(law_firm_id=a.id, fap_vigencia_cnpj_id=vig.id, employer_cnpj=CNPJ_EMP_FMT,
                 fap_vigencia_years='2026')
    db.session.add_all([
        Benefit(benefit_number='6407132987', benefit_type='B94', insured_cpf='012.345.678-90',
                insured_nit='12345678901', insured_date_of_birth=date(1980, 5, 10),
                benefit_start_date=date(2023, 9, 1), benefit_end_date=date(2023, 12, 1),
                cat_number='2023.123.456-7/01', first_instance_status='indeferido',
                second_instance_status='indeferido', **comum),
        Benefit(benefit_number='6222222222', benefit_type='B91', insured_cpf='98765432100',
                benefit_start_date=date(2022, 2, 2), first_instance_status='deferido', **comum),
        Benefit(benefit_number='6333333333', benefit_type='B91', insured_cpf='55566677788', **comum),
        # Outro escritório: nunca pode aparecer.
        Benefit(law_firm_id=b.id, benefit_number='6999999999', benefit_type='B91', insured_cpf='11111111111'),
        _item(a, identificador='6407132987', tipo='B94', cpf='01234567890', nit='12345678901',
              data_nascimento=date(1980, 5, 10), data_inicio=date(2023, 9, 1), data_cessacao=date(2023, 12, 1)),
        _item(a, identificador='6222222222', cpf='98765432100', data_inicio=date(2022, 2, 2),
              estado_atual='EXCLUIDO'),
        _item(a, identificador='6444444444', cpf='11144477735'),
        FapCalculoEstabelecimento(law_firm_id=a.id, ano_vigencia=2026, cnpj=CNPJ_EMP, cnpj_raiz=CNPJ_EMP[:8],
                                  calculo_atual_id=10, tem_itens=True, situacao='ok',
                                  synced_at=datetime.utcnow()),
        SeguradoNome(law_firm_id=a.id, cpf='01234567890', nome='MARIA DA SILVA SOUZA', status='encontrado',
                     fonte='teste', consultado_em=datetime.utcnow()),
    ])
    u = User(law_firm_id=a.id, name='conferir', role='lawyer', is_active=True,
             email='conferir__test_conferir_beneficios@example.com')
    u.set_password('x')
    db.session.add(u)
    db.session.commit()
    token = api_token_service.criar(u, 'teste conferir')[1]
    return a, token


def _por_posicao(r):
    return {i['posicao']: i for i in r['itens']}


def _campos(item, chave):
    return sorted(d['campo'] for d in item[chave])


def _codigos(item):
    return sorted(a['codigo'] for a in item['alertas'])


ENTRADA = [
    # 1. tudo confere, com pontuação e datas em formatos diferentes
    {'numero': '640.713.298-7', 'cpf': '012.345.678-90', 'nit': '123.45678.90-1', 'especie': 'B-94',
     'dib': '01/09/2023', 'dcb': '2023-12-01', 'nascimento': '10.05.1980', 'cnpj': CNPJ_EMP_FMT,
     'vigencia': 2026, 'nome': 'Maria da Silva Souza', 'cat': '20231234567/01'},
    # 2. CPF, espécie e DIB errados; já excluído do cálculo e deferido
    {'numero': '6222222222', 'cpf': '111.444.777-35', 'especie': '94', 'dib': '01/01/2023'},
    # 3. só o número: está na Central, mas o cálculo sincronizado não o traz
    '6333333333',
    # 4. só no cálculo: não contestado; vigência errada
    {'numero': '6444444444', 'vigencia': '2025'},
    # 5. não existe (e existe em outro escritório)
    {'numero': '699.999.999-9'},
    # 6. número incompleto
    {'numero': '64071329'},
    # 7. nome de outra pessoa
    {'numero': '6407132987', 'nome': 'João Pereira'},
    # 8. nome abreviado confere
    {'numero': '6407132987', 'nome': 'MARIA SOUZA'},
    # 9. sem dígitos
    {'numero': 'abc'},
    # 10. data ilegível e CNPJ pela raiz
    {'numero': '6407132987', 'dib': 'setembro', 'cnpj': '11.222.333'},
]


def test_conferencia(a):
    print('\n1) Comparação campo a campo')
    r = svc.conferir(a.id, ENTRADA)
    it = _por_posicao(r)
    check('um item por entrada, na ordem', [i['posicao'] for i in r['itens']] == list(range(1, 11)))

    i1 = it[1]
    check('1: tudo confere', i1['situacao'] == 'confere' and not i1['divergencias'], str(i1['divergencias']))
    check('1: conferiu os dez campos',
          sorted(i1['conferidos']) == sorted(['cpf', 'nit', 'especie', 'dib', 'dcb', 'nascimento', 'cnpj',
                                              'vigencia', 'nome', 'cat']), str(i1['conferidos']))
    check('1: achado na Central e no cálculo', len(i1['central']) == 1 and len(i1['calculo']) == 1)
    check('1: nome revelado volta', i1['segurado_nome'] == 'MARIA DA SILVA SOUZA', str(i1['segurado_nome']))
    check('1: indeferido nas duas instâncias', 'indeferido_nas_duas_instancias' in _codigos(i1), str(_codigos(i1)))
    check('1: status por instância como na tela',
          (i1['central'][0]['status_1a_instancia'], i1['central'][0]['status_2a_instancia'])
          == ('indeferido', 'indeferido'), str(i1['central'][0]))

    i2 = it[2]
    check('2: divergente em CPF, espécie e DIB', i2['situacao'] == 'divergente'
          and _campos(i2, 'divergencias') == ['cpf', 'dib', 'especie'], str(i2['divergencias']))
    cpf = next(d for d in i2['divergencias'] if d['campo'] == 'cpf')
    check('2: divergência mostra petição e base', cpf['peticao'] == '111.444.777-35'
          and cpf['base'] == ['987.654.321-00'], str(cpf))
    especie = next(d for d in i2['divergencias'] if d['campo'] == 'especie')
    check('2: espécie normalizada (94 → B94) contra B91', especie['peticao'] == 'B94'
          and especie['base'] == ['B91'], str(especie))
    check('2: alerta de excluído do cálculo e de deferido',
          {'excluido_do_calculo', 'deferido'} <= set(_codigos(i2)), str(_codigos(i2)))

    i3 = it[3]
    check('3: só número = confere (nada a comparar)', i3['situacao'] == 'confere' and i3['conferidos'] == [])
    check('3: fora do cálculo sincronizado', 'fora_do_calculo' in _codigos(i3), str(_codigos(i3)))

    i4 = it[4]
    check('4: vigência divergente', _campos(i4, 'divergencias') == ['vigencia'], str(i4['divergencias']))
    check('4: não contestado na vigência', 'nao_contestado' in _codigos(i4), str(_codigos(i4)))
    check('4: só no cálculo', not i4['central'] and len(i4['calculo']) == 1)

    i5 = it[5]
    check('5: não encontrado (o de outro escritório não aparece)', i5['situacao'] == 'nao_encontrado'
          and not i5['central'] and not i5['calculo'], str(i5))
    i6 = it[6]
    check('6: número incompleto avisa os 10 dígitos', i6['situacao'] == 'nao_encontrado'
          and any('10 dígitos' in a['mensagem'] for a in i6['alertas']), str(i6['alertas']))

    check('7: nome de outra pessoa diverge', _campos(it[7], 'divergencias') == ['nome'], str(it[7]['divergencias']))
    check('8: nome abreviado confere', it[8]['situacao'] == 'confere', str(it[8]['divergencias']))
    check('9: sem dígitos = inválido', it[9]['situacao'] == 'invalido', str(it[9]))

    i10 = it[10]
    check('10: data ilegível não vira divergência', 'dib' not in _campos(i10, 'divergencias')
          and 'dib' in _campos(i10, 'nao_conferidos'), str(i10))
    check('10: CNPJ pela raiz confere', 'cnpj' in i10['conferidos'] and i10['situacao'] == 'confere',
          str(i10['divergencias']))

    check('resumo bate com os itens',
          (r['total'], r['conferem'], r['com_divergencia'], r['nao_encontrados'])
          == (10, 4, 3, 2), str({k: r[k] for k in ('total', 'conferem', 'com_divergencia', 'nao_encontrados')}))
    check('dica para a IA', bool(r.get('dica')))


def test_entrada(a):
    print('\n2) Entrada')
    r = svc.conferir(a.id, json.dumps([{'numero': '6407132987'}]))
    check('lista como texto JSON', r['total'] == 1 and r['itens'][0]['situacao'] == 'confere')
    for ruim, nome in (([], 'lista vazia'), ('não é json', 'texto que não é JSON'),
                       ([{'cpf': '1'}], 'item sem número'),
                       ([{'numero': str(6000000000 + i)} for i in range(svc.LIMITE + 1)], 'acima do limite')):
        try:
            svc.conferir(a.id, ruim)
            check(f'{nome}: recusa', False)
        except ValueError as e:
            check(f'{nome}: recusa com explicação', len(str(e)) > 10, str(e))

    from mcp_server.tools.fap import conferir_dados_beneficios_handler
    r = conferir_dados_beneficios_handler(a.id, [{'numero': '6407132987', 'cpf': '01234567890'}])
    check('MCP: handler devolve o mesmo', r['itens'][0]['situacao'] == 'confere')
    try:
        conferir_dados_beneficios_handler(a.id, [])
        check('MCP: entrada inválida vira ToolError', False)
    except ToolError:
        check('MCP: entrada inválida vira ToolError', True)


def test_api(a, token):
    print('\n3) API')
    from app.services import public_api_campos as C
    from app.services.public_api_catalogo import ROTAS

    c = app.test_client()
    h = {'Authorization': f'Bearer {token}'}
    r = c.post('/api/v1/fap/beneficios/conferir', json={'beneficios': ENTRADA[:3]}, headers=h)
    check('POST /fap/beneficios/conferir: 200', r.status_code == 200, f'{r.status_code} {r.get_data(as_text=True)[:200]}')
    corpo = r.get_json() or {}
    check('API: mesmos itens do serviço', [i['situacao'] for i in corpo.get('itens', [])]
          == ['confere', 'divergente', 'confere'], str(corpo)[:200])
    check('API: sem os textos para a IA', 'dica' not in corpo)
    rota = next(rr for rr in ROTAS if rr.caminho == '/fap/beneficios/conferir')
    problemas = C.conferir(corpo, rota.resposta)
    check('API: resposta confere com os campos declarados', not problemas, '; '.join(problemas[:5]))

    r = c.post('/api/v1/fap/beneficios/conferir', json={'beneficios': ['6407132987']}, headers=h)
    check('API: lista de números simples', r.status_code == 200 and r.get_json()['total'] == 1,
          r.get_data(as_text=True)[:200])
    r = c.post('/api/v1/fap/beneficios/conferir', json={'beneficios': []}, headers=h)
    check('API: lista vazia é 400', r.status_code == 400, str(r.status_code))
    r = c.post('/api/v1/fap/beneficios/conferir', json={'beneficios': 'abc'}, headers=h)
    check('API: texto no lugar da lista é 400', r.status_code == 400, str(r.status_code))
    r = c.post('/api/v1/fap/beneficios/conferir', json={'beneficios': ['6407132987'], 'x': 1}, headers=h)
    check('API: parâmetro desconhecido é 400', r.status_code == 400, str(r.status_code))


def test_revisor():
    print('\n4) Revisor no Claude')
    import ast

    from app.services import fap_review_claude_service as claude_svc

    for modo, texto in claude_svc._ETAPAS.items():
        check(f'etapa de leitura ({modo}) manda conferir os dados dos benefícios',
              'conferir_dados_beneficios' in texto.split('\n3.')[0], texto[:120])
        check(f'etapa de revisão ({modo}) transforma divergência em achado',
              'divergên' in texto.split('\n3.')[1], texto[-200:])
    check('modelo de apresentação tem a seção dos dados', '🔎' in claude_svc._COMO_MOSTRAR)

    arvore = ast.parse((Path(__file__).resolve().parent.parent / 'mcp_server' / 'server.py').read_text())
    docs = {n.name: ast.get_docstring(n) or '' for n in ast.walk(arvore) if isinstance(n, ast.FunctionDef)}
    for nome in ('revisar_peticao_inicial', 'comparar_versoes_peticao'):
        check(f'{nome}: a descrição cita conferir_dados_beneficios', 'conferir_dados_beneficios' in docs[nome])


def main() -> int:
    with app.app_context():
        a, token = _setup()
        try:
            test_conferencia(a)
            test_entrada(a)
            test_api(a, token)
            test_revisor()
        finally:
            db.session.rollback()
            _cleanup()
    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} verificação(ões) falharam:')
        for f in _falhas:
            print(f'   · {f}')
        return 1
    print('✅ Todas as verificações passaram.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
