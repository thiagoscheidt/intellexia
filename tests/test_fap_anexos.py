#!/usr/bin/env python3
"""
Anexos das contestações do FAP (`fap_anexos_service`, `scripts/fap_baixar_anexos.py`).

1. Recálculos: só do escritório, só situação ok, sem o cálculo original; filtros.
2. Simulação conta e não grava nada.
3. --baixar grava arquivo, `_anexos.json` e `indice.csv`; a 2ª rodada não baixa de novo.
4. Arquivo com base64 inválido ou tamanho diferente do anunciado não vai ao disco.
5. 403 conta como sem acesso; 401 para a execução (saída 2).
6. Nome vindo do portal não sai da pasta.
7. Registro: liga ao benefício da Central (vigência + CNPJ + NB), lê o texto,
   classifica (HISMED com CID, CONBAS), é idempotente.
8. Busca: termo no índice (se o Meilisearch estiver no ar) e no banco, NB como
   filtro exato, CID, outro escritório não vê; recorte com e sem documento.
10. OCR: PDF só de imagem é lido, ganha tipo e a marca de OCR, e não é tentado de novo;
    tipo pelo nome do arquivo.
9. Telas: documentos do benefício e o arquivo (outro escritório 404), filtro
   "com/sem documento" e o recorte na lista da Central, linha do cálculo FAP.

Não abre o portal: o cliente é substituído. Escritórios descartáveis, removidos no fim.

    uv run python tests/test_fap_anexos.py
"""
import base64
import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, Benefit, FapCalculoItem, User, FapCalculoEstabelecimento, FapContestacaoAnexo, FapVigenciaCnpj, LawFirm
from app.services import fap_anexos_busca_service as busca
from app.services import fap_anexos_service as svc
from app.services import fap_calculo_client as client
from app.services.fap_web_service import FapWebResult
import importlib.util

_spec = importlib.util.spec_from_file_location(
    'fap_baixar_anexos', Path(__file__).resolve().parent.parent / 'scripts' / 'fap_baixar_anexos.py')
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

CNPJS_FIRMA = ('00000000002535', '00000000002616')
EST_A = '11222333000181'
EST_B = '11222333000262'
_falhas = []
_B = []


def check(nome, condicao, detalhe=''):
    print(f'  {"✅" if condicao else "❌"} {nome}{"" if condicao or not detalhe else " — " + str(detalhe)}')
    if not condicao:
        _falhas.append(nome)


def _pdf(linhas):
    import fitz
    doc = fitz.open()
    pagina = doc.new_page()
    for i, linha in enumerate(linhas):
        pagina.insert_text((40, 60 + 16 * i), linha)
    return doc.tobytes()


PDF = _pdf(['Historico de Pericias Medicas (HISMED) - Dados Gerais', 'Instituto Nacional do Seguro Social',
            'NB: 648.526.463-2', 'Especie: 91 - AUXILIO POR INCAPACIDADE TEMPORARIA - ACIDENTE DO TRABALHO',
            'Diagnostico:', 'M54.5', 'Conclusao: 2 - Data de cessacao do beneficio', 'Nexo Tecnico: lombalgia'])
PDF2 = _pdf(['INFORMACOES DA CONCESSAO DO BENEFICIO (CONBAS)', 'Instituto Nacional do Seguro Social',
             'Especie: 94 - AUXILIO-ACIDENTE', 'Situacao: Cessado', 'Acidente de trajeto na via publica'])


def _anexo(i, nome, conteudo):
    return {'id': i, 'tipoElemento': {'codigo': 'BENEFICIO', 'descricao': 'Benefício'}, 'idElemento': i * 10,
            'nb': 6485264632, 'nome': nome, 'dataEnvio': '2026-08-11', 'quantidadeBytes': len(conteudo)}


