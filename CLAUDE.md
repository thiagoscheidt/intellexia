# IntellexIA — Instruções para o Claude

## Visão Geral

**IntellexIA** é uma plataforma de automação jurídica com IA, focada em **direito trabalhista e previdenciário** (especialmente casos de FAP — Fator Acidentário de Prevenção). O sistema gerencia processos judiciais, analisa documentos, gera petições e oferece uma base de conhecimento consultável via agentes de IA.

---

## Stack Tecnológico

| Camada     | Tecnologia                                     |
| ---------- | ---------------------------------------------- |
| Backend    | Python + Flask 3.1                             |
| ORM        | SQLAlchemy via Flask-SQLAlchemy                |
| LLM        | OpenAI (GPT-4o-mini, GPT-5-mini) via LangChain |
| Vector DB  | Qdrant (busca semântica) + FAISS (local)       |
| Full-text  | Meilisearch                                    |
| Documentos | Docling, PyMuPDF, pdfplumber, python-docx      |
| DB Dev     | SQLite                                         |
| DB Prod    | MySQL 8.0                                      |
| Infra      | Docker Compose (MySQL + Qdrant + Meilisearch)  |
| Frontend   | Jinja2 + AdminLTE + Bootstrap                  |

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
│   │   └── fap/                 # Classificador de casos FAP
│   ├── blueprints/              # Rotas Flask (uma pasta por módulo)
│   ├── models.py                # Modelos SQLAlchemy
│   └── services/                # Camada de serviços
├── templates/                   # Templates Jinja2
├── static/                      # Assets (AdminLTE, Bootstrap)
├── database/                    # Migrations SQL
├── docker/                      # Docker Compose
└── main.py                      # Entry point
```

---

## Arquitetura de Agentes de IA

### Padrão Principal: Composição Sequencial

Os agentes são classes Python especializadas, orquestradas em pipelines pela camada de serviços. Não há framework de orquestração externo — a composição é feita diretamente em código.

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

---

### Agentes por Domínio

#### Processamento de Documentos (`document_processing/`)

| Agente                         | Responsabilidade                                               |
| ------------------------------ | -------------------------------------------------------------- |
| `AgentDocumentReader`          | Análise técnico-jurídica livre de documentos                   |
| `AgentDocumentExtractor`       | Extração estruturada: número do processo, partes, vara, tipo   |
| `AgentInitialPetitionAnalysis` | Análise de petições iniciais: pedidos, benefícios, fundamentos |

**Fluxo:**
```
Arquivo → FileAgent → DocumentProcessorService (Docling/pdfplumber)
       → AgentDocumentExtractor (FAISS local + LLM)
       → AgentInitialPetitionAnalysis (se petição inicial)
       → KnowledgeIngestionAgent (Qdrant + Meilisearch)
```

#### Base de Conhecimento / RAG (`knowledge_base/`)

| Agente                         | Responsabilidade                                             |
| ------------------------------ | ------------------------------------------------------------ |
| `ContextRetrievalRoutingAgent` | Decide se busca contexto e qual modo (semântico / full-text) |
| `QueryEnhancerAgent`           | Reescreve a pergunta para otimizar busca semântica           |
| `KeywordExtractionAgent`       | Extrai CPF, CNPJ, número de processo para busca textual      |
| `KnowledgeQueryAgent`          | Orquestrador principal: busca + geração de resposta          |
| `KnowledgeIngestionAgent`      | Ingere documentos no Qdrant e Meilisearch                    |

**Fluxo de consulta:**
```
Pergunta do usuário
  → ContextRetrievalRoutingAgent (buscar? semântico ou full-text?)
  → QueryEnhancerAgent OU KeywordExtractionAgent
  → Qdrant (semântico) OU Meilisearch (full-text)
  → KnowledgeQueryAgent (gera resposta com fontes + sugestões)
  → TokenUsageService (rastreia custo)
```

#### Geração de Documentos (`legal_drafting/`)

- **`AgentTextGenerator`**: Gera petições usando OpenAI Assistants API com `file_search` sobre templates DOCX enviados.

#### Classificação FAP (`fap/`)

- **`FapCaseClassifierAgent`**: Classifica razões de contestação de FAP com score de confiança.

---

## Camada de Serviços

| Serviço                          | Responsabilidade                                          |
| -------------------------------- | --------------------------------------------------------- |
| `DocumentProcessorService`       | Conversão de documentos, extração de tabelas, FAISS local |
| `KnowledgeBaseProcessingService` | Orquestra pipeline completo: arquivo → banco de dados     |
| `TokenUsageService`              | Rastreia tokens e calcula custo USD por chamada LLM       |

---

## Variáveis de Ambiente Importantes

```bash
# Modelos LLM
QUERY_MODEL=gpt-4o-mini
KB_ROUTER_MODEL=gpt-5-nano
KB_QUERY_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
VECTOR_SIZE=1536

# Serviços externos
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=knowledge_base
MEILISEARCH_HOST=http://localhost:7700

# Configuração do agente KB
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

- **Blueprints Flask**: cada módulo tem seu próprio Blueprint (`cases_bp`, `documents_bp`, etc.)
- **Saída estruturada**: agentes retornam Pydantic models, não strings livres
- **Degradação graciosa**: todo agente tem fallback (regex, LLM direto sem tools, resposta simplificada)
- **Rastreamento de tokens**: toda chamada LLM deve passar por `TokenUsageService`
- **Tabelas PDF**: lógica de carry-over para células vazias (CNPJ/NIT que se repetem em linhas)
- **Dual vector store**: Qdrant para busca conceitual, Meilisearch para busca por termos exatos (CPF, CNPJ, número de processo)

---

## Inicialização Local

```bash
# Subir serviços de infraestrutura
docker compose -f docker/docker-compose.yml up -d

# Instalar dependências (usa uv)
uv sync

# Rodar aplicação
uv run main.py
# ou
uv run flask run
# ou
uv run gunicorn main:app
```

---

## Domínio Jurídico

Principais conceitos do domínio presentes no código:

- **FAP**: Fator Acidentário de Prevenção — índice que ajusta alíquota previdenciária da empresa
- **Benefício B91/B94**: tipos de benefício previdenciário por acidente de trabalho
- **NIT**: Número de Identificação do Trabalhador
- **Polo ativo/passivo**: partes do processo (autor/réu)
- **Pedidos**: lista de requerimentos da petição inicial
- **DataJud**: API do CNJ para consulta de processos judiciais
- **SGT-TPU**: sistema de tabelas processuais unificadas do CNJ
