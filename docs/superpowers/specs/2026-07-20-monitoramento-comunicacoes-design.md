# Design — Monitoramento de Comunicações Processuais (Comunica PJe / DJEN)

**Data:** 2026-07-20
**Status:** Aprovado (brainstorming com o usuário)

## Objetivo

Novo módulo "Monitoramento de Comunicações" que usa a API pública do Comunica PJe
(`https://comunicaapi.pje.jus.br/api/v1`) — interface do DJEN (Diário de Justiça
Eletrônico Nacional, Resolução CNJ 455/2022) — como fonte oficial de comunicações
processuais (intimações, citações etc.) para o escritório.

## Decisões de produto (aprovadas)

1. **Radar completo por OAB**: monitora todas as comunicações dos advogados do
   escritório, não apenas processos já cadastrados.
2. **Importação automática flagada**: processo desconhecido vira `JudicialProcess`
   com `origin='comunica_auto'` e `discovery_status='pending_review'`; o Painel
   Processual mostra esses numa aba "Descobertos" separada da lista principal,
   com confirmação em 1 clique. Histórico completo de comunicações do processo é
   importado via `numeroProcesso`.
3. **Sem IA na v1**: apenas os dados estruturados que a API entrega. IA (resumo,
   prazo, urgência), agenda/tarefas, opt-in por advogado e tools MCP ficam para v2.
4. **Todos os advogados** com `oab_number` + `oab_uf` preenchidos são monitorados.
   Sem UF → pulado com log, sem quebrar.
5. **Tela + digest por e-mail** reusando `notification_service` (novo
   `notification_type`).

## Modelo de dados

### Nova tabela `process_communications`

Dado bruto e imutável da API. Campos:

- `law_firm_id` FK (tenant, obrigatório), `judicial_process_id` FK nullable
  (preenchido sempre que o número CNJ for resolvível)
- `comunica_id` (id numérico da API), `hash` — **unique `(law_firm_id, hash)`**
  para deduplicação (padrão FAP Web: mesmo hash → UPDATE, não INSERT)
- `sigla_tribunal`, `tipo_comunicacao`, `tipo_documento`, `nome_orgao`,
  `nome_classe`, `codigo_classe`, `data_disponibilizacao` (Date)
- `numero_processo` (só dígitos, p/ matching) + `numero_processo_mascara`
- `texto` (inteiro teor), `link`, `meio`
- `destinatarios_json`, `advogados_json`, `raw_json` (payload completo — resiliência
  a mudanças de schema do CNJ)
- `matched_lawyer_id` FK (qual OAB trouxe), `read_at`, `read_by_user_id`
- `created_at`, `updated_at`

### Nova tabela `communication_sync_states`

Uma linha por `(law_firm_id, lawyer_id)`: `last_synced_date` (marca d'água),
`last_run_at`, `last_error`. Falha **não avança** a marca d'água (mesmo contrato
do `notification_service`).

### Alterações em tabelas existentes

- `lawyers`: + `oab_uf` VARCHAR(2)
- `judicial_processes`: + `origin` VARCHAR(20) default `'manual'`
  (`manual` | `comunica_auto`) e + `discovery_status` VARCHAR(20) default
  `'confirmed'` (`confirmed` | `pending_review` | `ignored`)

Migration standalone idempotente: `database/add_communications_monitoring.py`.

## Client — `app/services/comunica_pje_client.py`

`ComunicaPjeClient`, molde do `DataJudAPI`:

- `requests.Session`, sem auth, base URL via env `COMUNICA_PJE_API_URL`
  (default `https://comunicaapi.pje.jus.br/api/v1`)
- `get_comunicacoes(numero_oab, uf_oab, data_inicio, data_fim, pagina,
  itens_por_pagina)` e `get_comunicacoes_processo(numero_processo, ...)`
- `iter_comunicacoes(...)` — generator que encapsula a paginação
- Backoff exponencial para 429/5xx, timeout, parse tolerante (campo ausente →
  None, nunca derruba o batch)
