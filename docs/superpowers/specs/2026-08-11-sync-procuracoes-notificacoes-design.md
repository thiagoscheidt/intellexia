# Sincronização isolada de procurações FAP + notificações

**Data:** 2026-08-11
**Status:** aprovado para implementação

## Objetivo

Separar a sincronização das **procurações eletrônicas** do FAP Web do cron completo
(`scripts/fap_sync_cron.py`), para poder rodá-la de poucos em poucos minutos, e usá-la como
gatilho de duas notificações novas:

1. **Alerta de mudança** — sai a cada execução do sync que encontre procuração nova ou
   alteração relevante em procuração existente;
2. **Resumo diário de procurações** — sai uma vez ao dia, pela manhã, com as que estão
   chegando ao fim da vigência e as que entraram desde o último envio.

## Problema atual

| | |
|---|---|
| Acoplamento | A sincronização de procurações é a etapa `[2/3]` do cron completo, que também faz empresas, contestações (busca paralela × N anos) e download de PDFs. Rodar procurações de 10 em 10 minutos hoje significaria rodar tudo isso junto. |
| Duplicação tripla | O mesmo upsert existe em `scripts/fap_sync_cron.py::sync_procuracoes` e em `app/blueprints/fap_panel.py::sync_procuracoes` (rota `POST /fap-panel/sync/procuracoes`). Um terceiro chamador viraria a terceira cópia. |
| Não há detecção de mudança | O upsert reescreve **todos** os campos em toda execução; o contador `updated` conta todo registro existente, não mudança real. Não há como saber o que mudou. |

## Decisões

| Tema | Decisão |
|---|---|
| Separação | Serviço único `fap_procuracoes_service`; o cron completo **mantém** a etapa, agora delegando ao serviço |
| Registro de mudança | Tabela `fap_web_procuracoes_change_history`, espelhando `FapWebContestacaoChangeHistory` |
| Gatilho do alerta | Procuração nova + mudança de `situacao_codigo` + mudança de `data_inicio`/`data_fim` |
| Janela do resumo | 30 dias, em blocos por urgência; só procurações `DEFERIDA` |
| Resiliência | Ambas as notificações usam a janela `last_sent_at`: sem novidade não envia, falha de envio **não** avança a janela |

## Arquitetura

```
scripts/fap_procuracoes_sync.py         (cron ~10 min, flock)
  ├─ FapWebService.check_session()      → expirada = exit 2, sem martelar o portal
  ├─ fap_procuracoes_service.sync_procuracoes(svc, law_firm_id)
  │    ├─ FapWebService.fetch_procuracoes()          ← rede
  │    ├─ upsert por (law_firm_id, protocolo) com diff campo a campo
  │    └─ grava FapWebProcuracaoChangeHistory quando há diff real
  └─ notification_service.send_procuracoes_alert(law_firm_id)
       ├─ fap_procuracoes_service.build_procuracoes_alert(law_firm_id, since)
       ├─ render_template('emails/procuracoes_alert.html', ...)
       └─ email_service.send_email(...)

scripts/send_notifications.py           (cron horário — SEM alteração)
  └─ notification_service.send_procuracoes_digest(law_firm_id)   ← novo em SENDERS
       └─ fap_procuracoes_service.build_procuracoes_digest(law_firm_id, since)

scripts/fap_sync_cron.py                (cron diário — etapa [2/3] passa a delegar)
app/blueprints/fap_panel.py             (rota POST /sync/procuracoes passa a delegar)
```

---

### 1. `app/services/fap_procuracoes_service.py` (novo)

Fonte única. Recebe um `FapWebService` já autenticado — quem chama monta a autenticação
(o painel usa a da sessão via `build_fap_service`, os scripts usam `FAP_AUTH_JSON`).

```python
TRACKED_FIELDS = (
    'tipo_procuracao_codigo', 'tipo_procuracao_descricao',
    'situacao_codigo', 'situacao_descricao',
    'data_inicio', 'data_fim',
    'cnpj_raiz_outorgante', 'nome_empresa_outorgante',
    'cpf_outorgado', 'cnpj_raiz_outorgado',
    'data_cadastro',
)

# Subconjunto que gera e-mail. O resto vira histórico silencioso.
ALERT_FIELDS = ('situacao_codigo', 'data_inicio', 'data_fim')

VENCIMENTO_DIAS = 30          # janela do resumo diário
VENCIDA_LOOKBACK_DIAS = 30    # até quando uma vencida continua no e-mail
SITUACAO_VIGENTE = 'DEFERIDA'

def sync_procuracoes(svc, law_firm_id: int) -> dict
def build_procuracoes_alert(law_firm_id: int, since: datetime) -> dict
def build_procuracoes_digest(law_firm_id: int, since: datetime) -> dict
def ultima_sincronizacao(law_firm_id: int) -> datetime | None
```

