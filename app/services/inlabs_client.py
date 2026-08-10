"""
Client do INLABS (Imprensa Nacional) — único ponto do sistema que fala com
https://inlabs.in.gov.br.

Mecanismo confirmado contra a implementação de referência oficial da Imprensa
Nacional (github.com/Imprensa-Nacional/inlabs, public/python/):

  1. POST /logar.php com form {email, password} → cookie inlabs_session_cookie
  2. GET /index.php?p=YYYY-MM-DD&dl=<arquivo> com os headers Cookie e
     origem=736372697074
  3. XML:  YYYY-MM-DD-DO1.zip     (seções DO1 DO2 DO3 DO1E DO2E DO3E)
     PDF:  YYYY_MM_DD_ASSINADO_do1.pdf  (do1 do2 do3; já contempla as extras)
  4. HTTP 404 = não publicado naquele dia/seção. É estado normal, não erro.

Três defeitos do script oficial que este client corrige de propósito:
  - lá, login() chama a si mesmo sem teto em ConnectionError (recursão infinita
    se a rede cair) → aqui, retry com limite e backoff;
  - lá, nenhuma requisição tem timeout (uma conexão presa trava o cron) → aqui,
    timeout explícito em tudo;
  - lá, há exit() dentro da função de download → aqui, erro vira exceção e quem
    chama decide.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date

import requests

logger = logging.getLogger(__name__)

URL_LOGIN = 'https://inlabs.in.gov.br/logar.php'
URL_DOWNLOAD = 'https://inlabs.in.gov.br/index.php?p='

# Marca que a Imprensa Nacional espera nos downloads automatizados
# ('736372697074' é "script" em hexadecimal)
ORIGEM_SCRIPT = '736372697074'

DEFAULT_TIMEOUT = int(os.environ.get('DOU_DOWNLOAD_TIMEOUT', '120'))
MAX_RETRIES = 3
BACKOFF_BASE = 2  # segundos: 2, 4, 8


class InlabsError(Exception):
    """Falha genérica ao falar com o INLABS."""


class InlabsNotConfigured(InlabsError):
    """INLABS_EMAIL / INLABS_PASSWORD ausentes no .env."""


class InlabsAuthError(InlabsError):
    """Login recusado: o INLABS não devolveu o cookie de sessão."""


class InlabsUnavailable(InlabsError):
    """INLABS fora do ar (5xx). Transitório — a próxima execução tenta de novo."""


def is_configured() -> bool:
    """True quando há credenciais no ambiente. Sem elas o módulo não roda."""
    return bool(os.environ.get('INLABS_EMAIL') and os.environ.get('INLABS_PASSWORD'))


def xml_filename(data: date, secao: str) -> str:
    """2026-08-10 + 'DO1' → '2026-08-10-DO1.zip' (seção em MAIÚSCULAS)."""
    return f"{data.strftime('%Y-%m-%d')}-{secao.upper()}.zip"


def pdf_filename(data: date, secao: str) -> str:
    """2026-08-10 + 'do1' → '2026_08_10_ASSINADO_do1.pdf' (seção em minúsculas)."""
    return f"{data.strftime('%Y_%m_%d')}_ASSINADO_{secao.lower()}.pdf"


class InlabsClient:
    """Sessão autenticada com o INLABS. Reutilize a instância entre downloads."""

    def __init__(self, email: str | None = None, password: str | None = None,
                 timeout: int | None = None):
        self._email = email or os.environ.get('INLABS_EMAIL')
        self._password = password or os.environ.get('INLABS_PASSWORD')
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._session = requests.Session()
        self._cookie: str | None = None

    # ------------------------------------------------------------------ login

    def login(self) -> None:
        """Autentica e guarda o cookie de sessão. Idempotente por instância."""
        if not self._email or not self._password:
            raise InlabsNotConfigured(
                'INLABS_EMAIL e INLABS_PASSWORD não configurados no .env'
            )

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        payload = {'email': self._email, 'password': self._password}

        resposta = self._request_com_retry('POST', URL_LOGIN, headers=headers,
                                           data=payload)

        # Distinguir "fora do ar" de "credencial errada" antes de olhar o
        # cookie. O portal responde 502 com uma página "Sistema em Manutenção";
        # sem esta checagem isso virava "verifique as credenciais" e mandava
        # quem lê o log caçar problema no lugar errado.
        if resposta.status_code >= 500:
            raise InlabsUnavailable(
                f'INLABS indisponível (HTTP {resposta.status_code}) — '
                f'provavelmente em manutenção; a próxima execução tenta de novo'
            )
        if resposta.status_code != 200:
            raise InlabsError(f'INLABS devolveu HTTP {resposta.status_code} no login')

        cookie = self._session.cookies.get('inlabs_session_cookie')
        if not cookie:
            raise InlabsAuthError(
                'INLABS não devolveu inlabs_session_cookie — verifique as credenciais'
            )
        self._cookie = cookie
        logger.info('INLABS: sessão autenticada')

    def _garantir_sessao(self) -> None:
        if not self._cookie:
            self.login()

    # --------------------------------------------------------------- download

    def download_xml_zip(self, data: date, secao: str) -> bytes | None:
        """Baixa o ZIP de XML da (data, seção). None quando não publicado (404)."""
        return self._download(data, xml_filename(data, secao))

    def download_pdf(self, data: date, secao: str) -> bytes | None:
        """Baixa o PDF assinado da (data, seção). None quando não publicado (404)."""
        return self._download(data, pdf_filename(data, secao))

    def _download(self, data: date, arquivo: str) -> bytes | None:
        self._garantir_sessao()
        url = f"{URL_DOWNLOAD}{data.strftime('%Y-%m-%d')}&dl={arquivo}"

        resposta = self._request_com_retry('GET', url, headers=self._headers_download())

        # Cookie expirado no meio de um backfill longo: relogin transparente,
        # uma única retentativa. Segunda falha propaga.
        if resposta.status_code in (401, 403):
            logger.info('INLABS: sessão expirada, refazendo login')
            self._cookie = None
            self.login()
            resposta = self._request_com_retry('GET', url, headers=self._headers_download())

        if resposta.status_code == 404:
            logger.info('INLABS: %s não publicado (404)', arquivo)
            return None
        if resposta.status_code != 200:
            raise InlabsError(f'INLABS devolveu HTTP {resposta.status_code} para {arquivo}')

        # O INLABS tem DUAS formas de dizer "não publicado", e só uma delas é
        # 404. Quando a data existe mas o arquivo não (uma edição extra que não
        # saiu), responde 404. Quando a **data inteira** não existe — fim de
        # semana, feriado — responde 200 com a página HTML do portal (~37 KB).
        # Sem esta checagem o HTML seguia como se fosse o arquivo e estourava
        # BadZipFile lá na ingestão, marcando todo fim de semana como falha.
        tipo = (resposta.headers.get('Content-Type') or '').lower()
        if 'text/html' in tipo:
            logger.info('INLABS: %s não publicado (portal devolveu HTML)', arquivo)
            return None

        return resposta.content

    def _headers_download(self) -> dict:
        return {'Cookie': f'inlabs_session_cookie={self._cookie}', 'origem': ORIGEM_SCRIPT}

    # ---------------------------------------------------------------- retry

    def _request_com_retry(self, method: str, url: str, **kwargs):
        """Retry com teto e backoff exponencial.

        O script oficial recorre infinitamente em ConnectionError; aqui a
        recursão vira laço com limite, e o erro final propaga em vez de travar.
        """
        kwargs.setdefault('timeout', self._timeout)
        ultimo_erro = None

        for tentativa in range(1, MAX_RETRIES + 1):
            try:
                return self._session.request(method, url, **kwargs)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as exc:
                ultimo_erro = exc
                if tentativa == MAX_RETRIES:
                    break
                espera = BACKOFF_BASE ** tentativa
                logger.warning(
                    'INLABS: falha de rede (%s), tentativa %d/%d, aguardando %ds',
                    exc.__class__.__name__, tentativa, MAX_RETRIES, espera,
                )
                time.sleep(espera)

        raise InlabsError(
            f'INLABS inacessível após {MAX_RETRIES} tentativas: {ultimo_erro}'
        ) from ultimo_erro
