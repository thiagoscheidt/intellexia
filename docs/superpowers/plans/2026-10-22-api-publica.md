# API do IntellexIA — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** API REST de leitura (`/api/v1`) sobre a base do escritório, com token pessoal gerenciado por tela e por MCP, e documentação gerada do código.

**Architecture:** Um registro de rotas (`public_api_catalogo`) declara cada rota com módulo, parâmetros e um adaptador que chama o **handler do MCP** já existente. O blueprint `public_api` monta as rotas a partir do registro e cuida de autenticação Bearer, CORS, erros, limite e registro de uso. Do mesmo registro saem o OpenAPI, a página de documentação e a ferramenta `documentacao_api` do MCP.

**Tech Stack:** Flask 3.1, SQLAlchemy, MySQL/SQLite, FastMCP 3.2.4 (só no servidor MCP), testes como scripts executáveis em `tests/`.

**Spec:** `docs/superpowers/specs/2026-10-22-api-publica-e-biblioteca-de-prompts-design.md` (Parte 1). A Biblioteca de Prompts (Parte 2) terá plano próprio.

## Global Constraints

- Prefixo `/api/v1`; autenticação **só** `Authorization: Bearer <token>`. Cookie de sessão e token em query string nunca autenticam.
- Token: `itx_` + `secrets.token_urlsafe(30)`; banco guarda só SHA-256 (hex) e `last4`; validade 30, 90 (padrão), 180 dias ou sem validade.
- Permissões conferidas **a cada requisição** no `User` atual (`is_active`, `get_module_permissions()`, `role`), nunca de retrato.
- Módulo novo `api` ("API e integrações") **dentro** dos padrões de todos os papéis.
- Nomes de parâmetros e chaves de resposta **iguais aos da ferramenta MCP equivalente** (`server.py`), em português.
- Erro sempre `{"erro": "<mensagem>"}`; 400 parâmetro, 401 token, 403 módulo, 404 não encontrado, 429 limite, 500 inesperado (sem traceback na resposta).
- CORS: `Access-Control-Allow-Origin: *`, `Access-Control-Allow-Headers: Authorization, Content-Type`, `Access-Control-Allow-Methods: GET, POST, OPTIONS`; sem `Allow-Credentials`.
- Limites (env): `API_LIMITE_POR_MINUTO=120` por token, em memória por processo; `API_LIMITE_PERGUNTAS_DIA=200` por usuário; revelar nome usa `CPF_NOME_LIMITE_DIARIO_MCP` **somando `origem` `mcp` + `api`**.
- Uso registrado em `user_mcp_calls` com `kind='api'` e `name='<MÉTODO> <caminho do registro>'` (ex.: `GET /fap/beneficios/{id}`), **sem argumentos**.
- Endereços via `app/utils/urls.py` (`app_public_url()`), nunca domínio fixo.
- Toda query filtra por `law_firm_id` do dono do token (os handlers já fazem; a API nunca recebe escritório por parâmetro).
- Migrations standalone em `database/`, idempotentes, dentro de `app.app_context()`.
- Commit e push **só quando o Thiago pedir**; cada task termina pronta para commit.

## Review Focus

1. **Filtro com nome errado** (`?tipo_benefico=B91`): 400 listando os parâmetros válidos da rota — nunca ignorar e devolver a base inteira. Teste na Task 3.
2. **Tipo errado** (`?limite=abc`, `/fap/beneficios/xyz`): 400 com o nome do parâmetro, nunca 500. Teste na Task 3.
3. **Token fora do header** (`?token=itx_...`) ou `bearer` minúsculo/espaço extra: query string → 401; esquema do header sem diferenciar maiúsculas e com `strip()`. Teste na Task 2.
4. **Exceção inesperada no handler**: 500 `{"erro": "Erro interno..."}`, logada com traceback, contada como erro no uso. Teste na Task 2.
5. **Preflight `OPTIONS` sem token** (navegador): 204 com os headers CORS, sem exigir token nem contar uso. Teste na Task 2.

---

### Task 1: Token de API — modelo, migration, permissão e serviço

**Files:**
- Modify: `app/models.py` (classe `ApiToken`, perto de `McpOAuthToken`)
- Modify: `app/utils/permissions.py` (`'api': 'API e integracoes'` em `MODULE_PERMISSIONS`; `'minha_api.': 'api'` em `ENDPOINT_MODULE_MAP`)
- Create: `database/add_api_tokens_table.py`
- Create: `app/services/api_token_service.py`
- Test: `tests/test_api_tokens.py`