**Instantes em UTC** (`_utcnow()`), não `datetime.now()`. Descoberto na implementação:
`main.py` define `TZ=America/Sao_Paulo`, então `datetime.now()` devolve hora local — 3 h
atrás do UTC em que `NotificationSetting.last_sent_at` é gravado. Como `synced_at` é a coluna
comparada com essa janela, gravá-la em hora local deixaria a janela 3 h no futuro: nenhuma
mudança seria alertada até o relógio local ultrapassar o `last_sent_at`, e o alerta "imediato"
sairia em rajadas de 3 em 3 horas. Datas de vigência seguem em data local (`date.today()`) —
`data_fim` é data comercial brasileira, não instante.

**`sync_procuracoes`** — retorna
`{'ok', 'total', 'created', 'updated', 'unchanged', 'alertaveis', 'expired', 'message'}`.

Para cada item da API:

1. `protocolo` vazio → ignora (comportamento atual).
2. Parse dos campos (as funções `_parse_date` / `_parse_datetime` de hoje, movidas para cá).
3. Busca por `(law_firm_id, protocolo)` — a chave UNIQUE já existente.
4. **Novo** → INSERT + linha de histórico `change_type='created'`, `is_alertavel=True`.
5. **Existente** → diff sobre `TRACKED_FIELDS`. Com diff: linha de histórico
   `change_type='updated'` com `old_values`/`new_values` só dos campos que mudaram, e
   `is_alertavel = bool(set(changed) & set(ALERT_FIELDS))`. Sem diff: só atualiza
   `last_synced_at` e conta em `unchanged`.
6. `raw_data` e `last_synced_at` são reescritos sempre, mas ficam **fora** de
   `TRACKED_FIELDS` — senão toda execução seria "mudança".

Falha na busca (`result.ok == False`) devolve `{'ok': False, 'expired': ..., 'message': ...}`
sem tocar no banco.

**`build_procuracoes_alert(law_firm_id, since)`** — lê o histórico com
`synced_at > since` e `is_alertavel = True`, agrupado por tipo:

```python
{
  'novas': [ {protocolo, outorgante, cnpj_raiz, tipo, situacao, data_inicio, data_fim}, ... ],
  'alteradas': [ {protocolo, outorgante, mudancas: [{campo, de, para}, ...]}, ... ],
  'totais': {'novas': n, 'alteradas': m, 'total': n + m},
  'has_novidades': bool,
}
```

Rótulos de campo (`situacao_codigo` → "Situação", `data_fim` → "Fim da vigência") ficam num
dicionário no serviço, para o template não decidir nomenclatura.

**`build_procuracoes_digest(law_firm_id, since)`** — quatro blocos, todos restritos a
`situacao_codigo == 'DEFERIDA'`:

| Bloco | Critério |
|---|---|
| `vencidas` | `hoje - 30 <= data_fim < hoje`, **exceto** as com renovação (ver abaixo) |
| `vence_7` | `hoje <= data_fim <= hoje + 7` |
| `vence_30` | `hoje + 7 < data_fim <= hoje + 30` |
| `ultimas` | as 5 mais recentes por `data_cadastro`, com `is_nova` nas do período |

**A fonte de "novas" é `data_cadastro`, não o histórico** (corrigido depois do primeiro
envio real). O histórico só conhece o que apareceu depois que este código entrou no ar: numa
base já sincronizada — 2.829 procurações e zero linhas de histórico — toda procuração
existente casa por protocolo no primeiro run e vira `unchanged`, nunca `created`. O bloco
ficaria vazio por semanas, até surgir uma procuração inédita. `data_cadastro` (a data em que
o **portal FAP** registrou a procuração) está preenchida em 100% das linhas, vale
retroativamente e é a verdade da origem. A comparação com a janela passa por `_sp_naive()`:
`data_cadastro` vem em horário de Brasília e `last_sent_at` em UTC — comparar direto engoliria
3 h de cadastros a cada envio.

**Blocos longos são cortados no corpo** (`LIMITE_POR_BLOCO = 10`, `LIMITE_ULTIMAS = 5`): o
primeiro envio real trazia 88 cartões. O total continua inteiro no cabeçalho de cada bloco e
nos contadores; o excedente vira "e mais N não listada(s)" com link para o painel.

Mais `'ultima_sincronizacao'` (o maior `last_synced_at` do escritório) e
`'sync_atrasado'` (bool, `> 24 h`).

**Supressão de renovada:** uma renovação chega do portal como **protocolo novo**, não como
alteração da antiga. Uma procuração vencida é omitida do bloco `vencidas` quando existe outra
`DEFERIDA` do mesmo `(cnpj_raiz_outorgante, tipo_procuracao_codigo)` com `data_fim` posterior.
Sem isso, o e-mail cobraria por 30 dias uma renovação já feita.