# recálculo → lista de anexos; anexo → conteúdo (ou resposta)
LISTAS = {
    101: [_anexo(1, 'B91 6485264632.pdf', PDF), _anexo(2, '../../fora.pdf', PDF2)],
    102: [],
    201: 'proibido',
}
ARQUIVOS = {1: {'nome': 'B91 6485264632.pdf', 'base64': base64.b64encode(PDF).decode()},
            2: {'nome': 'fora.pdf', 'base64': base64.b64encode(PDF2).decode()}}
CHAMADAS = {'lista': 0, 'download': 0}


def _listar(_svc, ano, cnpj, calculo_id):
    CHAMADAS['lista'] += 1
    v = LISTAS.get(calculo_id, [])
    if v == 'proibido':
        return FapWebResult(ok=False, status_code=403, message='Sem acesso')
    if v == 'expirada':
        return FapWebResult(ok=False, expired=True, status_code=401)
    return FapWebResult(ok=True, data=v)


def _baixar(_svc, ano, cnpj, calculo_id, anexo_id):
    CHAMADAS['download'] += 1
    return FapWebResult(ok=True, data=ARQUIVOS[anexo_id])


def _cleanup():
    for cnpj in CNPJS_FIRMA:
        firm = LawFirm.query.filter_by(cnpj=cnpj).first()
        if firm:
            FapContestacaoAnexo.query.filter_by(law_firm_id=firm.id).delete()
            FapCalculoItem.query.filter_by(law_firm_id=firm.id).delete()
            Benefit.query.filter_by(law_firm_id=firm.id).delete()
            from app.models import UserPageVisit
            for u in User.query.filter_by(law_firm_id=firm.id).all():
                UserPageVisit.query.filter_by(user_id=u.id).delete()
                db.session.delete(u)
            FapVigenciaCnpj.query.filter_by(law_firm_id=firm.id).delete()
            FapCalculoEstabelecimento.query.filter_by(law_firm_id=firm.id).delete()
            db.session.delete(firm)
    db.session.commit()


def _setup():
    _cleanup()
    ids = []
    for i, cnpj in enumerate(CNPJS_FIRMA):
        f = LawFirm(name=f'Escritório Teste Anexos FAP {i}', cnpj=cnpj)
        db.session.add(f)
        db.session.flush()
        ids.append(f.id)
    a, b = ids
    hist = lambda *ids_: json.dumps([{'id': x, 'tipo': t, 'data': '2026-10-20'} for x, t in ids_])
    db.session.add_all([
        FapCalculoEstabelecimento(law_firm_id=a, ano_vigencia=2026, cnpj=EST_A, cnpj_raiz=EST_A[:8], situacao='ok',
                                  calculo_atual_id=101, calculo_original_id=100,
                                  historico_json=hist((101, 'RECALCULO_ELETRONICO_SEGUNDA_INSTANCIA'),
                                                      (102, 'RECALCULO_ELETRONICO_PRIMEIRA_INSTANCIA'),
                                                      (100, 'CALCULO_ORIGINAL'))),
        FapCalculoEstabelecimento(law_firm_id=a, ano_vigencia=2025, cnpj=EST_B, cnpj_raiz=EST_B[:8], situacao='ok',
                                  calculo_atual_id=201, calculo_original_id=200,
                                  historico_json=hist((201, 'RECALCULO_ELETRONICO_PRIMEIRA_INSTANCIA'),
                                                      (200, 'CALCULO_ORIGINAL'))),
        FapCalculoEstabelecimento(law_firm_id=a, ano_vigencia=2026, cnpj='11222333000343', cnpj_raiz='11222333',
                                  situacao='sem_acesso', calculo_atual_id=301, calculo_original_id=300,
                                  historico_json=hist((301, 'RECALCULO'), (300, 'CALCULO_ORIGINAL'))),
        FapCalculoEstabelecimento(law_firm_id=b, ano_vigencia=2026, cnpj=EST_A, cnpj_raiz=EST_A[:8], situacao='ok',
                                  calculo_atual_id=901, calculo_original_id=900,
                                  historico_json=hist((901, 'RECALCULO'), (900, 'CALCULO_ORIGINAL'))),
    ])
    db.session.commit()
    return a, b


