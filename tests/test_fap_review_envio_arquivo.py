#!/usr/bin/env python3
"""
Teste do envio do arquivo da petição para a revisão pedida pelo Claude (RPI-37).

    uv run python tests/test_fap_review_envio_arquivo.py

Cobre:
  1. Link de envio: token só em hash, validade de 2 h, estados (válido,
     expirado, usado, inexistente) e recusas antes de criar (Id inválido,
     petição bloqueada)
  2. Contexto da página: petição existente × nova, próxima revisão
  3. Receber o arquivo: revisão pelo caminho da tela com o arquivo original,
     link consumido uma vez só, recusas (tipo mentindo, vazio, grande demais,
     petição bloqueada, revisão em andamento) que deixam o link valendo
  4. Página pública /revisao/enviar/<token>: abre sem login, estados do link,
     POST devolve JSON para a página e para o curl do Claude
  5. Link do Drive: formatos de link, download conferido, mensagem de
     compartilhamento quando não há acesso, Google Docs exportado como DOCX
  6. Correções da revisão final: nome em disco único, erro de banco vira 409
     sem deixar arquivo, token conferido antes de ler o corpo, id do Drive
     validado, nome com ponto sem extensão, usuário desativado

A IA é trocada por um agente falso e o e-mail é interceptado. Os dados criados
são removidos ao final.
"""

import hashlib
import os
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import (
    db,
    FapReviewAuditLog,
    FapReviewExecution,
    FapReviewPetition,
    LawFirm,
    User,
)
import app.blueprints.fap_review as fap_review_bp
from app.agents.fap_review.reviewer_agent import PetitionReviewResult
from app.services import email_service

_falhas = []
IDENT = '990000000041'
IDENT_NOVA = '990000000042'
IDENT_BLOQUEADA = '990000000043'
IDENTS = (IDENT, IDENT_NOVA, IDENT_BLOQUEADA)


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _payload(findings=None):
    findings = findings or []
    return {
        'tokens_used': 100, 'cost_usd': 0.01, 'findings': findings,
        'executive_summary': {
            'total_findings': len(findings), 'critical_findings': 0, 'moderate_findings': 0,
            'formal_findings': 0, 'correction_priority': 'baixa',
        },
    }


class _AgenteFalso:
    """No lugar do FapPetitionReviewerAgent: devolve um resultado vazio e guarda o que recebeu."""
    recebidos: list = []

    def __init__(self, **kwargs):
        pass

    def load_reference_documents(self, **kwargs):
        pass

    async def review_petition_single_version(self, **kwargs):
        _AgenteFalso.recebidos.append(kwargs)
        return PetitionReviewResult(analysis_type='single_version', **_payload())

    async def review_petition_comparative(self, **kwargs):
        _AgenteFalso.recebidos.append(kwargs)
        return PetitionReviewResult(analysis_type='comparative', **_payload())


_emails: list = []


def _email_falso(to, subject, html, text=None, **kwargs):
    _emails.append({'to': to, 'subject': subject, 'html': html})
    return True


def _esperar(revisao_id: int) -> FapReviewExecution:
    for t in threading.enumerate():
        if t.name == f'fap-review-{revisao_id}':
            t.join(timeout=60)
    db.session.rollback()  # MySQL REPEATABLE READ: enxergar o commit da thread
    return FapReviewExecution.query.get(revisao_id)


def _peticao(law_firm_id, user_id, ident, status='in_review', revisoes=0):
    p = FapReviewPetition(law_firm_id=law_firm_id, created_by_id=user_id,
                          office_document_identifier=ident, title=f'Petição {ident}',
                          workflow_status=status)
    db.session.add(p)
    db.session.flush()
    for n in range(1, revisoes + 1):
        db.session.add(FapReviewExecution(
            law_firm_id=law_firm_id, user_id=user_id, petition_id=p.id, execution_type='revision',
            status='completed', revision_number=n, law_firm_document_identifier=ident,
            completed_at=datetime.now()))
    db.session.commit()
    return p


