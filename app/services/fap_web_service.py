"""
FapWebService — encapsula todas as chamadas HTTP ao portal FAP/Dataprev.

Uso:
    auth = FapWebAuthPayload(cookies={"SESSION": "...", "XSRF-TOKEN": "..."}, user_agent="...")
    service = FapWebService(auth)

    ok, status = service.check_session()
    companies  = service.fetch_companies()
    items      = service.fetch_contestacoes(cnpj="12345678", year=2023)
    pdf_bytes, filename = service.download_contestacao(year=2023, cnpj="12345678000195", contestacao_id=42)
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
import base64
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_BASE_URL = 'https://fap-mps.dataprev.gov.br'
_DEFAULT_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/147.0.0.0 Safari/537.36'
)


# ---------------------------------------------------------------------------
# Tipos de resultado
# ---------------------------------------------------------------------------

@dataclass
class FapWebResult:
    """Resultado genérico de uma chamada ao FAP Web."""
    ok: bool
    data: Any = None
    message: str = ''
    status_code: int | None = None
    expired: bool = False


@dataclass
class FapWebAuthPayload:
    """Dados de autenticação extraídos do portal FAP."""
    cookies: dict[str, str] = field(default_factory=dict)
    user_agent: str = ''

    # ── Helpers ──────────────────────────────────────────────────────────

    @property
    def cookie_string(self) -> str:
        return '; '.join(f'{k}={v}' for k, v in self.cookies.items() if k and v)

    @property
    def xsrf_token(self) -> str:
        return self.cookies.get('XSRF-TOKEN', '')

    @property
    def effective_user_agent(self) -> str:
        return self.user_agent.strip() or _DEFAULT_UA

    # ── Serialização ─────────────────────────────────────────────────────

    def to_json(self) -> str:
        return json.dumps({'cookies': self.cookies, 'userAgent': self.user_agent})

    @classmethod
    def from_json(cls, raw: str) -> 'FapWebAuthPayload':
        """Desserializa a partir do JSON armazenado na sessão Flask."""
        data = json.loads(raw)
        return cls(
            cookies=data.get('cookies') or {},
            user_agent=(data.get('userAgent') or '').strip(),
        )

    @classmethod
    def from_dict(cls, d: dict) -> 'FapWebAuthPayload':
        return cls(
            cookies=d.get('cookies') or {},
            user_agent=(d.get('userAgent') or '').strip(),
        )


# ---------------------------------------------------------------------------
# Service principal
# ---------------------------------------------------------------------------

class FapWebService:
    """Serviço para comunicação com o portal FAP/Dataprev."""

    def __init__(self, auth: FapWebAuthPayload) -> None:
        self.auth = auth
        self._ssl_ctx = self._build_ssl_ctx()

    # ── SSL ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_ssl_ctx() -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
        ctx.options |= getattr(ssl, 'OP_LEGACY_SERVER_CONNECT', 0)
        return ctx

    # ── Construção de headers ─────────────────────────────────────────────

    def _base_headers(
        self,
        accept: str = 'application/json;charset=utf-8',
        referer: str = 'https://fap-mps.dataprev.gov.br/contestacoes-eletronicas',
    ) -> dict:
        headers = {
            'Accept': accept,
            'Accept-Language': 'pt-BR,pt;q=0.9',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Cookie': self.auth.cookie_string,
            'DNT': '1',
            'Pragma': 'no-cache',
            'Referer': referer,
            'User-Agent': self.auth.effective_user_agent,
        }
        if self.auth.xsrf_token:
            headers['X-XSRF-TOKEN'] = self.auth.xsrf_token
        return headers

    # ── Execução de requisição ────────────────────────────────────────────

    def _get(
        self,
        url: str,
        timeout: int = 30,
        referer: str = 'https://fap-mps.dataprev.gov.br/contestacoes-eletronicas',
    ) -> tuple[bytes, int]:
        """Faz um GET e retorna (body_bytes, http_status).
        Lança urllib.error.HTTPError / URLError em caso de falha.
        """
        req = urllib.request.Request(url, headers=self._base_headers(referer=referer), method='GET')
        with urllib.request.urlopen(req, timeout=timeout, context=self._ssl_ctx) as resp:
            return resp.read(), resp.status

    # ── Verificar sessão ─────────────────────────────────────────────────

    def check_session(self) -> FapWebResult:
        """Verifica se a sessão FAP ainda está ativa.

        Returns:
            FapWebResult com ok=True se a sessão é válida.
        """
        url = f'{_BASE_URL}/gateway/oauth2/token'
        try:
            _, status = self._get(url, timeout=15)
            return FapWebResult(ok=True, status_code=status)
        except urllib.error.HTTPError as e:
            expired = e.code in (401, 403)
            return FapWebResult(
                ok=False,
                expired=expired,
                status_code=e.code,
                message=f'HTTP {e.code}',
            )
        except Exception as e:
            return FapWebResult(ok=False, message=str(e))

    # ── Listar empresas com procuração ────────────────────────────────────

    def fetch_companies(self) -> FapWebResult:
        """Busca as empresas com procuração cadastradas no FAP.

        Returns:
            FapWebResult com data=list[dict] em caso de sucesso.
        """
        url = f'{_BASE_URL}/gateway/fap/v1/procuracoes/empresas'
        try:
            body, _ = self._get(url, timeout=15)
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', errors='replace')
            return FapWebResult(
                ok=False,
                status_code=e.code,
                message=f'Erro HTTP {e.code} ao consultar o sistema FAP.',
                data={'detail': detail[:500]},
            )
        except urllib.error.URLError as e:
            return FapWebResult(ok=False, message=f'Falha de conexão com o sistema FAP: {e.reason}')
        except Exception as e:
            return FapWebResult(ok=False, message=f'Erro inesperado: {str(e)}')

        try:
            companies = json.loads(body.decode('utf-8'))
        except Exception:
            return FapWebResult(
                ok=False,
                message='Resposta inválida do sistema FAP (não é JSON).',
                data={'detail': body[:300].decode('utf-8', errors='replace')},
            )

        return FapWebResult(ok=True, data=companies)

    # ── Listar procurações eletrônicas ─────────────────────────────────────

    def fetch_procuracoes(self) -> FapWebResult:
        """Busca as procurações eletrônicas cadastradas no FAP.

        Returns:
            FapWebResult com data=list[dict] em caso de sucesso.
        """
        url = f'{_BASE_URL}/gateway/fap/v1/procuracoes'
        try:
            body, _ = self._get(
                url,
                timeout=15,
                referer='https://fap-mps.dataprev.gov.br/procuracoes',
            )
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', errors='replace')
            return FapWebResult(
                ok=False,
                status_code=e.code,
                message=f'Erro HTTP {e.code} ao consultar procurações eletrônicas.',
                data={'detail': detail[:500]},
            )
        except urllib.error.URLError as e:
            return FapWebResult(ok=False, message=f'Falha de conexão com o sistema FAP: {e.reason}')
        except Exception as e:
            return FapWebResult(ok=False, message=f'Erro inesperado: {str(e)}')

        try:
            procuracoes = json.loads(body.decode('utf-8'))
        except Exception:
            return FapWebResult(
                ok=False,
                message='Resposta inválida do sistema FAP (não é JSON).',
                data={'detail': body[:300].decode('utf-8', errors='replace')},
            )

        return FapWebResult(ok=True, data=procuracoes)

    # ── Listar contestações de uma empresa/vigência ───────────────────────

    def fetch_contestacoes(self, cnpj: str, year: int | str) -> FapWebResult:
        """Busca as contestações de um CNPJ em um determinado ano de vigência.

        Args:
            cnpj:  CNPJ raiz (8 dígitos) ou CNPJ completo (14 dígitos).
            year:  Ano de vigência (ex: 2023).

        Returns:
            FapWebResult com data=list[dict] em caso de sucesso.
        """
        url = f'{_BASE_URL}/gateway/fap/v1/vigencias/{year}/empresa/{cnpj}/contestacoes'
        try:
            body, _ = self._get(url, timeout=30)
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', errors='replace')
            if e.code in (401, 403):
                msg = (
                    f'Sessão expirada ou não autorizada (HTTP {e.code}). '
                    'Acesse o portal FAP, faça login, exporte um novo arquivo de sessão e atualize os dados de autenticação.'
                )
            else:
                msg = f'Erro HTTP {e.code} ao consultar contestações.'
            return FapWebResult(
                ok=False,
                expired=e.code in (401, 403),
                status_code=e.code,
                message=msg,
                data={'detail': detail[:500]},
            )
        except urllib.error.URLError as e:
            return FapWebResult(ok=False, message=f'Falha de conexão: {e.reason}')
        except Exception as e:
            return FapWebResult(ok=False, message=f'Erro inesperado: {str(e)}')

        try:
            items = json.loads(body.decode('utf-8'))
        except Exception:
            return FapWebResult(
                ok=False,
                message='Resposta inválida do sistema FAP (não é JSON).',
                data={'detail': body[:300].decode('utf-8', errors='replace')},
            )

        if not isinstance(items, list):
            return FapWebResult(
                ok=False,
                message='Formato de resposta inesperado.',
                data={'detail': str(items)[:300]},
            )

        return FapWebResult(ok=True, data=items)

    # ── Baixar PDF de uma contestação ─────────────────────────────────────

    def download_contestacao(
        self,
        year: int | str,
        cnpj: str,
        contestacao_id: int | str,
    ) -> FapWebResult:
        """Faz download do PDF de julgamento de uma contestação.

        Returns:
            FapWebResult com data={'pdf_bytes': bytes, 'filename': str} em caso de sucesso.
        """
        url = (
            f'{_BASE_URL}/gateway/fap/v1'
            f'/vigencias/{year}/empresa/{cnpj}/contestacoes/{contestacao_id}/imprimir'
        )
        try:
            body, _ = self._get(url, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return FapWebResult(
                    ok=False,
                    expired=True,
                    status_code=e.code,
                    message='Sessão expirada ou não autorizada. Atualize os dados de autenticação.',
                )
            return FapWebResult(ok=False, status_code=e.code, message=f'Erro HTTP {e.code} ao buscar documento.')
        except urllib.error.URLError as e:
            return FapWebResult(ok=False, message=f'Falha de conexão: {e.reason}')
        except Exception as e:
            return FapWebResult(ok=False, message=f'Erro inesperado: {str(e)}')

        try:
            api_data = json.loads(body)
            filename = api_data.get('nome') or f'contestacao_{contestacao_id}.pdf'
            pdf_bytes = base64.b64decode(api_data['base64'])
        except Exception as e:
            return FapWebResult(ok=False, message=f'Erro ao processar resposta do servidor: {str(e)}')

        return FapWebResult(ok=True, data={'pdf_bytes': pdf_bytes, 'filename': filename})