def test_recalculos(a):
    print('\n1. Recálculos')
    recs = svc.recalculos(a)
    ids = sorted(r.calculo_id for r in recs)
    check('só do escritório, situação ok, sem o original', ids == [101, 102, 201], ids)
    check('filtro de vigência', sorted(r.calculo_id for r in svc.recalculos(a, anos=[2025])) == [201])
    check('filtro de raiz sem os zeros', len(svc.recalculos(a, raizes=['11222333'])) == 3)
    check('filtro de estabelecimento', sorted(r.calculo_id for r in svc.recalculos(a, cnpjs=[EST_A])) == [101, 102])


def test_simulacao(a, pasta):
    print('\n2. Simulação')
    CHAMADAS.update(lista=0, download=0)
    r = svc.executar(a, None, pasta=pasta, log=lambda m: None)
    check('conta anexos e tamanho', r['anexos'] == 2 and r['bytes'] == len(PDF) + len(PDF2), r)
    check('403 é sem acesso, não erro', r['sem_acesso'] == 1 and r['erros'] == 0, r)
    check('não baixa nem grava', CHAMADAS['download'] == 0 and not any(pasta.iterdir()))


def test_baixar(a, pasta):
    print('\n3. Baixar e retomar')
    CHAMADAS.update(lista=0, download=0)
    r = svc.executar(a, None, pasta=pasta, baixar=True, log=lambda m: None)
    rec = pasta / '2026' / EST_A / '101'
    arq = rec / '1 - B91 6485264632.pdf'
    check('arquivo gravado igual ao do portal', arq.exists() and arq.read_bytes() == PDF, r)
    check('lista do portal ao lado', (rec / svc.LISTA_DA_PASTA).exists())
    check('sem .part sobrando', not list(pasta.rglob('*.part')))
    with (pasta / svc.INDICE).open(encoding='utf-8-sig') as f:
        linhas = list(csv.DictReader(f, delimiter=';'))
    check('índice com os dois anexos', len(linhas) == 2 and all(l['arquivo'] for l in linhas), linhas)
    check('relatório', r['baixados'] == 2 and r['ja_no_disco'] == 0 and not r['incompleta'], r)

    CHAMADAS.update(lista=0, download=0)
    r2 = svc.executar(a, None, pasta=pasta, baixar=True, log=lambda m: None)
    check('2ª rodada não baixa de novo', CHAMADAS['download'] == 0 and r2['ja_no_disco'] == 2, r2)
    check('recálculo sem anexo ganha marca vazia', (pasta / '2026' / EST_A / '102' / svc.LISTA_DA_PASTA).exists())
    CHAMADAS.update(lista=0, download=0)
    r3 = svc.executar(a, None, pasta=pasta, baixar=True, somente_novos=True, log=lambda m: None)
    check('--somente-novos só consulta o que nunca foi consultado', CHAMADAS['lista'] == 1
          and r3['ja_consultados'] == 2, (CHAMADAS, r3['ja_consultados']))

    print('\n6. Nome do portal')
    fora = [p for p in pasta.rglob('*fora.pdf')]
    check('"../../fora.pdf" fica dentro da pasta do recálculo',
          len(fora) == 1 and fora[0].parent == rec, fora)
    check('nome_seguro', svc.nome_seguro('../a/b\\c.pdf') == '_a_b_c.pdf' and svc.nome_seguro('') == 'anexo')


