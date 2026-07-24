# Notificação por e-mail do Radar + destaque de sentença

**Data:** 2026-07-24
**Módulos afetados:** `settings` (Notificações), `notification_service`, novo `process_radar_service`, `communication_monitor_service`, templates de e-mail, cron de notificações.

## Objetivo

Criar uma **terceira notificação por e-mail** — o **Resumo do Radar** (Mesa de Trabalho do Painel de Processos) — no mesmo padrão das duas existentes (Resumo FAP e Comunicações processuais). Além disso, **destacar visualmente as decisões/sentenças** dentro do resumo, tanto no novo e-mail do Radar quanto na notificação de Comunicações que já existe.

Decisões tomadas no brainstorming:

- **Fonte:** o widget **Radar da Mesa de Trabalho** (o mesmo do dashboard do Painel de Processos), que agrega: providências apontadas pela IA, publicações não lidas de processos vinculados e movimentações recentes do DataJud (incluindo decisões/sentenças).
- **Semântica de "sentença":** **destaque no resumo** — sem envio extra/imediato. As decisões aparecem realçadas dentro do e-mail periódico, no horário já configurado.
- **Detecção de decisão:** reutiliza a lista `DECISION_WORDS` de `datajud_snapshot_service` (`sentenca`, `acordao`, `procedencia`, `homologacao`, ...), já validada e consistente com o que a tela marca como "decisão".
- **Arquitetura:** extrair a lógica do Radar (hoje inline no blueprint do dashboard) para um serviço `process_radar_service` — **fonte única** de tela e e-mail. O e-mail mostra o **estado atual** do Radar (todas as pendências abertas), mas **só dispara quando há item novo** desde o último envio.

## Contexto atual (o que já existe)

- **`NotificationSetting`** (`app/models.py`): tabela genérica, uma linha por `(law_firm_id, notification_type)`. Constantes `TYPE_FAP_DIGEST` e `TYPE_COMMUNICATIONS_DIGEST`. **Novo tipo = nova constante, sem schema novo.**
- **`notification_service`**: `is_due`/`due_settings` (agenda horária), `_digest_window_start` (janela desde `last_sent_at`), `SENDERS` (mapa tipo → função `send_*`). Contrato dos digests: sem novidades não envia (só avança a janela); falha de envio não avança a janela.
- **`settings.py` / `notifications.html`**: um card por tipo, com switch ativo/inativo, frequência (diário/semanal), horário, dia da semana, destinatários e botão "Enviar teste para mim". O JS de cada card é uma cópia da mesma mecânica.
- **Radar inline** (`process_panel.py`, ~linhas 1106–1196): monta `radar_items` (kinds `ia`, `publicacao`, `decisao`, `movimentacao`), ordena por `when` desc, corta em 8 e expõe `radar_total`. Cada item tem `kind`, `label`, `process_id`, `process_number`, `when`, `url` (mais `tipo` na publicação).
- **`build_communications_digest`** (`communication_monitor_service.py`): agrupa comunicações da janela por processo; cada comunicação tem `tipo`, `tipo_documento`, `orgao`, `data`, `link`.
- **`datajud_snapshot_service.DECISION_WORDS`** + `is_decision_movement(name)`: normaliza acentos/caixa e testa contra a lista de palavras de decisão.

## Arquitetura

### 1. Novo serviço `app/services/process_radar_service.py` (fonte única do Radar)

Extrai o bloco inline do dashboard para uma função reutilizável.

```python
def build_radar(law_firm_id, limit=8):
    """Itens do Radar da Mesa de Trabalho (providências IA + publicações não lidas
    + movimentações DataJud recentes), ordenados por recência.
    Retorna (items, total). Cada item ganha `is_decision` (bool)."""
```

- Move para cá toda a lógica hoje em `process_panel.py` (as três varreduras + ordenação + `radar_total`).
- Cada item passa a carregar **`is_decision`**:
  - kind `decisao` (DataJud) → `True` (já vem de `is_decision_movement`);
  - kinds `publicacao`/`ia` → aplica `DECISION_WORDS` sobre `tipo` + `label`/`tipo_documento`;
  - kind `movimentacao` → `False`.
- `process_panel.py` passa a chamar `process_radar_service.build_radar(law_firm_id, limit=8)` — comportamento da tela **idêntico** (mesma ordenação, mesmo corte, mesmo `radar_total`). Nenhuma mudança visual no dashboard.
- **Sem consulta a APIs externas** — lê `ProcessCommunication`, `ProcessDeadline`, `ProcessDatajudSnapshot` já persistidos (igual ao código atual).

Uma função adicional monta o pacote do e-mail:

```python
def build_radar_digest(law_firm_id, since, limit=RADAR_DIGEST_LIMIT):
    """Estado atual do Radar para o e-mail. Marca `is_new` (item com `when` > since)
    e `is_decision` por item; totais = {total, novos, decisoes}.
    has_novidades = existe algum item com is_new (só então o e-mail é enviado)."""
```

