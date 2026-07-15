"""
Teste ponta a ponta do fluxo OAuth do servidor MCP.

Exercita, contra o app ASGI real (sem rede):
  1. Discovery (/.well-known/oauth-authorization-server)
  2. Dynamic Client Registration (/register)
  3. /authorize com PKCE → redirect para /consent
  4. /consent sem sessão → redirect para /login?next=...
  5. /consent com cookie de sessão Flask válido → aprovação → code
  6. /token (authorization_code + PKCE) → access/refresh tokens
  7. Chamada MCP autenticada (initialize + tools/call list_fap_companies)
  8. Chamada sem token → 401
  9. Tool sem permissão de módulo → erro claro
 10. Refresh com rotação (token antigo revogado)

Uso:
    uv run python tests/test_mcp_oauth.py
"""
import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["MCP_PUBLIC_URL"] = "http://localhost:8001"

import httpx
from flask.sessions import SecureCookieSessionInterface

from main import app as flask_app
from app.models import db, LawFirm, User, McpOAuthClient, McpOAuthToken
import mcp_server.server as mcp_server_module

REDIRECT_URI = "http://localhost:33418/callback"
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, ok))
    print(f"{'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        raise AssertionError(f"{name}: {detail}")


def make_session_cookie(user_id):
    serializer = SecureCookieSessionInterface().get_signing_serializer(flask_app)
    return serializer.dumps({"user_id": user_id})


def parse_mcp_response(resp):
    """Extrai o payload JSON-RPC de resposta JSON ou SSE."""
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        for line in resp.text.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:])
        return None
    return resp.json()


