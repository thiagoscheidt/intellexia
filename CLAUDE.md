# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão Geral

**IntellexIA** é uma plataforma de automação jurídica com IA, focada em **direito trabalhista e previdenciário** (especialmente casos de FAP — Fator Acidentário de Prevenção). O sistema gerencia processos judiciais, analisa documentos, gera petições e oferece uma base de conhecimento consultável via agentes de IA.

---

## Stack Tecnológico

| Camada     | Tecnologia                                     |
| ---------- | ---------------------------------------------- |
| Backend    | Python 3.11–3.13 + Flask 3.1                   |
| ORM        | SQLAlchemy via Flask-SQLAlchemy                |
| LLM        | OpenAI (GPT-4o-mini, GPT-5-mini) via LangChain |
| Vector DB  | Qdrant (busca semântica) + FAISS (local)       |
| Full-text  | Meilisearch                                    |
| Documentos | Docling, PyMuPDF, pdfplumber, python-docx      |
| DB Dev     | SQLite (`instance/intellexia.db`)              |
| DB Prod    | MySQL 8.0 (via `pymysql`)                      |
| Infra      | Docker Compose (MySQL + Qdrant + Meilisearch)  |
| Frontend   | Jinja2 + AdminLTE 4 + Bootstrap 5              |
| Deps       | `uv` (não use `pip` diretamente)               |

---

## Comandos de Desenvolvimento

```bash
# Subir infra (MySQL, Qdrant, Meilisearch)
docker compose -f docker/docker-compose.yml up -d

# Instalar dependências
uv sync

# Rodar aplicação (dev — SQLite, debug ativo, cria tabelas automaticamente)
uv run python main.py
# ou
uv run flask run

# Produção (MySQL + Gunicorn)
uv run gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app
```

### Testes

Não há framework de testes configurado. Os arquivos em `tests/` e `scripts/tests/` são **scripts executáveis** que importam `main.app` e usam `app.test_client()` / `app.app_context()`. Rode-os individualmente:

```bash
uv run python tests/test_dashboard.py
uv run python scripts/tests/test_document_extractor.py --knowledge-id 123
```

### Migrations

**Não há Alembic.** Cada migração é um script Python isolado em `database/` (ex.: `add_fap_reason_column.py`, `add_benefits_table.py`). Rode manualmente com `uv run python database/<script>.py`. Para recriar do zero: `uv run python database/recreate_database.py` (APAGA TUDO). Novas migrations seguem este padrão de script standalone.

**Checklist mínimo para todo script de migration:**

1. Nome descritivo em `database/` — prefixo `add_*`, `alter_*` ou `remove_*`.
2. Executar dentro de `with app.app_context():`.
3. Verificar existência prévia (coluna/tabela/índice) para garantir idempotência.
4. Emitir mensagens claras de sucesso e erro.

---

## Estrutura de Diretórios

```
intellexia/
├── app/
│   ├── agents/                  # Agentes de IA
│   │   ├── core/                # FileAgent (upload OpenAI)
│   │   ├── document_processing/ # Extração e análise de documentos
│   │   ├── knowledge_base/      # RAG: roteamento, query, ingestão
│   │   ├── legal_drafting/      # Geração de petições
│   │   └── fap/                 # Classificador/gerador de seções FAP
│   ├── blueprints/              # Rotas Flask (uma pasta por módulo)
│   ├── services/                # Camada de serviços (orquestração)
│   ├── middlewares.py           # Auth + context processors
│   ├── models.py                # Modelos SQLAlchemy (~2100 linhas)
│   ├── prompts/                 # Prompts de agentes
│   └── utils/                   # timezone.py (SP_TZ), document_utils.py
├── database/                    # Scripts de migration (não-Alembic)
├── docker/                      # docker-compose.yml + configs
├── docs/                        # Documentação funcional (40+ .md)
├── scripts/                     # Scripts utilitários + scripts/tests/
├── templates/                   # Jinja2 (AdminLTE)
├── static/                      # Assets
├── tests/                       # Scripts de teste standalone
└── main.py                      # Entry point — define `app` Flask
```