**Interfaces:**
- Produces:
  - `ApiToken` (`api_tokens`): `id, law_firm_id (FK), user_id (FK CASCADE), name String(100), token_hash String(64) unique, last4 String(4), expires_at DateTime UTC nullable, revoked_at DateTime nullable, revoked_by_id (FK users SET NULL), created_at, last_used_at, last_used_ip String(45)`; propriedade `ativo -> bool`.
  - `api_token_service.PREFIXO = 'itx_'`, `VALIDADES_DIAS = (30, 90, 180, None)`
  - `criar(user: User, nome: str, dias: int | None = 90) -> tuple[ApiToken, str]` (commita; `dias` fora de `VALIDADES_DIAS` → `ValueError`)
  - `listar(user: User) -> list[ApiToken]` (do usuário, mais novo primeiro, inclui revogados)
  - `listar_do_escritorio(law_firm_id: int) -> list[ApiToken]`
  - `revogar(token_id: int, por: User) -> ApiToken` (dono ou admin do mesmo escritório; senão `PermissionError`; já revogado é idempotente)
  - `autenticar(token_em_claro: str, ip: str | None = None) -> User` (levanta `TokenInvalido(mensagem)`; atualiza `last_used_at`/`last_used_ip` sem commitar)
  - `serializar(t: ApiToken) -> dict` com `id, nome, final, criado_em, expira_em, ultimo_uso, situacao` (`ativo|vencido|revogado`) — nunca o hash.

- [ ] **Step 1: Escrever `tests/test_api_tokens.py`** no molde de `tests/test_mcp_uso.py` (escritório descartável com CNPJ fixo, `check()`, limpeza no fim). Asserções:
  - `criar` devolve texto que começa com `itx_`, `len > 40`; no banco `token_hash == sha256(texto).hexdigest()`, `last4 == texto[-4:]` e o texto não aparece em nenhuma coluna;
  - `autenticar(texto)` devolve o usuário; `autenticar('itx_errado')` → `TokenInvalido`;
  - token com `expires_at` no passado → `TokenInvalido` com "vencido" na mensagem; revogado → "revogado";
  - usuário com `is_active=False` → `TokenInvalido`;
  - `revogar` por outro lawyer → `PermissionError`; por admin do escritório → ok; admin de **outro** escritório → `PermissionError`;
  - `get_default_module_permissions('lawyer')` contém `'api'`;
  - apagar o usuário apaga os tokens.
- [ ] **Step 2:** `uv run python tests/test_api_tokens.py` → falha de import (`ApiToken`).
- [ ] **Step 3:** Implementar modelo, permissão e serviço. Comparar hash com `hmac.compare_digest` depois de buscar pelo hash. `expires_at` em UTC (`_utcnow()` como em `fap_procuracoes_service`).
- [ ] **Step 4:** Migration `database/add_api_tokens_table.py`: cria `api_tokens` se não existir e acrescenta `'api'` ao `module_permissions` gravado de cada usuário não-admin que tem lista própria (`parse_module_permissions` só aplica os padrões a quem tem a coluna vazia; quem tem lista gravada ficaria sem o módulo). Mostra quantos usuários recebeu; rodar duas vezes: a segunda diz que a tabela já existe e que 0 usuários mudaram. Acrescentar ao teste: usuário lawyer com `module_permissions` gravado sem `api` passa a ter `api` depois de `aplicar_modulo_api()` (função da migration, importável).
- [ ] **Step 5:** `uv run python tests/test_api_tokens.py` → todos ✅.

---

### Task 2: Núcleo do blueprint `public_api`

**Files:**
- Create: `app/blueprints/public_api.py` (`public_api_bp`, `url_prefix='/api/v1'`)
- Modify: `app/blueprints/__init__.py`, `main.py` (registrar)
- Modify: `app/middlewares.py` (`check_session` e qualquer outro `before_request` dependente de sessão retornam `None` logo no início quando `request.blueprint == 'public_api'`)
- Test: `tests/test_api_nucleo.py`

