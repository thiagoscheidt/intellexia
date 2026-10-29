"""
Arquivos de uma revisão feita no Claude, anexados depois de gravar.

A revisão roda na conversa e só o resultado chega pelo MCP: o Claude não tem
como mandar o arquivo pela chamada (reescreveria 5–10 MB como texto). Ao
gravar, a resposta traz um link para esta revisão, que serve a dois caminhos:

- o próprio Claude manda com `curl`, se o ambiente de código dele tiver rede
  (na conta do Thiago chega; na da Daniella, em 28/10/2026, a sessão estava
  sem saída de rede — `Could not resolve host`);
- a pessoa abre o link no navegador e solta os arquivos.

Os arquivos vão para as colunas que a tela já usa — documento principal,
versão revisada e planilha de benefícios —, então baixar, pré-visualizar e
reaproveitar a planilha na revisão seguinte funcionam sem nada novo.

O token é assinado (itsdangerous, como a recuperação de senha), sem tabela: a
autorização é "esta revisão, deste usuário", e cada campo só é preenchido uma
vez — o link não troca o arquivo de ninguém.
"""
from __future__ import annotations

import json
import os
import secrets
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import update
from werkzeug.utils import secure_filename

from app.models import db, FapReviewExecution, User
from app.services import fap_review_service as _svc
from app.utils.permissions import has_module_permission
from app.utils.timezone import SP_TZ

SALT = 'fap-review-arquivos-claude'
VALIDADE = timedelta(hours=24)
MAX_ARQUIVO_BYTES = 30 * 1024 * 1024

# Onde o claude.ai põe os anexos: muda de conta para conta (27–28/10/2026).
ONDE_ESTAO_OS_ANEXOS = (
    'Os anexos da conversa costumam ficar em /mnt/user-data/uploads/ (em algumas contas, '
    '/mnt/user-data/attachments/); se não estiverem lá, procure antes de pedir de novo ao usuário: '
    'find / -name "*.xlsx" -o -name "*.csv" -o -name "*.docx" -o -name "*.pdf" 2>/dev/null '
    '| grep -v -e /usr/ -e /proc/.'
)

PETICAO, REVISADA, PLANILHA = 'peticao', 'revisada', 'planilha'
_TIPOS = {
    PETICAO: ('pdf', 'docx', 'txt'),
    REVISADA: ('pdf', 'docx', 'txt'),
    PLANILHA: ('xlsx', 'csv'),
}


class EnvioRecusado(Exception):
    """Envio recusado, com o status HTTP e a mensagem para quem enviou."""

    def __init__(self, status_http: int, mensagem: str):
        super().__init__(mensagem)
        self.status_http = status_http
        self.mensagem = mensagem


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt=SALT)


def _url(token: str) -> str:
    """Endereço absoluto do link, também fora de requisição (MCP)."""
    from flask import url_for
    from app.utils.urls import app_public_url

    with current_app.test_request_context(base_url=app_public_url()):
        return url_for('fap_review_arquivos.pagina', token=token, _external=True)


def campos(execution: FapReviewExecution) -> list[str]:
    """Campos que esta revisão aceita: a versão revisada só na comparação."""
    if execution.comparative_analysis:
        return [PETICAO, REVISADA, PLANILHA]
    return [PETICAO, PLANILHA]


def _planilha_gravada(execution) -> dict | None:
    try:
        dados = json.loads(execution.benefits_spreadsheet_json or 'null')
    except (TypeError, json.JSONDecodeError):
        return None
    return dados if isinstance(dados, dict) and dados.get('path') else None


def recebidos(execution: FapReviewExecution) -> dict:
    """{campo: nome do arquivo} do que já está na revisão."""
    feitos = {}
    if execution.main_document_path:
        feitos[PETICAO] = execution.main_document_filename or Path(execution.main_document_path).name
    if execution.compared_document_path:
        feitos[REVISADA] = Path(execution.compared_document_path).name
    planilha = _planilha_gravada(execution)
    if planilha:
        feitos[PLANILHA] = planilha.get('name') or Path(planilha['path']).name
    return feitos