**Código legado (evitar modificar; consulte antes de reutilizar):**
- `app/routes.py` — antiga, substituída por blueprints. Mantém apenas `/api/health` e rota de teste.
- `app/routes_backup.py`, `old/` — arquivos históricos sem uso ativo.
- `agent_document_generator.py` (raiz) — agente FAP legado, ainda importado por `petitions.py` para geração de petições FAP via python-docx. Funcional mas não evoluir.

**Estado dos módulos:**

| Módulo | Estado | Observação |
|---|---|---|
| cases, knowledge_base, fap_panel, fap_reasons | **Estável** | Código limpo, sem TODOs |
| documents, petitions, clients, lawyers, courts, benefits | **Estável** | CRUD simples, funcional |
| process_panel, disputes_center, fap_review | **Em desenvolvimento ativo** | Lógica complexa, bem estruturada |
| assistant | **Limitado** | Pattern-matching apenas — não usa agentes de IA |

---

## Arquitetura da Aplicação

### Entry Point e Configuração

`main.py` carrega `.env` manualmente (não usa `python-dotenv` em runtime), define timezone global `America/Sao_Paulo`, escolhe SQLite/MySQL via `ENVIRONMENT`, e registra **todos os blueprints** e middlewares. Instâncias de teste/scripts que precisam do contexto Flask devem fazer `from main import app` e usar `with app.app_context():`.

### Blueprints Registrados

`auth`, `dashboard`, `cases`, `clients`, `lawyers`, `courts`, `benefits`, `documents`, `petitions`, `assistant`, `tools`, `settings`, `knowledge_base`, `admin_users`, `process_panel`, `disputes_center`, `case_comments`, `fap_reasons`, `fap_panel`, `fap_review`, `docs`. Cada um em `app/blueprints/<nome>.py`, expondo `<nome>_bp`.

**Função de cada blueprint:**

| Blueprint | Prefixo de rota | Função |
|---|---|---|
| `auth` | `/` | Login, logout, registro |
| `dashboard` | `/` | Dashboard com estatísticas gerais |
| `cases` | `/cases` | Gestão de casos, templates, KB por caso |
| `clients` | `/clients` | CRUD de clientes (CNPJ, contatos) |
| `lawyers` | `/lawyers` | CRUD de advogados |
| `courts` | `/courts` | CRUD de varas/tribunais |
| `benefits` | `/cases/<id>/benefits` | Benefícios associados a casos |
| `documents` | `/cases/<id>/documents` | Documentos de casos com análise IA |
| `petitions` | `/cases/<id>/petitions` | Geração e versionamento de petições |
| `assistant` | `/assistente-juridico` | Chat com pattern-matching básico (sem IA avançada) |
| `knowledge_base` | `/knowledge-base` | KB global com busca vetorial, chat, categorias, tags |
| `process_panel` | `/process-panel` | Painel de processos judiciais com fases, teses, impugnação |
| `disputes_center` | `/disputes-center` | Gestão de contestações FAP (benefícios, CATs, folha, vínculos) |
| `fap_panel` | `/fap-panel` | Sincronização com FAP Web, download de PDFs em lote |
| `fap_review` | `/fap-review` | Revisão de petições FAP com IA, score de qualidade por advogado |
| `fap_reasons` | `/cases/fap-reasons` | Catálogo de motivos FAP configurável |
| `case_comments` | — | Threads de comentários em casos |
| `settings` | — | Preferências e integrações por usuário |
| `admin_users` | — | Gerenciamento de usuários (admin-only) |
| `docs` | `/docs` | Manual de uso dos painéis (renderizado dos markdowns) + assistente "pergunte ao manual" |

### Documentação do usuário (Manual + Assistente "pergunte ao manual")

