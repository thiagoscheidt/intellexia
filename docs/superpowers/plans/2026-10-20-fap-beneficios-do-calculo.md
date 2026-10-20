# Benefícios do cálculo FAP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sincronizar do portal FAP todos os benefícios (B91–B94) e CATs de cada cálculo, de todas as vigências, empresas e estabelecimentos; completar CPF/nascimento/RMI/total pago na Central; listar tudo numa tela nova do Painel FAP e no MCP.

**Architecture:** Cliente fino sobre o `FapWebService._get` existente → parser puro → serviço de sincronização (rede em threads, banco em sequência, como o `fap_sync_cron`) → duas tabelas novas com `law_firm_id`. Um serviço de consulta único alimenta a tela (blueprint novo `fap_calculo`, sob `/fap-panel/calculo`) e as tools MCP.

**Tech Stack:** Python 3.12, Flask 3.1, SQLAlchemy (Flask-SQLAlchemy), MySQL/SQLite, Jinja2 + AdminLTE/Bootstrap 5, FastMCP.

**Spec:** `docs/superpowers/specs/2026-10-20-fap-beneficios-do-calculo-design.md`

## Global Constraints

- Toda tabela nova tem `law_firm_id`; toda query filtra por ele. Escritório da sincronização = `FAP_SYNC_LAW_FIRM_ID`; credencial = `FAP_AUTH_JSON` (via `FapWebAuthPayload.from_env()`).
- Identificadores sempre por `app.utils.cnpj.completar_zeros`: CNPJ 14, raiz 8, CPF 11. NIT, NB e nº da CAT: string só de dígitos. Nunca `[:8]` de número sem zero (E01).
- Base dos endpoints: `https://fap-mps.dataprev.gov.br/gateway/fap/v1` — `/vigencias/anos`, `/vigencias/{ano}/empresa/{raiz8}/estabelecimentos`, `/vigencias/{ano}/empresa/{cnpj14}/calculos`, `.../calculos/{id}/beneficios/` (com a barra final: todas as espécies), `.../calculos/{id}/cats`. Referer `https://fap-mps.dataprev.gov.br/consultar-fap`.
- Paralelismo como o `fap_sync_cron`: env `FAP_CALCULO_SYNC_WORKERS`, padrão 8, máximo 20; rede em threads, banco só no fluxo principal.
- Nunca apagar item por ausência numa execução; 401/403/404 de uma empresa ou estabelecimento não apaga nada.
- "Contestado" = mesmo número **e mesma vigência** na Central (`benefits` pela vigência da FK `fap_vigencia_cnpj_id` → `fap_vigencia_cnpjs.vigencia_year`; `fap_contestation_cats.cat_number` + `vigencia_year`).
- CPF e nascimento exibidos inteiros (tela e MCP), só para o módulo `fap_panel`; nunca em log.
- Completar a Central: CPF e nascimento o portal sobrescreve sempre; RMI (`initial_monthly_benefit`) e `total_paid` só se vazios, com o valor da linha da **mesma vigência** do benefício.
- Migrations: script em `database/`, prefixo `add_`, `with app.app_context()`, idempotente, mensagens `[OK]`/`[ERRO]` (padrão de `database/add_fap_procuracoes_change_history_table.py`).
- Testes: scripts em `tests/` (padrão `check()` + `main()` + exit code), escritório descartável criado e removido; sem rede (dublê de `FapWebService`).
- Não tocar em `app/blueprints/fap_panel.py` nem `app/services/fap_web_service.py`: há alterações de outra sessão sem commit neles. Commitar só os arquivos de cada tarefa (`git add <arquivos>`; nada de `git add -A`).

## Review Focus

1. Sessão fica parcial no meio da carga (403 em várias empresas) → nada apagado, empresa conta como "sem acesso" e entra de novo na próxima execução. Teste na Task 6.
2. Estabelecimento com `/calculos` só de eventos (sem `id`) ou 404 → registrado sem item, sem exceção, sem chamada de benefícios. Teste na Task 4.
3. Mesmo NB no cálculo de duas vigências → duas linhas; "contestado" e o total pago completado seguem a vigência de cada uma. Testes nas Tasks 5 e 7.
4. CPF/NB/CNPJ chegando como número com zero perdido (CPF `1234567890`) → gravado `01234567890`. Teste na Task 3.
5. Rodar de novo depois de interromper: com `--somente-novos` pula estabelecimento já gravado; sem ele, cálculo com o mesmo id não busca itens de novo. Testes nas Tasks 4 e 6.