**`has_novidades`** do digest é `True` quando **qualquer** bloco tem item — inclusive sem
novidade nenhuma no período. É diferente dos outros três digests do sistema, e de propósito:
uma procuração que vence em 3 dias e não teve evento algum é justamente o aviso mais
importante; exigir novidade a silenciaria. O custo aceito é a repetição diária enquanto o
vencimento estiver na janela.

### 2. Modelo `FapWebProcuracaoChangeHistory` (`fap_web_procuracoes_change_history`)

Espelho de `FapWebContestacaoChangeHistory` (`app/models.py:2679`), com as colunas de
identidade trocadas:

| Coluna | Tipo | Observação |
|---|---|---|
| `id` | Integer PK | |
| `law_firm_id` | FK `law_firms.id`, index | multi-tenant |
| `procuracao_db_id` | FK `fap_web_procuracoes.id` ON DELETE CASCADE, index | |
| `protocolo` | String(50), index | |
| `cnpj_raiz_outorgante` | String(20), index | desnormalizado: o e-mail não precisa de JOIN |
| `nome_empresa_outorgante` | String(500) | idem |
| `change_type` | String(30), index | `created` \| `updated` |
| `changed_fields` | Text | JSON: lista de campos |
| `old_values` / `new_values` | Text | JSON |
| `is_alertavel` | Boolean, index, default False | a linha cruza `ALERT_FIELDS`? |
| `synced_at` | DateTime, index | **coluna da janela das notificações** |
| `created_at` / `updated_at` | DateTime | |

`is_alertavel` é calculado na gravação para o e-mail não precisar abrir o JSON de cada linha.
Relação inversa `change_history` em `FapWebProcuracao`, com `cascade='all, delete-orphan'`.

**Migration:** `database/add_fap_procuracoes_change_history_table.py`, no padrão do projeto —
`with app.app_context():`, checagem prévia por `inspect(db.engine).has_table(...)`, mensagens
de sucesso e erro.

### 3. `scripts/fap_procuracoes_sync.py` (novo)

Só procurações: sem empresas, sem contestações, sem download de PDF.

```
carrega .env → FAP_AUTH_JSON → check_session → sync_procuracoes → send_procuracoes_alert
```

- Flags: `--dry-run` (busca e mostra o diff, não grava nem envia), `--law-firm-id`,
  `--no-notify`.
- Escritório: `FAP_SYNC_LAW_FIRM_ID` ou primeiro `LawFirm` ativo — reusa `_get_law_firm_id`.
- Códigos de saída: `0` ok · `1` erro · `2` sessão FAP expirada. Código próprio para expiração
  porque o script roda de minuto em minuto e o log precisa distinguir "credencial vencida" de
  "portal fora do ar".
- Cron sugerido (o intervalo é uma linha de crontab, não código):

```
*/10 * * * * cd /sites/intellexia && flock -n /tmp/intellexia_fap_procuracoes.lock \
    uv run python scripts/fap_procuracoes_sync.py >> /var/log/intellexia/fap_procuracoes.log 2>&1
```

`flock -n` é obrigatório: em intervalo curto, dois runs simultâneos se atropelariam no upsert.

### 4. Alerta — `NotificationSetting.TYPE_PROCURACOES_ALERT = 'procuracoes_alert'`

Notificação **de evento**: quem dispara é o script de sync, não o cron horário.

`send_procuracoes_alert(law_firm_id, force=False, override_recipients=None, dry_run=False)`
segue o mesmo contrato dos três digests existentes:

- janela = `last_sent_at`, ou (primeiro envio) `agora - 24 h`;
- sem novidade e sem `force` → `skipped`, e a janela **avança**;
- falha de envio → `failed`, e a janela **não** avança — o próximo run reenvia o mesmo período.
  É isso que faz o alerta sobreviver a SMTP fora do ar.

Assunto: `Procurações FAP — 2 novas · 1 alterada (11/08/2026)`.

**`due_settings()` precisa excluir os tipos de evento.** `is_due()` hoje só checa
`send_hour` + destinatários; com `send_hour` no default (8), o `send_notifications.py` das 8h
mandaria o alerta de novo, duplicado. Entra:

```python
EVENT_TYPES = {NotificationSetting.TYPE_PROCURACOES_ALERT}
# em due_settings(): query.filter(NotificationSetting.notification_type.notin_(EVENT_TYPES))
```

### 5. Resumo diário — `NotificationSetting.TYPE_PROCURACOES_DIGEST = 'procuracoes_digest'`

Tipo periódico comum. Entra em `SENDERS` e o `scripts/send_notifications.py` **não muda**.
Padrão: diário, 8h — configurável na tela como os demais.

Assunto: `Procurações FAP — 3 vencendo · 2 novas (11/08/2026)`.