def test_arquivo_ruim(a, pasta):
    print('\n4. Arquivo que não confere')
    ARQUIVOS[1] = {'nome': 'x.pdf', 'base64': base64.b64encode(PDF[:-5]).decode()}
    ARQUIVOS[2] = {'nome': 'y.pdf', 'base64': '%%%não é base64%%%'}
    try:
        r = svc.executar(a, None, pasta=pasta, baixar=True, log=lambda m: None, cnpjs=[EST_A])
    finally:
        ARQUIVOS[1] = {'nome': 'B91 6485264632.pdf', 'base64': base64.b64encode(PDF).decode()}
        ARQUIVOS[2] = {'nome': 'fora.pdf', 'base64': base64.b64encode(PDF2).decode()}
    check('dois erros, nenhum arquivo', r['erros'] == 2 and r['baixados'] == 0
          and not [p for p in pasta.rglob('*.pdf*')], r)
    check('motivos', any('tamanho' in m for m in r['motivos_erro']) and any('base64' in m for m in r['motivos_erro']),
          dict(r['motivos_erro']))


def test_registro_e_busca(a, pasta):
    print('\n7. Registro no banco')
    svc.executar(a, None, pasta=pasta, baixar=True, log=lambda m: None)
    vig = FapVigenciaCnpj(law_firm_id=a, employer_cnpj='11.222.333/0001-81', vigencia_year='2026')
    db.session.add(vig)
    db.session.flush()
    deferido = Benefit(law_firm_id=a, benefit_number='648.526.463-2', fap_vigencia_cnpj_id=vig.id,
                       first_instance_status='indeferido', second_instance_status='deferido')
    sem_doc = Benefit(law_firm_id=a, benefit_number='1112223334', fap_vigencia_cnpj_id=vig.id,
                      first_instance_status='indeferido', second_instance_status='rejected')
    db.session.add_all([deferido, sem_doc])
    db.session.commit()

    r = svc.registrar(a, pasta, log=lambda m: None)
    linhas = FapContestacaoAnexo.query.filter_by(law_firm_id=a).order_by(FapContestacaoAnexo.anexo_id).all()
    check('um registro por anexo', len(linhas) == 2 and r['novos'] == 2, r)
    check('ligado ao benefício pela vigência + CNPJ + NB', all(l.benefit_id == deferido.id for l in linhas),
          [l.benefit_id for l in linhas])
    check('instância do recálculo', all(l.instancia == 2 for l in linhas), [l.instancia for l in linhas])
    hismed = linhas[0]
    check('HISMED com CID', hismed.tipo_documento == 'HISMED' and 'M54.5' in (hismed.campos_json or ''),
          (hismed.tipo_documento, hismed.campos_json))
    check('CONBAS', linhas[1].tipo_documento == 'CONBAS', linhas[1].tipo_documento)
    check('texto lido', all(l.texto_status == 'ok' and 'Instituto' in (l.texto or '') for l in linhas))
    r2 = svc.registrar(a, pasta, log=lambda m: None)
    check('2ª rodada não duplica nem relê', r2['novos'] == 0 and r2['textos_lidos'] == 0
          and FapContestacaoAnexo.query.filter_by(law_firm_id=a).count() == 2, r2)

    print('\n8. Busca')
    docs = busca.anexos_do_beneficio(a, benefit_id=deferido.id)
    check('documentos do benefício', len(docs) == 2, docs)
    check('documentos por vigência + CNPJ + NB',
          len(busca.anexos_do_beneficio(a, ano=2026, cnpj=EST_A, nb='6485264632')) == 2)
    indice_no_ar = (r.get('indice') or {}).get('indexados') == 2
    res = busca.pesquisar(a, 'trajeto')
    check(f'termo no texto ({res["fonte"]})', res['total'] == 1 and res['itens'][0]['tipo_documento'] == 'CONBAS', res)
    check('trecho grifado', '<mark>' in (res['itens'][0]['trecho'] or '').lower() if res['itens'] else False)
    check('NB é filtro exato', busca.pesquisar(a, '6485264632')['total'] == 2)
    check('CID', busca.pesquisar(a, cid='M54.5')['total'] == 1)
    check('outro escritório não vê', busca.pesquisar(_B[0], 'trajeto')['total'] == 0)
    if not indice_no_ar:
        print('  (Meilisearch fora do ar: só a busca pelo banco foi testada)')
    else:
        busca.configurar('fap_anexos_inexistente_x', esperar=True)
        busca._estado['cliente'] = None
        import app.services.fap_anexos_busca_service as m
        host = m.MEILISEARCH_HOST
        m.MEILISEARCH_HOST = 'http://127.0.0.1:9'
        try:
            res = busca.pesquisar(a, 'trajeto')
            check('índice fora do ar cai para o banco', res['fonte'] == 'banco' and res['total'] == 1, res)
        finally:
            m.MEILISEARCH_HOST = host
            busca._estado['cliente'] = None
            busca.configurar('fap_anexos_test', esperar=True)

    test_telas(a, pasta, deferido, sem_doc)
    doc = busca.documentacao_por_resultado(a)
    check('recorte da 2ª instância (os anexos são do recálculo de 2ª): com doc deferido, sem doc indeferido',
          doc[2]['com']['deferido'] == 1 and doc[2]['sem']['indeferido'] == 1, doc)
    check('na 1ª instância os dois ficam sem documento', doc[1]['sem']['indeferido'] == 2 and doc[1]['com']['decididos'] == 0, doc)
    FapContestacaoAnexo.query.filter_by(law_firm_id=a).delete()
    Benefit.query.filter_by(law_firm_id=a).delete()
    FapVigenciaCnpj.query.filter_by(law_firm_id=a).delete()
    db.session.commit()


