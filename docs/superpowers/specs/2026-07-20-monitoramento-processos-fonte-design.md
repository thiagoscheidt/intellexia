# Monitoramento de Processos — rename + campo de fonte

**Data:** 2026-07-20
**Objetivo:** (1) renomear a feature "Monitoramento de Comunicações" para **"Monitoramento de Processos"**; (2) registrar em cada comunicação **de qual fonte de informação** ela veio, preparado para novas fontes no futuro.

## Decisões

- **Rename só de exibição**: sidebar, títulos, hero, breadcrumbs e rótulo do módulo de permissão mudam para "Monitoramento de Processos". Endpoint (`communications.*`), URL (`/comunicacoes`) e chave de permissão (`communications`) **não mudam** — links, favoritos e permissões já configuradas continuam válidos.
- **Campo `source`** em `process_communications`: `VARCHAR(30) NOT NULL DEFAULT 'comunica_pje'`, indexado. Backfill automático via DEFAULT na migration (`database/add_process_communications_source_column.py`).
- **Extensível por constante**: fontes conhecidas vivem no modelo — `ProcessCommunication.SOURCE_COMUNICA_PJE` + `SOURCE_LABELS` (valor → rótulo de exibição). Nova fonte no futuro = nova constante + rótulo + o ingestor passar `source=...` ao `_upsert_communication` (que aceita o parâmetro e carimba no INSERT; no UPDATE a fonte original é preservada).
- Os dois modos atuais de sincronização (por OAB e por caderno) usam a **mesma** fonte `comunica_pje` — o modo é "como" se busca, a fonte é "de onde" vem o dado.

## UI

- Filtro "Fonte" na lista (select com as fontes existentes no escritório, rótulo amigável).
- Coluna "Fonte" com badge na tabela e linha "Fonte" no detalhe.

## Testes

`tests/test_caderno_sync.py` estendido: fonte carimbada no insert, filtro por fonte na query (11/11). Render verificado: lista renomeada com filtro/badge funcionando, detalhe com fonte, filtro por query string ok.
