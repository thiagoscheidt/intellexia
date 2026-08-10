# Módulo Diário Oficial — captura e armazenamento do DOU via INLABS

**Data:** 2026-08-10
**Estado:** design aprovado, pronto para plano de implementação
**Escopo:** Fase 1 — capturar e armazenar. Sem watchlist, sem alerta, sem integração com outros módulos.

---

## 1. Objetivo

Trazer o Diário Oficial da União para dentro do IntellexIA: baixar diariamente as
edições publicadas no [INLABS](https://inlabs.in.gov.br) da Imprensa Nacional,
quebrar o XML matéria a matéria, persistir em banco e expor uma tela de acervo
navegável mais um painel de saúde da captura.

### O que esta fase NÃO faz

Estas capacidades foram discutidas e conscientemente adiadas. Cada uma vira seu
próprio spec:

- **Watchlist / alertas** — vigiar termos, CNPJs de clientes ou atos do CNPS e
  avisar quando baterem.
- **Busca full-text** no acervo inteiro (Meilisearch).
- **Casamento com o Painel FAP** — ligar a publicação do resultado da contestação
  ao registro de `FapWebContestacao.data_dou_date`.
- **Análise por IA** das matérias capturadas.

A modelagem desta fase (matéria a matéria, com texto e órgão em coluna própria) é
o que torna todas elas possíveis depois sem remodelar nada.

### Decisão de sequenciamento

O usuário quer as quatro capacidades acima, mas pediu explicitamente para tratar
este módulo "como uma coisa individual por enquanto" e, "nesse momento, só
armazenar os dados do DOU". As três primeiras são consumidoras do mesmo corpus e
compartilham uma única máquina de regras (uma watchlist com sementes diferentes:
FAP pré-carregada, clientes derivada dos CNPJs cadastrados, livre digitada pelo
usuário). Construir o corpus primeiro é o pré-requisito de todas.

---

## 2. Restrições e descobertas que moldam o design

### 2.1 A janela do INLABS é móvel

O portal mantém aproximadamente **4 meses** de edições (na inspeção de
2026-08-10, de 2026-04-13 em diante). Edições mais antigas caem do portal. O que
não for capturado agora se perde. Daí o backfill fazer parte da entrega.

### 2.2 O INLABS reescreve datas passadas

Na mesma inspeção, `2026-08-01` (3,08 MB) constava como modificado em
`10-08-2026 09:58`; `2026-07-25` e `2026-07-11` apresentam o mesmo padrão, com
tamanhos muito abaixo da média diária — indício de edições suplementares
acrescentadas depois. **Um cron que só olha "hoje" perde essas republicações.**
Ver §6 (janela de reverificação).

### 2.3 O XML é barato; o PDF é caro

Medido em 2026-08-10: os três ZIPs XML somam ~6 MB; os três PDFs assinados somam
~89 MB. O custo de disco do módulo é essencialmente o PDF.

**Decisão:** guardar os dois (XML e PDF assinado), com política de retenção
apenas para o PDF. Estimativa: ~11 GB de backfill + ~32 GB/ano. O servidor tem
125 GB livres, compartilhados entre dev e produção — daí a retenção ser
obrigatória, não opcional.

### 2.4 O DOU é dado público idêntico para todo escritório

Ver §5.1 (exceção ao invariante de multi-tenancy).

---

## 3. Mecanismo do INLABS

Confirmado contra a implementação de referência oficial da Imprensa Nacional
(`github.com/Imprensa-Nacional/inlabs`, `public/python/`), não por memória.

| Etapa | Detalhe |
|---|---|
| Login | `POST https://inlabs.in.gov.br/logar.php`, form url-encoded, campos `email` e `password` |
| Sessão | cookie `inlabs_session_cookie` retornado na resposta |
| Download | `GET https://inlabs.in.gov.br/index.php?p=YYYY-MM-DD&dl=<arquivo>` |
| Headers do download | `Cookie: inlabs_session_cookie=<valor>` e `origem: 736372697074` |
| Arquivo XML | `YYYY-MM-DD-<SECAO>.zip`, seção em maiúsculas |
| Seções XML | `DO1 DO2 DO3 DO1E DO2E DO3E` — as terminadas em `E` são as **edições extras**, arquivos separados |
| Arquivo PDF | `YYYY_MM_DD_ASSINADO_<secao>.pdf`, seção em **minúsculas** (`do1 do2 do3`) — o PDF **já contempla as edições extras** |
| Ausência | HTTP 404 é resposta normal (dia sem publicação naquela seção), não é erro |

Total por dia: **6 ZIPs XML + 3 PDFs assinados**, sendo os 404 esperados e
frequentes (extras não saem todo dia).

### 3.1 Defeitos do script oficial que NÃO devem ser replicados

O código de referência é didático, não de produção. O client do IntellexIA
corrige:

1. **Recursão infinita** — `login()` chama a si mesmo em `ConnectionError` sem
   teto. Substituir por retry com limite (3) e backoff exponencial.
2. **Ausência de `timeout`** — nenhuma requisição tem timeout; uma conexão presa
   trava o cron indefinidamente. Definir timeout explícito (conexão e leitura).
3. **`exit()` dentro da função de download** — inaceitável em código de serviço.
   Erros viram exceção tratada pelo chamador.

Adicionalmente: **relogin transparente** quando o cookie expirar no meio de um
backfill longo (uma retentativa por operação; se o segundo login falhar, propaga).

### 3.2 Credenciais

`INLABS_EMAIL` e `INLABS_PASSWORD` no `.env`. Como o corpus é global (§5.1), é
uma credencial do sistema, não do escritório.

Sem as variáveis, o módulo **degrada graciosamente**: o serviço registra em log e
retorna sem executar, no mesmo contrato do `email_service`. A tela de captura
mostra o estado "não configurado" em vez de erro.

---

## 4. Arquitetura

Espelha o módulo `communications` (Monitoramento de Processos), que já provou o
padrão fonte-externa → client isolado → serviço de ingestão → tabela com dedup →
tela neste projeto.

```
scripts/sync_dou.py                          cron + backfill + CLI
  └─ app/services/inlabs_client.py           ÚNICO ponto que fala com o INLABS
  └─ app/services/dou_ingestion_service.py   baixa → descompacta → parseia → persiste
       └─ app/services/dou_xml_parser.py     XML bytes → list[dict]  (função pura)
  └─ app/models.py: DouEdition, DouArticle, DouSyncRun

app/blueprints/dou.py                        rotas
templates/dou/                               telas Acervo e Captura
database/add_dou_tables.py                   migration standalone
```

### Por que o parser é um módulo separado

`dou_xml_parser` recebe bytes de XML e devolve `list[dict]`. Sem rede, sem banco,
sem Flask. É testável com um arquivo de amostra em `tests/fixtures/` e é a peça
que mais tende a quebrar quando a Imprensa Nacional alterar o schema — deve ser a
única peça que precisa mudar nesse caso.

### Fronteiras

- **`inlabs_client`** — autenticação, montagem de URL, download de bytes, retry,
  rate limiting. Não conhece banco nem modelo de dados.
- **`dou_xml_parser`** — bytes → dicts. Não conhece rede nem banco.
- **`dou_ingestion_service`** — orquestra: pede bytes ao client, grava arquivo em
  disco, chama o parser, faz upsert no banco, registra a execução. É o único que
  conhece as três coisas.
- **`dou.py` (blueprint)** — só consulta e apresenta. Nunca baixa nada de forma
  síncrona numa requisição de usuário.

---

## 5. Modelo de dados

### 5.1 Exceção ao invariante de multi-tenancy

O CLAUDE.md estabelece que toda tabela de negócio carrega `law_firm_id` e toda
query de listagem filtra por ele. **As tabelas do DOU são exceção consciente e
devem ser documentadas como tal no CLAUDE.md.**

Razão: o DOU é dado público federal, byte a byte idêntico para todo escritório.
Replicá-lo por tenant duplicaria ~11 GB de backfill e ~32 GB/ano por escritório e
multiplicaria o tempo do cron pelo número de clientes, sem proteger nenhum
sigilo. O corpus é um **catálogo público compartilhado**.

O que for específico de escritório em fases futuras (watchlist, marcação de
leitura, favoritos) entra em **tabela própria, com `law_firm_id`**, referenciando
o catálogo. O invariante continua valendo para todo dado de negócio.

### 5.2 `dou_editions`

Uma linha por `(data, seção)`. Seção aqui é a do XML (`DO1`…`DO3E`).

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | Integer PK | |
| `data_publicacao` | Date | indexado |
| `secao` | String(10) | `DO1`,`DO2`,`DO3`,`DO1E`,`DO2E`,`DO3E` |
| `qtd_materias` | Integer | preenchido após o parse |
| `zip_path` | String(500) | caminho relativo em `uploads/` |
| `zip_bytes` | BigInteger | |
| `content_signature` | String(64) | SHA-256 do ZIP — detecta republicação |
| `pdf_path` | String(500) | nulo em seções `*E` (o PDF cobre as extras) |
| `pdf_bytes` | BigInteger | |
| `pdf_purged_at` | DateTime | marcado quando a retenção poda o PDF |
| `status` | String(20) | `pending`,`downloaded`,`parsed`,`not_published`,`error` |
| `error_message` | Text | |
| `baixado_em` / `processado_em` | DateTime | |

Restrição: `UNIQUE (data_publicacao, secao)`.

### 5.3 `dou_articles`

Uma linha por matéria (`<article>` do XML).

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | Integer PK | |
| `edition_id` | FK → `dou_editions` | indexado |
| `art_id` | String(50) | atributo `id` do INLABS |
| `id_materia` | String(50) | atributo `idMateria` |
| `pub_name` | String(10) | `DO1`… — desnormalizado para filtro barato |
| `pub_date` | Date | idem, indexado |
| `edicao` | String(20) | número da edição |
| `pagina` | String(20) | `numberPage` |
| `pdf_page` | Text | URL da página no pesquisa.in.gov.br |
| `orgao_hierarquia` | String(500) | `artCategory` — hierarquia do órgão, indexado |
| `identifica` | String(500) | ex. `PORTARIA Nº 1.234, DE 8 DE AGOSTO DE 2026` |
| `art_type` | String(100) | tipo do ato, indexado |
| `art_class` | String(255) | |
| `ementa` | Text | |
| `titulo` / `subtitulo` | Text | |
| `texto` | `db.Text(16777215)` | MEDIUMTEXT — texto limpo, sem tags |
| `texto_html` | `db.Text(16777215)` | conteúdo original de `<Texto>` |
| `raw_xml` | `db.Text(16777215)` | o `<article>` inteiro, verbatim |
| `hash` | String(64) | SHA-256 do conteúdo — **UNIQUE** |
| `created_at` / `updated_at` | DateTime | |

Índices: `(pub_date, pub_name)`, `orgao_hierarquia`, `art_type`, `hash` UNIQUE.

`raw_xml` é a apólice de seguro: se o parser mapear um campo errado, o dado não
se perde — reprocessa a partir do banco, sem rebaixar do INLABS.

**Nota de implementação:** os nomes de atributo acima refletem o formato XML
publicado do DOU e devem ser **confirmados contra o primeiro ZIP real** durante a
implementação. O parser mapeia de forma defensiva (atributo ausente → `None`,
nunca exceção), e `raw_xml` garante que uma divergência de schema não cause perda
de dado.

### 5.4 `dou_sync_runs`

Auditoria de cada execução — alimenta a aba Captura.

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | Integer PK | |
| `modo` | String(20) | `cron`, `backfill`, `manual` |
| `iniciado_em` / `finalizado_em` | DateTime | |
| `data_inicial` / `data_final` | Date | janela processada |
| `edicoes_baixadas` | Integer | |
| `materias_inseridas` / `materias_atualizadas` | Integer | |
| `nao_publicados` | Integer | contagem de 404 esperados |
| `erros` | Integer | |
| `status` | String(20) | `running`, `success`, `partial`, `error` |
| `detalhe_json` | JSON | por dia/seção, para diagnóstico |

---

## 6. Idempotência e agendamento

### 6.1 Dedup

O `hash` da matéria é UNIQUE e definido como
`SHA-256(art_id | id_materia | pub_date | pub_name | raw_xml)`, com os campos
concatenados por `|` e `raw_xml` normalizado (whitespace entre tags colapsado).

Incluir `raw_xml` significa que **qualquer alteração de conteúdo gera um hash
novo** — republicação com texto corrigido entra como matéria distinta, não
sobrescreve silenciosamente a anterior. O upsert, portanto, casa por
`(art_id, id_materia, edition_id)`: encontrando a linha, atualiza os campos e o
`hash`; não encontrando, insere. O `hash` UNIQUE é a rede de segurança contra
INSERT duplicado quando a mesma matéria chega duas vezes na mesma execução.

Reprocessar o mesmo dia é **UPDATE, nunca INSERT duplicado** — mesma regra do
`ProcessCommunication`. Isso torna qualquer reexecução segura.

### 6.2 Janela de reverificação

Motivada por §2.2. Toda execução do cron reconfere os **últimos 7 dias**
(parametrizável via `DOU_RECHECK_DAYS`):

1. Baixa o ZIP da data/seção **em memória**.
2. Calcula o SHA-256 e compara com `dou_editions.content_signature`.
3. **Igual** → descarta os bytes sem tocar no disco nem no banco. Custo: apenas o
   download.
4. **Diferente ou inexistente** → grava o arquivo (substituindo o anterior),
   atualiza `content_signature` e reprocessa o XML.

A ordem importa: gravar antes de comparar sobrescreveria um arquivo íntegro por
um download possivelmente truncado. O disco só é tocado quando há mudança real.

Custo da janela: 7 dias × 6 seções × ~1 MB ≈ 42 MB de download por execução,
sem escrita em disco no caso comum.

### 6.3 Cadência

Cron **3×/dia** (07h, 12h, 19h). A edição normal sai pela manhã; as extras saem a
qualquer hora do dia. Usar `flock` para evitar sobreposição, no mesmo padrão do
`sync_process_communications.py`.

### 6.4 Commit por unidade

Commit por `(dia, seção)`. Uma execução interrompida (deploy, queda, Ctrl-C)
retoma sem perder o já feito e sem duplicar — mesma propriedade do modo `--full`
do sync de comunicações.

### 6.5 Falha não avança marca d'água

Se o download ou o parse de uma `(data, seção)` falhar, a edição fica com
`status='error'` e a próxima execução tenta de novo. Falha nunca é registrada
como sucesso.

---

## 7. Arquivos em disco e retenção

**Layout:** `uploads/dou/YYYY/MM/DD/` — ZIPs e PDFs da data. O banco guarda
**caminho relativo**, nunca absoluto (dev e produção têm raízes diferentes).

Sem `law_firm_id` no caminho, diferentemente dos demais uploads do projeto —
consequência direta do corpus ser global (§5.1).

**Retenção:** `DOU_PDF_RETENTION_MONTHS` (padrão `24`). Uma rotina de poda remove
PDFs mais antigos que a janela e marca `pdf_purged_at`; a linha em
`dou_editions` permanece, com o PDF ausente sinalizado na tela. XML, texto e
metadados **nunca são podados**.

Sem retenção, ~32 GB/ano esgotam os 125 GB livres em cerca de três anos, num
servidor compartilhado com produção.

---

## 8. Interface

Módulo **"Diário Oficial"**, prefixo `/dou`, blueprint `dou_bp`, herdando de
`templates/layout/base.html` e usando `page_hero`, conforme as convenções de
frontend do projeto.

### 8.1 Aba Acervo

- Navegação por **data** e **seção**.
- Lista de matérias com filtro por **órgão** (`orgao_hierarquia`) e **tipo de
  ato** (`art_type`), paginada.
- Detalhe da matéria: `identifica`, ementa, texto, órgão, página, edição, e link
  para a página oficial (`pdf_page`).
- Download do PDF assinado da edição, quando presente.

Sem busca por termo nesta fase (fica para o spec de busca full-text). A navegação
é por data/seção/órgão/tipo, que os índices do §5.3 atendem.

### 8.2 Aba Captura

Estado da ingestão: dias capturados, matérias por dia, 404s, falhas, última
execução, e botão **"reprocessar data"**.

### 8.3 Permissões

Módulo normal em `app/utils/permissions.py`:

- `MODULE_PERMISSIONS['dou'] = 'Diario Oficial'`
- `ENDPOINT_MODULE_MAP['dou.'] = 'dou'`
- **Fora dos defaults de não-admin** (entra em `_RESTRICTED_BY_DEFAULT`), como
  `clients`/`lawyers`/`courts` — o admin concede por usuário na tela de
  Administração de Usuários.

Sem chip de contador no header nesta fase: não há fila nem pendência a comunicar
enquanto não existir watchlist.

---

## 9. Script de sincronização

`scripts/sync_dou.py`, no padrão de `sync_process_communications.py` (docstring
com modos e sugestão de cron, `_log` com timestamp, `argparse`).

```bash
uv run python scripts/sync_dou.py                          # cron: hoje + janela de reverificação
uv run python scripts/sync_dou.py --data 2026-08-10        # uma data específica
uv run python scripts/sync_dou.py --secoes DO1,DO3         # subconjunto de seções
uv run python scripts/sync_dou.py --sem-pdf                # só XML
uv run python scripts/sync_dou.py --dry-run                # não grava nada
uv run python scripts/sync_dou.py --backfill --desde 2026-04-13
```

**Backfill:** entregue como **comando manual**, não acoplado ao deploy. São ~11 GB
e horas de download; o cron diário sobe primeiro, e o resgate histórico roda
quando o usuário decidir. Percorre dia a dia com commit por dia — interrompível e
retomável.

**Cron sugerido:**

```cron
0 7,12,19 * * * cd /sites/intellexia && flock -n /tmp/intellexia_dou.lock \
    uv run python scripts/sync_dou.py >> /var/log/intellexia/sync_dou.log 2>&1
```

---

## 10. Tratamento de erro

| Situação | Comportamento |
|---|---|
| Credenciais ausentes no `.env` | Loga e retorna sem executar; tela mostra "não configurado" |
| Credenciais inválidas (sem cookie) | Erro explícito, execução abortada, `dou_sync_runs.status='error'` |
| HTTP 404 no download | Estado normal: `status='not_published'`, contabilizado em `nao_publicados` |
| Falha de rede | Retry com teto (3) e backoff; esgotado, marca a `(data,seção)` como `error` e segue para a próxima |
| Cookie expirado no meio do backfill | Relogin transparente, uma retentativa; segunda falha propaga |
| ZIP corrompido | `status='error'` com mensagem; arquivo preservado em disco para diagnóstico |
| Matéria sem atributo esperado | Campo vira `None`; nunca derruba o parse do restante da edição |
| Disco cheio | Erro explícito e abortar — nunca gravar arquivo truncado |

---

## 11. Testes

Seguindo o padrão do projeto (scripts executáveis em `tests/`, sem framework):

- **`tests/test_dou_xml_parser.py`** — o mais valioso. Roda contra um XML de
  amostra em `tests/fixtures/`, sem rede e sem banco. Cobre: matéria completa,
  atributo ausente, texto com HTML embutido, acentuação/encoding, e edição com
  múltiplas matérias.
- **`tests/test_dou_ingestion.py`** — idempotência: ingerir o mesmo ZIP duas vezes
  produz o mesmo número de linhas, a segunda como UPDATE. E republicação (mesma
  data, conteúdo diferente) atualiza em vez de duplicar.
- **Verificação manual do client** — `--dry-run` contra o INLABS real, confirmando
  login, cookie e os 404 esperados.

---

## 12. Migration

`database/add_dou_tables.py`, no padrão standalone do projeto: executa dentro de
`with app.app_context():`, verifica existência prévia de cada tabela antes de
criar (idempotente) e emite mensagens claras de sucesso e erro.

---

## 13. Documentação a atualizar

- **`CLAUDE.md`** — registrar o blueprint `dou` na tabela de blueprints, o
  `inlabs_client`/`dou_ingestion_service` na camada de serviços, as variáveis de
  ambiente novas, e **a exceção de multi-tenancy do §5.1** (é o ponto que mais
  confundiria quem chegar depois).
- **`docs/MANUAL_DIARIO_OFICIAL.md`** — manual de uso, registrado em `_MANUALS`
  (`manual_renderer.py`) e `_MANUAL_FILES` (`manual_assistant_service.py`).
  Usar os marcadores de realce do projeto; o `> [!DOU]` já existe e é o
  apropriado aqui.

---

## 14. Variáveis de ambiente novas

```bash
INLABS_EMAIL=...
INLABS_PASSWORD=...
DOU_SECOES=DO1,DO2,DO3,DO1E,DO2E,DO3E   # padrão: todas
DOU_RECHECK_DAYS=7                      # janela de reverificação
DOU_PDF_RETENTION_MONTHS=24             # 0 = nunca podar
DOU_DOWNLOAD_TIMEOUT=120                # segundos
```

---

## 15. Decisões registradas

| Decisão | Escolha | Razão |
|---|---|---|
| Escopo da fase 1 | Só capturar e armazenar | Pedido explícito do usuário; corpus é pré-requisito das demais fases |
| Formatos | XML + PDF assinado completo | Usuário quer a versão certificada disponível |
| Granularidade | Matéria a matéria | Único formato que sustenta as fases 2–4 sem remodelar |
| Multi-tenancy | Catálogo global, sem `law_firm_id` | Dado público idêntico; replicar custaria ~32 GB/ano por escritório |
| Nome / URL | "Diário Oficial" / `/dou` | Consistente com `fap_panel`, `process_panel` |
| Permissão | Módulo normal, concedível por usuário | Fora dos defaults, como os cadastros |
| Backfill | Comando manual, não no deploy | ~11 GB e horas de download; não deve amarrar o deploy |
| Retenção | Só PDF, padrão 24 meses | Servidor compartilhado com produção, 125 GB livres |
| Busca por termo | Adiada | Vira spec próprio, com Meilisearch |