---

### Task 1: Modelos e migration

**Files:**
- Modify: `app/models.py` (acrescentar ao fim do bloco FAP, depois de `FapWebProcuracaoChangeHistory`)
- Create: `database/add_fap_calculo_tables.py`
- Test: `tests/test_fap_calculo_modelos.py`

**Interfaces:**
- Produces:
  - `FapCalculoEstabelecimento` (`fap_calculo_estabelecimentos`), unique `uq_fap_calc_estab` (`law_firm_id`, `ano_vigencia`, `cnpj`). Colunas: `id`, `law_firm_id` (FK, index), `ano_vigencia` Integer index, `cnpj` String(14) index, `cnpj_raiz` String(8) index, `calculo_atual_id` BigInteger, `calculo_atual_tipo` String(80), `calculo_atual_data` Date, `calculo_original_id` BigInteger, `tem_itens` Boolean, `historico_json` Text (lista `{id, tipo, data}` do `/calculos`, mais recente primeiro), `protocolo` String(40), `situacao` String(20) (`ok` | `sem_calculo` | `sem_acesso` | `erro`), `erro` String(255), `synced_at` DateTime (UTC), `created_at`, `updated_at`.
  - `FapCalculoItem` (`fap_calculo_itens`), unique `uq_fap_calc_item` (`law_firm_id`, `ano_vigencia`, `cnpj`, `tipo`, `identificador`). Colunas: `id`, `law_firm_id`, `ano_vigencia` Integer, `cnpj` String(14), `cnpj_raiz` String(8), `tipo` String(4) (`B91`|`B92`|`B93`|`B94`|`CAT`), `identificador` String(30) (NB ou nº CAT), `nit` String(20), `cpf` String(11), `data_nascimento` Date, `valor_mensal` Numeric(14,2), `total_pago` Numeric(14,2), `data_despacho` Date, `data_inicio` Date, `data_cessacao` Date, `data_inicio_contabilizacao` Date, `data_fim_contabilizacao` Date, `meses_contabilizacao` Numeric(10,4), `bloqueio` Boolean, `estado_atual` String(20), `estado_original` String(20), `calculo_id` BigInteger, `cnpj_original` String(14), `cnpj_atribuido` String(14), `data_acidente` Date, `data_cadastro_cat` Date, `data_obito` Date, `recibo_esocial` String(60), `raw_json` Text, `first_seen_at` DateTime, `last_seen_at` DateTime. Índices compostos: (`law_firm_id`, `cpf`), (`law_firm_id`, `nit`), (`law_firm_id`, `identificador`), (`law_firm_id`, `ano_vigencia`, `tipo`), (`law_firm_id`, `cnpj_raiz`).

- [ ] **Step 1: Write the failing test** — `test_cria_e_unique`: com escritório descartável, grava um `FapCalculoEstabelecimento` e um `FapCalculoItem` (B91, NB `6505977833`, ano 2026, CNPJ `07718633008163`); um segundo item com a mesma chave (`law_firm_id`, 2026, CNPJ, `B91`, `6505977833`) dá `IntegrityError`; o mesmo NB com `ano_vigencia=2025` grava.
- [ ] **Step 2: Run** `uv run python tests/test_fap_calculo_modelos.py` — Expected: FAIL (ImportError dos modelos).
- [ ] **Step 3: Implement** os dois modelos e `database/add_fap_calculo_tables.py` (cria as duas tabelas pelo metadata se não existirem, como `add_fap_procuracoes_change_history_table.py`). Rodar a migration local: `uv run python database/add_fap_calculo_tables.py` → `[OK] Tabela ... criada`; segunda execução → `já existe`.
- [ ] **Step 4: Run** o teste — Expected: `✅ Tudo verde`.
- [ ] **Step 5: Commit** `git add app/models.py database/add_fap_calculo_tables.py tests/test_fap_calculo_modelos.py && git commit -m "FAP cálculo: tabelas de estabelecimentos e itens do cálculo"`

### Task 2: Cliente da Consulta do FAP

**Files:**
- Create: `app/services/fap_calculo_client.py`
- Test: `tests/test_fap_calculo_client.py`

