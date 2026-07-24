# Login com Google (restrito a usuários já cadastrados)

**Data:** 2026-07-24
**Status:** aprovado para implementação

## Objetivo

Oferecer "Continuar com Google" na tela de login como **alternativa** ao login por
e-mail/senha, que permanece intacto. O Google serve apenas para *autenticar* — a
*autorização* continua sendo do IntellexIA: só entra quem já tem `User` na base.
O fluxo **nunca cria usuário nem escritório**.

## Decisões

| Questão | Decisão |
|---|---|
| Chave de identificação | E-mail verificado pelo Google, casado com `User.email` (case-insensitive) |
| Vínculo com a conta Google | Grava `sub` (ID imutável do Google) no primeiro login |
| Troca de conta Google (mesmo e-mail) | Revinculação automática: e-mail bate + `email_verified` → sobrescreve o `sub` |
| Fluxo técnico | Authorization Code com redirect, via Authlib (já instalado como dependência do `fastmcp`) |
| Login por senha | Preservado, sem alteração de comportamento |

Com revinculação automática o `sub` é registro/auditoria; a garantia efetiva é
"o Google confirmou que essa pessoa é dona deste e-mail" (`email_verified`).

## Fluxo e rotas

Duas rotas novas em `app/blueprints/auth.py`, ambas em `public_endpoints`
(`app/middlewares.py`):

- **`GET /login/google`** — guarda o `next` (validado por `_safe_next_url`) na
  sessão e redireciona ao Google com escopo `openid email profile`. `state` e
  `nonce` são gerados e conferidos pelo Authlib.
- **`GET /login/google/callback`** — o Authlib troca o `code` pelo token usando o
  `CLIENT_SECRET` e valida o `id_token` (assinatura via JWKS do Google, `iss`,
  `aud`, `exp`, `nonce`). De lá saem `email`, `email_verified`, `sub` e `name`.

O `redirect_uri` é montado com `app_public_url()` (`app/utils/urls.py`) +
`url_for('auth.google_callback')` — **não** com `_external=True`: a app não usa
ProxyFix e atrás do nginx sairia `http://` com host errado.

A configuração do Authlib fica isolada em `app/services/google_oauth.py`
(`init_google_oauth(app)` + `google_login_enabled()`), chamada no `main.py`. Sem
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` o recurso não existe: o botão some da
tela e as rotas devolvem erro amigável (mesma degradação graciosa do
`email_service`).

## Regras de decisão (nesta ordem)

1. `email_verified` diferente de `true` → recusa.
2. Busca `User` por e-mail case-insensitive (`func.lower(User.email)`). Não achou
   → recusa com mensagem neutra ("Esta conta Google não está autorizada. Fale com
   o administrador do escritório."), sem revelar se o e-mail existe.
3. `user.is_active` falso → mesma mensagem de conta inativa do login por senha.
4. `user.law_firm.is_active` falso → mesma mensagem de escritório inativo.
5. Passou: se `google_sub` estiver vazio **ou diferente**, grava o novo `sub` e
   `google_linked_at` (revinculação automática); atualiza `last_login`/
   `last_activity` e monta a sessão.

Se o `sub` já estiver em outro usuário (pessoa trocou de e-mail no escritório), o
vínculo antigo é limpo antes de gravar, para não violar o índice único.

## Dados

Duas colunas em `users`:

| Coluna | Tipo | Observação |
|---|---|---|
| `google_sub` | `VARCHAR(64) NULL` | índice único (vários `NULL` são permitidos) |
| `google_linked_at` | `DATETIME NULL` | auditoria do vínculo |

Migration standalone idempotente: `database/add_google_auth_to_users.py`.

## Refactor pontual

`login_post` monta sete chaves de sessão à mão. Extrair
`_start_user_session(user, remember=False)` no próprio `auth.py` e usar nos dois
caminhos — senão qualquer chave nova de sessão passa a existir só em um dos
logins. É a única mudança em código existente.

## Tela de login

Abaixo do botão "Entrar", separador "ou" e botão branco "Continuar com Google"
com o "G" oficial em SVG inline (sem CDN novo). É um `<a href>` fora do `<form>`,
então não interfere no submit AJAX. Renderizado só quando `google_login_enabled()`.

`templates/login.html` não renderiza flash messages, então os erros do Google
voltam como `/login?erro=<código>` e a view `login()` traduz o código em texto,
exibido na caixa de alerta que já existe.

## Configuração no Google Cloud Console

- **Authorized redirect URIs** (exatos, um por ambiente):
  - `https://<domínio de produção>/login/google/callback`
  - `https://rs-dev.intellexia.com.br/login/google/callback`
  - `http://localhost:5000/login/google/callback` (dev local)
- **OAuth consent screen**: escopos `openid`, `email`, `profile` são não-sensíveis
  → não exige verificação do Google. Se o app estiver *External* em modo
  *Testing*, só entram os "test users" — publicar o app (ou usar *Internal*, se o
  escritório for Google Workspace).
- `.env`: `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET`.

## Adição posterior: medir a adoção

Para saber se o time vai usar o Google e quando usou, duas colunas a mais em
`users` (migration `database/add_google_login_stats_to_users.py`):

| Coluna | Tipo | Observação |
|---|---|---|
| `google_last_login_at` | `DATETIME NULL` | último login pelo botão do Google |
| `google_login_count` | `INTEGER NOT NULL DEFAULT 0` | quantas vezes entrou por lá |

Só o caminho do Google incrementa (`_start_user_session(..., via_google=True)`).
`access_audit_service` expõe `google_last_login`, `google_login_count` e
`last_login_via_google` por usuário, mais `google_users` e
`google_logins_today` nas estatísticas. A tela `/admin/access-audit` ganha a
coluna "Login com Google", um marcador no "Último login" quando o acesso mais
recente veio do Google e o contador "X de Y já entraram com Google".

## Verificação

Script standalone `tests/test_google_login.py` (padrão do diretório, com
`app.test_client()`), com o retorno do Google mockado: e-mail não cadastrado →
recusa; usuário inativo → recusa; escritório inativo → recusa;
`email_verified=false` → recusa; primeiro login → grava `sub`; login com `sub`
diferente → revincula; Google não configurado → recusa amigável.