def test_link(law_firm_id, user_id):
    print('\n1) Link de envio')
    from app.services.fap_review_upload_service import (
        LINK_VALIDITY, create_upload_link, find_link,
    )
    link, token = create_upload_link(law_firm_id, user_id, IDENT, 'Petição do link')
    check('token longo o bastante', len(token) >= 40, str(len(token)))
    check('banco guarda só o hash do token',
          link.token_hash == hashlib.sha256(token.encode()).hexdigest() and link.token_hash != token)
    check('validade de 2 horas', link.expires_at - link.created_at == timedelta(hours=2) == LINK_VALIDITY,
          str(link.expires_at - link.created_at))
    achado, estado = find_link(token)
    check('link novo é válido', estado == 'valido' and achado.id == link.id, estado)
    check('token qualquer é inexistente', find_link('lixo') == (None, 'inexistente'))

    link.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    check('link vencido é expirado', find_link(token)[1] == 'expirado')
    link.expires_at = datetime.utcnow() + timedelta(hours=1)
    link.used_at = datetime.utcnow()
    db.session.commit()
    check('link usado é usado', find_link(token)[1] == 'usado')

    try:
        create_upload_link(law_firm_id, user_id, 'FAP-1')
        check('Id não numérico para petição nova é recusado', False, 'passou')
    except ValueError:
        check('Id não numérico para petição nova é recusado', True)

    _peticao(law_firm_id, user_id, IDENT_BLOQUEADA, status='awaiting_approval')
    try:
        create_upload_link(law_firm_id, user_id, IDENT_BLOQUEADA)
        check('petição aguardando aprovação é recusada', False, 'passou')
    except ValueError as e:
        check('petição aguardando aprovação é recusada', 'não aceita nova revisão' in str(e), str(e))


def test_contexto_pagina(law_firm_id, user_id):
    print('\n2) Contexto da página')
    from app.services.fap_review_upload_service import create_upload_link, link_page_context
    p = _peticao(law_firm_id, user_id, IDENT, revisoes=2)
    link, _ = create_upload_link(law_firm_id, user_id, IDENT, 'título ignorado')
    ctx = link_page_context(link)
    check('petição existente: próxima é a revisão 3', ctx['proxima_revisao'] == 3, str(ctx['proxima_revisao']))
    check('petição existente: não é nova', ctx['peticao_nova'] is False)
    check('petição existente: título da petição', ctx['titulo'] == p.title, ctx['titulo'])
    check('mostra quem pediu', ctx['pedido_por'] == User.query.get(user_id).name, ctx['pedido_por'])
    check('sem bloqueio nem revisão em andamento',
          ctx['bloqueio'] is None and ctx['em_andamento'] is None)

    link, _ = create_upload_link(law_firm_id, user_id, IDENT_NOVA, 'Impugnação nova')
    ctx = link_page_context(link)
    check('Id novo: petição nova, revisão 1',
          ctx['peticao_nova'] is True and ctx['proxima_revisao'] == 1, str(ctx))
    check('Id novo: título informado', ctx['titulo'] == 'Impugnação nova', ctx['titulo'])


def _docx_bytes(texto: str) -> bytes:
    import io
    from docx import Document
    doc = Document()
    doc.add_paragraph(texto)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


PDF_MINIMO = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


def _arquivo(conteudo: bytes, nome: str):
    import io
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(conteudo), filename=nome)


def _recusa(token, arquivo):
    from app.services.fap_review_upload_service import UploadRecusado, receive_upload
    try:
        r = receive_upload(token, arquivo)
        return None, r
    except UploadRecusado as e:
        return e, None