def _logar(client, firm_id, email):
    u = User.query.filter_by(email=email).first()
    if u is None:
        u = User(law_firm_id=firm_id, name='adv anexos', role='admin', is_active=True, email=email)
        u.set_password('x')
        db.session.add(u)
        db.session.commit()
    with client.session_transaction() as sess:
        sess['user_id'] = u.id
        sess['law_firm_id'] = firm_id
        sess['user_role'] = u.role
        sess['user_module_permissions'] = u.get_module_permissions()


def test_telas(a, pasta, deferido, sem_doc):
    print('\n9. Telas')
    pasta_real = svc.PASTA_PADRAO / str(a)
    if pasta_real.exists():
        shutil.rmtree(pasta_real)
    shutil.copytree(pasta, pasta_real)
    try:
        c = app.test_client()
        _logar(c, a, 'adv_a__test_anexos@example.com')
        r = c.get(f'/disputes-center/benefits/{deferido.id}/anexos')
        anexos = (r.get_json() or {}).get('anexos') or []
        check('documentos do benefício', r.status_code == 200 and len(anexos) == 2 and all(x['url'] for x in anexos),
              (r.status_code, anexos))
        r = c.get(anexos[0]['url']) if anexos else None
        check('arquivo do anexo', r is not None and r.status_code == 200 and r.data[:4] == b'%PDF',
              r.status_code if r else None)
        pagina = f"/disputes-center/anexos/{anexos[0]['id']}/pagina/1.png" if anexos else ''
        r = c.get(pagina)
        check('página como imagem PNG', r.status_code == 200 and r.data[:8] == b'\x89PNG\r\n\x1a\n'
              and anexos[0]['paginas'] == 1, (r.status_code, anexos[0].get('paginas') if anexos else None))
        check('página que não existe: 404', c.get(pagina.replace('/1.png', '/9.png')).status_code == 404)
        r = c.get('/disputes-center/api/list?quick_documento=com&vigencia_id=')
        j = r.get_json() or {}
        ids = [x['id'] for x in j.get('data') or []]
        check('filtro "com documento"', r.status_code == 200 and ids == [deferido.id]
              and j['data'][0]['anexos_count'] == 2, (r.status_code, ids))
        r = c.get('/disputes-center/api/list?quick_documento=sem')
        check('filtro "sem documento"', [x['id'] for x in (r.get_json() or {}).get('data') or []] == [sem_doc.id])
        doc = ((r.get_json() or {}).get('filtered_stats') or {}).get('documentacao')
        check('recorte vai na 1ª página da lista', doc is not None and '1' in {str(k) for k in doc}, doc)

        db.session.add(FapCalculoItem(law_firm_id=a, ano_vigencia=2026, cnpj=EST_A, cnpj_raiz=EST_A[:8], tipo='B91',
                                      identificador='6485264632', calculo_id=101))
        db.session.commit()
        r = c.get('/fap-panel/calculo/?vigencia=2026')
        check('linha do cálculo FAP mostra os documentos', r.status_code == 200
              and b'Documentos enviados ao FAP' in r.data and b'B91 6485264632.pdf' in r.data, r.status_code)

        # MCP e API: a mesma resposta, conferida contra os campos declarados da API.
        from app.services import public_api_campos as campos_api
        from mcp_server.tools import fap_anexos as ferramenta
        busca_mcp = ferramenta.search_fap_attachments_handler(a, 'trajeto', app_public_url='https://x')
        item = (busca_mcp.get('itens') or [{}])[0]
        check('MCP: pesquisa com trecho «» e link', busca_mcp['total_encontrado'] == 1 and '«' in (item.get('trecho') or '')
              and (item.get('url_arquivo') or '').startswith('https://x/disputes-center/anexos/'), busca_mcp)
        check('MCP: uma imagem por página', item.get('url_paginas') == [
            f"https://x/disputes-center/anexos/{item.get('documento_id')}/pagina/1.png"], item.get('url_paginas'))
        check('MCP: campos da pesquisa = declarados na API', not campos_api.conferir(busca_mcp, campos_api.FAP_DOCUMENTOS),
              campos_api.conferir(busca_mcp, campos_api.FAP_DOCUMENTOS))
        lido = ferramenta.read_fap_attachment_handler(a, item.get('documento_id'), app_public_url='https://x')
        check('MCP: ler documento traz o texto', 'trajeto' in (lido.get('texto') or ''), lido)
        lido.pop('dica', None)
        check('MCP: campos do documento = declarados na API', not campos_api.conferir(lido, campos_api.FAP_DOCUMENTO),
              campos_api.conferir(lido, campos_api.FAP_DOCUMENTO))
        try:
            ferramenta.search_fap_attachments_handler(a)
            check('MCP: sem filtro recusa', False)
        except Exception as e:
            check('MCP: sem filtro recusa', 'filtro' in str(e))

        c2 = app.test_client()
        _logar(c2, _B[0], 'adv_b__test_anexos@example.com')
        check('outro escritório: benefício 404', c2.get(f'/disputes-center/benefits/{deferido.id}/anexos').status_code == 404)
        check('outro escritório: arquivo 404', c2.get(anexos[0]['url']).status_code == 404 if anexos else False)
        check('outro escritório: página 404', c2.get(pagina).status_code == 404)
        try:
            ferramenta.read_fap_attachment_handler(_B[0], item.get('documento_id'))
            check('MCP: outro escritório não lê', False)
        except Exception as e:
            check('MCP: outro escritório não lê', 'não encontrado' in str(e))
    finally:
        shutil.rmtree(pasta_real, ignore_errors=True)


