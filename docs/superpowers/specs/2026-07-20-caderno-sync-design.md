# Sincronização por Caderno (DJEN) — Design e validação

**Data:** 2026-07-20
**Objetivo:** oferecer um segundo modo de sincronização do radar de comunicações: em vez de 1 consulta à API por advogado (OAB), baixar o **caderno diário compactado** de cada tribunal e filtrar localmente pelas OABs do escritório.

## Validação prática (PoC executada contra a API real)

- `GET /caderno/TJSC/2026-07-17/D` → 200: 39.720 comunicações, zip de 32 MB com 40 arquivos `.json`; TRF4 na mesma data: 19,6 MB / 31.747 comunicações.
- Formato interno: cada `.json` tem envelope `{count, items}` com **schema idêntico** ao de `GET /comunicacao` (incluindo `destinatarioadvogados[].advogado.numero_oab/uf_oab`) — `parse_comunicacao` funciona sem alteração.
- Varredura local de 39.720 itens: **2,4s**. URL do zip é temporária (5 min) — baixar logo após obter os metadados.
- ~2% dos registros têm `numero_oab` não numérico → matching normaliza com `only_digits` dos dois lados.
- Smoke test real (dry-run, TRF4 17/07): 31.747 varridas, **5 do escritório encontradas** — exatamente as mesmas que a consulta por OAB retorna; como já estavam no banco, foram `updated`, comprovando o dedup por hash entre os dois modos.
- Atenção: as comunicações do escritório concentram-se em TRF1–TRF5, TRT2 e STJ — o caderno é **por tribunal**, então o modo caderno precisa da lista certa de tribunais (padrão: os do histórico do próprio escritório).

## Quando cada modo vale a pena

| | Por OAB (padrão) | Por caderno |
|---|---|---|
| Requisições/dia | 1+ por advogado (22 hoje) | 1 metadado + 1 download por tribunal (7 hoje) |
| Banda | mínima | ~20-30 MB por tribunal grande |
| Limite 10.000 resultados | sujeito | imune |
| Advogado novo sem histórico | pega tudo (30 dias) | só pega do dia do caderno em diante |
| Tribunal novo (sem histórico) | pega automaticamente | precisa entrar na lista de siglas |

O modo OAB continua **padrão**; caderno é opção explícita (`--caderno`), útil para escritórios com muitos advogados ou como redundância.

## Implementação

- **Client** (`comunica_pje_client.py`): `get_caderno(sigla, data, meio='D')` (metadados via `_get`, com pacing/retry) e `iter_caderno_comunicacoes(meta)` (download em streaming para tempfile, itera os itens dos `.json` do zip).
- **Service** (`communication_monitor_service.py`): `firm_tribunal_siglas(law_firm_id)` (tribunais do histórico) e `sync_law_firm_from_cadernos(law_firm_id, data=None, siglas=None, client=None, dry_run=False)` — monta índice `(oab_digits, uf) → lawyer_id` dos advogados monitoráveis, varre cada caderno, e para cada match reusa `parse_comunicacao` + `_upsert_communication` (mesmo dedup por hash, mesma descoberta automática de processos). Caderno com status ≠ "Processado" → `skipped` sem falha. Falha de um tribunal não afeta os demais.
- **CLI** (`scripts/sync_process_communications.py`): `--caderno [--data YYYY-MM-DD] [--tribunais TRF4,TRF3]`; sem `--tribunais`, usa o histórico do escritório; escritório sem histórico → `no_tribunals`, exige lista explícita.
- **Sem watermark**: o modo caderno não altera `CommunicationSyncState` dos advogados (que pertence ao modo OAB); a idempotência vem do upsert por hash.

## Testes

- `tests/test_caderno_sync.py` (sem rede, client fake com caderno em memória): matching com OAB normalizada (formatada vs dígitos, UF errada não casa), vínculo ao advogado, descoberta de processo, dedup em segunda rodada, caderno indisponível → skipped, dry-run não persiste, siglas padrão do histórico. 9/9.
- Smoke real: `--caderno --dry-run --law-firm-id 1 --data 2026-07-17 --tribunais TRF4` → 5/5 comunicações do escritório encontradas.
