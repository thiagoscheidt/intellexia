# Auditoria de Acesso de Usuários — Design

**Data:** 2026-07-20
**Objetivo:** permitir que o administrador do escritório saiba (1) quando foi o último login de cada usuário, (2) quais telas cada usuário acessou, e (3) quantos usuários estão logados agora — via um dashboard admin-only, com custo mínimo de performance.

## Contexto existente (reaproveitado)

- `User.last_login` — já preenchido no login (`app/blueprints/auth.py`).
- `User.last_activity` — já atualizado a cada request autenticada pelo middleware `check_session` (`app/middlewares.py`), que já faz um `db.session.commit()` por request.
- Padrão admin-only: `require_admin` (session `user_role == 'admin'`) + módulo `admin_users` no catálogo de permissões.

Ou seja: "último login" e "usuários online" **não precisam de estrutura nova**. Só "telas acessadas" precisa.

## Abordagens consideradas

1. **Log bruto por request** (tabela append-only com cada acesso): simples, mas cresce sem limite e adiciona um INSERT por request — descartada pelo requisito de baixo custo.
2. **Agregado diário por (usuário, endpoint, dia) com upsert** — *escolhida*: volume minúsculo (usuários × telas distintas × dias), e a escrita entra no **mesmo commit** que o middleware já faz para `last_activity`, ou seja, zero commits adicionais.
3. Analytics externo (Matomo etc.): dependência nova e infra extra — descartada.

## Estrutura nova

### Tabela `user_page_visits` (modelo `UserPageVisit`)

| Coluna | Tipo | Observação |
|---|---|---|
| `id` | Integer PK | |
| `law_firm_id` | Integer FK `law_firms.id`, indexada | multi-tenancy |
| `user_id` | Integer FK `users.id` | |
| `endpoint` | String(150) | endpoint Flask (ex.: `cases.cases_list`) |
| `visit_date` | Date | dia em `America/Sao_Paulo` |
| `hits` | Integer default 1 | contagem de acessos no dia |
| `last_seen_at` | DateTime | último acesso |

Índices: único `(user_id, endpoint, visit_date)`; secundário `(law_firm_id, visit_date)`.

### Captura no middleware

Dentro do bloco autenticado de `check_session`, antes do commit existente, chama `access_audit_service.record_page_visit(user)` que registra apenas **navegação de tela**:

- método `GET`;
- não é `static` nem endpoint público;
- não é chamada AJAX/JSON (`X-Requested-With: XMLHttpRequest`, `request.is_json`, ou `Accept` sem `text/html`).

Upsert: SELECT pela chave única (indexada) + INSERT ou `hits += 1`. Falha no registro **nunca** derruba a request (try/except com log). Custo: 1 SELECT indexado + 1 INSERT/UPDATE dentro do commit que já existia.

### Usuários online

Sem estrutura nova: `User.last_activity >= agora − 15 min` (constante `ONLINE_WINDOW_MINUTES = 15` no service). Mesma base de tempo (`datetime.now()`) que o middleware usa para gravar.

## Service — `app/services/access_audit_service.py`

Fonte única para tela (e futuro MCP):

- `record_page_visit(user)` — upsert descrito acima (não comita; o middleware comita).
- `get_overview_stats(law_firm_id)` — online agora, logins hoje, ativos hoje, total de usuários.
- `get_users_activity(law_firm_id)` — por usuário: last_login, last_activity, online?, última tela e telas distintas hoje.
- `get_user_screens(law_firm_id, user_id, days=30)` — telas agregadas do período (hits somados, último acesso), com rótulo amigável derivado de `MODULE_PERMISSIONS` + `get_module_from_endpoint`.

## Blueprint e permissões

- `access_audit_bp`, prefixo `/admin/access-audit`, rotas: `GET /` (dashboard) e `GET /users/<id>/screens` (JSON para o modal de detalhe).
- Decorators `require_law_firm` + `require_admin` (mesmo padrão de `admin_users.py`).
- `ENDPOINT_MODULE_MAP`: `'access_audit.' → 'admin_users'` (só admin tem esse módulo por padrão) — o middleware de permissão de módulo também bloqueia.
- Sidebar: item "Atividade de Usuários" na seção ADMINISTRAÇÃO (visível só para admin).

## Dashboard (`templates/admin/access_audit.html`)

- 4 cards: **Online agora**, **Logins hoje**, **Ativos hoje**, **Total de usuários**.
- Tabela de usuários: nome, papel, último login, última atividade, badge online/offline, última tela.
- Botão "telas" por usuário → modal com telas acessadas nos últimos 30 dias (nome amigável, endpoint, acessos, último acesso). JS nativo, padrão AdminLTE/Bootstrap do projeto. Datas via filtros `datetime_sp`.
- Todas as queries filtram `law_firm_id`.

## Migration

`database/add_user_page_visits_table.py` — padrão standalone do projeto: `app_context`, verificação de existência prévia (idempotente), mensagens claras.

## Retenção / custo

Volume estimado: com 20 usuários × ~30 telas × 365 dias ≈ 200 mil linhas/ano no pior caso teórico (na prática bem menos, pois só telas realmente visitadas geram linha). Sem necessidade de purga imediata; se necessário no futuro, um script `remove_old_user_page_visits.py` (> 180 dias) resolve.

## Testes

`tests/test_access_audit.py` (script standalone, padrão do projeto): valida upsert do service, cálculo de online/ativos, bloqueio da rota para não-admin e resposta 200 para admin.

## Error handling

- Registro de visita em try/except — nunca quebra a request.
- Rotas JSON retornam 403 para não-admin (padrão `require_admin`).
- Usuário inexistente/outro escritório no detalhe → 404.