def test_ocr(a, pasta):
    print('\n10. OCR dos digitalizados')
    import fitz
    from app.services import fap_anexos_conteudo as conteudo
    check('tipo pelo nome', conteudo.tipo_pelo_nome('Dados Básicos da Concessão - CONBAS.pdf') == 'CONBAS'
          and conteudo.tipo_pelo_nome('CAT 2024.581997.5-01.pdf') == 'CAT'
          and conteudo.tipo_pelo_nome('6485264632_vinculado ao CNPJ da empresa.pdf') == 'OUTRO'
          and conteudo.tipo_pelo_nome('Vinculo_CNIS_16822716360.doc') == 'CNIS')
    # PDF só de imagem: o texto vira figura e a página não tem camada de texto.
    origem = fitz.open()
    pg = origem.new_page()
    pg.insert_text((40, 80), 'Historico de Pericias Medicas HISMED', fontsize=18)
    pg.insert_text((40, 120), 'Diagnostico M54.5 lombalgia trajeto', fontsize=18)
    imagem = pg.get_pixmap(dpi=150).tobytes('png')
    digitalizado = fitz.open()
    digitalizado.new_page().insert_image(fitz.Rect(0, 0, 595, 842), stream=imagem)
    destino = pasta / '2026' / EST_A / '777' / '9 - laudo digitalizado.pdf'
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(digitalizado.tobytes())
    check('o PDF de teste não tem texto', len(conteudo.extrair_texto(str(destino))) < conteudo.MINIMO_DE_TEXTO)
    linha = FapContestacaoAnexo(law_firm_id=a, anexo_id=9, ano_vigencia=2026, cnpj=EST_A, cnpj_raiz=EST_A[:8],
                                recalculo_id=777, nb='6485264632', nome='laudo digitalizado.pdf',
                                arquivo=str(destino.relative_to(pasta)), texto_status='sem_texto',
                                tipo_documento='OUTRO')
    db.session.add(linha)
    db.session.commit()
    r = svc.aplicar_ocr(a, pasta, log=lambda m: None)
    db.session.refresh(linha)
    check('OCR leu o texto', r['lidos'] == 1 and 'lombalgia' in (linha.texto or '').lower(), (r, linha.texto))
    check('tipo pelo texto do OCR e CID', linha.tipo_documento == 'HISMED' and 'M54.5' in (linha.campos_json or ''),
          (linha.tipo_documento, linha.campos_json))
    check('marca de OCR na busca', busca.anexos_do_beneficio(a, ano=2026, cnpj=EST_A, nb='6485264632')[0]['texto_por_ocr'])
    r2 = svc.aplicar_ocr(a, pasta, log=lambda m: None)
    check('não tenta de novo', r2['candidatos'] == 0, r2)
    FapContestacaoAnexo.query.filter_by(law_firm_id=a).delete()
    db.session.commit()