**Interfaces:**
- Consumes: `FapWebService._get(url, timeout, referer) -> (bytes, status)` e `FapWebResult` de `app/services/fap_web_service.py` (sem modificar o arquivo).
- Produces (todas devolvem `FapWebResult`; `data` é o JSON decodificado):
  - `listar_anos(svc) -> FapWebResult` (lista de int)
  - `listar_estabelecimentos(svc, ano: int, raiz8: str) -> FapWebResult` (lista de CNPJ14 str, já completados)
  - `listar_calculos(svc, ano: int, cnpj14: str) -> FapWebResult` (lista crua)
  - `listar_beneficios(svc, ano: int, cnpj14: str, calculo_id: int) -> FapWebResult`
  - `listar_cats(svc, ano: int, cnpj14: str, calculo_id: int) -> FapWebResult`
  - Erros: 401 → `expired=True`; 403 → `status_code=403`, mensagem "sem acesso (sessão parcial ou sem procuração)"; 404 → `ok=True, data=[]` (portal responde 404 quando a raiz não tem cálculo na vigência — 11 de 874 em 2026); outros HTTP/rede → `ok=False` com a mensagem; JSON inválido → `ok=False`.

- [ ] **Step 1: Write the failing tests** com um dublê que substitui `svc._get` e registra as URLs: `test_urls` (benefícios termina em `/calculos/804038558/beneficios/` com a barra; CATs em `/cats`; referer `/consultar-fap`); `test_estabelecimentos_completa_zeros` (resposta `[7718633008163]` → `['07718633008163']`); `test_404_vazio`; `test_403_sem_acesso` (`ok False`, `status_code 403`, `expired False`); `test_401_expira` (`expired True`).
- [ ] **Step 2: Run** `uv run python tests/test_fap_calculo_client.py` — Expected: FAIL (módulo não existe).
- [ ] **Step 3: Implement** as cinco funções; `timeout=60` (há `/calculos` de 34 s).
- [ ] **Step 4: Run** — Expected: `✅ Tudo verde`.
- [ ] **Step 5: Commit** `git add app/services/fap_calculo_client.py tests/test_fap_calculo_client.py && git commit -m "FAP cálculo: cliente da Consulta do FAP"`

### Task 3: Parser puro

**Files:**
- Create: `app/services/fap_calculo_parser.py`
- Test: `tests/test_fap_calculo_parser.py`

**Interfaces:**
- Produces:
  - `resumir_calculos(calculos: list[dict]) -> dict` com `atual_id`, `atual_tipo`, `atual_data` (date), `original_id`, `tem_itens` (bool: soma de `quantidadeB91..B94 + quantidadeCat` > 0 em **algum** cálculo), `historico` (lista `{id, tipo, data}` só dos que têm `id`, na ordem recebida), `protocolo`. Sem cálculo com `id` → `atual_id None`, `tem_itens False`.
  - `normalizar_beneficio(d: dict) -> dict` com as chaves das colunas de `FapCalculoItem` (`tipo` = `especie`, `identificador` = NB dígitos, `estado_atual` = `estado`), `raw_json` incluído.
  - `normalizar_cat(d: dict) -> dict` (`tipo='CAT'`, `identificador` = `numeroCat` dígitos, `cnpj_original`/`cnpj_atribuido` completados para 14).

- [ ] **Step 1: Write the failing tests:** `test_resumo_unidasul` (lista de 5 eventos com 3 cálculos — atual `RECALCULO_ELETRONICO_SEGUNDA_INSTANCIA` id `804038558`, original `CALCULO_ORIGINAL`, `tem_itens True`); `test_sem_cálculo` (só eventos sem `id`); `test_tem_itens_pelo_original` (atual com todas as quantidades 0 e original com `quantidadeB94: 1` → `True` — o recálculo excluiu); `test_beneficio` com o item real do recon (`nb 6505977833`, `valorMensal "1598.72"`, `totalPago "2991.15"`, `dataNascimento "1976-05-14"`, `mesesContabilizacao "1.8710"`) → `Decimal('1598.72')`, `date(1976,5,14)`, `estado_atual 'ORIGINAL'`; `test_cpf_com_zero` (`cpf: 1234567890` → `'01234567890'`); `test_cat` (`numeroCat`, `cnpjAtribuido: 33592510007590` → 14 dígitos, `dataObito None`).
- [ ] **Step 2: Run** `uv run python tests/test_fap_calculo_parser.py` — Expected: FAIL.
- [ ] **Step 3: Implement** (datas `YYYY-MM-DD` → `date`, vazio → `None`; decimais por `Decimal(str(v))`).
- [ ] **Step 4: Run** — Expected: `✅ Tudo verde`.
- [ ] **Step 5: Commit** `git add app/services/fap_calculo_parser.py tests/test_fap_calculo_parser.py && git commit -m "FAP cálculo: parser dos cálculos, benefícios e CATs"`