O manual de uso dos painéis tem **fonte única em Markdown**: `docs/MANUAL_DASHBOARD.md`, `docs/MANUAL_PAINEL_FAP.md`, `docs/MANUAL_PAINEL_CONTESTACOES.md`. **Edite apenas esses `.md`** — a página `/docs/manuais` é renderizada em runtime a partir deles (cache por mtime). Não há HTML a gerar/manter manualmente; não existe mais `docs/manual_paineis.html`.

- **Pipeline de render**: `app/services/manual_renderer.py` (markdown-it-py + BeautifulSoup) → template `templates/docs/manuais.html`. Rota em `app/blueprints/docs.py`.
- **Convenções de realce no markdown** (interpretadas pelo renderer):
  - Avisos coloridos: citação (`>`) com marcador na 1ª linha — `> [!DOU]` (dourado/Diário Oficial), `> [!ALERTA]` (âmbar), `> [!INFO]` (azul), `> [!IA]` (roxo); `>` sem marcador = callout neutro.
  - Pílulas de origem: numa célula de tabela, escrever só o rótulo `FAP Web` / `IA` / `Sistema` / `Relatório` / `Cálculo` (ou lista separada por vírgula) vira pílula colorida.
  - Índice lateral: gerado automaticamente dos títulos `##`.
- **Assistente** (`ManualAssistantService` em `app/services/`, endpoint `POST /docs/chat`): chat flutuante na própria página, responde **só com base nos manuais** (lidos inteiros no prompt, sem RAG), modelo `DEFAULT_MODEL_MINI` (override via env `MANUAL_ASSISTANT_MODEL`). Lê os mesmos `.md`, então página e chat nunca dessincronizam.
- **Acesso**: `/docs/*` exige login, mas o prefixo `docs.` não está mapeado a módulo de permissão — qualquer usuário logado acessa.

### Multi-Tenancy (CRÍTICO)

O sistema é multi-tenant por **escritório de advocacia** (`LawFirm`). Quase todas as tabelas de negócio carregam `law_firm_id`. Toda query de listagem DEVE filtrar por `law_firm_id`:

```python
law_firm_id = session.get('law_firm_id')  # ou get_current_law_firm_id()
Case.query.filter_by(law_firm_id=law_firm_id)...
```

Uploads também são segregados por escritório (ex.: `uploads/cases_knowledge_base/{law_firm_id}/`). O helper `get_current_law_firm_id()` aparece duplicado em vários blueprints — é o padrão corrente.

### Autenticação e Middlewares

Sessão Flask (cookie) com `user_id` + `law_firm_id`. `app/middlewares.py::check_session` é um `before_request` global que redireciona para `auth.login` se não autenticado (exceto endpoints `public_endpoints`). Também atualiza `User.last_activity` a cada request autenticada. Para APIs JSON, retorna `401`.

Decorator `@require_law_firm` garante que há escritório na sessão.

### Timezone

Todas as datas de exibição usam `America/Sao_Paulo`. Filtros Jinja: `datetime_sp`, `date_sp`. Helper: `app.utils.timezone.now_sp()`. Datetimes sem `tzinfo` são tratados como UTC antes da conversão.

---

## Arquitetura de Agentes de IA

### Padrão Principal: Composição Sequencial

Agentes são classes Python especializadas, orquestradas em pipelines pela camada de serviços. **Não há framework de orquestração externo** — a composição é feita diretamente em código.

### Padrão de criação de agentes

```python
agent = create_agent(
    model=ChatOpenAI(...),
    response_format=ToolStrategy(PydanticSchema),
    system_prompt="..."
)
response = agent.invoke({"messages": [...]})
result = response.get("structured_response")  # instância do Pydantic model
```

Fallback quando há limite de recursão:
```python
llm = ChatOpenAI(...).with_structured_output(PydanticSchema)
result = llm.invoke([...messages...])
```

### Agentes por Domínio

#### Processamento de Documentos (`app/agents/document_processing/`)