- Parâmetros de data reais da API: `dataDisponibilizacaoInicio` /
  `dataDisponibilizacaoFim` (validados por script exploratório em
  `scripts/tests/test_comunica_pje_client.py`)

## Sincronização — `app/services/communication_monitor_service.py`

Fonte única para tela, digest e futuras tools MCP.

```
para cada law_firm:
  para cada Lawyer com oab_number + oab_uf:
    desde = last_synced_date - 2 dias (margem)
    para cada comunicação (paginada) no período:
      hash já existe p/ o escritório? → atualiza campos mutáveis, segue
      resolver JudicialProcess pelo numero_processo (dígitos)
        não existe → criar origin='comunica_auto', discovery_status='pending_review'
                   → importar histórico completo via numeroProcesso
      persistir comunicação vinculada
    sucesso → marca d'água = hoje; falha → mantém e registra last_error
```

Número CNJ ausente/inválido → comunicação salva sem vínculo (visível na tela
com aviso).

### Cron — `scripts/sync_process_communications.py`

1×/dia de manhã cedo (DJEN publica 1×/dia em dias úteis). `flock`, log em
`/var/log/intellexia/`, entrada nova documentada no `cron.md`. Execução
sequencial com sleep entre chamadas (educado com rate limit). Flags:
`--law-firm-id`, `--dry-run`.

## Telas

### Blueprint novo `communications` (`/comunicacoes`)

- Lista com filtros: tribunal, tipo de comunicação, advogado, período,
  não-lidas, número de processo; paginação; badge de não-lidas no menu.
- Detalhe: texto integral, metadados, botão "Documento original" (link da API),
  atalho para o processo no Painel Processual; marcar como lida.
- AdminLTE, herda `layout/base.html`, padrão `page_hero`, filtro tenant
  obrigatório em toda query.

### Painel Processual

- Lista principal filtra `discovery_status='confirmed'` (processos `manual`
  continuam aparecendo — default do novo campo é `confirmed`).
- Nova aba/filtro **"Descobertos"**: processos `comunica_auto` +
  `pending_review`, com ações "Confirmar" (→ `confirmed`) e "Ignorar"
  (→ `ignored`, some das listas padrão).
- Detalhe do processo: seção/timeline de comunicações do DJEN (leitura da
  tabela nova, visual próprio com pílula "DJEN").

## Notificação por e-mail

- Novo `notification_type='communications_digest'`, função
  `send_communications_digest` registrada em `SENDERS`.
- Card em Settings → Notificações (infra genérica existente, sem schema novo).
- Template `templates/emails/communications_digest.html`: tabelas + CSS inline,
  links absolutos via `APP_PUBLIC_URL`; comunicações do período agrupadas por
  processo. Sem novidades no período → não envia (só avança janela).
- Consome o mesmo `communication_monitor_service` da tela (queries únicas).

## Riscos e degradação

| Risco | Mitigação |
|---|---|
| API não documentada, schema pode mudar | Client isolado; `raw_json` persistido; parse tolerante |
| Rate limit (429) | Backoff + cadência diária + execução sequencial |
| CNJ inválido/ausente | Salva sem vínculo, não perde dado |
| SMTP ausente | Digest degrada gracioso (loga e retorna False) |
| OAB sem UF | Advogado pulado com log |

## Testes (scripts standalone, padrão do projeto)

- `scripts/tests/test_comunica_pje_client.py` — smoke contra a API real +
  validação de parâmetros aceitos (rodar manualmente).
- `tests/test_communication_monitor.py` — sync com client fake: dedup por hash,
  criação flagada de processo, marca d'água, CNJ inválido.
- `tests/test_communications_routes.py` — rotas via `app.test_client()`:
  lista, filtros, marcar lida, confirmar/ignorar descoberto, tenant isolation.

## Fora da v1 (registrado para v2)

IA (resumo/prazo/urgência), agenda/tarefas, WhatsApp/push, opt-in por advogado,
tools MCP, widget de dashboard.