**Interfaces:**
- Consumes: `api_token_service.autenticar`, `TokenInvalido`; `access_audit_service.record_mcp_call(user_id, law_firm_id, kind, name, ok, elapsed_ms, error)`.
- Produces:
  - `Contexto` (dataclass): `user_id: int, law_firm_id: int, modulos: list[str], papel: str, app_public_url: str`
  - `ErroApi(Exception)`: `(mensagem: str, status: int)`
  - `executar(nome_uso: str, modulo: str | None, funcao: Callable[[Contexto], tuple[dict, int] | dict]) -> Response` — autentica, confere módulo, aplica limite por minuto, chama, converte erros, registra uso (`kind='api'`), devolve JSON. Usado pela Task 3 para montar cada rota.
  - Rota `GET /api/v1/eu` → `{usuario: {id, nome, email, papel}, escritorio: {id, nome}, modulos, token: {nome, final, expira_em}, consultas_nome_restantes_hoje}` (o último só com `fap_panel`).

Conversões no `executar`: `ErroApi` → seu status; `fastmcp.exceptions.ToolError` → 400; dict com chave `erro` e nada mais relevante numa rota marcada como detalhe é tratado na Task 3; qualquer outra exceção → `logger.exception` + 500 `{"erro": "Erro interno ao processar a requisição."}`. CORS em `after_request` do blueprint; `OPTIONS` respondido antes da autenticação com 204. Limite por minuto: dicionário `{token_hash: deque[timestamps]}` protegido por `threading.Lock`, janela de 60 s, 429 com header `Retry-After`.

- [ ] **Step 1: Escrever `tests/test_api_nucleo.py`** com `app.test_client()`. Asserções:
  - sem header → 401 `{"erro": ...}`; `?token=<válido>` sem header → 401;
  - `Authorization: bearer  <válido> ` (minúsculo, espaços) → 200 em `/api/v1/eu`;
  - sessão logada (`client.session_transaction()` com `user_id`) e sem header → 401;
  - `/eu` traz `modulos` atuais: retirar `fap_panel` do usuário depois de criar o token e chamar de novo → `fap_panel` some e `consultas_nome_restantes_hoje` não vem;
  - `OPTIONS /api/v1/eu` sem token → 204 com `Access-Control-Allow-Origin: *`; resposta 200 também traz o header;
  - rota de teste registrada só no teste que levanta `RuntimeError` → 500 sem "Traceback" no corpo e uma linha em `user_mcp_calls` com `kind='api'`, `errors=1`;
  - `API_LIMITE_POR_MINUTO=3` (monkeypatch do valor lido) → 4ª chamada 429 com `Retry-After`;
  - `user.last_activity` não muda com chamada de API.
- [ ] **Step 2:** Rodar → falha (404 em `/api/v1/eu`).
- [ ] **Step 3:** Implementar blueprint, `executar`, CORS, limite, `/eu`, registro e o desvio no middleware.
- [ ] **Step 4:** Rodar → todos ✅. Rodar também `uv run python tests/test_mcp_uso.py` (o middleware mexido não pode quebrar a auditoria de tela).

---

### Task 3: Registro de rotas + FAP e segurados

**Files:**
- Create: `app/services/public_api_catalogo.py`
- Modify: `app/blueprints/public_api.py` (monta uma view Flask por `Rota` do registro)
- Modify: `app/services/segurado_nome_service.py`, `mcp_server/tools/fap.py`
- Test: `tests/test_api_rotas.py`, `tests/test_segurado_nome.py` (ampliar)

**Interfaces:**
- Consumes: `Contexto`, `ErroApi`, `executar` (Task 2); handlers de `mcp_server/tools/fap.py`, `fap_calculo.py`, `insights.py`.
- Produces:
  - `Param(nome: str, tipo: Literal['string','integer','boolean'], descricao: str, obrigatorio: bool = False, local: Literal['query','path','body'] = 'query')`
  - `Rota(metodo: str, caminho: str, modulo: str, resumo: str, params: tuple[Param, ...], chamar: Callable[[Contexto, dict], dict], detalhe: bool = False, grupo: str = '')`; `caminho` no formato OpenAPI (`/fap/beneficios/{id}`)
  - `ROTAS: tuple[Rota, ...]`
  - `ler_parametros(rota: Rota, args: Mapping, corpo: dict | None, caminho: dict) -> dict` — converte tipos; nome desconhecido ou tipo inválido → `ErroApi(..., 400)` nomeando o parâmetro e listando os válidos.
  - `segurado_nome_service.ORIGEM_API = 'api'`, `ORIGENS_AUTOMATIZADAS = (ORIGEM_MCP, ORIGEM_API)`, `consultas_automatizadas_hoje(law_firm_id, user_id) -> int` (substitui `consultas_mcp_hoje`; manter o nome antigo como alias até o fim do plano não é preciso — trocar os usos).
  - `revelar_nome_segurado_handler(law_firm_id, user_id, cpf, origem='mcp')`.

