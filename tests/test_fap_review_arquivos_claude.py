#!/usr/bin/env python3
"""
Revisão feita no Claude: arquivos anexados depois de gravar e tabela dos dados dos benefícios.

    uv run python tests/test_fap_review_arquivos_claude.py

O Claude não consegue mandar o arquivo pela chamada do MCP (teria de reescrever
5–10 MB como texto). Ao gravar, a resposta traz um link de uso por campo:
o Claude tenta uma vez com `curl` e, se a rede do ambiente dele falhar, a
pessoa solta os arquivos na página. Os arquivos vão para as colunas que a tela
já usa (documento principal, versão revisada, planilha).

Cobre:
  1. Gravar devolve o link, o curl pronto e onde ficam os anexos
  2. Link: token adulterado, vencido e de revisão que não é do Claude recusados
  3. Página abre sem login; envio por multipart (o mesmo do curl) preenche as
     colunas; campo já preenchido recusado; conteúdo que não bate com o nome
     recusado sem deixar arquivo; "revisada" só na comparação
  4. Dados dos benefícios: conferir_revisao_peticao roda a conferência com a
     lista que o Claude mandou e grava a tabela na revisão; entrada ruim vira
     aviso, sem derrubar a revisão; a tela mostra a tabela

Os dados e arquivos criados são removidos ao final.
"""

import io
import json
import sys
import zipfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402
from app.models import (  # noqa: E402
    db,
    Benefit,
    FapReviewAuditLog,
    FapReviewDraft,
    FapReviewExecution,
    FapReviewPetition,
    LawFirm,
    User,
)
from app.services import fap_review_arquivos_service as arq  # noqa: E402
from app.services import fap_review_claude_service as claude_svc  # noqa: E402

IDENT = '990000000046'
IDENT_COMP = '990000000047'
IDENTS = (IDENT, IDENT_COMP)

_falhas = []
_arquivos = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _resultado():
    return {
        'findings': [], 'missing_documents': [], 'theses': [], 'comparative_changes': [],
        'executive_summary': {'total_findings': 0, 'critical_findings': 0, 'moderate_findings': 0,
                              'formal_findings': 0, 'correction_priority': 'baixa'},
    }


def _docx(texto='Petição de teste') -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', f'<w:document><w:body><w:p><w:r><w:t>{texto}</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


def _xlsx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('xl/workbook.xml', '<workbook/>')
    return buf.getvalue()


def _gravada(firm_id, user_id, ident, modo='revisao', **extra):
    r = claude_svc.conferir(firm_id, user_id, _resultado(), modo, identificador=ident, **extra)
    g = claude_svc.gravar(firm_id, user_id, r['rascunho_id'], identificador=ident, titulo='Teste arquivos',
                          nome_arquivo='peticao.docx')
    return r, g


def _token(link: str) -> str:
    return link.rstrip('/').rsplit('/', 1)[-1]


def test_gravar_devolve_link(firm_id, user_id):
    print('\n1) Gravar devolve o link de envio')
    _r, g = _gravada(firm_id, user_id, IDENT)
    envio = g.get('envio_dos_arquivos') or {}
    check('resposta traz envio_dos_arquivos', bool(envio), str(g)[:300])
    check('link aponta para /revisao/arquivos/', '/revisao/arquivos/' in envio.get('link', ''), envio.get('link', ''))
    check('curl pronto com o campo da petição e o link', 'curl' in envio.get('curl', '')
          and 'peticao=@' in envio['curl'] and envio['link'] in envio['curl'], envio.get('curl', ''))
    check('revisão: sem campo da versão revisada', 'revisada=@' not in envio.get('curl', ''))
    como = envio.get('como_enviar', '')
    check('como enviar: uma tentativa, link se falhar, pastas dos anexos',
          all(t in como.lower() for t in ('uma vez', '/mnt/user-data/uploads', '/mnt/user-data/attachments', 'link')), como)
    check('próximo passo manda seguir o envio', 'envio_dos_arquivos' in g.get('proximo_passo', ''))
    de_novo = claude_svc.gravar(firm_id, user_id, _r['rascunho_id'])
    check('gravar de novo (já gravada) também traz o link', bool((de_novo.get('envio_dos_arquivos') or {}).get('link')))
    return g