def test_expirada(a, pasta):
    print('\n5. Sessão expirada')
    LISTAS[101] = 'expirada'
    try:
        codigo = script.main(['--escritorio', str(a), '--baixar', '--pasta', str(pasta), '--workers', '1'],
                             svc=object())
    finally:
        LISTAS[101] = [_anexo(1, 'B91 6485264632.pdf', PDF), _anexo(2, '../../fora.pdf', PDF2)]
    check('script sai com 2', codigo == script.EXIT_EXPIRADA, codigo)


if __name__ == '__main__':
    orig = (client.listar_anexos, client.baixar_anexo)
    client.listar_anexos, client.baixar_anexo = _listar, _baixar
    try:
        with app.app_context():
            a, _b = _setup()
            _B.append(_b)
            busca.configurar('fap_anexos_test', esperar=True)
            try:
                busca._indice().delete_documents_by_filter(f'law_firm_id = {a}')
            except Exception:
                pass
            try:
                test_recalculos(a)
                for teste in (test_simulacao, test_baixar, test_arquivo_ruim, test_registro_e_busca, test_ocr, test_expirada):
                    pasta = Path(tempfile.mkdtemp(prefix='fap_anexos_test_'))
                    try:
                        teste(a, pasta)
                    finally:
                        shutil.rmtree(pasta, ignore_errors=True)
            finally:
                _cleanup()
    finally:
        client.listar_anexos, client.baixar_anexo = orig
    print('\n' + ('✅ Todos os testes passaram' if not _falhas else f'❌ {len(_falhas)} falha(s): {_falhas}'))
    sys.exit(1 if _falhas else 0)