Rotas desta task (parâmetros = os da ferramenta MCP de mesmo papel em `server.py`): `GET /fap/empresas`, `/fap/contestacoes`, `/fap/contestacoes/{id}` (detalhe), `/fap/beneficios`, `/fap/beneficios/{id}` (detalhe), `/fap/resumo`, `/fap/filtros`, `/fap/procuracoes`, `/fap/calculo/beneficios`, `/fap/calculo/resumo`, `/segurados` (`cpf`, `nit`, `nome`; ao menos um, senão 400), `POST /segurados/revelar-nome` (corpo `{"cpf": ...}`). Em rota `detalhe=True`, resposta com chave `erro` contendo "não encontrad" vira 404.

Mensagem do limite de nome passa a dizer "pelo Claude ou pela API".

- [ ] **Step 1: Escrever `tests/test_api_rotas.py`** (escritório descartável com 2 empresas, 3 benefícios, 1 contestação; segundo escritório com 1 benefício). Asserções:
  - para cada rota GET de lista desta task, a resposta da API com `limite=2` é **igual** ao retorno do handler MCP chamado direto com os mesmos argumentos;
  - `?tipo_benefico=B91` → 400 e a mensagem contém `tipo_beneficio`; `?limite=abc` → 400 contendo `limite`; `/fap/beneficios/xyz` → 404 do Flask ou 400, nunca 500;
  - `/fap/beneficios/<id do outro escritório>` → 404;
  - usuário sem `fap_panel` → 403 em todas as rotas `fap/*` e `segurados*`;
  - `/segurados` sem parâmetro → 400;
  - todo `Rota.caminho` do registro tem view montada (`app.url_map`) e vice-versa para o blueprint.
- [ ] **Step 2: Ampliar `tests/test_segurado_nome.py`**: com limite 2, uma revelação `mcp` + uma `api` esgotam a cota; a terceira por qualquer das duas → 429/`NomeNaoRevelavel`; revelação `tela` não conta. Usar CPFs fictícios válidos (nunca CPF real) e `cpf_nome_client` substituído por stub, como o teste já faz.
- [ ] **Step 3:** Rodar os dois → falham.
- [ ] **Step 4:** Implementar registro, `ler_parametros`, montagem das views e a cota compartilhada.
- [ ] **Step 5:** Rodar `tests/test_api_rotas.py`, `tests/test_segurado_nome.py` e `tests/test_mcp_fap_status_instancia.py` → todos ✅.

---

### Task 4: Base de conhecimento, jurisprudência e processos

**Files:**
- Modify: `app/services/public_api_catalogo.py`
- Test: `tests/test_api_rotas.py` (ampliar)

**Interfaces:**
- Consumes: `Rota`, `Param` (Task 3); handlers de `knowledge.py`, `jurisprudence.py`, `process_panel.py`, `numero_processo.py`.
- Produces: rotas `GET /base-conhecimento/pesquisa`, `GET /base-conhecimento/arquivos/{id}` (detalhe), `POST /base-conhecimento/perguntar` (corpo `{"pergunta": ...}`), `GET /jurisprudencia`, `/jurisprudencia/{id}` (detalhe), `/jurisprudencia/panorama`, `/jurisprudencia/filtros`, `/jurisprudencia/{id}/parecidas`, `GET /processos`, `/processos/{id}` (detalhe), `GET /numero-processo/{numero}` (módulo `None` na rota; o handler recebe `ctx.modulos`, como no MCP).
  - Limite de perguntas: antes de chamar, soma `calls` de hoje em `user_mcp_calls` (`kind='api'`, `name='POST /base-conhecimento/perguntar'`, `call_date` = hoje SP) e devolve 429 se `>= API_LIMITE_PERGUNTAS_DIA`.

`/jurisprudencia/{id}` e `/jurisprudencia/panorama` colidem no Flask: declarar `{id}` como inteiro (`<int:id>`) na montagem.