def test_link(firm_id, user_id, g):
    print('\n2) Link')
    token = _token(g['envio_dos_arquivos']['link'])
    execution, estado = arq.ler_link(token)
    check('token válido abre a revisão', estado == 'valido' and execution.id == g['revisao_id'], estado)
    check('token adulterado: inexistente', arq.ler_link(token[:-3] + 'abc')[1] == 'inexistente')
    check('vazio: inexistente', arq.ler_link('')[1] == 'inexistente')
    validade = arq.VALIDADE
    arq.VALIDADE = timedelta(seconds=-1)
    try:
        check('vencido: expirado', arq.ler_link(token)[1] == 'expirado')
    finally:
        arq.VALIDADE = validade
    execution.review_origin = None
    db.session.commit()
    try:
        check('revisão que não é do Claude: inexistente', arq.ler_link(token)[1] == 'inexistente')
    finally:
        execution.review_origin = 'claude'
        db.session.commit()


def test_envio(firm_id, user_id, g):
    print('\n3) Envio')
    client = app.test_client()
    link = g['envio_dos_arquivos']['link']
    caminho = '/revisao/arquivos/' + _token(link)

    pagina = client.get(caminho)
    corpo = pagina.get_data(as_text=True)
    check('página abre sem login', pagina.status_code == 200, str(pagina.status_code))
    check('página mostra a petição e o campo da petição', 'Teste arquivos' in corpo and 'name="peticao"' in corpo)
    check('página sem cache', 'no-store' in pagina.headers.get('Cache-Control', ''))

    r = client.post(caminho, data={}, content_type='multipart/form-data')
    check('sem arquivo: 400', r.status_code == 400, r.get_data(as_text=True)[:200])

    r = client.post(caminho, data={'peticao': (io.BytesIO(b'%PDF-1.4 falso'), 'peticao.docx')},
                    content_type='multipart/form-data')
    check('conteúdo diferente do nome: 400', r.status_code == 400, r.get_data(as_text=True)[:200])
    execution = FapReviewExecution.query.get(g['revisao_id'])
    check('recusado não deixa arquivo nem coluna', not execution.main_document_path)

    r = client.post(caminho, data={'revisada': (io.BytesIO(_docx()), 'v2.docx')}, content_type='multipart/form-data')
    check('"revisada" fora da comparação: 400', r.status_code == 400, r.get_data(as_text=True)[:200])

    r = client.post(caminho, data={'peticao': (io.BytesIO(_docx()), 'Petição Empresa X.docx'),
                                   'planilha': (io.BytesIO(_xlsx()), 'beneficios.xlsx')},
                    content_type='multipart/form-data')
    dados = r.get_json() or {}
    check('petição e planilha juntas: 200', r.status_code == 200 and dados.get('ok'), str(dados)[:300])
    db.session.expire_all()
    execution = FapReviewExecution.query.get(g['revisao_id'])
    principal = Path(execution.main_document_path or '')
    _arquivos.append(principal)
    check('documento principal gravado na coluna e no disco', principal.is_file()
          and principal.read_bytes() == _docx(), str(principal))
    check('nome original guardado', execution.main_document_filename == 'Petição Empresa X.docx',
          execution.main_document_filename)
    planilha = json.loads(execution.benefits_spreadsheet_json or '{}')
    _arquivos.append(Path(planilha.get('path', '')))
    check('planilha no formato da tela (name + path)', planilha.get('name') == 'beneficios.xlsx'
          and Path(planilha.get('path', '')).is_file(), str(planilha))
    check('resposta lista o que entrou', sorted(dados.get('recebidos', {})) == ['peticao', 'planilha'], str(dados))

    r = client.post(caminho, data={'peticao': (io.BytesIO(_docx('outra')), 'outra.docx')},
                    content_type='multipart/form-data')
    check('campo já preenchido: 409', r.status_code == 409, r.get_data(as_text=True)[:200])
    db.session.expire_all()
    check('o primeiro arquivo continua', Path(FapReviewExecution.query.get(g['revisao_id']).main_document_path)
          .read_bytes() == _docx())
    pagina = client.get(caminho).get_data(as_text=True)
    check('página mostra os recebidos e nenhum campo aberto', 'name="peticao"' not in pagina
          and 'name="planilha"' not in pagina and 'recebid' in pagina.lower())
    check('auditoria do envio', FapReviewAuditLog.query.filter_by(
        entity_type='execution', entity_id=g['revisao_id'], action='files_attached').count() == 1)

    _r, gc = _gravada(firm_id, user_id, IDENT_COMP, 'comparacao')
    envio = gc.get('envio_dos_arquivos') or {}
    check('comparação: curl com original e revisada', 'peticao=@' in envio.get('curl', '')
          and 'revisada=@' in envio.get('curl', ''), envio.get('curl', ''))
    caminho_c = '/revisao/arquivos/' + _token(envio['link'])
    r = client.post(caminho_c, data={'revisada': (io.BytesIO(_docx('v2')), 'v2.docx')},
                    content_type='multipart/form-data')
    check('comparação: revisada aceita', r.status_code == 200, r.get_data(as_text=True)[:200])
    db.session.expire_all()
    comparada = Path(FapReviewExecution.query.get(gc['revisao_id']).compared_document_path or '')
    _arquivos.append(comparada)
    check('comparação: vai para a coluna da versão revisada', comparada.is_file())