def test_receber(law_firm_id, user_id):
    print('\n3) Receber o arquivo')
    from app.services import fap_review_upload_service as up
    from app.services.fap_review_service import start_text_review, upload_directory

    _emails.clear()
    _AgenteFalso.recebidos = []
    link, token = up.create_upload_link(law_firm_id, user_id, IDENT, 'Impugnação pelo link')
    erro, r = _recusa(token, _arquivo(_docx_bytes('Texto da petição pelo link de envio.'),
                                      'Petição SENDAS.docx'))
    check('DOCX aceito', erro is None, str(erro and erro.mensagem))
    if erro:
        return
    check('revisão 1 da petição nova', r['numero_revisao'] == 1, str(r))
    check('pergunta pronta para o Claude',
          r['pergunta_claude'] == f'Como está a revisão 1 da petição {IDENT}?', r['pergunta_claude'])
    check('devolve o nome do arquivo recebido', r['arquivo'] == 'Petição SENDAS.docx', r.get('arquivo'))
    check('traz o link da revisão', f'/fap-review/revision/{r["revisao_id"]}' in r['link'])
    execution = _esperar(r['revisao_id'])
    check('execução concluída pela thread da tela', execution.status == 'completed',
          f'{execution.status} {execution.error_message}')
    check('agente recebeu o texto do DOCX (extraído como na tela)',
          'pelo link de envio' in ((_AgenteFalso.recebidos or [{}])[0].get('petition_text') or ''))
    check('nome original guardado na execução', execution.main_document_filename == 'Petição SENDAS.docx',
          execution.main_document_filename)
    check('arquivo salvo em disco', Path(execution.main_document_path).exists())
    achado, estado = up.find_link(token)
    check('link consumido e ligado à execução',
          estado == 'usado' and achado.execution_id == execution.id, estado)
    check('e-mail a quem pediu', len(_emails) == 1, str(len(_emails)))

    erro, _ = _recusa(token, _arquivo(_docx_bytes('de novo'), 'outra.docx'))
    check('segundo envio pelo mesmo link: 409', erro is not None and erro.status_http == 409,
          str(erro and erro.status_http))

    # Corrida: o segundo envio passou da checagem do link antes de o primeiro
    # gravar. Quem barra é o UPDATE ... WHERE used_at IS NULL na transação.
    find_original = up.find_link
    up.find_link = lambda t: (find_original(t)[0], 'valido')
    revisoes_antes = FapReviewExecution.query.filter_by(petition_id=execution.petition_id).count()
    try:
        erro, _ = _recusa(token, _arquivo(_docx_bytes('corrida'), 'corrida.docx'))
    finally:
        up.find_link = find_original
    db.session.rollback()
    check('envio simultâneo: 409 e nenhuma revisão a mais',
          erro is not None and erro.status_http == 409
          and FapReviewExecution.query.filter_by(petition_id=execution.petition_id).count() == revisoes_antes,
          str(erro and erro.status_http))

    link, token = up.create_upload_link(law_firm_id, user_id, IDENT)
    pasta = upload_directory(law_firm_id, 'revisions')
    antes = len(list(pasta.iterdir()))
    erro, _ = _recusa(token, _arquivo(PDF_MINIMO, 'x.docx'))
    check('PDF com nome .docx: 400', erro is not None and erro.status_http == 400, str(erro and erro.status_http))
    erro, _ = _recusa(token, _arquivo(b'', 'vazio.pdf'))
    check('arquivo vazio: 400', erro is not None and erro.status_http == 400, str(erro and erro.status_http))
    erro, _ = _recusa(token, _arquivo(b'GIF89a....', 'foto.gif'))
    check('tipo não aceito: 400', erro is not None and erro.status_http == 400, str(erro and erro.status_http))
    erro, _ = _recusa(token, None)
    check('sem arquivo: 400', erro is not None and erro.status_http == 400, str(erro and erro.status_http))
    limite = up.MAX_UPLOAD_BYTES
    up.MAX_UPLOAD_BYTES = 1024
    try:
        erro, _ = _recusa(token, _arquivo(b'%PDF-1.4\n' + b'0' * 4096, 'grande.pdf'))
    finally:
        up.MAX_UPLOAD_BYTES = limite
    check('acima do limite: 413', erro is not None and erro.status_http == 413, str(erro and erro.status_http))
    check('recusas não deixaram arquivo na pasta', len(list(pasta.iterdir())) == antes)
    check('recusas deixaram o link valendo', up.find_link(token)[1] == 'valido')

    petition = FapReviewPetition.query.filter_by(law_firm_id=law_firm_id, office_document_identifier=IDENT).first()
    petition.workflow_status = 'awaiting_approval'
    db.session.commit()
    erro, _ = _recusa(token, _arquivo(PDF_MINIMO, 'p.pdf'))
    check('petição bloqueada depois do link: 403', erro is not None and erro.status_http == 403,
          str(erro and erro.status_http))
    check('e o link continua valendo', up.find_link(token)[1] == 'valido')
    petition.workflow_status = 'in_review'
    db.session.commit()

    aberta = start_text_review(law_firm_id, user_id, IDENT, 'Texto em revisão. ' * 20)
    antes = len(list(pasta.iterdir()))
    erro, _ = _recusa(token, _arquivo(PDF_MINIMO, 'p.pdf'))
    check('revisão em andamento: 409 apontando a que roda',
          erro is not None and erro.status_http == 409 and erro.extra.get('revisao_id') == aberta['revisao_id'],
          str(erro and (erro.status_http, erro.extra)))
    check('arquivo não guardado', len(list(pasta.iterdir())) == antes)
    check('link continua valendo para reenviar', up.find_link(token)[1] == 'valido')
    em_andamento = FapReviewExecution.query.get(aberta['revisao_id'])
    em_andamento.status = 'failed'
    db.session.commit()

    _AgenteFalso.recebidos = []
    erro, r = _recusa(token, _arquivo(PDF_MINIMO, 'peticao.pdf'))
    check('PDF aceito', erro is None, str(erro and erro.mensagem))
    if not erro:
        _esperar(r['revisao_id'])
        check('PDF vai como anexo, sem texto extraído (como na tela)',
              _AgenteFalso.recebidos and _AgenteFalso.recebidos[0].get('petition_text') is None)

    link, token = up.create_upload_link(law_firm_id, user_id, IDENT_NOVA)
    erro, r = _recusa(token, _arquivo(b'Texto puro da peticao. ' * 20, 'Petição'))
    check('nome sem extensão: o tipo sai do conteúdo e a revisão abre', erro is None, str(erro and erro.mensagem))
    if not erro:
        execution = _esperar(r['revisao_id'])
        check('arquivo salvo com extensão', Path(execution.main_document_path).suffix == '.txt',
              execution.main_document_path)


