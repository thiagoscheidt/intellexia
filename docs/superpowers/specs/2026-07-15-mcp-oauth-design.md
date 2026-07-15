# MCP com OAuth reusando a base de usuários — Design

**Data:** 2026-07-15 · **Status:** aprovado (Abordagem A)

## Objetivo

Substituir o Bearer estático do servidor MCP (`mcp_server/server.py`) por OAuth 2.1 completo,
autenticando contra a base de usuários existente do IntellexIA e reusando a sessão de login
do Flask (mesmo domínio). O Claude Code conecta em `https://rs-dev.intellexia.com.br/mcp`,
o navegador abre, o usuário (já logado) autoriza, e as tools passam a conhecer
`user_id`/`law_firm_id`/permissões — o parâmetro `law_firm_id` é removido das tools.

## Decisões aprovadas

1. **Abordagem A**: OAuth embutido no servidor MCP via `OAuthProvider` do FastMCP 3.2.4
   (discovery RFC 8414, Dynamic Client Registration, PKCE, `/authorize`, `/token` — tudo já
   implementado no SDK; nós implementamos o storage e a etapa de login/consentimento).
2. **`law_firm_id` sai das assinaturas** das tools; sempre derivado do token.
3. **Permissões espelhadas**: cada tool exige o módulo correspondente do
   `MODULE_PERMISSIONS` (`fap_panel`, `knowledge_base`, `fap_review`). Sem o módulo → erro
   claro de permissão.
4. Deploy no mesmo servidor (esta máquina), atrás do nginx existente de
   `rs-dev.intellexia.com.br`, backend uvicorn em `127.0.0.1:8001`.

## Arquitetura

```
Claude Code ──► https://rs-dev.intellexia.com.br/mcp  (nginx)
                  ├─ /mcp, /mcp/*  ──► uvicorn 127.0.0.1:8001 (strip /mcp)
                  └─ /.well-known/oauth-* ──► uvicorn 8001 (discovery)
uvicorn (mcp_server/server.py)
  ├─ FastMCP + IntellexiaOAuthProvider (OAuth AS + Resource Server)
  ├─ /consent (custom route) — lê cookie de sessão do Flask, tela de autorização
  └─ tools → identidade via get_access_token().claims
Flask (porta 5051) — login existente; ganha suporte a ?next= no /login
```

### Fluxo OAuth

1. Claude Code faz POST no `/mcp` → 401 com `resource_metadata` → discovery → DCR em
   `/mcp/register` → abre navegador em `/mcp/authorize?...` (PKCE S256).
2. `authorize()` salva a transação (params + client) em memória (TTL 10 min) e redireciona
   para `/mcp/consent?txn=...`.
3. `/consent` (GET): decodifica o cookie de sessão do Flask (mesma `SECRET_KEY`, mesmo
   domínio, via `SecureCookieSessionInterface`).
   - Sem sessão → redirect `https://rs-dev.intellexia.com.br/login?next=<consent_url>`.
   - Com sessão → recarrega `User` do banco (valida `is_active` + escritório ativo) e
     renderiza tela de consentimento (usuário, escritório, cliente OAuth) com CSRF.
4. `/consent` (POST approve): gera authorization code com snapshot de claims
   (`user_id`, `law_firm_id`, `email`, `name`, `role`, `modules[]`) → redirect ao
   `redirect_uri` do cliente com `code`+`state`. Deny → `error=access_denied`.
5. `/token`: troca code → access token (opaco, 1 h) + refresh token (opaco, 30 dias),
   persistidos no MySQL/SQLite. Refresh rotaciona o par e **recarrega o usuário do banco**
   (revalida ativo + permissões atuais).
6. Cada request MCP: `verify_token` busca o token no banco → `AccessToken.claims`.

### Storage

- `mcp_oauth_clients` — clientes DCR: `client_id` (único), `client_info_json`, `created_at`.
- `mcp_oauth_tokens` — access e refresh: `token` (único, indexado), `token_type`,
  `client_id`, `user_id`, `law_firm_id`, `claims_json`, `scopes_json`, `expires_at`,
  `revoked`, `pair_token`, `created_at`.