- [ ] **Step 1: Ampliar o teste**: paridade com o handler em `/processos` e `/jurisprudencia` (com 1 decisão e 1 processo semeados); usuário sem `process_panel` → 403 nessas e 200 em `/numero-processo/{n}` com só as bases permitidas; `/base-conhecimento/perguntar` com `API_LIMITE_PERGUNTAS_DIA=1` e o `KnowledgeQueryAgent` substituído por stub → 2ª chamada 429; `/jurisprudencia/panorama` não cai na rota de detalhe.
- [ ] **Step 2:** Rodar → falha.
- [ ] **Step 3:** Acrescentar as linhas ao registro.
- [ ] **Step 4:** Rodar → todos ✅.

---

### Task 5: OpenAPI, página de documentação e manual

**Files:**
- Modify: `app/services/public_api_catalogo.py` (`openapi(base_url: str) -> dict`, `resumo_markdown() -> str`)
- Modify: `app/blueprints/public_api.py` (`GET /api/v1/openapi.json`, autenticado, módulo `api`)
- Create: `app/blueprints/minha_api.py` (`minha_api_bp`, `url_prefix='/minha-api'`; nesta task só a rota `GET /documentacao`)
- Create: `templates/minha_api/documentacao.html`
- Create: `docs/MANUAL_API.md`; registrar em `_MANUALS` (`app/services/manual_renderer.py`) e `_MANUAL_FILES` (`app/services/manual_assistant_service.py`)
- Test: `tests/test_api_documentacao.py`

**Interfaces:**
- Consumes: `ROTAS` (Task 3–4).
- Produces: `openapi(base_url)` — OpenAPI 3.1 com `servers=[{url: base_url + '/api/v1'}]`, `securitySchemes.bearer` (`http`/`bearer`), uma operação por `Rota` com `summary`, `tags=[grupo]`, parâmetros e `x-modulo`. `resumo_markdown()` — uma linha por rota (`MÉTODO caminho — resumo — parâmetros`), usado pela ferramenta MCP da Task 7.

Página: agrupada por `grupo`, para cada rota método, caminho, resumo, tabela de parâmetros e exemplo `curl` com `$INTELLEXIA_TOKEN`; no topo o endereço base (`app_public_url() + '/api/v1'`), o link do `openapi.json` e a seção "Usar no Claude Code" com o prompt de partida do spec. Visual do app (herda `layout/base.html`), sem Swagger de CDN. Manual: o que é, quem tem acesso (módulo `api`), criar token, cuidados (token é pessoal, não publicar página com token fora do escritório, não versionar), uso no Claude Code, limites.

- [ ] **Step 1: Escrever o teste**: `openapi()` tem exatamente uma operação por `Rota` e todo parâmetro `path` declarado aparece no caminho; `GET /api/v1/openapi.json` com token → 200 e `servers[0].url` termina em `/api/v1`; sem token → 401; `GET /minha-api/documentacao` logado → 200 e contém cada `caminho` do registro; usuário sem módulo `api` → redireciona (regra do middleware); `/docs/manuais` lista o manual da API.
- [ ] **Step 2:** Rodar → falha.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Rodar → todos ✅. Abrir a página no app com Playwright (`uv run --with playwright`), print em `instance/`, conferir tema claro e escuro.

---

### Task 6: Tela "Minha API"

**Files:**
- Modify: `app/blueprints/minha_api.py` (`GET /` lista, `POST /tokens` cria, `POST /tokens/<id>/revogar`, `GET /escritorio` admin)
- Create: `templates/minha_api/index.html`
- Modify: `templates/partials/header.html` ou o menu do usuário (item "Minha API" visível com `can_view_module('api')`, perto de Perfil)
- Test: `tests/test_minha_api_tela.py`

**Interfaces:**
- Consumes: `api_token_service.criar/listar/listar_do_escritorio/revogar/serializar` (Task 1).
- Produces: telas; nenhuma interface nova.

Criar mostra o token **uma vez** num modal com Copiar e o aviso "não aparece de novo" — o texto vem na resposta do POST (renderizado na própria página de resposta, nunca em `flash` nem na URL). Validade em `<select>` com 30/90/180/sem validade, 90 marcado. Aba "Tokens do escritório" só para admin (`@require_admin_user`), com dono, final, último uso e Revogar. Atalhos para a documentação e o manual.