### Task 4: Buscar e gravar um estabelecimento

**Files:**
- Create: `app/services/fap_calculo_sync_service.py`
- Test: `tests/test_fap_calculo_sync.py`

**Interfaces:**
- Consumes: Task 2 (cliente), Task 3 (parser), Task 1 (modelos).
- Produces:
  - `@dataclass BuscaEstabelecimento`: `ano: int`, `cnpj: str`, `situacao: str` (`ok`|`sem_calculo`|`sem_acesso`|`erro`|`expirada`), `resumo: dict | None`, `itens_atual: list[dict] | None` (None = não buscou), `estados_original: dict[tuple[str,str], str]` (chave (tipo, identificador)), `erro: str = ''`.
  - `buscar_estabelecimento(svc, ano: int, cnpj14: str, calculo_atual_id_gravado: int | None) -> BuscaEstabelecimento` — só rede, segura em thread. Busca `/calculos`; se `tem_itens` e o `atual_id` mudou (ou nunca gravado), busca benefícios e CATs do atual; se além disso `original_id != atual_id`, busca benefícios e CATs do original só para `estados_original`. `atual_id` igual ao gravado → `itens_atual None`.
  - `gravar_estabelecimento(law_firm_id: int, busca: BuscaEstabelecimento) -> dict` — só banco, fluxo principal. Upsert de `FapCalculoEstabelecimento`; quando `itens_atual` não é None, upsert dos itens pela chave única (`first_seen_at` na criação, `last_seen_at` = agora UTC em todo item visto, `estado_original` do mapa ou `ORIGINAL` quando atual == original); item gravado antes e ausente agora fica intacto. Devolve `{'itens_novos': n, 'itens_atualizados': n}`. `situacao` diferente de `ok`/`sem_calculo` não toca nos itens.

- [ ] **Step 1: Write the failing tests** com dublê de cliente (monkeypatch das funções de `fap_calculo_client`) e escritório descartável: `test_primeira_busca_grava_itens` (2 B91 + 1 CAT; atual ≠ original; original com os mesmos itens → `estado_original 'ORIGINAL'`, um deles `estado_atual 'EXCLUIDO'`); `test_mesmo_calculo_nao_busca_itens` (segunda busca com `calculo_atual_id_gravado` igual → `itens_atual None`, dublê de benefícios não chamado, itens no banco intactos); `test_item_que_sumiu_fica` (recálculo novo sem um dos B91 → linha continua, `last_seen_at` antigo); `test_sem_calculo` (só eventos → `situacao 'sem_calculo'`, nenhuma chamada de benefícios); `test_403_nao_apaga` (`/calculos` 403 → `sem_acesso`, itens anteriores intactos); `test_tem_itens_false_nao_chama_beneficios`.
- [ ] **Step 2: Run** `uv run python tests/test_fap_calculo_sync.py` — Expected: FAIL.
- [ ] **Step 3: Implement** `buscar_estabelecimento` e `gravar_estabelecimento`; datetimes em UTC (padrão `fap_procuracoes_service._utcnow`); nada de CPF em log.
- [ ] **Step 4: Run** — Expected: `✅ Tudo verde`.
- [ ] **Step 5: Commit** `git add app/services/fap_calculo_sync_service.py tests/test_fap_calculo_sync.py && git commit -m "FAP cálculo: busca e gravação por estabelecimento"`

### Task 5: Completar a Central

**Files:**
- Modify: `app/services/fap_calculo_sync_service.py`
- Test: `tests/test_fap_calculo_completar.py`

**Interfaces:**
- Consumes: Task 1, modelos `Benefit`, `FapVigenciaCnpj`.
- Produces: `completar_central(law_firm_id: int, ano: int | None = None) -> dict` → `{'beneficios_vistos', 'cpf', 'nascimento', 'rmi', 'total_pago'}` (quantos campos foram gravados). Casa `Benefit.benefit_number` (só dígitos) com `FapCalculoItem.identificador`, tipo ≠ CAT, **mesma vigência** (`FapVigenciaCnpj.vigencia_year` da FK do benefício == `str(item.ano_vigencia)`); com mais de uma linha (mesma vigência, CNPJs diferentes) prefere a do CNPJ do benefício. Idempotente.

