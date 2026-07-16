# Notificações por e-mail (SMTP) + Resumo FAP

**Data:** 2026-07-16
**Status:** aprovado para implementação

## Objetivo

Dar ao IntellexIA a capacidade de **enviar e-mails** (hoje inexistente no projeto) e usá-la na
primeira notificação: um **Resumo FAP** periódico, muito parecido com o widget
"Contestações FAP — recentes" do dashboard (Publicadas no D.O.U. / Cadastradas / Atualizadas).

## Decisões

| Tema | Decisão |
|---|---|
| Escopo | Admin do escritório define destinatários e agendamento (tela admin-only) |
| Credenciais SMTP | `.env` global (um servidor para a plataforma) — senha nunca no banco |
| Conteúdo | Destaque do que mudou no período **+** panorama das mais recentes |
| Gatilho | Cron horário + botão "Enviar agora" (teste) na tela |
| Estrutura | Uma página `Notificações` com **um card por tipo**; tabela genérica por (escritório, tipo) |
| Regra dos dados | Serviço compartilhado — dashboard e e-mail chamam a mesma função |

## Arquitetura

```
scripts/send_notifications.py  (cron horário, flock)
  └─ notification_service.due_settings(now) -> [NotificationSetting]
     └─ notification_service.send_fap_digest(law_firm_id)
        ├─ fap_digest_service.build_fap_digest(law_firm_id, since)  ← mesma regra do dashboard
        ├─ render_template('emails/fap_digest.html', ...)
        └─ email_service.send_email(...)  ← smtplib (stdlib)
```

### 1. `app/services/email_service.py`

Base reutilizável, `smtplib` da stdlib (sem dependência nova).

```python
is_configured() -> bool
send_email(to: list[str], subject: str, html: str, text: str | None = None,
           inline_images: dict | None = None) -> bool
```

- Env: `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`,
  `SMTP_FROM_NAME` (IntellexIA), `SMTP_USE_TLS`, `SMTP_TIMEOUT`.
- Porta 465 → `SMTP_SSL`; demais → `starttls` quando `SMTP_USE_TLS`.
- Multipart `alternative` (texto + HTML); `inline_images` anexa por CID (logo).
- **Degradação graciosa**: sem config, loga e retorna `False`; exceções viram log + `False`.

### 2. `app/services/fap_digest_service.py`

Recebe os builders extraídos de `app/blueprints/dashboard.py`, com `since` opcional:

```python
build_latest_dou(law_firm_id, limit=10, since=None)
build_latest_cadastro(law_firm_id, limit=10, since=None)
build_latest_atualizacao(law_firm_id, limit=10, since=None)
build_fap_digest(law_firm_id, since, limit=10) -> dict
```

`build_fap_digest` retorna `{"novidades": {dou, cadastro, atualizacao},
"recentes": {dou, cadastro, atualizacao}, "totais": {...}, "periodo": {...}}`.
O dashboard passa a importar daqui (uma fonte só, como nos exports do MCP).

### 3. Modelo `NotificationSetting` (`notification_settings`)

| Campo | Tipo | Uso |
|---|---|---|
| `law_firm_id` + `notification_type` | FK + String(50) | únicos juntos; hoje `'fap_digest'` |
| `is_enabled` | Boolean | liga/desliga |
| `frequency` | String(20) | `daily` \| `weekly` |
| `send_hour` | Integer | 0–23 (horário de São Paulo) |
| `send_weekday` | Integer | 0=segunda … 6=domingo (só `weekly`) |
| `recipients_json` | Text | lista de e-mails |
| `last_sent_at` | DateTime (UTC) | janela do "desde o último envio" |

Migration standalone idempotente: `database/add_notification_settings_table.py`.

### 4. Tela — `templates/settings/notifications.html`

- `GET/POST /settings/notifications` no blueprint `settings`, **admin-only**.
- `POST /settings/notifications/fap-digest/send-now` → envia **só para o admin logado**,
  assunto `[TESTE]`, sem alterar `last_sent_at`.
- Item no menu Configurações da sidebar (admin-only), card "Resumo FAP" + status do SMTP.

### 5. `app/services/notification_service.py`

- `due_settings(now)` — quais configs estão no horário (frequência/hora/dia vs `last_sent_at`).
- `send_fap_digest(law_firm_id, force=False, override_recipients=None)`:
  - `since` = `last_sent_at` ou fallback (24 h no diário, 7 dias no semanal);
  - **sem novidades → não envia**, apenas avança `last_sent_at`;
  - falha de envio → **não** avança a janela (a próxima hora tenta de novo);
  - URLs absolutas via `APP_PUBLIC_URL` + `test_request_context` (padrão dos exports MCP).

### 6. E-mail — `templates/emails/fap_digest.html`

HTML de e-mail: tabelas + CSS inline, fundo claro, logo do IntellexIA por CID. Sem abas
(não existem em cliente de e-mail): seção **"O que mudou no período"** (D.O.U. / Cadastradas /
Atualizadas, com contagem) e **"Mais recentes"** abaixo, incluindo as etiquetas de "Alterou".

### 7. Cron — `scripts/send_notifications.py`

Roda de hora em hora, com `flock`, no padrão de `cron.md`. Suporta `--dry-run` e
`--law-firm-id`. Entrada documentada em `cron.md`.

### 8. Testes — `tests/test_notifications.py`

Script executável (padrão do projeto): monta o digest numa janela conhecida, renderiza o
template, valida `due_settings` e, havendo SMTP no `.env`, faz um envio real.

## Multi-tenancy

Toda query filtra `law_firm_id`; destinatários e agendamento são por escritório; o cron
itera sobre as linhas de `notification_settings`.