| Agente                         | Responsabilidade                                               |
| ------------------------------ | -------------------------------------------------------------- |
| `AgentDocumentReader`          | Análise técnico-jurídica livre de documentos                   |
| `AgentDocumentExtractor`       | Extração estruturada: número do processo, partes, vara, tipo   |
| `AgentInitialPetitionAnalysis` | Análise de petições iniciais: pedidos, benefícios, fundamentos |
| `AgentDocumentSummary`         | Resumo sintético                                               |
| `AgentPetitionSummary`         | Resumo de petições                                             |
| `AgentSentenceSummary`         | Resumo de sentenças                                            |

**Fluxo:**
```
Arquivo → FileAgent → DocumentProcessorService (Docling/pdfplumber)
       → AgentDocumentExtractor (FAISS local + LLM)
       → AgentInitialPetitionAnalysis (se petição inicial)
       → KnowledgeIngestionAgent (Qdrant + Meilisearch)
```

#### Base de Conhecimento / RAG (`app/agents/knowledge_base/`)

| Agente                         | Responsabilidade                                             |
| ------------------------------ | ------------------------------------------------------------ |
| `ContextRetrievalRoutingAgent` | Decide se busca contexto e qual modo (semântico / full-text) |
| `QueryEnhancerAgent`           | Reescreve a pergunta para otimizar busca semântica           |
| `KeywordExtractionAgent`       | Extrai CPF, CNPJ, número de processo para busca textual      |
| `KnowledgeQueryAgent`          | Orquestrador principal: busca + geração de resposta          |
| `KnowledgeIngestionAgent`      | Ingere documentos no Qdrant e Meilisearch                    |
| `CaseKnowledgeIngestor`        | Ingere base de conhecimento específica do caso               |

**Fluxo de consulta:**
```
Pergunta do usuário
  → ContextRetrievalRoutingAgent (buscar? semântico ou full-text?)
  → QueryEnhancerAgent OU KeywordExtractionAgent
  → Qdrant (semântico) OU Meilisearch (full-text)
  → KnowledgeQueryAgent (gera resposta com fontes + sugestões)
  → TokenUsageService (rastreia custo)
```

#### Geração de Documentos (`app/agents/legal_drafting/`)

- **`AgentTextGenerator`**: Gera petições usando OpenAI Assistants API com `file_search` sobre templates DOCX enviados.
- **`AgentAppealGenerator`**: Gera recursos/apelações.

#### FAP (`app/agents/fap/`)

- **`FapCaseClassifierAgent`**: Classifica um benefício em motivo FAP. Detecta "null tokens" (`"nada consta"`, `"NL"`, `"sem observação"`) e retorna `unable_to_classify=True` nesses casos.
- **`FAPContestationClassifierAgent`**: Classifica justificativas de contestação em tópicos jurídicos. Usa `temperature=0.0`. Limiar mínimo `MIN_CONFIDENCE = 0.80`. Retorna array de tópicos — um benefício pode ter múltiplos tópicos simultâneos. Os tópicos são whitelist configurável (ex: `"ACIDENTE DE TRAJETO"`, `"NEXO TÉCNICO PREVIDENCIÁRIO PENDENTE DE JULGAMENTO"`, `"ERRO DE ESTABELECIMENTO"`, `"PRÉ-FAP"`, ~20 ao total). Prompt e reference são **versionados por law_firm** (tabelas `FapContestationClassifierPromptVersion` e `FapContestationClassifierReferenceVersion`).
- **`FapContestationJudgmentMetadataAgent`**: Extrai metadados estruturados de decisões judiciais FAP (número processo, data, órgão, decisão, fundamentação).
- **`FapSectionGeneratorAgent`**: Popula template DOCX com dados reais. Coleta todos os textos com índices, envia em uma única requisição IA, aplica substituições preservando 100% da formatação. Placeholders não resolvidos são mantidos.
- **`FapPetitionReviewerAgent`** (`app/agents/fap/`): Revisa petições FAP. Suporta análise simples (documento único) e análise comparativa (original vs revisado). Retorna `findings[]`, `missing_documents[]` e `benefits_check{}`. Achados descartados pelo usuário são ignorados por fingerprint em revisões futuras.

> **FAP Review**: agente revisor usa `temperature=0.0` (determinístico).