- [ ] **Step 1: Write the failing tests:** `test_preenche_vazios` (benefício 2026 sem CPF/RMI/total → recebe `'…'`, `1598.72`, `2991.15`); `test_cpf_sobrescreve_rmi_nao` (benefício com CPF diferente e RMI preenchida → CPF trocado, RMI mantida); `test_mesma_vigencia` (NB em 2025 e 2026 com totais diferentes; benefício ligado à vigência 2026 recebe o total de 2026); `test_sem_item_nao_toca`; `test_tenant` (item de outro escritório não completa).
- [ ] **Step 2: Run** `uv run python tests/test_fap_calculo_completar.py` — Expected: FAIL.
- [ ] **Step 3: Implement** em lotes (por ano), commit por lote.
- [ ] **Step 4: Run** — Expected: `✅ Tudo verde`.
- [ ] **Step 5: Commit** `git add app/services/fap_calculo_sync_service.py tests/test_fap_calculo_completar.py && git commit -m "FAP cálculo: completa CPF, nascimento, RMI e total pago na Central"`

### Task 6: Sincronização completa e script

**Files:**
- Modify: `app/services/fap_calculo_sync_service.py`
- Create: `scripts/fap_calculo_sync.py`
- Modify: `CLAUDE.md` (seção nova "Benefícios do cálculo FAP" depois de "Sessão do portal FAP e automação de navegador"; linha na tabela de serviços)
- Test: `tests/test_fap_calculo_sync.py` (acrescentar)

**Interfaces:**
- Consumes: Task 4, Task 5 (`completar_central`).
- Produces:
  - `sincronizar(law_firm_id: int, svc, anos: list[int] | None = None, raizes: list[str] | None = None, cnpjs: list[str] | None = None, workers: int = 8, somente_novos: bool = False, log=print) -> dict` — `anos None` = `listar_anos`; `raizes None` = `FapCompany.cnpj` do escritório (completadas para 8). Para cada (ano, raiz): `listar_estabelecimentos` (403 → conta em `sem_acesso`, segue); busca em `ThreadPoolExecutor(workers)` e grava conforme cada future termina, no fluxo principal, `commit` por estabelecimento. `somente_novos=True` pula CNPJ que já tem `FapCalculoEstabelecimento` com `situacao in ('ok','sem_calculo')` no ano. Sessão expirada (401) interrompe tudo e devolve `{'expirada': True, ...}`. Devolve contagens: `estabelecimentos`, `com_itens`, `itens_novos`, `itens_atualizados`, `sem_acesso`, `erros`, `expirada`.
  - Script `scripts/fap_calculo_sync.py`: argumentos `--vigencia` (repetível), `--empresa` (raiz, repetível), `--estabelecimento` (CNPJ, repetível), `--somente-novos`, `--sem-completar`; workers de `FAP_CALCULO_SYNC_WORKERS` (padrão 8, máx 20, aviso se inválido — igual a `_fetch_workers` do `fap_sync_cron`); escritório de `FAP_SYNC_LAW_FIRM_ID`; ao fim chama `completar_central` (Task 5) salvo `--sem-completar`. Saída 0 ok, 1 erro de configuração, 2 sessão expirada (mesmos códigos do `fap_navegar_portal.py`).

- [ ] **Step 1: Write the failing tests:** `test_sincronizar_duas_raizes_uma_sem_acesso` (raiz A 403 em `/estabelecimentos`, raiz B com 2 estabelecimentos → `sem_acesso 1`, itens de B gravados, nada de A apagado); `test_somente_novos_pula_gravados` (segunda chamada com `somente_novos=True` não chama `/calculos` dos já gravados); `test_expirada_interrompe` (401 no meio → `expirada True`, código de saída 2 ao rodar `main()` do script com o dublê).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `sincronizar` e o script; CLAUDE.md com: endpoints, o que é `EXCLUIDO`, escala medida (874 raízes, 20.320 estabelecimentos em 2026, ~1 h por vigência com 8 workers), regra de "contestado", e o comando de carga inicial (`uv run python scripts/fap_calculo_sync.py --somente-novos`, retomável).
- [ ] **Step 4: Run** `uv run python tests/test_fap_calculo_sync.py` — Expected: `✅ Tudo verde`. Smoke real, uma raiz pequena: `uv run python scripts/fap_calculo_sync.py --vigencia 2026 --empresa 07718633 --sem-completar` → 65 estabelecimentos, sem erro.
- [ ] **Step 5: Commit** `git add app/services/fap_calculo_sync_service.py scripts/fap_calculo_sync.py CLAUDE.md tests/test_fap_calculo_sync.py && git commit -m "FAP cálculo: sincronização paralela de todas as vigências"`