def envio_para_o_claude(execution: FapReviewExecution) -> dict:
    """O bloco que a gravação devolve: link, curl pronto e o que fazer se falhar."""
    token = _serializer().dumps({'e': execution.id, 'u': execution.user_id})
    link = _url(token)
    vale_ate = datetime.now(timezone.utc).astimezone(SP_TZ) + VALIDADE
    comparacao = bool(execution.comparative_analysis)
    partes = ['curl -sS --max-time 180',
              '-F peticao=@"CAMINHO_DA_VERSAO_ORIGINAL"' if comparacao else '-F peticao=@"CAMINHO_DA_PETICAO"']
    if comparacao:
        partes.append('-F revisada=@"CAMINHO_DA_VERSAO_REVISADA"')
    partes.append('-F planilha=@"CAMINHO_DA_PLANILHA"')
    partes.append(f'"{link}"')
    return {
        'link': link,
        'valido_ate': f'{vale_ate:%d/%m %H:%M}',
        'curl': ' '.join(partes),
        'como_enviar': (
            'Anexe à revisão gravada os arquivos que o usuário mandou nesta conversa. Tente UMA vez, no seu '
            'ambiente de código, o "curl" acima com os caminhos dos anexos — tire o -F da planilha se não '
            'houver planilha. ' + ONDE_ESTAO_OS_ANEXOS + ' Se a resposta tiver "ok": true, diga ao usuário que '
            'os arquivos ficaram na revisão. Qualquer outra resposta ou erro de rede (host não resolvido, '
            'proxy 403, tempo esgotado) ou sem ambiente de código: não tente de novo nem por outro caminho e '
            f'NUNCA mande o conteúdo do arquivo pelo MCP — mostre o link ao usuário para ele soltar os '
            f'arquivos na página (vale até {vale_ate:%d/%m %H:%M}).'
        ),
    }


def ler_link(token: str | None) -> tuple[FapReviewExecution | None, str]:
    """Revisão do token e o estado: 'valido', 'expirado' ou 'inexistente'."""
    token = str(token or '').strip()
    if not token:
        return None, 'inexistente'
    try:
        dados = _serializer().loads(token, max_age=VALIDADE.total_seconds())
    except SignatureExpired:
        return None, 'expirado'
    except BadSignature:
        return None, 'inexistente'
    if not isinstance(dados, dict):
        return None, 'inexistente'
    execution = FapReviewExecution.query.filter_by(id=dados.get('e'), user_id=dados.get('u')).first()
    if not execution or not _svc.is_claude_review(execution):
        return None, 'inexistente'
    return execution, 'valido'


def contexto_da_pagina(execution: FapReviewExecution) -> dict:
    petition = execution.petition
    return {
        'titulo': petition.title if petition else '',
        'identificador': execution.law_firm_document_identifier or '',
        'numero_revisao': execution.revision_number,
        'comparacao': bool(execution.comparative_analysis),
        'campos': campos(execution),
        'recebidos': recebidos(execution),
        'link_revisao': _svc.revision_result_url(execution.id),
    }


# ── Receber ──────────────────────────────────────────────────────────


def _tipo_pelo_conteudo(path: Path) -> str | None:
    with open(path, 'rb') as fh:
        cabeca = fh.read(8192)
    if cabeca.startswith(b'%PDF'):
        return 'pdf'
    if cabeca.startswith(b'PK\x03\x04'):
        try:
            with zipfile.ZipFile(path) as zf:
                nomes = set(zf.namelist())
        except zipfile.BadZipFile:
            return None
        if 'word/document.xml' in nomes:
            return 'docx'
        if 'xl/workbook.xml' in nomes:
            return 'xlsx'
        return None
    # Texto: sem byte nulo e sem cara de página HTML (erro de download não é petição).
    if b'\x00' in cabeca or cabeca.lstrip()[:15].lower().startswith((b'<!doctype', b'<html')):
        return None
    return 'texto'


def _conferir_tipo(path: Path, nome: str, campo: str) -> str:
    """Tipo do arquivo salvo; o conteúdo tem de bater com o nome e com o campo."""
    aceitos = _TIPOS[campo]
    rotulo = ', '.join(t.upper() for t in aceitos)
    if path.stat().st_size == 0:
        raise EnvioRecusado(400, f'"{nome}" está vazio.')
    ext = Path(nome).suffix.lower().lstrip('.')
    if not (ext.isalpha() and len(ext) <= 5):
        ext = ''  # "Petição 5001234-56.2024": o ponto é do número do processo
    if ext in ('doc', 'xls'):
        raise EnvioRecusado(400, f'"{nome}": .{ext} não é aceito. Salve como {rotulo} e envie de novo.')
    if ext and ext not in aceitos:
        raise EnvioRecusado(400, f'"{nome}": aqui só {rotulo}.')
    detectado = _tipo_pelo_conteudo(path)
    if detectado == 'texto':
        detectado = ext if ext in ('txt', 'csv') else ('csv' if campo == PLANILHA else 'txt')
    if detectado not in aceitos:
        raise EnvioRecusado(400, f'O conteúdo de "{nome}" não parece ser {rotulo}.')
    if ext and ext != detectado:
        raise EnvioRecusado(400, f'"{nome}" diz ser .{ext}, mas o conteúdo é de {detectado.upper()}.')
    return detectado


