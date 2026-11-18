#!/usr/bin/env python3
"""
Anexos das contestações do FAP (`fap_anexos_service`, `scripts/fap_baixar_anexos.py`).

1. Recálculos: só do escritório, só situação ok, sem o cálculo original; filtros.
2. Simulação conta e não grava nada.
3. --baixar grava arquivo, `_anexos.json` e `indice.csv`; a 2ª rodada não baixa de novo.
4. Arquivo com base64 inválido ou tamanho diferente do anunciado não vai ao disco.
5. 403 conta como sem acesso; 401 para a execução (saída 2).
6. Nome vindo do portal não sai da pasta.

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
from app.models import db, FapCalculoEstabelecimento, LawFirm
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


def check(nome, condicao, detalhe=''):
    print(f'  {"✅" if condicao else "❌"} {nome}{"" if condicao or not detalhe else " — " + str(detalhe)}')
    if not condicao:
        _falhas.append(nome)


PDF = b'%PDF-1.7\n' + b'x' * 200
PDF2 = b'%PDF-1.4\n' + b'y' * 50


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
            try:
                test_recalculos(a)
                for teste in (test_simulacao, test_baixar, test_arquivo_ruim, test_expirada):
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