### Task 7: Serviço de consulta

**Files:**
- Create: `app/services/fap_calculo_query_service.py`
- Test: `tests/test_fap_calculo_consulta.py`

**Interfaces:**
- Produces:
  - `TIPOS = ('B91', 'B92', 'B93', 'B94', 'CAT')`; `SITUACOES = ('conta', 'excluido')`.
  - `contestado_expr(law_firm_id)` — expressão SQL booleana (EXISTS) para usar em filtro e coluna: benefício → `benefits` do escritório com `benefit_number == identificador` e vigência da FK == `ano_vigencia`; CAT → `fap_contestation_cats` com `cat_number == identificador` e `vigencia_year == ano_vigencia`.
  - `filtrar(law_firm_id: int, *, vigencia: int | None = None, raizes: list[str] | None = None, grupo: str | None = None, cnpj: str | None = None, identificador: str | None = None, tipos: list[str] | None = None, situacao: str | None = None, contestado: bool | None = None)` → Query de `FapCalculoItem`. `identificador`: só dígitos; 11 → CPF ou NIT; outro tamanho → NB, nº CAT ou NIT. `situacao 'conta'` = `estado_atual == 'ORIGINAL'`; `'excluido'` = `'EXCLUIDO'`. `grupo` pelo `fap_group_service.apply_group_filter(..., FapCalculoItem.cnpj_raiz, coluna_e_raiz=True)`.
  - `contadores(query) -> dict` → `{'total', 'por_tipo': {tipo: n}, 'excluidos', 'nao_contestados'}` (GROUP BY, sem carregar linhas).
  - `pagina(query, page: int, per_page: int = 50) -> (itens: list[dict], total: int)` — cada dict com as colunas, `empresa_nome` e `contestado: bool`, `beneficio_central_id` (id do benefício da mesma vigência, para o link), ordem `ano_vigencia desc, cnpj, tipo, identificador, id`.

- [ ] **Step 1: Write the failing tests** com escritório descartável e itens/benefícios/CATs criados à mão: `test_filtro_tipo_e_cat` (tipos `['CAT']` só CATs); `test_contestado_por_vigencia` (NB contestado em 2025 aparece contestado em 2025 e **não** em 2026; filtro `contestado=False` em 2026 traz ele); `test_identificador_cpf_com_pontuacao` (`'012.345.678-90'` acha o CPF `01234567890`); `test_situacao_excluido`; `test_contadores_batem_com_filtro`; `test_tenant`.
- [ ] **Step 2: Run** `uv run python tests/test_fap_calculo_consulta.py` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — Expected: `✅ Tudo verde`.
- [ ] **Step 5: Commit** `git add app/services/fap_calculo_query_service.py tests/test_fap_calculo_consulta.py && git commit -m "FAP cálculo: consulta com filtros e contestado por vigência"`

### Task 8: Tela no Painel FAP

**Files:**
- Create: `app/blueprints/fap_calculo.py` (`fap_calculo_bp`, `url_prefix='/fap-panel/calculo'`, rota `GET /` endpoint `fap_calculo.beneficios_page`, `@require_law_firm`)
- Create: `templates/fap_calculo/beneficios.html`
- Modify: `app/blueprints/__init__.py`, `main.py` (registrar), `app/utils/permissions.py` (`'fap_calculo.': 'fap_panel'` no `ENDPOINT_MODULE_MAP`), `templates/partials/sidebar.html` (item "Benefícios do cálculo" no grupo Painel FAP; o `menu-open`/`active` do grupo passa a aceitar também `fap_calculo.`), `docs/MANUAL_PAINEL_FAP.md` (seção "Tela 5 — Benefícios do cálculo FAP")
- Test: `tests/test_fap_calculo_tela.py`

**Interfaces:**
- Consumes: Task 7 (`filtrar`, `contadores`, `pagina`, `TIPOS`).
- Produces: parâmetros GET da tela — `vigencia`, `raiz`, `grupo`, `cnpj`, `q` (identificador), `tipo` (repetível), `situacao`, `contestado` (`sim`|`nao`), `page`.

