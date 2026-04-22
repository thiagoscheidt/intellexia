# FAP — Painel de Sincronização (`fap_panel`)

Documento de continuidade — estado em **21/04/2026**.

---

## Visão Geral

O módulo `fap_panel` (`app/blueprints/fap_panel.py`, prefixo `/fap-panel`) gerencia a sincronização de contestações e procurações do portal FAP para o banco de dados local, além de baixar os PDFs das contestações e exibi-los na interface.

---

## Arquivos Envolvidos

| Arquivo | Responsabilidade |
|---|---|
| `app/blueprints/fap_panel.py` | Blueprint principal com todas as rotas do painel |
| `app/blueprints/disputes_center.py` | Rotas de importação/download usadas pelo painel (rota `fap_auto_import_import_contestacao`, `fap_auto_import_download_contestacao`) |
| `app/models.py` | Modelos `FapWebContestacao`, `FapWebProcuracao`, `FapCompany`, `FapAutoImportedContestacao` |
| `app/services/fap_web_service.py` | `FapWebService` — comunicação com a API do portal FAP |
| `templates/fap_panel/sync.html` | Página de sincronização (seleção de empresa + anos + botão de download) |
| `templates/fap_panel/contestacoes.html` | Listagem/tabela de contestações sincronizadas |
| `database/add_fap_web_contestacoes_file_path_column.py` | Migration: adiciona coluna `file_path` em `fap_web_contestacoes` |

---

## Modelo `FapWebContestacao`

Tabela `fap_web_contestacoes`. Campos relevantes para o módulo de sync:

```python
id               # PK
law_firm_id      # multi-tenant
contestacao_id   # ID da contestação no portal FAP
cnpj             # CNPJ do estabelecimento (14 dígitos, zerofill)
cnpj_raiz        # 8 dígitos
ano_vigencia     # inteiro
instancia_codigo / instancia_descricao
situacao_codigo  / situacao_descricao
protocolo
data_transmissao
raw_data         # JSON bruto da API
last_synced_at
file_path        # Caminho relativo do PDF local (ex: uploads/fap_web_contestacoes/{law_firm_id}/{ano}/{cnpj}/{contestacao_id}_{filename})
```

> **Migration**: `database/add_fap_web_contestacoes_file_path_column.py`
> Rodar com: `uv run python database/add_fap_web_contestacoes_file_path_column.py`

---

## Rotas do Blueprint `fap_panel`

### `GET /fap-panel/sync`
Página de sincronização. Exibe lista de empresas (`FapCompany`) e anos disponíveis (2010–ano atual). Lê `fap_auto_import_auth` da sessão Flask para autenticar no portal FAP.

### `POST /fap-panel/sync/run-year`
Sincroniza **metadados** de contestações de uma empresa + ano.

- Body: `{ "cnpj": "12345678", "year": 2023 }`
- Chama `FapWebService(auth).fetch_contestacoes(cnpj, year)`
- Persiste/atualiza registros em `FapWebContestacao` (**sem tocar em `file_path`**)
- Retorna imediatamente: `{ "ok": true, "year": 2023, "total": 10, "created": 7, "updated": 3 }`

### `POST /fap-panel/sync/download-year`
Enfileira download de PDFs em background para registros sem `file_path`.

- Body: `{ "cnpj": "12345678" }` (ou com `"year"` para filtrar por ano)
- Coleta todos os `FapWebContestacao` com `file_path IS NULL` do escritório
- Lança `threading.Thread(daemon=True)` com `ThreadPoolExecutor(max_workers=3)` interno
- Cada worker: chama `FapWebService.download_contestacao()`, salva em `uploads/fap_web_contestacoes/{law_firm_id}/{ano}/{cnpj}/{contestacao_id}_{filename}`, atualiza `rec.file_path` no banco
- Retorna imediatamente: `{ "ok": true, "queued": N }`
- **Deduplicação**: filtra `file_path IS NULL` → registros já com arquivo não são reprocessados. O `sync_run_year` nunca sobrescreve `file_path`.

### `GET /fap-panel/contestacoes/<rec_id>/file`
Serve o PDF local de uma contestação.

- Verifica `law_firm_id` (multi-tenant)
- Resolve `rec.file_path` para caminho absoluto
- Retorna o PDF via `send_file`; `?inline=1` para visualização no browser
- Remove o prefixo `{contestacao_id}_` do nome de download

### `GET /fap-panel/sync/summary`
AJAX — retorna lista de contestações sincronizadas por empresa (JSON).