def _salvar(stream, nome: str, campo: str, law_firm_id: int) -> str:
    """Grava em `.part`, confere e só então renomeia. Recusa apaga o parcial."""
    pasta = _svc.upload_directory(law_firm_id, 'revisions')
    parcial = pasta / f'{secrets.token_hex(8)}.part'
    gravados = 0
    try:
        with open(parcial, 'wb') as fh:
            while True:
                pedaco = stream.read(65536)
                if not pedaco:
                    break
                gravados += len(pedaco)
                if gravados > MAX_ARQUIVO_BYTES:
                    raise EnvioRecusado(413, f'"{nome}" passa de {MAX_ARQUIVO_BYTES // (1024 * 1024)} MB.')
                fh.write(pedaco)
        tipo = _conferir_tipo(parcial, nome, campo)
        seguro = secure_filename(nome) or campo
        if not seguro.lower().endswith(f'.{tipo}'):
            seguro = (Path(seguro).stem or campo) + f'.{tipo}'
        destino = pasta / f"{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(3)}_claude_{campo}_{seguro}"
        os.replace(parcial, destino)
        return str(destino)
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise


def _coluna_vazia(campo: str):
    if campo == PETICAO:
        return FapReviewExecution.main_document_path.is_(None)
    if campo == REVISADA:
        return FapReviewExecution.compared_document_path.is_(None)
    return FapReviewExecution.benefits_spreadsheet_json.is_(None)


def _valores(campo: str, caminho: str, nome: str) -> dict:
    if campo == PETICAO:
        return {'main_document_path': caminho, 'main_document_filename': nome[:255]}
    if campo == REVISADA:
        return {'compared_document_path': caminho}
    return {'benefits_spreadsheet_json': json.dumps({'name': nome, 'path': caminho}, ensure_ascii=False)}


def receber(token: str, arquivos: dict) -> dict:
    """Recebe os arquivos (campo → FileStorage) e preenche as colunas da revisão.

    Tudo ou nada: um arquivo recusado não deixa os outros gravados, para a
    pessoa corrigir e mandar o mesmo envio de novo. Campo já preenchido é 409.
    """
    execution, estado = ler_link(token)
    if estado == 'expirado':
        raise EnvioRecusado(410, 'Este link expirou. Anexe os arquivos pela tela da revisão.')
    if estado != 'valido':
        raise EnvioRecusado(404, 'Link não encontrado.')

    # Permissão lida de novo no envio, como a API: quem foi desativado ou perdeu o Revisor não anexa.
    user = User.query.get(execution.user_id)
    if (not user or not user.is_active or user.law_firm_id != execution.law_firm_id
            or not user.law_firm or not user.law_firm.is_active
            or not has_module_permission('fap_review', user.role, user.module_permissions)):
        raise EnvioRecusado(403, 'Quem gravou esta revisão não tem mais acesso ao Revisor de Petições.')

    aceitos = campos(execution)
    enviados = {c: f for c, f in arquivos.items() if f is not None and getattr(f, 'filename', '')}
    if not enviados:
        raise EnvioRecusado(400, 'Nenhum arquivo enviado. Campos aceitos: ' + ', '.join(aceitos) + '.')
    fora = [c for c in enviados if c not in aceitos]
    if fora:
        raise EnvioRecusado(400, f'Campo não aceito nesta revisão: {", ".join(fora)}. '
                                 f'Aceitos: {", ".join(aceitos)}.')
    ja = recebidos(execution)
    repetidos = [c for c in enviados if c in ja]
    if repetidos:
        raise EnvioRecusado(409, 'Já recebido nesta revisão: '
                            + ', '.join(f'{c} ("{ja[c]}")' for c in repetidos) + '.')

    salvos: dict[str, str] = {}
    try:
        for campo, arquivo in enviados.items():
            salvos[campo] = _salvar(arquivo.stream, arquivo.filename, campo, execution.law_firm_id)
        for campo, caminho in salvos.items():
            # Dois envios ao mesmo tempo: só o primeiro preenche o campo.
            resultado = db.session.execute(
                update(FapReviewExecution)
                .where(FapReviewExecution.id == execution.id, _coluna_vazia(campo))
                .values(**_valores(campo, caminho, enviados[campo].filename))
            )
            if resultado.rowcount == 0:
                raise EnvioRecusado(409, f'Já recebido nesta revisão: {campo}.')
        db.session.commit()
    except BaseException:
        db.session.rollback()
        for caminho in salvos.values():
            Path(caminho).unlink(missing_ok=True)
        raise

    nomes = {c: enviados[c].filename for c in salvos}
    _svc.log_audit(execution.law_firm_id, execution.user_id, 'files_attached', 'execution', execution.id,
                   'Arquivos anexados à revisão feita no Claude: ' + ', '.join(nomes.values()))
    return {
        'recebidos': nomes,
        'revisao_id': execution.id,
        'numero_revisao': execution.revision_number,
        'link': _svc.revision_result_url(execution.id),
        'mensagem': 'Arquivos anexados à revisão ' + str(execution.revision_number) + ': '
                    + ', '.join(nomes.values()) + '.',
    }