def test_pagina(law_firm_id, user_id):
    print('\n4) Página pública de envio')
    from app.services import fap_review_upload_service as up

    client = app.test_client()  # sem sessão: o link é a autorização
    link, token = up.create_upload_link(law_firm_id, user_id, IDENT_NOVA, 'Impugnação da página')
    r = client.get(f'/revisao/enviar/{token}')
    body = r.get_data(as_text=True)
    check('GET abre sem login', r.status_code == 200, str(r.status_code))
    check('mostra o Id Wrike, a revisão e o título',
          IDENT_NOVA in body and 'revisão 1' in body and 'Impugnação da página' in body)
    check('é a página B ("Confira e envie o arquivo")', 'Confira e envie o arquivo' in body)
    check('não é guardada em cache', 'no-store' in (r.headers.get('Cache-Control') or ''))

    r = client.get('/revisao/enviar/token-que-nao-existe')
    check('token inexistente: 404 sem dizer de quem é',
          r.status_code == 404 and IDENT_NOVA not in r.get_data(as_text=True), str(r.status_code))

    link2, token2 = up.create_upload_link(law_firm_id, user_id, IDENT_NOVA)
    link2.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    r = client.get(f'/revisao/enviar/{token2}')
    check('link expirado: 410', r.status_code == 410, str(r.status_code))

    import io
    r = client.post(f'/revisao/enviar/{token}', data={}, content_type='multipart/form-data')
    check('POST sem arquivo: 400 em JSON', r.status_code == 400 and r.get_json() and r.get_json()['ok'] is False,
          str(r.status_code))
    r = client.post(f'/revisao/enviar/{token}',
                    data={'arquivo': (io.BytesIO(_docx_bytes('Petição pela página.')), 'peticao.docx')},
                    content_type='multipart/form-data')
    j = r.get_json() or {}
    check('POST com DOCX: 200 e pergunta para o Claude',
          r.status_code == 200 and j.get('ok') is True and j.get('pergunta_claude'), str(r.status_code))
    if j.get('revisao_id'):
        _esperar(j['revisao_id'])
    r = client.post(f'/revisao/enviar/{token}',
                    data={'arquivo': (io.BytesIO(_docx_bytes('De novo.')), 'peticao.docx')},
                    content_type='multipart/form-data')
    check('POST repetido: 409 em JSON', r.status_code == 409 and (r.get_json() or {}).get('ok') is False,
          str(r.status_code))
    r = client.get(f'/revisao/enviar/{token}')
    check('link usado: página diz que já foi usado e leva à revisão',
          r.status_code == 200 and 'já foi usado' in r.get_data(as_text=True)
          and f'/fap-review/revision/{j.get("revisao_id")}' in r.get_data(as_text=True))

    logado = app.test_client()
    with logado.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['law_firm_id'] = law_firm_id
    link3, token3 = up.create_upload_link(law_firm_id, user_id, IDENT_NOVA)
    r = logado.get(f'/revisao/enviar/{token3}')
    check('logado também abre (não redireciona)', r.status_code == 200, str(r.status_code))