### `POST /fap-panel/sync/procuracoes`
Sincroniza procurações eletrônicas do portal FAP para `FapWebProcuracao`.

### Demais rotas
- `GET /fap-panel/contestacoes` — listagem com filtros (ano, CNPJ, instância, situação, protocolo)
- `GET /fap-panel/contestacoes/export-excel` — exportação por contestação
- `GET /fap-panel/contestacoes/export-excel-agrupado` — exportação agrupada por (vigência, CNPJ)
- `GET /fap-panel/procuracoes` — listagem de procurações com filtros

---

## Fluxo Completo de Sincronização

```
Usuário na página /fap-panel/sync
  │
  ├─ Clica "Sincronizar todos os anos"
  │    └─ JS chama POST /fap-panel/sync/run-year para cada ano (BATCH_SIZE=20)
  │         └─ Salva metadados → retorna imediatamente
  │
  └─ Clica "Baixar PDFs"
       └─ JS chama POST /fap-panel/sync/download-year (UMA chamada, sem year)
            └─ Backend coleta todos os pending (file_path IS NULL)
            └─ Lança background thread
                 └─ ThreadPoolExecutor(max_workers=3)
                      └─ Cada worker: download → salva PDF → atualiza file_path no DB
            └─ Resposta imediata: { "ok": true, "queued": N }
```

---

## Página de Contestações (`/fap-panel/contestacoes`)

### Indicadores visuais por contestação

Cada célula da tabela exibe (macro `_render_cell`):

- **Protocolo** + **Situação**
- Badge verde `bi-hdd-fill Local` — aparece quando `c.file_path` está preenchido (arquivo PDF salvo localmente)
- **Botão Visualizar (eye)**: usa rota local `/fap-panel/contestacoes/<id>/file?inline=1` se tiver arquivo local; caso contrário, vai ao portal FAP via `disputes_center.fap_auto_import_download_contestacao`
- **Botão Baixar (`hdd-fill` ou `file-earmark-arrow-down`)**: mesma lógica — local primeiro, portal FAP como fallback
- **Botão Importar**: disponível para contestações não importadas; passa `data-rec-id` para o JS

### Importação em lote ("Importar p/ Relatórios")

O JS (`btnImportAll`) coleta todos os botões `.import-pending-btn` das linhas filtradas e chama `POST /disputes-center/fap-auto-import/import-contestacao` em batches de 20 (paralelos via `Promise.all`).

O payload agora inclui `rec_id`:
```json
{ "year": 2023, "cnpj": "00000000000000", "contestacao_id": 12345, "rec_id": 99 }
```

---

## Rota de Importação (`disputes_center`)

`POST /disputes-center/fap-auto-import/import-contestacao`

**Lógica de arquivo (adicionada):**

1. Se `rec_id` fornecido → busca `FapWebContestacao` no banco
2. Se `rec.file_path` existe e arquivo está no disco → lê bytes localmente (**sem chamada ao portal FAP**)
3. Caso contrário → chama `FapWebService.download_contestacao()` normalmente
4. Cria `FapContestationJudgmentReport` + `FapAutoImportedContestacao` + ingere na base de conhecimento

---

## Localização dos PDFs

| Tipo | Caminho |
|---|---|
| PDFs sincronizados (fap_panel) | `uploads/fap_web_contestacoes/{law_firm_id}/{ano_vigencia}/{cnpj14}/{contestacao_id}_{filename}` |
| PDFs importados para relatórios | `uploads/fap_contestation_reports/{timestamp}_{filename}` |

---

## Pendências / Próximos Passos

- [ ] **Rodar migration** `uv run python database/add_fap_web_contestacoes_file_path_column.py` (necessário se o banco ainda não tem a coluna `file_path`)
- [ ] Verificar se a página `sync.html` exibe progresso do download em background (os workers rodam assíncronos; considerar um endpoint de polling de status)
- [ ] Exibir na página de sync quantos PDFs já foram baixados vs. pendentes (contador por ano/empresa)
- [ ] Possível: botão "Baixar PDFs" por empresa/ano individual (atualmente baixa tudo de uma vez)

---

## Observações Técnicas

- **Multi-tenancy**: toda query filtra por `law_firm_id` da sessão
- **Thread safety**: cada worker do `ThreadPoolExecutor` abre seu próprio `app.app_context()` para operações de banco
- **Autenticação FAP**: `fap_auto_import_auth` (JSON serializado) armazenado na sessão Flask; contém cookies/token do portal FAP
- `FapWebService` está em `app/services/fap_web_service.py`; `FapWebAuthPayload.from_json()` deserializa a sessão
