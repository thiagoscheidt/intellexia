# Explicação IA automática de novas comunicações no sync (Design)

**Data:** 2026-07-24
**Escopo:** `app/services/communication_monitor_service.py` + `scripts/sync_process_communications.py`

## Objetivo

Hoje a explicação IA de uma comunicação processual (`explain_communication`, cache em
`ProcessCommunication.analysis_json`) só é gerada quando o usuário clica em
"Explicar com IA" na tela de Monitoramento de Processos. Este design faz o cron de
sincronização gerar e salvar essa explicação automaticamente para cada comunicação
**nova** — como se o usuário tivesse clicado no botão — de forma que ao abrir a tela
a explicação já esteja pronta.

## Decisões (aprovadas pelo usuário)

1. **Modos**: roda no incremental diário (por OAB) e no `--caderno`. **Nunca** no
   `--full` (carga histórica pode criar milhares de comunicações) nem no `--dry-run`.
2. **Escopo por execução**: só as comunicações criadas na rodada atual. Backlog
   antigo (ex.: de um `--full` anterior) continua sob demanda pelo botão da tela.
3. **Padrão**: ligada por padrão; nova flag `--sem-ia` desliga.
4. **Teto**: 100 explicações por escritório por execução (proteção de custo contra
   rajadas, ex.: primeira rodada após dias parado). Quando truncar, logar quantas
   ficaram de fora.

## Arquitetura

### Serviço — `explain_new_communications(law_firm_id, since, limit=100)`

Nova função em `communication_monitor_service.py` (fonte única, reutilizável pela
tela no futuro):

- **Seleção**: `ProcessCommunication` do escritório com `analysis_json IS NULL`,
  `texto IS NOT NULL` e `created_at >= since`, ordenada por
  `data_disponibilizacao DESC, id DESC`, limitada a `limit`. `since` usa
  `datetime.now()` — o mesmo relógio do default de `created_at` (TZ global do
  processo). Filtrar por "sem análise" torna a função idempotente:
  rodar de novo não regera nada (o cache de `explain_communication` também protege).
- **Execução**: para cada comunicação, chama a já existente
  `explain_communication(law_firm_id, comm.id, user_id=_system_user_id(law_firm_id))`.
  Cada chamada é uma transação curta com commit próprio — **nenhuma chamada de
  IA/HTTP dentro da transação do sync**, respeitando a disciplina rede/escrita de
  `_ingest_batch` (lock em `users` via FK já congelou produção).
- **Falhas**: exceção em uma explicação → `db.session.rollback()` + `logger.warning`
  e segue para a próxima. O sync nunca falha por causa da IA; a comunicação fica
  para o botão manual (degradação graciosa).
- **Retorno**: `{'explained': n, 'failed': n, 'pending': n}` — `pending` é quantas
  elegíveis ficaram de fora do teto.
- **Tokens**: `explain_communication` já rastreia via agente/`TokenUsageService`,
  atribuído ao usuário de sistema do escritório.

### Script — `sync_process_communications.py`

- Nova flag `--sem-ia` ("não gera a explicação IA das comunicações novas").
- Captura `run_start` (UTC) **antes** do sync.
- Após o sync de cada escritório (modos incremental e `--caderno`), se não for
  `--dry-run` nem `--full` nem `--sem-ia`, chama
  `monitor.explain_new_communications(firm_id, since=run_start)`.
- Log por escritório: `🤖 escritório X · N explicada(s), M falha(s)`; se
  `pending > 0`, acrescenta aviso de truncamento pelo teto.
- Exit code: falhas de explicação **não** contam como falha do script (só falhas
  de sincronização mantêm o comportamento atual).

## Fora do escopo

- Botão "Explicar com IA" da tela e endpoint atual — inalterados.
- `sync_process` (botão de sincronizar um processo na tela) — inalterado.
- Drenagem de backlog antigo sem explicação.

## Testes

Sem framework de testes no projeto (scripts standalone). Verificação:

- Script standalone em `tests/` ou execução manual com `--dry-run` / `--law-firm-id`
  num ambiente com poucas comunicações novas, conferindo `analysis_json` preenchido.
- Conferir que `--sem-ia`, `--full` e `--dry-run` não disparam explicação.
- Simular falha do agente (ex.: sem `OPENAI_API_KEY`) e conferir que o sync conclui
  com sucesso e loga o warning.
