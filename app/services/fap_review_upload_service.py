"""
Envio do arquivo da petição para a revisão pedida pelo Claude (RPI-37).

O MCP só recebe o que o Claude escreve na chamada: com a petição anexada, ele
reescreveria o texto inteiro como argumento (10–15 min numa petição longa). Aqui
ficam os caminhos para o arquivo original chegar sem isso:

- **link de envio** de uso único — a pessoa abre no navegador e solta o arquivo,
  ou o próprio Claude manda com `curl` (mesmo endereço);
- **link do Drive** — o IntellexIA baixa pela conta de serviço ou como público.

Os dois terminam em ``fap_review_service.open_file_review``, o mesmo ponto do
texto curto, e no disparo em segundo plano da tela.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from app.models import db, FapReviewExecution, FapReviewUploadLink, User
from app.services import fap_review_service as _svc
from app.utils.permissions import has_module_permission
from app.utils.timezone import SP_TZ

LINK_VALIDITY = timedelta(hours=2)
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def create_upload_link(law_firm_id: int, user_id: int, identifier: str,
                       title: str = '') -> tuple[FapReviewUploadLink, str]:
    """Cria o link de envio. Devolve (registro, token em claro — só existe aqui).

    Recusa antes de criar o que a tela recusaria (ValueError): Id Wrike inválido
    para petição nova e petição bloqueada.
    """
    _petition, identifier = _svc.check_new_revision_allowed(law_firm_id, identifier)
    token = secrets.token_urlsafe(32)
    now = _utcnow()
    link = FapReviewUploadLink(
        law_firm_id=law_firm_id,
        user_id=user_id,
        token_hash=_hash(token),
        identifier=identifier,
        title=str(title or '').strip()[:255],
        expires_at=now + LINK_VALIDITY,
        created_at=now,
    )
    db.session.add(link)
    db.session.commit()
    return link, token


def upload_link_url(token: str) -> str:
    """Endereço absoluto do link de envio, também fora de requisição (MCP)."""
    from flask import current_app, url_for
    from app.utils.urls import app_public_url

    with current_app.test_request_context(base_url=app_public_url()):
        return url_for('fap_review_upload.enviar', token=token, _external=True)


def find_link(token: str | None) -> tuple[FapReviewUploadLink | None, str]:
    """Link do token e o estado: 'valido', 'expirado', 'usado' ou 'inexistente'."""
    token = str(token or '').strip()
    link = FapReviewUploadLink.query.filter_by(token_hash=_hash(token)).first() if token else None
    if not link:
        return None, 'inexistente'
    if link.used_at:
        return link, 'usado'
    if link.expires_at <= _utcnow():
        return link, 'expirado'
    return link, 'valido'


def expires_at_sp(link: FapReviewUploadLink) -> datetime:
    """Validade do link no horário de São Paulo (o banco guarda UTC)."""
    return link.expires_at.replace(tzinfo=timezone.utc).astimezone(SP_TZ)


def link_page_context(link: FapReviewUploadLink) -> dict:
    """O que a página de envio mostra antes de a pessoa soltar o arquivo."""
    from app.models import FapReviewPetition

    petition = FapReviewPetition.query.filter_by(
        law_firm_id=link.law_firm_id,
        office_document_identifier=link.identifier,
    ).first()
    user = User.query.get(link.user_id)
    if petition:
        titulo = petition.title
    else:
        titulo = link.title or 'Petição nova'
    return {
        'titulo': titulo,
        'identificador': link.identifier,
        'peticao_nova': petition is None,
        'proxima_revisao': _svc._next_revision_number(petition),
        'pedido_por': user.name if user else '',
        'expira_em': expires_at_sp(link),
        'bloqueio': _svc.describe_new_revision_block(petition),
        'em_andamento': _svc.running_revision(petition),
    }


# ── Receber o arquivo ────────────────────────────────────────────────


class UploadRecusado(Exception):
    """Envio recusado, com o status HTTP e a mensagem para quem enviou.

    Toda recusa deixa o link valendo (exceto o próprio link inválido): a
    pessoa corrige o arquivo e manda de novo pelo mesmo endereço.
    """

    def __init__(self, status_http: int, mensagem: str, **extra):
        super().__init__(mensagem)
        self.status_http = status_http
        self.mensagem = mensagem
        self.extra = extra


_TIPOS_ACEITOS = 'PDF, DOCX ou TXT'


def _tipo_pelo_conteudo(path: Path) -> str | None:
    with open(path, 'rb') as fh:
        cabeca = fh.read(8192)
    if cabeca.startswith(b'%PDF'):
        return 'pdf'
    if cabeca.startswith(b'PK\x03\x04'):
        try:
            with zipfile.ZipFile(path) as zf:
                return 'docx' if 'word/document.xml' in zf.namelist() else None
        except zipfile.BadZipFile:
            return None
    # Texto: sem byte nulo e sem cara de página HTML (erro de download não é petição).
    if b'\x00' in cabeca or cabeca.lstrip()[:15].lower().startswith((b'<!doctype', b'<html')):
        return None
    return 'txt'


def validate_review_file(path, filename: str) -> str:
    """Confere o arquivo salvo e devolve o tipo ('pdf', 'docx' ou 'txt').

    O tipo sai do conteúdo, não só do nome: nada chega ao agente sem provar que
    é o que diz ser. Sem extensão no nome, vale o conteúdo; com extensão, os dois
    têm de bater.
    """
    path = Path(path)
    if path.stat().st_size == 0:
        raise UploadRecusado(400, 'O arquivo está vazio.')
    ext = Path(str(filename or '')).suffix.lower().lstrip('.')
    if not (ext.isalpha() and len(ext) <= 5):
        ext = ''  # "Petição 5001234-56.2024": o ponto é do número do processo, não extensão
    if ext == 'doc':
        raise UploadRecusado(400, 'Arquivos .doc não são aceitos. Salve como DOCX ou PDF e envie de novo.')
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise UploadRecusado(400, f'Tipo de arquivo não aceito: envie {_TIPOS_ACEITOS}.')
    detectado = _tipo_pelo_conteudo(path)
    if not detectado:
        raise UploadRecusado(400, f'O conteúdo não parece ser {_TIPOS_ACEITOS}.')
    if ext and ext != detectado:
        raise UploadRecusado(400, f'O arquivo diz ser .{ext}, mas o conteúdo é de {detectado.upper()}.')
    return detectado


def _nome_em_disco(original: str, tipo: str) -> str:
    seguro = secure_filename(original or '')
    if not seguro.lower().endswith(f'.{tipo}'):
        seguro = (Path(seguro).stem or 'peticao') + f'.{tipo}'
    # O pedaço aleatório impede que dois envios do mesmo nome no mesmo segundo
    # caiam no mesmo arquivo — e que a recusa de um apague o do outro.
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S_')}{secrets.token_hex(3)}_{seguro}"


def save_review_file(stream, original_name: str, law_firm_id: int) -> tuple[str, str]:
    """Grava o arquivo conferido na pasta de revisões. Devolve (caminho, tipo).

    Escreve em `.part` e só renomeia depois de conferido; recusa apaga o parcial.
    """
    directory = _svc.upload_directory(law_firm_id, 'revisions')
    parcial = directory / f'{secrets.token_hex(8)}.part'
    gravados = 0
    try:
        with open(parcial, 'wb') as fh:
            while True:
                pedaco = stream.read(65536)
                if not pedaco:
                    break
                gravados += len(pedaco)
                if gravados > MAX_UPLOAD_BYTES:
                    raise UploadRecusado(
                        413, f'O arquivo passa de {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.')
                fh.write(pedaco)
        tipo = validate_review_file(parcial, original_name)
        destino = directory / _nome_em_disco(original_name, tipo)
        os.replace(parcial, destino)
        return str(destino), tipo
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise


def pergunta_claude(numero_revisao: int, identifier: str) -> str:
    """A pergunta que a página manda copiar: funciona numa conversa nova do Claude."""
    return f'Como está a revisão {numero_revisao} da petição {identifier}?'


class _LinkJaUsado(Exception):
    pass


def receive_upload(token: str, file_storage) -> dict:
    """Recebe o arquivo pelo link de envio e abre a revisão.

    Mesmo caminho da tela: arquivo original em disco, `open_file_review` e a
    thread de `_start_review_in_background` (com e-mail a quem pediu). O link é
    consumido na transação que cria a execução — dois envios simultâneos não
    abrem duas revisões. Recusa levanta `UploadRecusado`.
    """
    from app.blueprints.fap_review import _start_review_in_background

    link, estado = find_link(token)
    if estado == 'inexistente':
        raise UploadRecusado(404, 'Link de envio não encontrado.')
    if estado == 'expirado':
        raise UploadRecusado(410, 'Este link de envio expirou. Peça um novo ao Claude.')
    if estado == 'usado':
        raise UploadRecusado(409, 'Este link já foi usado para enviar um arquivo.',
                             **_revisao_do_link(link))

    # Permissão lida de novo no envio, como a API faz a cada requisição: quem foi
    # desativado (ou perdeu o Revisor) nas 2 horas do link não abre revisão paga.
    user = User.query.get(link.user_id)
    if (not user or not user.is_active or user.law_firm_id != link.law_firm_id
            or not user.law_firm or not user.law_firm.is_active
            or not has_module_permission('fap_review', user.role, user.module_permissions)):
        raise UploadRecusado(403, 'Quem pediu esta revisão não tem mais acesso ao Revisor de Petições.')

    if file_storage is None or not getattr(file_storage, 'filename', ''):
        raise UploadRecusado(400, "Envie o arquivo da petição no campo 'arquivo'.")
    original = file_storage.filename
    caminho, _tipo = save_review_file(file_storage.stream, original, link.law_firm_id)

    def _consumir(execution):
        resultado = db.session.execute(
            update(FapReviewUploadLink)
            .where(FapReviewUploadLink.id == link.id, FapReviewUploadLink.used_at.is_(None))
            .values(used_at=_utcnow(), execution_id=execution.id)
        )
        if resultado.rowcount == 0:
            raise _LinkJaUsado()

    try:
        aberta = _svc.open_file_review(
            link.law_firm_id, link.user_id, link.identifier, caminho, original,
            title=link.title, on_created=_consumir,
        )
    except ValueError as e:
        Path(caminho).unlink(missing_ok=True)
        raise UploadRecusado(403, str(e)) from e
    except (_LinkJaUsado, IntegrityError):
        # IntegrityError: dois envios simultâneos para petição nova — o segundo
        # bate na chave única do Id Wrike. Uma revisão só ficou; este vira 409.
        db.session.rollback()
        Path(caminho).unlink(missing_ok=True)
        raise UploadRecusado(409, 'Este link já foi usado para enviar um arquivo.',
                             **_revisao_do_link(FapReviewUploadLink.query.get(link.id)))
    except Exception:
        db.session.rollback()
        Path(caminho).unlink(missing_ok=True)
        raise

    if aberta['ja_em_andamento']:
        Path(caminho).unlink(missing_ok=True)
        raise UploadRecusado(
            409,
            f"A revisão {aberta['numero_revisao']} desta petição ainda está em processamento. "
            'Espere ela terminar e envie de novo por este mesmo link '
            f"(vale até {expires_at_sp(link):%H:%M}).",
            revisao_id=aberta['revisao_id'], numero_revisao=aberta['numero_revisao'],
        )

    _start_review_in_background(aberta['revisao_id'], link.law_firm_id, caminho, None,
                                notify_user=True)
    numero = aberta['numero_revisao']
    return {
        'revisao_id': aberta['revisao_id'],
        'numero_revisao': numero,
        'peticao_id': aberta['peticao_id'],
        'titulo': aberta['titulo'],
        'arquivo': original,
        'link': _svc.revision_result_url(aberta['revisao_id']),
        'pergunta_claude': pergunta_claude(numero, link.identifier),
        'mensagem': (
            f'Recebi "{original}". A revisão {numero} está em processamento e leva alguns '
            'minutos; quem pediu recebe um e-mail quando terminar.'
        ),
    }


def _revisao_do_link(link) -> dict:
    if not link or not link.execution_id:
        return {}
    execution = FapReviewExecution.query.get(link.execution_id)
    if not execution:
        return {}
    return {
        'revisao_id': execution.id,
        'numero_revisao': execution.revision_number,
        'link': _svc.revision_result_url(execution.id),
    }


# ── Link do Drive ────────────────────────────────────────────────────

SERVICE_ACCOUNT_EMAIL = 'intellexia-drive@intellexia-503416.iam.gserviceaccount.com'
DRIVE_SEM_ACESSO = (
    'Não consegui abrir o arquivo no Drive. Compartilhe com '
    f'{SERVICE_ACCOUNT_EMAIL} (Leitor) ou deixe aberto a qualquer pessoa com o '
    'link, e me peça de novo.'
)
_DRIVE_ID = re.compile(r'/d/([A-Za-z0-9_-]{5,})')
_DRIVE_ID_VALIDO = re.compile(r'[A-Za-z0-9_-]{5,}')
_GDOC_EXPORT_URL = 'https://docs.google.com/document/d/{id}/export?format=docx'


def drive_file_id_from_link(link: str) -> tuple[str, bool]:
    """Id do arquivo num link do Drive e se é um Google Docs nativo."""
    url = urlparse(str(link or '').strip())
    eh_docs = url.netloc.endswith('docs.google.com') and url.path.startswith('/document/')
    achado = _DRIVE_ID.search(url.path)
    file_id = achado.group(1) if achado else (parse_qs(url.query).get('id') or [''])[0]
    # O id vira caminho da API do Drive com o token da conta de serviço: só os
    # caracteres de um id de verdade, senão "abc/../files" reescreveria a chamada.
    if not _DRIVE_ID_VALIDO.fullmatch(file_id) or 'google.com' not in url.netloc:
        raise ValueError('Não reconheci o link do Drive. Use o link de compartilhamento do arquivo '
                         '(https://drive.google.com/file/d/...).')
    return file_id, eh_docs


def _nome_do_download(resposta, file_id: str) -> str:
    cabecalho = resposta.headers.get('Content-Disposition') or ''
    achado = re.search(r"filename\*=UTF-8''([^;]+)", cabecalho) or re.search(r'filename="?([^";]+)', cabecalho)
    return unquote(achado.group(1)).strip() if achado else f'{file_id}.docx'


def _baixar_gdoc_anonimo(file_id: str, dest_dir: Path) -> tuple[str, str]:
    """Google Docs público exportado em DOCX, sem conta de serviço."""
    resposta = requests.get(_GDOC_EXPORT_URL.format(id=file_id), stream=True, timeout=90,
                            allow_redirects=True)
    try:
        if resposta.status_code != 200 or 'text/html' in (resposta.headers.get('Content-Type') or ''):
            raise ValueError(DRIVE_SEM_ACESSO)
        destino = dest_dir / f'{secrets.token_hex(8)}_{file_id[:8]}.part'
        with open(destino, 'wb') as fh:
            for pedaco in resposta.iter_content(chunk_size=65536):
                if pedaco:
                    fh.write(pedaco)
        return str(destino), _nome_do_download(resposta, file_id)
    except requests.RequestException as e:
        raise ValueError(DRIVE_SEM_ACESSO) from e
    finally:
        resposta.close()


def download_review_file_from_drive(link: str, law_firm_id: int) -> tuple[str, str]:
    """Baixa a petição de um link do Drive para a pasta de revisões. Devolve (caminho, nome).

    Conta de serviço primeiro (só para o escritório configurado), depois o
    download público — a regra de `download_drive_file`. Google Docs nativo sai
    em DOCX. O arquivo passa pela mesma conferência do link de envio; o que não
    for PDF/DOCX/TXT (inclusive página de login do Google) é apagado.
    """
    from app.services import google_drive_client
    from app.services import impugnacao_import_service as _imp

    file_id, eh_docs = drive_file_id_from_link(link)
    directory = _svc.upload_directory(law_firm_id, 'revisions')
    caminho = None
    try:
        if eh_docs:
            if _imp._usa_conta_de_servico(law_firm_id):
                try:
                    caminho, nome, _ = google_drive_client.cliente().baixar(
                        file_id, str(directory), gdoc_como=google_drive_client.MIME_DOCX)
                except google_drive_client.DriveErro:
                    caminho = None
            if not caminho:
                caminho, nome = _baixar_gdoc_anonimo(file_id, directory)
        else:
            caminho, nome, _ = _imp.download_drive_file(
                file_id, str(directory), law_firm_id=law_firm_id,
                gdoc_como=google_drive_client.MIME_DOCX)
    except (_imp.DriveAccessError, google_drive_client.DriveErro) as e:
        raise ValueError(DRIVE_SEM_ACESSO) from e

    try:
        tipo = validate_review_file(caminho, nome)
    except UploadRecusado as e:
        Path(caminho).unlink(missing_ok=True)
        raise ValueError(e.mensagem) from e
    destino = directory / _nome_em_disco(nome, tipo)
    os.replace(caminho, destino)
    return str(destino), nome