- [ ] **Step 1: Escrever o teste**: POST criar → 200 e o corpo contém o token uma vez; GET seguinte da lista não contém o token, contém o final; revogar o próprio → situação "revogado"; lawyer em `/minha-api/escritorio` → negado; admin → vê token de outro usuário do escritório e nenhum de outro escritório; CSRF/POST sem sessão → login.
- [ ] **Step 2:** Rodar → falha.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Rodar → ✅; print das duas abas com Playwright em `instance/`.

---

### Task 7: Ferramentas MCP de token e documentação

**Files:**
- Create: `mcp_server/tools/api_tokens.py`
- Modify: `mcp_server/server.py` (4 ferramentas, `require_module("api")`)
- Modify: `docs/MANUAL_MCP.md` (linhas na tabela + "N ferramentas")
- Test: `tests/test_mcp_api_tokens.py`; rodar `tests/test_mcp_catalogo.py`

**Interfaces:**
- Consumes: `api_token_service` (Task 1), `public_api_catalogo.resumo_markdown()` (Task 5).
- Produces:
  - `minha_api_handler(law_firm_id, user_id, app_public_url) -> dict`: `endereco`, `documentacao` (URL da página), `openapi`, `tokens` (serializados), `consultas_nome_restantes_hoje`.
  - `criar_token_api_handler(law_firm_id, user_id, nome, validade_dias=90) -> dict`: `token`, `final`, `expira_em`, `orientacao`.
  - `revogar_token_api_handler(law_firm_id, user_id, token_id) -> dict`.
  - `documentacao_api_handler(app_public_url, grupo=None) -> dict`: `endereco`, `rotas` (texto de `resumo_markdown`, filtrado por grupo), `openapi`.

Docstring de `criar_token_api`: usar só quando o usuário pedir um token; mostrar o token uma vez; orientar guardar em variável de ambiente ou `.env` fora do git; nunca repetir depois nem gravar em arquivo versionado. `revogar` só revoga token do próprio usuário (o admin revoga dos outros pela tela).

- [ ] **Step 1: Escrever o teste** chamando os handlers: criar devolve `itx_...` e `minha_api` lista o token sem o texto; revogar token de outro usuário → `ToolError`; `documentacao_api(grupo='fap')` só traz rotas `/fap`.
- [ ] **Step 2:** Rodar → falha.
- [ ] **Step 3:** Implementar handlers, ferramentas e manual.
- [ ] **Step 4:** `uv run python tests/test_mcp_api_tokens.py` e `uv run python tests/test_mcp_catalogo.py` → ✅.

---

### Task 8: Uso da API na Atividade de Usuários + documentação do projeto

**Files:**
- Modify: `app/services/access_audit_service.py` (`get_users_mcp` separa `calls_today` em MCP e `api_calls_today`; `get_user_mcp_functions` devolve `kind` como já faz)
- Modify: `templates/admin/access_audit.html` (contagem "API hoje" ao lado do MCP; no modal, rótulo "API" para `kind='api'`)
- Modify: `CLAUDE.md` (linhas de `public_api` e `minha_api` na tabela de blueprints; `api_token_service` e `public_api_catalogo` na de serviços; env `API_LIMITE_POR_MINUTO`, `API_LIMITE_PERGUNTAS_DIA`; a cota compartilhada de nome; a regra "rota nova = linha no registro, mesmos nomes de parâmetro da ferramenta MCP")
- Test: `tests/test_mcp_uso.py` (ampliar)

- [ ] **Step 1: Ampliar o teste**: uma linha `kind='api'` hoje aparece em `api_calls_today` e **não** soma em `calls_today` do MCP; o modal lista a função com `kind='api'`.
- [ ] **Step 2:** Rodar → falha.
- [ ] **Step 3:** Implementar e documentar.
- [ ] **Step 4:** Rodar todos os testes do plano: `test_api_tokens`, `test_api_nucleo`, `test_api_rotas`, `test_api_documentacao`, `test_minha_api_tela`, `test_mcp_api_tokens`, `test_mcp_uso`, `test_segurado_nome`, `test_mcp_catalogo` → ✅.

---

## Deploy (homologação e produção)

1. `uv run python database/add_api_tokens_table.py`
   (cria a tabela e libera o módulo `api` para os usuários que já existem)
2. Conferir na Administração de Usuários que um advogado aparece com "API e integrações" marcado.
3. Reiniciar o app e o serviço do MCP.