**Regras de negócio FAP embutidas no código:**
- Status bruto do FAP Web é normalizado: `"em andamento"`, `"EM ANÁLISE"` → `"analyzing"`.
- Tópicos FAP de um benefício ficam em `Benefit.fap_contestation_topics_json` (array JSON). Campo legado `fap_contestation_topic` (string única) ainda existe.
- `FapWebContestacao` com mesmo `(contestacao_id, cnpj_raiz)` → UPDATE, não INSERT (deduplicação).
- Marcar primeira instância como deferida pode ser feito em lote para todos os benefícios de uma vigência.
- Prompt do classificador é customizável por escritório sem alterar código.

**Workflows FAP:**

```
# Sincronização + Classificação
FapPanel → FapWebService.fetch_contestacoes(cnpj, year)
  → cria/atualiza FapWebContestacao + ChangeHistory
  → FAPContestationClassifierAgent.classify(benefit_description)
     → carrega prompt + reference ativos (por law_firm)
     → OpenAI temperature=0.0
     → retorna selected_topics (confidence >= 0.80)
  → salva em Benefit.fap_contestation_topics_json

# Geração de Petição
Petitions.generate → AgentDocumentGenerator (raiz legado)
  → carrega template DOCX
  → FapSectionGeneratorAgent.populate_template(case_data)
     → textos + dados → OpenAI → mapeamento → aplica
  → salva Petition (DOCX)

# Revisão de Petição
FapReview.revision [POST]
  → upload DOCX (+ opcional: comparativo + planilha XLSX)
  → cria FapReviewExecution (status=processing)
  → FapPetitionReviewerAgent.review()
     → findings, missing_documents, benefits_check
  → persiste result_json; workflow_status evolui até "ready_for_filing"
```

---

## Camada de Serviços

| Serviço                                | Responsabilidade                                          |
| -------------------------------------- | --------------------------------------------------------- |
| `DocumentProcessorService`             | Conversão de documentos, extração de tabelas, FAISS local |
| `KnowledgeBaseProcessingService`       | Orquestra pipeline completo: arquivo → banco de dados     |
| `TokenUsageService`                    | Rastreia tokens e calcula custo USD por chamada LLM       |
| `TokenAnalyticsService`                | Agregações/relatórios de uso de tokens                    |
| `FapContestationJudgmentReportService` | Processa relatórios de julgamento FAP                     |
| `FapWebService`                        | Integração web para dados FAP                             |
| `JudicialSentenceAnalysisService`      | Análise de sentenças judiciais                            |
| `DataJudApi`                           | Integração com API DataJud do CNJ                         |
| `SgtTpuService`                        | Integração com SGT-TPU (tabelas processuais unificadas)   |
| `OpenCnpjService`                      | Consulta CNPJ via API pública                             |

`app/services/knowledge_base/` contém helpers menores: `chat_context`, `search_helpers`, `session_helpers`.

---

## Variáveis de Ambiente Importantes

```bash
# Ambiente e secrets
ENVIRONMENT=development          # ou 'production'
SECRET_KEY=...                   # ALTERE em produção
OPENAI_API_KEY=...
MEILISEARCH_API_KEY=...

# MySQL (produção; ou quando DATABASE_TYPE=mysql)
DATABASE_TYPE=mysql
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=...
MYSQL_PASSWORD=...
MYSQL_DATABASE=intellexia

# Modelos LLM
QUERY_MODEL=gpt-4o-mini
KB_ROUTER_MODEL=gpt-5-nano
KB_QUERY_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
VECTOR_SIZE=1536
OPENAI_MAX_TOKENS=2000
OPENAI_TEMPERATURE=0.7

# Serviços externos
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=knowledge_base
MEILISEARCH_HOST=http://localhost:7700

# Config do agente KB
KB_MAX_CONTEXT_RESULTS=10
KB_MAX_CONTEXT_CHARS_PER_SOURCE=3000
KB_AGENT_RECURSION_LIMIT=10
KB_MAX_HISTORY_MESSAGES=10
KB_MAX_HISTORY_CHARS=12000

# Processamento de documentos
MAX_CHARS_PER_CHUNK=1500
SUMMARY_MAX_CHARS=50000
```

