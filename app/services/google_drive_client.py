"""Acesso ao Google Drive pela conta de serviço do IntellexIA.

Todo contato com o Drive autenticado passa por aqui (mesmo papel do
`inlabs_client` e do `comunica_pje_client`). Módulo puro: não importa Flask nem
models — o `impugnacao_import_service`, que também é puro, usa este client.

A conta só enxerga o que o escritório compartilhou com ela. Arquivo não
compartilhado responde **404**, não 403: para o Drive, quem não tem acesso não
fica sabendo que o arquivo existe.

Autenticação: JWT assinado com a chave da conta (`joserfc`, que já vem com o
Authlib) trocado por token de acesso no `token_uri`. O `AssertionSession` do
Authlib faz o mesmo, mas emite avisos de API obsoleta a cada token.

Configuração só no `.env`:
    GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE  caminho do JSON da chave (em instance/)
    GOOGLE_DRIVE_LAW_FIRM_ID           escritório dono dos arquivos

Ver docs/superpowers/specs/2026-10-14-google-drive-conta-servico-design.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime
from typing import Optional

import requests
from werkzeug.utils import secure_filename

SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
API = 'https://www.googleapis.com/drive/v3'
MIME_PASTA = 'application/vnd.google-apps.folder'
MIME_PDF = 'application/pdf'
MIME_DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
# Documento nativo do Google não tem binário: só sai por exportação.
EXPORTAVEIS = {
    'application/vnd.google-apps.document': MIME_PDF,
}
_CAMPOS = ('id,name,mimeType,size,parents,driveId,webViewLink,modifiedTime,'
           'sharedWithMeTime,sharingUser(displayName,emailAddress),owners(displayName,emailAddress)')
_RAIZ_DO_PROJETO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DriveErro(Exception):
    """Base dos erros do Drive — a mensagem já vai pronta para a tela."""


class DriveNaoConfigurado(DriveErro):
    pass


class DriveSemAcesso(DriveErro):
    """O arquivo não existe para a conta: não foi compartilhado, ou deixou de ser."""


class DriveIndisponivel(DriveErro):
    """Rede, 5xx, credencial recusada, API desativada ou limite de requisições."""


# ── Configuração ──────────────────────────────────────────────────────

def caminho_da_chave() -> Optional[str]:
    bruto = (os.environ.get('GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE') or '').strip()
    if not bruto:
        return None
    return bruto if os.path.isabs(bruto) else os.path.join(_RAIZ_DO_PROJETO, bruto)


def law_firm_id_configurado() -> Optional[int]:
    bruto = (os.environ.get('GOOGLE_DRIVE_LAW_FIRM_ID') or '').strip()
    return int(bruto) if bruto.isdigit() else None


def configurado() -> bool:
    caminho = caminho_da_chave()
    return bool(caminho and os.path.isfile(caminho))


_cache_lock = threading.Lock()
_cache: dict = {}


def cliente() -> 'DriveClient':
    """Client da instalação, reaproveitado para não pedir token a cada chamada.

    Recria quando o arquivo da chave muda (troca de chave sem reiniciar).
    """
    caminho = caminho_da_chave()
    if not caminho or not os.path.isfile(caminho):
        raise DriveNaoConfigurado('Integração com o Google Drive não configurada.')
    assinatura = (caminho, os.path.getmtime(caminho))
    with _cache_lock:
        if _cache.get('assinatura') != assinatura:
            _cache['cliente'] = DriveClient.da_chave(caminho)
            _cache['assinatura'] = assinatura
        return _cache['cliente']


# ── Client ────────────────────────────────────────────────────────────

def tipo_do_arquivo(mime: Optional[str]) -> Optional[str]:
    """'pdf', 'docx', 'gdoc' (exportado como PDF) ou None (não ingerível)."""
    if mime == MIME_PDF:
        return 'pdf'
    if mime == MIME_DOCX:
        return 'docx'
    if mime in EXPORTAVEIS:
        return 'gdoc'
    return None


def _motivo_do_erro(resposta) -> str:
    try:
        erro = resposta.json().get('error') or {}
    except ValueError:
        return ''
    if isinstance(erro, str):  # endpoint de token: {"error": "invalid_grant", ...}
        return erro
    detalhes = erro.get('errors') or [{}]
    return (detalhes[0].get('reason') or erro.get('status') or '').strip()


class DriveClient:
    def __init__(self, info: dict, *, http=None, timeout: int = 60):
        faltando = [k for k in ('client_email', 'private_key', 'token_uri') if not info.get(k)]
        if faltando:
            raise DriveNaoConfigurado(f'Chave da conta de serviço incompleta: falta {", ".join(faltando)}.')
        self._info = info
        self._http = http or requests.Session()
        self._timeout = timeout
        self._token: Optional[str] = None
        self._expira_em = 0.0

    @classmethod
    def da_chave(cls, caminho: str, **kwargs) -> 'DriveClient':
        try:
            with open(caminho, encoding='utf-8') as fh:
                info = json.load(fh)
        except (OSError, ValueError) as exc:
            raise DriveNaoConfigurado(f'Não foi possível ler a chave da conta de serviço: {exc}') from exc
        return cls(info, **kwargs)

    @property
    def conta(self) -> str:
        return self._info['client_email']

    # ── token ──

    def _assinar(self) -> str:
        from joserfc import jwt
        from joserfc.jwk import RSAKey

        agora = int(time.time())
        cabecalho = {'alg': 'RS256'}
        if self._info.get('private_key_id'):
            cabecalho['kid'] = self._info['private_key_id']
        reivindicacoes = {'iss': self.conta, 'scope': SCOPE, 'aud': self._info['token_uri'],
                          'iat': agora, 'exp': agora + 3600}
        return jwt.encode(cabecalho, reivindicacoes, RSAKey.import_key(self._info['private_key']))

    def _token_de_acesso(self, renovar: bool = False) -> str:
        if self._token and not renovar and time.time() < self._expira_em - 60:
            return self._token
        try:
            resposta = self._http.post(self._info['token_uri'], data={
                'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                'assertion': self._assinar(),
            }, timeout=self._timeout)
        except requests.RequestException as exc:
            raise DriveIndisponivel(f'Não foi possível conectar ao Google: {exc}') from exc
        if resposta.status_code >= 500:
            raise DriveIndisponivel(f'O Google está indisponível agora (HTTP {resposta.status_code}).')
        if resposta.status_code != 200:
            motivo = _motivo_do_erro(resposta) or f'HTTP {resposta.status_code}'
            raise DriveIndisponivel(
                f'O Google recusou a chave da conta de serviço ({motivo}). '
                'Confira se a chave não foi revogada no Google Cloud.')
        dados = resposta.json()
        self._token = dados['access_token']
        self._expira_em = time.time() + int(dados.get('expires_in') or 3600)
        return self._token

    # ── requisições ──

    def _get(self, caminho: str, params: Optional[dict] = None, *, stream: bool = False):
        url = f'{API}/{caminho}'
        params = dict(params or {}, supportsAllDrives='true')
        for tentativa in (1, 2):
            cabecalhos = {'Authorization': f'Bearer {self._token_de_acesso(renovar=tentativa == 2)}'}
            try:
                resposta = self._http.get(url, params=params, headers=cabecalhos,
                                          stream=stream, timeout=self._timeout)
            except requests.RequestException as exc:
                raise DriveIndisponivel(f'Não foi possível conectar ao Google Drive: {exc}') from exc
            if resposta.status_code == 401 and tentativa == 1:
                resposta.close()
                continue  # token vencido antes da hora: pede outro uma vez
            break
        if resposta.status_code == 200:
            return resposta
        motivo = _motivo_do_erro(resposta)
        status = resposta.status_code
        resposta.close()
        if status == 404:
            raise DriveSemAcesso('O arquivo não está compartilhado com a conta de serviço (ou foi removido).')
        if status == 403:
            if motivo in ('accessNotConfigured', 'SERVICE_DISABLED'):
                raise DriveIndisponivel('A API do Google Drive está desativada no projeto da conta de serviço.')
            if 'RateLimit' in motivo or motivo in ('rateLimitExceeded', 'userRateLimitExceeded'):
                raise DriveIndisponivel('Limite de requisições do Google Drive atingido. Tente de novo em alguns minutos.')
            raise DriveSemAcesso(f'A conta de serviço não tem permissão para baixar este arquivo ({motivo or "403"}).')
        if status == 429:
            raise DriveIndisponivel('Limite de requisições do Google Drive atingido. Tente de novo em alguns minutos.')
        if status >= 500:
            raise DriveIndisponivel(f'O Google Drive está indisponível agora (HTTP {status}).')
        raise DriveIndisponivel(f'O Google Drive recusou a requisição (HTTP {status}{": " + motivo if motivo else ""}).')

    def listar(self) -> list[dict]:
        """Tudo o que a conta enxerga: arquivos e pastas, inclusive dentro de pasta compartilhada."""
        itens, pagina = [], None
        while True:
            params = {'q': 'trashed = false', 'pageSize': 1000, 'corpora': 'allDrives',
                      'includeItemsFromAllDrives': 'true', 'orderBy': 'modifiedTime desc',
                      'fields': f'nextPageToken,files({_CAMPOS})'}
            if pagina:
                params['pageToken'] = pagina
            dados = self._get('files', params).json()
            itens.extend(dados.get('files') or [])
            pagina = dados.get('nextPageToken')
            if not pagina:
                return itens

    def metadados(self, file_id: str) -> dict:
        return self._get(f'files/{file_id}', {'fields': _CAMPOS}).json()

    def baixar(self, file_id: str, dest_dir: str, *, meta: Optional[dict] = None) -> tuple[str, str, str]:
        """Baixa para `dest_dir`. Devolve (caminho, nome original, sha256).

        Grava em `.part` e só renomeia depois de conferir que veio o arquivo —
        nunca a página HTML de erro — e com o tamanho anunciado.
        """
        meta = meta or self.metadados(file_id)
        mime = meta.get('mimeType')
        nome = (meta.get('name') or f'{file_id}').strip()
        if mime == MIME_PASTA:
            raise DriveSemAcesso('Pasta não se baixa: escolha os arquivos dentro dela.')
        exportar_como = EXPORTAVEIS.get(mime)
        if exportar_como:
            if not nome.lower().endswith('.pdf'):
                nome += '.pdf'
            resposta = self._get(f'files/{file_id}/export', {'mimeType': exportar_como}, stream=True)
            tamanho_esperado = None
        else:
            resposta = self._get(f'files/{file_id}', {'alt': 'media'}, stream=True)
            tamanho_esperado = int(meta['size']) if str(meta.get('size') or '').isdigit() else None

        os.makedirs(dest_dir, exist_ok=True)
        carimbo = datetime.now().strftime('%Y%m%d_%H%M%S')
        seguro = secure_filename(nome) or f'{file_id}.bin'
        destino = os.path.join(dest_dir, f'{carimbo}_{file_id[:8]}_{seguro}')
        parcial = destino + '.part'
        sha256, gravados, inicio = hashlib.sha256(), 0, b''
        try:
            with open(parcial, 'wb') as fh:
                for pedaco in resposta.iter_content(chunk_size=65536):
                    if not pedaco:
                        continue
                    if len(inicio) < 64:
                        inicio += pedaco[:64]
                    fh.write(pedaco)
                    sha256.update(pedaco)
                    gravados += len(pedaco)
        except requests.RequestException as exc:
            _remover(parcial)
            raise DriveIndisponivel(f'O download foi interrompido: {exc}') from exc
        except OSError:
            _remover(parcial)
            raise
        finally:
            resposta.close()

        tipo_resposta = (resposta.headers.get('Content-Type') or '').lower()
        cabeca = inicio.lstrip()[:15].lower()
        if 'text/html' in tipo_resposta or cabeca.startswith((b'<!doctype', b'<html')):
            _remover(parcial)
            raise DriveIndisponivel('O Google Drive devolveu uma página em vez do arquivo.')
        if tamanho_esperado is not None and gravados != tamanho_esperado:
            _remover(parcial)
            raise DriveIndisponivel(
                f'O download veio incompleto ({gravados} de {tamanho_esperado} bytes). Tente de novo.')
        os.replace(parcial, destino)
        return destino, nome[:255], sha256.hexdigest()


def _remover(caminho: str) -> None:
    try:
        os.remove(caminho)
    except OSError:
        pass