def test_dados_dos_beneficios(firm_id, user_id):
    print('\n4) Tabela dos dados dos benefícios')
    beneficio = Benefit.query.filter(Benefit.law_firm_id == firm_id, Benefit.benefit_number.isnot(None)).first()
    if not beneficio:
        print('  (sem benefício na base local — pulado)')
        return
    lista = [{'numero': beneficio.benefit_number}, {'numero': '9999999999'}]
    r = claude_svc.conferir(firm_id, user_id, _resultado(), 'revisao', identificador=IDENT,
                            beneficios_conferidos=lista)
    payload = json.loads(FapReviewDraft.query.get(r['rascunho_id']).result_json)
    bloco = payload.get('benefits_data_check') or {}
    check('tabela gravada no resultado', bloco.get('total') == 2, str(bloco)[:300])
    situacoes = {i['numero']: i['situacao'] for i in bloco.get('itens', [])}
    check('cada número com a situação da conferência', situacoes.get('9999999999') == 'nao_encontrado'
          and situacoes.get(beneficio.benefit_number) in ('confere', 'divergente'), str(situacoes))
    check('resposta resume a tabela', (r.get('dados_beneficios') or {}).get('total') == 2, str(r)[:300])
    check('sem nome do segurado na tabela gravada', 'segurado_nome' not in json.dumps(bloco))

    ruim = claude_svc.conferir(firm_id, user_id, _resultado(), 'revisao', identificador=IDENT,
                               beneficios_conferidos='não é json')
    check('lista ruim: aviso, revisão segue', bool(ruim.get('rascunho_id')) and bool(ruim.get('aviso_beneficios')),
          str(ruim)[:300])

    g = claude_svc.gravar(firm_id, user_id, r['rascunho_id'])
    client = app.test_client()
    with client.session_transaction() as s:
        user = User.query.get(user_id)
        s['user_id'] = user_id
        s['law_firm_id'] = firm_id
        s['user_role'] = user.role
        s['user_name'] = user.name
    pagina = client.get(f'/fap-review/revision/{g["revisao_id"]}').get_data(as_text=True)
    check('tela mostra a tabela dos dados', 'Dados dos benefícios' in pagina and '9999999999' in pagina)


def _limpar(firm_id, user_id):
    FapReviewDraft.query.filter_by(law_firm_id=firm_id, user_id=user_id).filter(
        FapReviewDraft.identifier.in_(IDENTS)).delete(synchronize_session=False)
    for p in FapReviewPetition.query.filter(FapReviewPetition.law_firm_id == firm_id,
                                            FapReviewPetition.office_document_identifier.in_(IDENTS)).all():
        p.latest_revision_id = None
        db.session.flush()
        for e in FapReviewExecution.query.filter_by(petition_id=p.id).all():
            FapReviewDraft.query.filter_by(saved_execution_id=e.id).delete(synchronize_session=False)
            FapReviewAuditLog.query.filter_by(entity_type='execution', entity_id=e.id).delete()
            db.session.delete(e)
        db.session.flush()
        FapReviewAuditLog.query.filter_by(entity_type='petition', entity_id=p.id).delete()
        db.session.delete(p)
    db.session.commit()
    for f in _arquivos:
        if str(f) not in ('', '.') and f.is_file():
            f.unlink()


def main():
    with app.app_context():
        firm = LawFirm.query.order_by(LawFirm.id).first()
        user = User.query.filter(User.law_firm_id == firm.id).order_by(User.id).first()
        print(f'Escritório: {firm.id} | usuário: {user.id}')
        _limpar(firm.id, user.id)
        try:
            g = test_gravar_devolve_link(firm.id, user.id)
            test_link(firm.id, user.id, g)
            test_envio(firm.id, user.id, g)
            test_dados_dos_beneficios(firm.id, user.id)
        finally:
            db.session.rollback()
            _limpar(firm.id, user.id)
            print('\n(dados de teste removidos)')
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