- Transações de autorização e authorization codes: memória do processo (vida < 10 min,
  worker único). Reinício no meio do fluxo = usuário tenta de novo.

### Mudanças em arquivos

| Arquivo | Mudança |
|---|---|
| `app/models.py` | + `McpOAuthClient`, `McpOAuthToken` |
| `database/add_mcp_oauth_tables.py` | migration idempotente (novo) |
| `mcp_server/oauth_provider.py` | `IntellexiaOAuthProvider` (novo) |
| `mcp_server/identity.py` | `get_identity()` / `require_module()` (novo) |
| `mcp_server/server.py` | reescrito: auth OAuth, rotas `/consent`, tools sem `law_firm_id`; Bearer estático e stdio removidos |
| `mcp_server/tools/*.py` | handlers inalterados (continuam recebendo `law_firm_id`, agora vindo do token) |
| `app/blueprints/auth.py` + `templates/login.html` | suporte a `?next=` seguro (path relativo apenas) |
| `deploy/intellexia-mcp.service`, `deploy/nginx-rs-dev-mcp.conf` | artefatos de deploy (novos) |
| README | seção MCP reescrita; token vazado removido |

### Mapeamento tool → módulo

| Tool | Módulo exigido |
|---|---|
| `query_knowledge_base` | `knowledge_base` |
| `list_fap_companies`, `list_fap_contestacoes`, `list_fap_benefits`, `get_benefit_detail` | `fap_panel` |
| `review_initial_petition` | `fap_review` |

### Nginx (rs-dev.intellexia.com.br)

```nginx
location = /mcp { proxy_pass http://127.0.0.1:8001/; ... }
location /mcp/ { proxy_pass http://127.0.0.1:8001/; ... }
location = /.well-known/oauth-authorization-server/mcp { proxy_pass http://127.0.0.1:8001/.well-known/oauth-authorization-server; }
location = /.well-known/oauth-authorization-server     { proxy_pass http://127.0.0.1:8001/.well-known/oauth-authorization-server; }
location /.well-known/oauth-protected-resource         { proxy_pass http://127.0.0.1:8001; }
```

(Confirmado por probe: com `base_url=https://rs-dev.intellexia.com.br/mcp` e
`http_app(path="/")`, o backend serve `/authorize`, `/token`, `/register`, `/` (MCP) e
`/.well-known/oauth-protected-resource/mcp/`; os metadados publicam os endpoints públicos
corretos sob `/mcp`.)

### Env

- `MCP_PUBLIC_URL` (default `https://rs-dev.intellexia.com.br/mcp`) — base pública.
- `APP_PUBLIC_URL` (default `https://rs-dev.intellexia.com.br`) — para o redirect de login.
- `MCP_HOST`/`MCP_PORT` mantidos. `MCP_API_KEY` e `MCP_TRANSPORT` removidos.

### Segurança

- PKCE S256 obrigatório e validação de `redirect_uri` — feitos pelo SDK.
- CSRF token na tela de consentimento; `next=` só aceita path relativo (`/...`, nunca `//`).
- Códigos de autorização single-use; refresh com rotação; revogação em par.
- Claims re-derivadas do banco a cada refresh (usuário desativado perde acesso em ≤ 1 h).
- Isolamento de tenant real: `law_firm_id` vem exclusivamente do token.

### Testes

`tests/test_mcp_oauth.py` (script standalone, padrão do projeto): via `httpx.ASGITransport`
exercita discovery → DCR → authorize → consent (cookie de sessão Flask forjado com a
`SECRET_KEY` real) → token → chamada JSON-RPC de tool com Bearer → recusa sem token,
recusa sem módulo, refresh com rotação.

### Conexão do Claude Code

```bash
claude mcp add --transport http intellexia https://rs-dev.intellexia.com.br/mcp
# depois: /mcp → Authenticate → navegador abre → autorizar
```