- [ ] **Step 1: Write the failing test** (test client, admin descartável, itens criados à mão): `test_tela_abre` (200, título "Benefícios do cálculo FAP"); `test_filtro_tipo_cat` (`?tipo=CAT` mostra só a CAT); `test_cpf_inteiro` (o CPF aparece inteiro, formatado por `formatar_cpf`); `test_sem_modulo_fap_panel` (usuário sem `fap_panel` não acessa); `test_link_contestado` (item contestado tem link para o benefício da Central).
- [ ] **Step 2: Run** `uv run python tests/test_fap_calculo_tela.py` — Expected: FAIL (404).
- [ ] **Step 3: Implement** seguindo o rascunho aprovado `.superpowers/mockups/listagem-beneficios-v1.html`: formulário GET com botão Pesquisar (sem busca por filtro, padrão FAP-33), chips de tipo, contadores de `contadores()`, tabela com as colunas do spec (G4) e linha expandível (`<details>` ou collapse do Bootstrap) com o restante; paginação do servidor como em `contestacoes_page`. Selects de vigência (anos de `FapCalculoEstabelecimento`), raiz (empresas do Painel FAP) e grupo (`fap_group_service.select_options`).
- [ ] **Step 4: Run** — Expected: `✅ Tudo verde`. Conferência no navegador (Playwright, padrão do FAP-33) com prints em `instance/`.
- [ ] **Step 5: Commit** `git add app/blueprints/fap_calculo.py templates/fap_calculo/beneficios.html app/blueprints/__init__.py main.py app/utils/permissions.py templates/partials/sidebar.html docs/MANUAL_PAINEL_FAP.md tests/test_fap_calculo_tela.py && git commit -m "Painel FAP: tela de benefícios do cálculo"`

### Task 9: MCP

**Files:**
- Create: `mcp_server/tools/fap_calculo.py`
- Modify: `mcp_server/server.py` (registrar duas tools; `buscar_por_segurado` com CPF ou NIT também consulta a base nova), `mcp_server/tools/insights.py` (`buscar_por_segurado_handler`: chave nova `beneficios_calculo_fap`), `docs/MANUAL_MCP.md` (duas linhas na tabela do Painel FAP e "**58 ferramentas**")
- Test: `tests/test_mcp_fap_calculo.py`

**Interfaces:**
- Consumes: Task 7.
- Produces:
  - `listar_beneficios_calculo_fap(vigencia=None, empresa=None, grupo=None, cnpj=None, cpf=None, nit=None, numero=None, tipo=None, situacao=None, contestado=None, limite=50, deslocamento=0)` → envelope `page_envelope` (`mcp_server/tools/pagination.py`); `tipo` aceita B91/B92/B93/B94/CAT; `situacao` `conta`|`excluido`; `contestado` bool; valor inválido → `ToolError` com os aceitos. `require_module("fap_panel")`.
  - `resumo_beneficios_calculo_fap(vigencia=None, empresa=None, grupo=None, cnpj=None, tipo=None)` → `contadores()` + cruzamento tipo × situação × contestado.
  - Docstrings: "contestado" é por vigência; `EXCLUIDO` = o portal tirou do cálculo no recálculo; o CPF vem inteiro.

- [ ] **Step 1: Write the failing tests:** `test_lista_por_cpf_sem_contestacao` (segurado só na base nova é achado pelo CPF); `test_tipo_invalido_toolerror`; `test_resumo_bate_com_lista`; `test_buscar_por_segurado_traz_calculo` (CPF sem benefício na Central → `beneficios_calculo_fap` com 1 item); depois rodar `uv run python tests/test_mcp_catalogo.py`.
- [ ] **Step 2: Run** `uv run python tests/test_mcp_fap_calculo.py` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** os dois testes e `tests/test_mcp_fap_panel.py`, `tests/test_mcp_fap_status_instancia.py` — Expected: todos verdes; catálogo "manual e servidor em dia".
- [ ] **Step 5: Commit** `git add mcp_server/tools/fap_calculo.py mcp_server/server.py mcp_server/tools/insights.py docs/MANUAL_MCP.md tests/test_mcp_fap_calculo.py && git commit -m "MCP: benefícios do cálculo FAP e CPF no buscar_por_segurado"`
