"""
IntellexiaOAuthProvider
=======================
OAuth 2.1 Authorization Server para o servidor MCP, autenticando contra a
base de usuários do IntellexIA e reusando a sessão de login do Flask
(mesmo domínio → mesmo cookie).

O protocolo (discovery, DCR, PKCE, /authorize, /token, /revoke) é implementado
pelo FastMCP/MCP SDK; esta classe implementa:
  - storage de clientes e tokens (MySQL/SQLite via SQLAlchemy)
  - a etapa de login/consentimento (/consent), lendo o cookie de sessão do Flask
  - emissão de tokens opacos com claims do usuário (user_id, law_firm_id, modules)
"""
from __future__ import annotations

import html
import json
import secrets
import time
from urllib.parse import quote, urlparse

from flask.sessions import SecureCookieSessionInterface
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from fastmcp.server.auth.auth import (
    AccessToken,
    ClientRegistrationOptions,
    OAuthProvider,
    RevocationOptions,
)

AUTH_CODE_TTL_SECONDS = 5 * 60
TXN_TTL_SECONDS = 10 * 60
ACCESS_TOKEN_TTL_SECONDS = 60 * 60          # 1 hora
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 dias


class IntellexiaOAuthProvider(OAuthProvider):
    """OAuth server MCP com login via sessão Flask e storage no banco do IntellexIA."""

    def __init__(self, *, base_url: str, app_public_url: str | None = None):
        super().__init__(
            base_url=base_url,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        )
        parsed = urlparse(base_url)
        # URL pública do app Flask (login) — por padrão, a raiz do mesmo domínio
        self.app_public_url = (app_public_url or f"{parsed.scheme}://{parsed.netloc}").rstrip("/")
        # Path público do consentimento (ex.: /mcp/consent), usado em redirects relativos
        self.consent_public_path = f"{parsed.path.rstrip('/')}/consent"

        # Estado de curta duração (worker único): transações de autorização e auth codes
        self._txns: dict[str, dict] = {}
        self._codes: dict[str, tuple[AuthorizationCode, dict]] = {}

    def _get_resource_url(self, path: str | None = None):
        # O endpoint MCP roda na raiz do app interno (path="/") e o path público
        # já está no base_url (/mcp). Sem isso, o resource anunciado ganharia
        # barra final (".../mcp/") e clientes com comparação estrita (RFC 9728,
        # ex.: Claude Code) rejeitariam por não bater com ".../mcp".
        return super()._get_resource_url(None if path == "/" else path)

    # ── Helpers de app/banco ──────────────────────────────────────────────────

    @staticmethod
    def _flask_app():
        from main import app
        return app

    def _load_flask_session(self, request: Request) -> dict | None:
        """Decodifica o cookie de sessão do Flask presente na request (mesmo domínio)."""
        app = self._flask_app()
        cookie_name = app.config.get("SESSION_COOKIE_NAME", "session")
        cookie_val = request.cookies.get(cookie_name)
        if not cookie_val:
            return None
        serializer = SecureCookieSessionInterface().get_signing_serializer(app)
        if serializer is None:
            return None
        try:
            data = serializer.loads(cookie_val)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _load_active_user(self, user_id: int):
        """Carrega o usuário do banco, validando usuário e escritório ativos."""
        from app.models import User

        user = User.query.get(user_id)
        if not user or not user.is_active:
            return None
        if not user.law_firm or not user.law_firm.is_active:
            return None
        return user

    @staticmethod
    def _build_claims(user) -> dict:
        return {
            "user_id": user.id,
            "law_firm_id": user.law_firm_id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "modules": user.get_module_permissions(),
        }

    def _prune_expired(self) -> None:
        now = time.time()
        for store, ttl_key in ((self._txns, "created_at"), ):
            for key in [k for k, v in store.items() if now - v[ttl_key] > TXN_TTL_SECONDS]:
                store.pop(key, None)
        for code in [c for c, (obj, _) in self._codes.items() if obj.expires_at < now]:
            self._codes.pop(code, None)

    # ── Clientes (Dynamic Client Registration) ────────────────────────────────

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        from app.models import McpOAuthClient

        with self._flask_app().app_context():
            row = McpOAuthClient.query.filter_by(client_id=client_id).first()
            if not row:
                return None
            return OAuthClientInformationFull.model_validate_json(row.client_info_json)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        from app.models import db, McpOAuthClient

        if not client_info.client_id:
            raise ValueError("client_id é obrigatório no registro de cliente")

        with self._flask_app().app_context():
            row = McpOAuthClient.query.filter_by(client_id=client_info.client_id).first()
            payload = client_info.model_dump_json()
            if row:
                row.client_info_json = payload
            else:
                db.session.add(McpOAuthClient(client_id=client_info.client_id, client_info_json=payload))
            db.session.commit()

    # ── Autorização: /authorize → /consent ────────────────────────────────────

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Guarda a transação e envia o navegador para a tela de consentimento."""
        self._prune_expired()
        txn_id = secrets.token_urlsafe(32)
        self._txns[txn_id] = {
            "client": client,
            "params": params,
            "csrf": secrets.token_urlsafe(32),
            "created_at": time.time(),
        }
        return f"{str(self.base_url).rstrip('/')}/consent?txn={txn_id}"

    async def consent_page(self, request: Request) -> Response:
        """GET /consent — exige sessão Flask ativa e mostra a tela de autorização."""
        self._prune_expired()
        txn_id = request.query_params.get("txn", "")
        txn = self._txns.get(txn_id)
        if not txn:
            return HTMLResponse(self._render_error(
                "Solicitação expirada",
                "A solicitação de autorização expirou ou é inválida. "
                "Volte ao Claude e tente conectar novamente."), status_code=400)

        session_data = self._load_flask_session(request)
        user_id = (session_data or {}).get("user_id")
        if not user_id:
            next_path = f"{self.consent_public_path}?txn={txn_id}"
            return RedirectResponse(
                f"{self.app_public_url}/login?next={quote(next_path, safe='')}", status_code=302
            )

        with self._flask_app().app_context():
            user = self._load_active_user(user_id)
            if not user:
                return HTMLResponse(self._render_error(
                    "Acesso negado",
                    "Seu usuário ou escritório está inativo. Entre em contato com o suporte."),
                    status_code=403)
            client = txn["client"]
            client_name = getattr(client, "client_name", None) or client.client_id
            return HTMLResponse(self._render_consent(
                txn_id=txn_id,
                csrf=txn["csrf"],
                user_name=user.name,
                user_email=user.email,
                law_firm_name=user.law_firm.name,
                client_name=client_name,
            ))

    async def consent_submit(self, request: Request) -> Response:
        """POST /consent — aprova ou nega; aprova emitindo o authorization code."""
        self._prune_expired()
        form = await request.form()
        txn_id = str(form.get("txn", ""))
        txn = self._txns.get(txn_id)
        if not txn or not secrets.compare_digest(str(form.get("csrf", "")), txn["csrf"]):
            return HTMLResponse(self._render_error(
                "Solicitação inválida",
                "Sessão de autorização inválida ou expirada. Tente conectar novamente."),
                status_code=400)

        session_data = self._load_flask_session(request)
        user_id = (session_data or {}).get("user_id")
        if not user_id:
            return HTMLResponse(self._render_error(
                "Não autenticado",
                "Sua sessão do IntellexIA expirou. Faça login e tente novamente."), status_code=401)

        params: AuthorizationParams = txn["params"]
        client: OAuthClientInformationFull = txn["client"]
        self._txns.pop(txn_id, None)

        if form.get("action") != "approve":
            return RedirectResponse(
                construct_redirect_uri(str(params.redirect_uri), error="access_denied", state=params.state),
                status_code=302,
            )

        with self._flask_app().app_context():
            user = self._load_active_user(user_id)
            if not user:
                return HTMLResponse(self._render_error(
                    "Acesso negado",
                    "Seu usuário ou escritório está inativo."), status_code=403)
            claims = self._build_claims(user)

        code_value = secrets.token_urlsafe(32)
        auth_code = AuthorizationCode(
            code=code_value,
            client_id=client.client_id,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=params.scopes or [],
            expires_at=time.time() + AUTH_CODE_TTL_SECONDS,
            code_challenge=params.code_challenge,
        )
        self._codes[code_value] = (auth_code, claims)

        return RedirectResponse(
            construct_redirect_uri(str(params.redirect_uri), code=code_value, state=params.state),
            status_code=302,
        )

    # ── Códigos e tokens ──────────────────────────────────────────────────────

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        entry = self._codes.get(authorization_code)
        if not entry:
            return None
        code_obj, _ = entry
        if code_obj.client_id != client.client_id or code_obj.expires_at < time.time():
            self._codes.pop(authorization_code, None)
            return None
        return code_obj

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        entry = self._codes.pop(authorization_code.code, None)
        if not entry:
            raise TokenError("invalid_grant", "Código de autorização inválido ou já utilizado.")
        _, claims = entry
        return self._issue_token_pair(client, claims, authorization_code.scopes)

    def _issue_token_pair(
        self, client: OAuthClientInformationFull, claims: dict, scopes: list[str]
    ) -> OAuthToken:
        from app.models import db, McpOAuthToken

        access_value = f"iax_at_{secrets.token_urlsafe(43)}"
        refresh_value = f"iax_rt_{secrets.token_urlsafe(43)}"
        now = int(time.time())

        with self._flask_app().app_context():
            common = dict(
                client_id=client.client_id,
                user_id=claims["user_id"],
                law_firm_id=claims["law_firm_id"],
                claims_json=json.dumps(claims, ensure_ascii=False),
                scopes_json=json.dumps(scopes),
            )
            db.session.add(McpOAuthToken(
                token=access_value, token_type="access",
                expires_at=now + ACCESS_TOKEN_TTL_SECONDS, pair_token=refresh_value, **common))
            db.session.add(McpOAuthToken(
                token=refresh_value, token_type="refresh",
                expires_at=now + REFRESH_TOKEN_TTL_SECONDS, pair_token=access_value, **common))
            # Limpeza oportunista de tokens expirados há mais de 60 dias
            cutoff = now - 60 * 24 * 3600
            McpOAuthToken.query.filter(
                McpOAuthToken.expires_at.isnot(None),
                McpOAuthToken.expires_at < cutoff,
            ).delete(synchronize_session=False)
            db.session.commit()

        return OAuthToken(
            access_token=access_value,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=refresh_value,
            scope=" ".join(scopes) if scopes else None,
        )

    def _load_token_row(self, token: str, token_type: str):
        from app.models import McpOAuthToken

        row = McpOAuthToken.query.filter_by(token=token, token_type=token_type).first()
        if not row or row.revoked:
            return None
        if row.expires_at is not None and row.expires_at < time.time():
            return None
        return row

    async def load_access_token(self, token: str) -> AccessToken | None:
        with self._flask_app().app_context():
            row = self._load_token_row(token, "access")
            if not row:
                return None
            return AccessToken(
                token=row.token,
                client_id=row.client_id,
                scopes=json.loads(row.scopes_json or "[]"),
                expires_at=row.expires_at,
                claims=json.loads(row.claims_json or "{}"),
            )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        with self._flask_app().app_context():
            row = self._load_token_row(refresh_token, "refresh")
            if not row or row.client_id != client.client_id:
                return None
            return RefreshToken(
                token=row.token,
                client_id=row.client_id,
                scopes=json.loads(row.scopes_json or "[]"),
                expires_at=row.expires_at,
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        from app.models import db, McpOAuthToken

        requested = set(scopes)
        if not requested.issubset(set(refresh_token.scopes)):
            raise TokenError("invalid_scope", "Escopos solicitados excedem os autorizados.")

        with self._flask_app().app_context():
            row = self._load_token_row(refresh_token.token, "refresh")
            if not row:
                raise TokenError("invalid_grant", "Refresh token inválido ou revogado.")

            # Revalida o usuário e re-deriva permissões atuais
            user = self._load_active_user(row.user_id)
            if not user:
                raise TokenError("invalid_grant", "Usuário ou escritório inativo.")
            claims = self._build_claims(user)

            # Rotação: revoga o par antigo
            McpOAuthToken.query.filter(
                McpOAuthToken.token.in_([row.token, row.pair_token])
            ).update({"revoked": True}, synchronize_session=False)
            db.session.commit()

        return self._issue_token_pair(client, claims, scopes or refresh_token.scopes)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        from app.models import db, McpOAuthToken

        with self._flask_app().app_context():
            row = McpOAuthToken.query.filter_by(token=token.token).first()
            if not row:
                return
            McpOAuthToken.query.filter(
                McpOAuthToken.token.in_([row.token, row.pair_token])
            ).update({"revoked": True}, synchronize_session=False)
            db.session.commit()

    # ── HTML ──────────────────────────────────────────────────────────────────
    # Visual alinhado à tela de login do IntellexIA (fundo #0A0B0F, card #11131A,
    # acento indigo, fonte Inter) — o usuário chega aqui vindo do login e a tela
    # de autorização precisa ser reconhecível como a mesma plataforma.

    def _page(self, title: str, body: str) -> str:
        logo_url = f"{self.app_public_url}/static/assets/img/logo_maior.png"
        return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — IntellexIA</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif;
    background: #0A0B0F; color: #f1f5f9; margin: 0;
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    padding: 40px 16px;
    background-image:
      radial-gradient(circle at 20% 20%, rgba(148,163,184,.08), transparent 35%),
      radial-gradient(circle at 80% 70%, rgba(99,102,241,.12), transparent 40%);
  }}
  .card {{
    width: 100%; max-width: 420px; background: #11131A;
    border: 1px solid #1e293b; border-radius: 24px;
    box-shadow: 0 24px 80px rgba(0,0,0,.45); overflow: hidden;
    animation: rise .35s ease-out;
  }}
  @keyframes rise {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: none; }} }}
  @media (prefers-reduced-motion: reduce) {{ .card {{ animation: none; }} }}
  .head {{ padding: 28px 32px 24px; text-align: center; border-bottom: 1px solid #1e293b; }}
  .head img {{ height: 56px; width: auto; object-fit: contain; }}
  .brand-fallback {{ display: none; font-weight: 700; font-size: 1.3rem; color: #a5b4fc; letter-spacing: .3px; }}
  h1 {{ font-size: 1.15rem; font-weight: 600; color: #fff; margin: 14px 0 4px; letter-spacing: -.01em; }}
  .sub {{ color: #94a3b8; font-size: .875rem; margin: 0; line-height: 1.5; }}
  .sub strong {{ color: #e2e8f0; font-weight: 600; }}
  .body {{ padding: 24px 32px 28px; }}
  .who {{
    display: flex; align-items: center; gap: 12px;
    background: #0d0f15; border: 1px solid #1e293b; border-radius: 14px; padding: 14px 16px;
  }}
  .avatar {{
    width: 40px; height: 40px; border-radius: 50%; flex: none;
    background: linear-gradient(135deg, #4f46e5, #7c3aed);
    display: flex; align-items: center; justify-content: center;
    font-weight: 600; font-size: .875rem; color: #fff;
  }}
  .who .name {{ font-weight: 600; font-size: .9rem; color: #f1f5f9; }}
  .who .meta {{ font-size: .78rem; color: #94a3b8; margin-top: 1px; }}
  ul.grants {{ list-style: none; margin: 18px 0 0; padding: 0; }}
  ul.grants li {{
    display: flex; gap: 10px; align-items: flex-start;
    font-size: .82rem; color: #cbd5e1; line-height: 1.45; padding: 5px 0;
  }}
  ul.grants svg {{ flex: none; margin-top: 2px; }}
  .actions {{ display: flex; gap: 12px; margin-top: 22px; }}
  button {{
    flex: 1; padding: 11px 0; border-radius: 12px; border: 0;
    font-family: inherit; font-size: .875rem; font-weight: 600; cursor: pointer;
    transition: background .15s ease;
  }}
  button:focus-visible {{ outline: none; box-shadow: 0 0 0 4px rgba(99,102,241,.3); }}
  .approve {{ background: #4f46e5; color: #fff; }}
  .approve:hover {{ background: #6366f1; }}
  .deny {{ background: transparent; color: #cbd5e1; border: 1px solid #334155; }}
  .deny:hover {{ background: #1e293b33; }}
  .foot {{ margin: 18px 0 0; text-align: center; font-size: .75rem; color: #64748b; }}
  p.error-msg {{ color: #94a3b8; font-size: .9rem; line-height: 1.6; margin: 0; }}
</style></head>
<body>
<main class="card">
  <div class="head">
    <img src="{html.escape(logo_url)}" alt="IntellexIA"
         onerror="this.style.display='none';this.nextElementSibling.style.display='block'">
    <div class="brand-fallback">IntellexIA</div>
    {body}
</main>
</body></html>"""

    def _render_consent(self, *, txn_id: str, csrf: str, user_name: str, user_email: str,
                        law_firm_name: str, client_name: str) -> str:
        initials = "".join(p[0] for p in user_name.split()[:2]).upper() if user_name else "?"
        check_icon = (
            '<svg width="15" height="15" viewBox="0 0 20 20" fill="none">'
            '<circle cx="10" cy="10" r="9" stroke="#4f46e5" stroke-width="1.5"/>'
            '<path d="M6.5 10.5l2.2 2.2 4.8-5.4" stroke="#a5b4fc" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>'
        )
        body = f"""
    <h1>Autorizar acesso</h1>
    <p class="sub"><strong>{html.escape(client_name)}</strong> quer acessar o IntellexIA em seu nome.</p>
  </div>
  <div class="body">
    <div class="who">
      <div class="avatar">{html.escape(initials)}</div>
      <div>
        <div class="name">{html.escape(user_name)}</div>
        <div class="meta">{html.escape(user_email)} · {html.escape(law_firm_name)}</div>
      </div>
    </div>
    <ul class="grants">
      <li>{check_icon}<span>Consultar dados conforme <strong>suas permissões de módulo</strong> (FAP, base de conhecimento, processos...)</span></li>
      <li>{check_icon}<span>Acesso restrito aos dados do escritório <strong>{html.escape(law_firm_name)}</strong></span></li>
      <li>{check_icon}<span>Você pode revogar o acesso a qualquer momento desconectando o aplicativo</span></li>
    </ul>
    <form method="post" action="{html.escape(self.consent_public_path)}">
      <input type="hidden" name="txn" value="{html.escape(txn_id)}">
      <input type="hidden" name="csrf" value="{html.escape(csrf)}">
      <div class="actions">
        <button class="deny" type="submit" name="action" value="deny">Negar</button>
        <button class="approve" type="submit" name="action" value="approve">Autorizar acesso</button>
      </div>
    </form>
    <p class="foot">Você será redirecionado de volta ao aplicativo.</p>
  </div>"""
        return self._page("Autorizar acesso", body)

    def _render_error(self, title: str, message: str) -> str:
        body = f"""
    <h1>{html.escape(title)}</h1>
  </div>
  <div class="body">
    <p class="error-msg">{html.escape(message)}</p>
  </div>"""
        return self._page(title, body)
