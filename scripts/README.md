# Scripts

Scripts utilitários e de processamento do IntellexIA. Todos devem ser executados a partir da raiz do projeto com `uv run`.

---

## Scripts de produção

### `classify_fap_benefits.py`

Classifica benefícios da tabela central `benefits` com o tópico de contestação FAP (campo `fap_contestation_topic`), usando o `FAPContestationClassifierAgent`. Suporta processamento paralelo via `--workers`.

```bash
uv run python scripts/classify_fap_benefits.py
uv run python scripts/classify_fap_benefits.py --workers 10
uv run python scripts/classify_fap_benefits.py --law-firm-id 1 --workers 10
uv run python scripts/classify_fap_benefits.py --benefit-id 123
uv run python scripts/classify_fap_benefits.py --force-reclassify --workers 10
uv run python scripts/classify_fap_benefits.py --batch-size 100 --workers 5
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `--batch-size` | `200` | Quantidade de benefícios por commit no banco |
| `--law-firm-id` | — | Restringe a um escritório específico |
| `--benefit-id` | — | Classifica apenas um benefício pelo ID |
| `--force-reclassify` | `false` | Reclassifica mesmo quem já tem tópico salvo |
| `--workers` | `1` | Chamadas LLM simultâneas. Recomendado: 5–10 |

---

### `process_fap_contestation_judgment_reports.py`

Processa relatórios de julgamento de contestação FAP com status `pending` (ou `error` com `--include-errors`), importando os benefícios para a tabela central.

```bash
uv run python scripts/process_fap_contestation_judgment_reports.py
uv run python scripts/process_fap_contestation_judgment_reports.py --batch-size 20
uv run python scripts/process_fap_contestation_judgment_reports.py --report-id 123
uv run python scripts/process_fap_contestation_judgment_reports.py --include-errors
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `--batch-size` | `100` | Máximo de relatórios por execução |
| `--report-id` | — | Processa apenas um relatório pelo ID |
| `--include-errors` | `false` | Reprocessa relatórios com status `error` |

---

### `process_knowledge_base.py`

Processa arquivos pendentes da Base de Conhecimento: extrai texto, gera embeddings e indexa no Qdrant + Meilisearch.

```bash
uv run python scripts/process_knowledge_base.py
uv run python scripts/process_knowledge_base.py --batch-size 20
uv run python scripts/process_knowledge_base.py --file-id 123
uv run python scripts/process_knowledge_base.py --include-errors
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `--batch-size` | `10` | Máximo de arquivos por execução |
| `--file-id` | — | Processa apenas um arquivo pelo ID |
| `--include-errors` | `false` | Reprocessa arquivos com status `error` |

---

### `process_judicial_sentence_analysis.py`

Processa análises de sentenças judiciais pendentes, usando IA para extrair estrutura e fundamentos.

```bash
uv run python scripts/process_judicial_sentence_analysis.py
uv run python scripts/process_judicial_sentence_analysis.py --batch-size 20
uv run python scripts/process_judicial_sentence_analysis.py --process-id 123
uv run python scripts/process_judicial_sentence_analysis.py --include-errors
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `--batch-size` | `10` | Máximo de itens por execução |
| `--process-id` | — | Enfileira e processa sentenças de um processo específico |
| `--include-errors` | `false` | Reprocessa itens com status `error` |

---

### `process_judicial_appeals.py`

Processa recursos judiciais pendentes e os gera usando IA (`AgentAppealGenerator`).

```bash
uv run python scripts/process_judicial_appeals.py
```

Sem argumentos — processa todos os recursos com status `pending`.

---

### `import_courts_from_txt.py`

Importa tribunais e varas de um arquivo JSON para a tabela `courts`. O arquivo JSON de varas unificado já está disponível em `scripts/varas_unificado.json`.

```bash
uv run python scripts/import_courts_from_txt.py scripts/varas_unificado.json --all-law-firms
uv run python scripts/import_courts_from_txt.py scripts/varas_unificado.json --law-firm-id 1
uv run python scripts/import_courts_from_txt.py --all-law-firms
```

| Argumento | Padrão | Descrição |
|---|---|---|
| `arquivo` (posicional) | `scripts/varas_unificado.json` | Caminho para o JSON de varas |
| `--law-firm-id` | — | Importa apenas para um escritório |
| `--all-law-firms` | — | Importa para todos os escritórios cadastrados |

Formato esperado do JSON:
```json
[
  {
    "tribunal": "TRF-3",
    "secao_judiciaria": "Seção Judiciária de São Paulo",
    "subsecao": "Mogi das Cruzes",
    "orgao_julgador": "2ª Vara Federal"
  }
]
```

---

### `unify_lines_file.py`

Utilitário para limpar um arquivo texto: remove linhas em branco e duplicadas, preservando a ordem da primeira ocorrência. Usado para preparar o `varas.txt` → `varas_unificado.json`.

```bash
uv run python scripts/unify_lines_file.py scripts/varas.txt --in-place
uv run python scripts/unify_lines_file.py scripts/varas.txt --output scripts/varas_unificado.txt
```

---

## Scripts de teste (`tests/`)

Scripts para testar agentes e services isoladamente, sem subir o servidor. Úteis durante desenvolvimento.

### `tests/test_document_extractor.py`

Testa o `AgentDocumentExtractor` com um arquivo real da `KnowledgeBase`.

```bash
uv run python scripts/tests/test_document_extractor.py
uv run python scripts/tests/test_document_extractor.py --knowledge-id 123
uv run python scripts/tests/test_document_extractor.py --law-firm-id 1
```

### `tests/test_document_processor_service.py`

Testa o `DocumentProcessorService` com diferentes métodos de extração.

```bash
uv run python scripts/tests/test_document_processor_service.py --knowledge-id 23
uv run python scripts/tests/test_document_processor_service.py --knowledge-id 23 --method markitdown
uv run python scripts/tests/test_document_processor_service.py --knowledge-id 23 --method docling
uv run python scripts/tests/test_document_processor_service.py --knowledge-id 23 --method process
uv run python scripts/tests/test_document_processor_service.py --knowledge-id 23 --method rag --query "sua pergunta aqui"
uv run python scripts/tests/test_document_processor_service.py --file caminho/para/arquivo.pdf --method all
```

| Método | Descrição |
|---|---|
| `markitdown` | Extração via MarkItDown |
| `docling` | Extração via Docling |
| `process` | Pipeline completo de processamento |
| `rag` | Consulta semântica no documento |
| `all` | Todos os métodos acima |

---

## Infraestrutura necessária

Alguns scripts dependem de serviços externos. Suba antes com:

```bash
docker compose -f docker/docker-compose.yml up -d
```

| Script | Qdrant | Meilisearch | OpenAI |
|---|---|---|---|
| `classify_fap_benefits.py` | — | — | ✅ |
| `process_fap_contestation_judgment_reports.py` | ✅ | ✅ | ✅ |
| `process_knowledge_base.py` | ✅ | ✅ | ✅ |
| `process_judicial_sentence_analysis.py` | — | — | ✅ |
| `process_judicial_appeals.py` | — | — | ✅ |
| `import_courts_from_txt.py` | — | — | — |