def test_drive(law_firm_id):
    print('\n5) Link do Drive')
    from app.services import fap_review_upload_service as up
    from app.services import impugnacao_import_service as imp
    from app.services.fap_review_service import upload_directory

    casos = {
        'https://drive.google.com/file/d/1AbC_d-9/view?usp=sharing': ('1AbC_d-9', False),
        'https://docs.google.com/document/d/1DoC_x/edit': ('1DoC_x', True),
        'https://drive.google.com/open?id=1OpEn': ('1OpEn', False),
        'https://drive.google.com/uc?id=1UcAbc&export=download': ('1UcAbc', False),
    }
    for link, esperado in casos.items():
        check(f'id do link {link[:40]}…', up.drive_file_id_from_link(link) == esperado,
              str(up.drive_file_id_from_link(link)))
    try:
        up.drive_file_id_from_link('https://exemplo.com/arquivo.pdf')
        check('link sem id do Drive é recusado', False, 'passou')
    except ValueError as e:
        check('link sem id do Drive é recusado', 'drive.google.com/file/d/' in str(e), str(e))

    pasta = upload_directory(law_firm_id, 'revisions')
    original = imp.download_drive_file
    try:
        def baixa_docx(file_id, dest_dir, *, law_firm_id, gdoc_como=None, timeout=90):
            destino = os.path.join(dest_dir, f'drive_{file_id}.docx')
            open(destino, 'wb').write(_docx_bytes('Petição que veio do Drive.'))
            return destino, 'Petição do Drive.docx', 'x'
        imp.download_drive_file = baixa_docx
        caminho, nome = up.download_review_file_from_drive(
            'https://drive.google.com/file/d/1Arquivo/view', law_firm_id)
        check('arquivo do Drive baixado e conferido', Path(caminho).exists() and nome == 'Petição do Drive.docx',
              f'{caminho} {nome}')
        Path(caminho).unlink(missing_ok=True)

        def sem_acesso(file_id, dest_dir, *, law_firm_id, gdoc_como=None, timeout=90):
            raise imp.DriveAccessError('sem compartilhamento')
        imp.download_drive_file = sem_acesso
        try:
            up.download_review_file_from_drive('https://drive.google.com/file/d/1Fechado/view', law_firm_id)
            check('sem acesso: mensagem de compartilhamento', False, 'passou')
        except ValueError as e:
            check('sem acesso: mensagem de compartilhamento',
                  'intellexia-drive@intellexia-503416.iam.gserviceaccount.com' in str(e)
                  and 'qualquer pessoa com o link' in str(e), str(e))

        antes = len(list(pasta.iterdir()))
        def baixa_html(file_id, dest_dir, *, law_firm_id, gdoc_como=None, timeout=90):
            destino = os.path.join(dest_dir, f'drive_{file_id}.pdf')
            open(destino, 'wb').write(b'<!DOCTYPE html><html>login</html>')
            return destino, 'coisa.pdf', 'x'
        imp.download_drive_file = baixa_html
        try:
            up.download_review_file_from_drive('https://drive.google.com/file/d/1Html/view', law_firm_id)
            check('conteúdo que não é petição é recusado', False, 'passou')
        except ValueError as e:
            check('conteúdo que não é petição é recusado', 'PDF, DOCX ou TXT' in str(e), str(e))
        check('e não fica arquivo na pasta', len(list(pasta.iterdir())) == antes)
    finally:
        imp.download_drive_file = original

    import requests as _requests

    class _Resposta:
        status_code = 200
        headers = {'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                   'Content-Disposition': "attachment; filename*=UTF-8''Peti%C3%A7%C3%A3o%20Docs.docx"}
        def __init__(self):
            self._b = _docx_bytes('Petição escrita no Google Docs.')
        def iter_content(self, chunk_size=65536):
            yield self._b
        def close(self):
            pass

    chamadas = []
    get_original = _requests.get
    try:
        def get_falso(url, *a, **k):
            chamadas.append(url)
            return _Resposta()
        _requests.get = get_falso
        caminho, nome = up.download_review_file_from_drive(
            'https://docs.google.com/document/d/1Docs/edit', law_firm_id)
        check('Google Docs exportado como DOCX', any('export?format=docx' in u for u in chamadas), str(chamadas))
        check('nome do Docs vem do download', nome == 'Petição Docs.docx', nome)
        check('arquivo do Docs conferido como DOCX', Path(caminho).suffix == '.docx' and Path(caminho).exists())
        Path(caminho).unlink(missing_ok=True)
    finally:
        _requests.get = get_original


def test_correcoes(law_firm_id, user_id):
    print('\n6) Correções da revisão final')
    from sqlalchemy.exc import IntegrityError
    from app.services import fap_review_upload_service as up
    from app.services import fap_review_service as svc

    check('nome em disco não repete no mesmo segundo',
          up._nome_em_disco('peticao.pdf', 'pdf') != up._nome_em_disco('peticao.pdf', 'pdf'))

    pasta = svc.upload_directory(law_firm_id, 'revisions')
    link, token = up.create_upload_link(law_firm_id, user_id, IDENT_NOVA)
    original = svc.open_file_review
    try:
        def colide(*a, **k):
            raise IntegrityError('INSERT', {}, Exception('1062 Duplicate entry'))
        svc.open_file_review = colide
        antes = len(list(pasta.iterdir()))
        erro, _ = _recusa(token, _arquivo(PDF_MINIMO, 'p.pdf'))
        check('chave duplicada no banco (envio duplo, petição nova): 409',
              erro is not None and erro.status_http == 409, str(erro and erro.status_http))
        check('e o arquivo não fica na pasta', len(list(pasta.iterdir())) == antes)

        def quebra(*a, **k):
            raise RuntimeError('banco fora')
        svc.open_file_review = quebra
        r = app.test_client().post(f'/revisao/enviar/{token}', data={'arquivo': (__import__('io').BytesIO(PDF_MINIMO), 'p.pdf')},
                                   content_type='multipart/form-data')
        check('erro inesperado: 500 em JSON (o curl lê)', r.status_code == 500 and (r.get_json() or {}).get('ok') is False,
              str(r.status_code))
        check('e o arquivo não fica na pasta', len(list(pasta.iterdir())) == antes)
    finally:
        svc.open_file_review = original
        db.session.rollback()

    from flask import Request
    leituras = []
    carregar = Request._load_form_data
    def contar(self):
        leituras.append(1)
        return carregar(self)
    Request._load_form_data = contar
    try:
        app.test_client().post('/revisao/enviar/token-invalido', data={'arquivo': (__import__('io').BytesIO(b'x' * 1000), 'a.pdf')},
                               content_type='multipart/form-data')
    finally:
        Request._load_form_data = carregar
    check('token inválido: o corpo do envio nem é lido', leituras == [], str(leituras))

    for ruim in ('https://drive.google.com/open?id=abc/../files', 'https://drive.google.com/uc?id=x?y=1'):
        try:
            up.drive_file_id_from_link(ruim)
            check(f'id do Drive com caractere estranho recusado ({ruim[-12:]})', False, 'passou')
        except ValueError:
            check(f'id do Drive com caractere estranho recusado ({ruim[-12:]})', True)

    caminho = pasta / 'teste_nome_com_ponto.part'
    caminho.write_bytes(_docx_bytes('conteúdo'))
    try:
        check('nome com ponto sem extensão vale pelo conteúdo',
              up.validate_review_file(caminho, 'Petição 5001234-56.2024') == 'docx')
    except up.UploadRecusado as e:
        check('nome com ponto sem extensão vale pelo conteúdo', False, e.mensagem)
    finally:
        caminho.unlink(missing_ok=True)

    user = User.query.get(user_id)
    link, token = up.create_upload_link(law_firm_id, user_id, IDENT_NOVA)
    user.is_active = False
    db.session.commit()
    try:
        erro, _ = _recusa(token, _arquivo(PDF_MINIMO, 'p.pdf'))
        check('usuário desativado depois do link: 403', erro is not None and erro.status_http == 403,
              str(erro and erro.status_http))
        check('e nada é revisado', FapReviewPetition.query.filter_by(
            law_firm_id=law_firm_id, office_document_identifier=IDENT_NOVA).first() is None)
    finally:
        user.is_active = True
        db.session.commit()


def _limpar(law_firm_id):
    from app.models import FapReviewUploadLink
    FapReviewUploadLink.query.filter(
        FapReviewUploadLink.law_firm_id == law_firm_id,
        FapReviewUploadLink.identifier.in_(IDENTS + ('FAP-1',)),
    ).delete(synchronize_session=False)
    petitions = FapReviewPetition.query.filter(
        FapReviewPetition.law_firm_id == law_firm_id,
        FapReviewPetition.office_document_identifier.in_(IDENTS)).all()
    for p in petitions:
        for e in FapReviewExecution.query.filter_by(petition_id=p.id).all():
            for caminho in (e.main_document_path, e.compared_document_path):
                if caminho:
                    Path(caminho).unlink(missing_ok=True)
            FapReviewAuditLog.query.filter_by(entity_type='execution', entity_id=e.id).delete()
            db.session.delete(e)
        p.latest_revision_id = None
        db.session.flush()
        FapReviewAuditLog.query.filter_by(entity_type='petition', entity_id=p.id).delete()
        db.session.delete(p)
    db.session.commit()


def main():
    with app.app_context():
        firm = LawFirm.query.order_by(LawFirm.id).first()
        user = User.query.filter(User.law_firm_id == firm.id, User.email.isnot(None)).first()
        print(f'Escritório: {firm.id} | usuário: {user.id}')

        _limpar(firm.id)
        originais = (fap_review_bp.FapPetitionReviewerAgent, email_service.send_email,
                     os.environ.get('OPENAI_API_KEY'))
        fap_review_bp.FapPetitionReviewerAgent = _AgenteFalso
        email_service.send_email = _email_falso
        os.environ.setdefault('OPENAI_API_KEY', 'sk-teste')
        try:
            test_link(firm.id, user.id)
            _limpar(firm.id)
            test_contexto_pagina(firm.id, user.id)
            _limpar(firm.id)
            test_receber(firm.id, user.id)
            _limpar(firm.id)
            test_pagina(firm.id, user.id)
            test_drive(firm.id)
            _limpar(firm.id)
            test_correcoes(firm.id, user.id)
        finally:
            fap_review_bp.FapPetitionReviewerAgent, email_service.send_email = originais[:2]
            if originais[2] is None:
                os.environ.pop('OPENAI_API_KEY', None)
            db.session.rollback()
            _limpar(firm.id)
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