---

## Convenções do Projeto

- **Blueprints**: um por módulo de negócio, com sufixo `_bp`. Registrar em `main.py` e exportar em `app/blueprints/__init__.py`.
- **Saída estruturada**: agentes retornam Pydantic models, não strings livres.
- **Degradação graciosa**: todo agente tem fallback (regex, LLM direto sem tools, resposta simplificada).
- **Rastreamento de tokens**: toda chamada LLM deve passar por `TokenUsageService`.
- **Model Picker de IA (frontend)**: usar componente padronizado e reutilizável, sem duplicar modal por tela.
  - Macro: `templates/partials/model_picker_modal.html`
  - CSS: `static/css/model-picker-modal.css`
  - JS: `static/js/model-picker-modal.js`
  - Regra: telas devem instanciar `window.ModelPickerModal(...)` e usar callbacks (`onSelect`, `getSelectedModelId`) para integrar estado local.
  - Não copiar HTML/JS/CSS do modal para templates de feature; evoluções devem ocorrer no componente compartilhado.
- **Tabelas PDF**: lógica de carry-over para células vazias (CNPJ/NIT que se repetem em linhas).
- **Dual vector store**: Qdrant para busca conceitual, Meilisearch para busca por termos exatos (CPF, CNPJ, número de processo).
- **Filtro de tenant obrigatório**: toda query de listagem filtra por `law_firm_id`. Nunca expor dados de outro escritório.
- **Datetimes em UTC no banco**; exibição em SP via filtros Jinja.
- **Poppler** é dependência externa para converter PDF → imagem em petições (`pdf2image`). Instale via chocolatey/scoop/apt/brew.

---

## Convenções Frontend

- **Base de layout**: `templates/layout/base.html`. Todos os templates herdam dele.
- **Componentes compartilhados**: reutilizar o que existe em `templates/partials/` antes de criar novo.
- **`page_hero`**: se a tela já usa esse padrão, mantê-lo. Preservar breadcrumbs, mensagens flash e estados de carregamento/erro.
- **Responsividade**: garantir funcionamento em desktop e mobile sem quebrar o layout existente.
- **JavaScript**: evitar frameworks novos; priorizar JS nativo no padrão atual do projeto. Reutilizar helpers existentes antes de criar utilitários paralelos. Tratar estados vazios e falhas de API com mensagens claras ao usuário.
- **CSS**: preferir estilos locais da página apenas quando necessário. Evitar colisão com estilos globais e manter nomenclatura clara. Preservar consistência visual entre módulos (cards, badges, formulários, tabelas).

---

## Boas Práticas de Alteração

- Fazer mudanças pequenas, focadas e consistentes com o estilo local do arquivo.
- Evitar refatoração ampla sem necessidade funcional clara.
- Preservar compatibilidade com o fluxo atual baseado em blueprints.
- Reutilizar serviços e helpers existentes antes de criar lógica paralela.
- Evitar novas dependências sem necessidade clara.
- Priorizar funções pequenas e reutilizáveis em vez de duplicação.
- Em caso de conflito entre documentação e código atual, o código prevalece.

---

## Domínio Jurídico

- **FAP**: Fator Acidentário de Prevenção — índice que ajusta alíquota previdenciária da empresa.
- **Benefício B91/B94**: auxílio-acidente / auxílio-doença acidentário.
- **NIT**: Número de Identificação do Trabalhador.
- **Polo ativo/passivo**: partes do processo (autor/réu).
- **Pedidos**: lista de requerimentos da petição inicial.
- **DataJud**: API do CNJ para consulta de processos judiciais.
- **SGT-TPU**: sistema de tabelas processuais unificadas do CNJ.
- **CAT**: Comunicação de Acidente de Trabalho.
- **CNIS / INFBEN**: extratos previdenciários do segurado/benefício.