### 6. E-mails — `templates/emails/procuracoes_alert.html` e `procuracoes_digest.html`

Tabelas + CSS inline, logo por CID via `_logo_bytes()`, links absolutos com
`test_request_context(base_url=app_public_url())` — mesmo padrão dos três e-mails existentes.

- **Alerta:** bloco "Novas" e bloco "Alteradas", este último com o de-para por campo
  (*situação: PENDENTE → DEFERIDA*).
- **Digest:** blocos vencidas (vermelho) → até 7 dias (vermelho) → 8–30 dias (âmbar) → novas.
  Rodapé com "última sincronização há X"; passando de 24 h, o aviso sobe em destaque. É o que
  impede a sessão FAP expirar em silêncio e o vazio ser lido como "nada mudou".

Ambos linkam para `/fap-panel/procuracoes` com o filtro correspondente — a tela já aceita
`vencendo_em` e `protocolo` por query string.

### 7. Tela — `templates/settings/notifications.html` + `app/blueprints/settings.py`

Dois cards novos, admin-only como a página inteira.

- **Card do alerta:** switch + destinatários + botão "Enviar teste". **Sem** frequência,
  horário ou dia da semana; uma linha explica que a checagem acompanha o cron de procurações.
- **Card do resumo diário:** cópia do padrão existente (frequência, horário, dia, destinatários).

`_save_digest_setting` exige `frequency`/`send_hour`/`send_weekday` e rejeitaria o form do
alerta. Refatoração mínima: a validação de destinatários + `is_enabled` (a parte comum) sai
para `_validate_recipients_form()`, e o alerta ganha `_save_event_setting(notification_type)`,
que salva só `is_enabled` e destinatários. `_send_digest_test` serve aos dois sem alteração.

Rotas novas:

```
POST /settings/notifications/procuracoes-alert
POST /settings/notifications/procuracoes-alert/send-now
POST /settings/notifications/procuracoes-digest
POST /settings/notifications/procuracoes-digest/send-now
```

### 8. Chamadores existentes passam a delegar

- `scripts/fap_sync_cron.py`: `sync_procuracoes()` sai do arquivo; a etapa `[2/3]` vira uma
  chamada ao serviço, seguida da mesma chamada a `send_procuracoes_alert`. O cron completo
  **continua** sincronizando procurações e **também** notifica — assim, se o cron dedicado não
  for instalado em produção, o alerta ainda sai uma vez por dia em vez de nunca. Não há risco
  de e-mail duplicado: a janela `last_sent_at` já foi avançada pelo run dedicado, então a
  segunda chamada não encontra novidade e devolve `skipped`.
- `app/blueprints/fap_panel.py`, `POST /sync/procuracoes`: o corpo do upsert (≈90 linhas) vira
  uma chamada ao serviço. O JSON de resposta ganha `unchanged` e mantém
  `ok`/`total`/`created`/`updated`/`message`/`expired` — o JS da tela não quebra.

### 9. Testes — `tests/test_procuracoes_sync.py`

Script standalone no padrão do projeto (`from main import app`, `with app.app_context():`),
sem rede: alimenta o serviço com uma lista de dicts no formato da API.

1. Primeira ingestão → `created`, histórico `created`, `is_alertavel=True`.
2. Reingestão idêntica → `unchanged`, **zero** linhas novas de histórico.
3. Mudança de `situacao_codigo` → `updated`, histórico com `is_alertavel=True` e de-para correto.
4. Mudança só de `nome_empresa_outorgante` → histórico gravado com `is_alertavel=False`;
   `build_procuracoes_alert` **não** a inclui.
5. `build_procuracoes_digest`: item em cada faixa cai no bloco certo; vencida com renovação
   posterior é suprimida; `situacao != DEFERIDA` fica de fora.
6. `due_settings()` não devolve `procuracoes_alert` mesmo na hora configurada.

## Multi-tenancy

`fap_web_procuracoes_change_history` carrega `law_firm_id` e toda query do serviço filtra por
ele. O sync roda para um escritório por execução — a autenticação FAP é um cookie só. As duas
`NotificationSetting` são por escritório, como as existentes.

## Fora de escopo

- **Não poda** procurações que sumirem do portal: revogação chega como `EXCLUIDA`, não como
  sumiço, e apagar a linha levaria o histórico junto.
- **Sem controle anti-flood** além do próprio ciclo do cron: no máximo um e-mail por execução,
  e só com mudança real. Procuração não oscila.
- **Sem tela de histórico**: a tabela é gravada e consumida pelos e-mails. Expor as mudanças
  em `/fap-panel/procuracoes` fica para depois.
- **Sem alerta de sessão FAP expirada por e-mail**: o sinal é o rodapé de saúde do resumo
  diário mais o exit code `2` no log.