async def run_oauth_flow(client, session_cookie):
    """DCR + authorize + consent + token. Retorna (tokens_dict, client_id)."""
    r = await client.get("/.well-known/oauth-authorization-server")
    check("discovery de metadados", r.status_code == 200, str(r.status_code))
    meta = r.json()
    check("endpoints publicados", all(k in meta for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint")))

    r = await client.post("/register", json={
        "redirect_uris": [REDIRECT_URI],
        "client_name": "Teste OAuth IntellexIA",
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    })
    check("dynamic client registration", r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}")
    client_id = r.json()["client_id"]

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)

    r = await client.get("/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
    })
    check("authorize redireciona para consent", r.status_code in (302, 307) and "/consent?txn=" in r.headers.get("location", ""), f"{r.status_code} {r.headers.get('location')}")
    consent_url = r.headers["location"]
    consent_path = "/" + consent_url.split("://", 1)[-1].split("/", 1)[-1]

    r = await client.get(consent_path)
    check("consent sem sessão exige login", r.status_code == 302 and "/login?next=" in r.headers.get("location", ""), f"{r.status_code} {r.headers.get('location')}")

    r = await client.get(consent_path, cookies={"session": session_cookie})
    check("consent com sessão renderiza tela", r.status_code == 200 and "Autorizar acesso" in r.text, f"{r.status_code}")
    txn = re.search(r'name="txn" value="([^"]+)"', r.text).group(1)
    csrf = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)

    r = await client.post("/consent", data={"txn": txn, "csrf": csrf, "action": "approve"},
                          cookies={"session": session_cookie})
    loc = r.headers.get("location", "")
    check("aprovação redireciona com code", r.status_code == 302 and loc.startswith(REDIRECT_URI) and "code=" in loc, f"{r.status_code} {loc}")
    qs = parse_qs(urlparse(loc).query)
    check("state preservado", qs.get("state", [None])[0] == state)
    code = qs["code"][0]

    r = await client.post("/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
        "client_id": client_id, "code_verifier": verifier,
    })
    check("troca code por tokens", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
    tokens = r.json()
    check("access e refresh emitidos", bool(tokens.get("access_token")) and bool(tokens.get("refresh_token")))
    return tokens, client_id


async def mcp_initialize(client, access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json, text/event-stream",
    }
    r = await client.post("/", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "teste", "version": "0.0.1"}},
    })
    check("initialize autenticado", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
    session_id = r.headers.get("mcp-session-id")
    headers["mcp-session-id"] = session_id
    await client.post("/", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    return headers


async def mcp_tool_call(client, headers, name, args, req_id=2):
    r = await client.post("/", headers=headers, json={
        "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
        "params": {"name": name, "arguments": args},
    })
    return r, parse_mcp_response(r)


async def main():
    suffix = secrets.token_hex(4)
    with flask_app.app_context():
        firm = LawFirm(name=f"Escritório Teste MCP {suffix}", cnpj=f"99{suffix}", is_active=True)
        db.session.add(firm)
        db.session.flush()
        user = User(law_firm_id=firm.id, name="Usuário MCP Teste",
                    email=f"mcp-test-{suffix}@teste.local", role="lawyer", is_active=True)
        user.set_password("senha-teste")
        user.set_module_permissions(["fap_panel", "knowledge_base"])
        db.session.add(user)
        db.session.commit()
        user_id, firm_id = user.id, firm.id

    session_cookie = make_session_cookie(user_id)
    asgi_app = mcp_server_module.mcp.http_app(path="/")
    client_id = None

    try:
        async with asgi_app.router.lifespan_context(asgi_app):
            transport = httpx.ASGITransport(app=asgi_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8001") as client:
                # Fluxo OAuth completo
                tokens, client_id = await run_oauth_flow(client, session_cookie)

                # Chamada MCP autenticada
                headers = await mcp_initialize(client, tokens["access_token"])
                r, payload = await mcp_tool_call(client, headers, "listar_empresas_fap", {})
                ok = r.status_code == 200 and not payload["result"].get("isError")
                check("tool com permissão executa", ok, f"{r.status_code} {json.dumps(payload)[:300]}")

                # Sem token → 401
                r = await client.post("/", json={"jsonrpc": "2.0", "id": 9, "method": "ping"},
                                      headers={"Accept": "application/json, text/event-stream"})
                check("sem token retorna 401", r.status_code == 401, str(r.status_code))

                # Token com claims sem o módulo fap_panel → erro de permissão
                with flask_app.app_context():
                    limited_claims = {"user_id": user_id, "law_firm_id": firm_id,
                                      "email": "x@x", "name": "x", "role": "user",
                                      "modules": ["knowledge_base"]}
                    db.session.add(McpOAuthToken(
                        token=f"iax_at_limited_{suffix}", token_type="access", client_id=client_id,
                        user_id=user_id, law_firm_id=firm_id,
                        claims_json=json.dumps(limited_claims), scopes_json="[]",
                        expires_at=None))
                    db.session.commit()
                headers2 = await mcp_initialize(client, f"iax_at_limited_{suffix}")
                r, payload = await mcp_tool_call(client, headers2, "listar_empresas_fap", {})
                is_err = payload["result"].get("isError")
                msg = json.dumps(payload["result"].get("content", ""), ensure_ascii=False)
                check("tool sem módulo é negada", bool(is_err) and "Painel FAP" in msg, msg[:200])

                # Refresh com rotação
                r = await client.post("/token", data={
                    "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                    "client_id": client_id,
                })
                check("refresh emite novos tokens", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
                new_tokens = r.json()
                check("refresh rotaciona", new_tokens["access_token"] != tokens["access_token"])

                r = await client.post("/", headers={
                    "Authorization": f"Bearer {tokens['access_token']}",
                    "Accept": "application/json, text/event-stream",
                }, json={"jsonrpc": "2.0", "id": 10, "method": "ping"})
                check("access antigo revogado após refresh", r.status_code == 401, str(r.status_code))

                r = await client.post("/", headers={
                    "Authorization": f"Bearer {new_tokens['access_token']}",
                    "Accept": "application/json, text/event-stream",
                }, json={"jsonrpc": "2.0", "id": 11, "method": "initialize",
                         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "t", "version": "0"}}})
                check("access novo funciona", r.status_code == 200, str(r.status_code))
    finally:
        with flask_app.app_context():
            McpOAuthToken.query.filter_by(law_firm_id=firm_id).delete(synchronize_session=False)
            if client_id:
                McpOAuthClient.query.filter_by(client_id=client_id).delete(synchronize_session=False)
            User.query.filter_by(id=user_id).delete(synchronize_session=False)
            LawFirm.query.filter_by(id=firm_id).delete(synchronize_session=False)
            db.session.commit()

    print(f"\n{'='*50}\n🎉 {len(CHECKS)} verificações passaram")


if __name__ == "__main__":
    asyncio.run(main())