- Mostra o **estado atual** (pendências abertas), não só a janela — assim uma providência importante não some por ter sido publicada antes do último envio.
- **`has_novidades = any(is_new)`**: o e-mail só sai quando há item novo desde `last_sent_at`; caso contrário só avança a janela (mesmo contrato dos outros digests).
- Ordena decisões primeiro, depois por `when` desc (destaque no topo).

### 2. `NotificationSetting.TYPE_RADAR_DIGEST = 'radar_digest'`

Nova constante no modelo. Sem migração de schema (tabela genérica).

### 3. `notification_service`

- `render_radar_digest(law_firm_id, since, is_test)` → renderiza `emails/radar_digest.html` (mesmo padrão de `render_communications_digest`, com `test_request_context(base_url=app_public_url())`).
- `send_radar_digest(law_firm_id, force, override_recipients, dry_run)` → cópia estrutural de `send_communications_digest`: destinatários, janela (`_digest_window_start`), skip sem novidades avançando a janela, assunto, `dry_run`, envio, `last_sent_at` só em envio real.
  - Assunto: `Radar — {N} pendência(s) / {D} decisão(ões) ({data})` ou `sem novidades`.
- Registrar em `SENDERS`: `TYPE_RADAR_DIGEST: send_radar_digest`. O cron (`send_due_notifications`) passa a cobrir o novo tipo automaticamente.

### 4. Destaque de sentença na notificação de Comunicações (já existente)

- Em `build_communications_digest`, cada comunicação ganha **`is_decision`** (aplica `DECISION_WORDS` a `tipo_comunicacao` + `tipo_documento`); `totais` ganha **`decisoes`** (contagem).
- `emails/communications_digest.html`: itens com `is_decision` recebem realce (faixa/etiqueta de alerta, ex.: pílula âmbar "Decisão/Sentença") e, se houver decisões, uma linha-resumo no topo (`{D} decisão(ões) no período`).

### 5. `templates/emails/radar_digest.html`

Novo template no padrão dos e-mails existentes (tabelas + CSS inline, logo via `cid:logo`, `is_test`, rodapé de descadastro). Estrutura:

- Cabeçalho "Radar — Mesa de Trabalho".
- Linha-resumo: `{total} pendência(s) · {decisoes} decisão(ões) · {novos} nova(s) desde o último envio`.
- **Bloco de decisões destacado** (cor de alerta) no topo, quando houver.
- Lista de itens do Radar: etiqueta por `kind` (IA / Publicação / Decisão / Movimentação), `process_number` linkado, `label`, data (`when`), badge "Novo" quando `is_new`.
- Botão "Abrir o Painel de Processos" (`url_for('process_panel...')`).

### 6. `settings.py` + `templates/settings/notifications.html`

- `notifications()` carrega também `radar_digest = get_or_create_setting(..., TYPE_RADAR_DIGEST)` e passa ao template.
- Rotas novas (espelhando as de Comunicações): `POST /notifications/radar-digest` (usa `_save_digest_setting(TYPE_RADAR_DIGEST)`) e `POST /notifications/radar-digest/send-now` (usa `_send_digest_test(send_radar_digest)`). **Reutiliza os helpers existentes** — sem lógica nova.
- Terceiro card no template, no mesmo layout (switch/frequência/horário/dia/destinatários/enviar teste). Ícone `bi bi-bullseye` (o mesmo do Radar na tela).

## Fluxo

```
Cron horário (scripts/send_notifications.py)
  → send_due_notifications → due_settings (inclui radar_digest no horário)
    → send_radar_digest(law_firm_id)
       → build_radar_digest(law_firm_id, since=last_sent_at)
          → process_radar_service.build_radar (estado atual) + is_new/is_decision
       → sem is_new? skip (avança janela)  |  com is_new? renderiza + envia
```

## Limites / decisões explícitas (YAGNI)

- **Sem envio imediato** de sentença (só destaque no resumo) — conforme escolhido.
- **Sem "marcar como ciente" pelo e-mail** — o e-mail é informativo; ações continuam na tela.
- **Sem novo schema** — reaproveita `notification_settings`.
- **Sem duplicar a lógica do Radar** — `process_panel.py` e o e-mail passam a consumir `process_radar_service`.
- O e-mail do Radar pode **sobrepor** itens do e-mail de Comunicações (uma publicação não lida aparece nos dois) — é intencional: são recortes diferentes (Radar = pendências acionáveis por processo vinculado; Comunicações = tudo que chegou do DJEN). O admin ativa os que quiser.

## Testes (scripts standalone, padrão do projeto)

- `scripts/tests/test_radar_digest.py`: com `app.app_context()`, monta cenário e valida `build_radar_digest` (has_novidades, is_new, is_decision, contagem de decisões) e o dry-run de `send_radar_digest`.
- Verificar que `process_panel` dashboard segue idêntico após a extração (radar_items/radar_total inalterados).
- Verificar `build_communications_digest` marcando `is_decision`/`decisoes` corretamente.

## Documentação

- Atualizar a seção **Notificações por e-mail** no `CLAUDE.md` (novo `TYPE_RADAR_DIGEST` + `send_radar_digest` em `SENDERS`; menção a `process_radar_service` como fonte única do Radar).
- Registrar `process_radar_service` na tabela da Camada de Serviços do `CLAUDE.md`.
