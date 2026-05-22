# TRUNCATE Process Panel + Knowledge Base (MySQL)

Use este script para limpar os dados operacionais do módulo `process_panel` e da `knowledge_base`.

## Atenção

- Este script apaga dados de processos, documentos, eventos, análises e base de conhecimento.
- Não inclui tabelas de configuração (`judicial_phases`, `judicial_document_types`, `judicial_legal_theses`, `knowledge_categories`, `knowledge_tags`).
- Execute no banco correto (ambiente de desenvolvimento/homologação).

```sql
SET FOREIGN_KEY_CHECKS = 0;

-- ================================
-- Knowledge Base / histórico de IA
-- ================================
TRUNCATE TABLE agent_execution_history;
TRUNCATE TABLE agent_token_usage;
TRUNCATE TABLE knowledge_chat_history;
TRUNCATE TABLE knowledge_chat_sessions;
TRUNCATE TABLE knowledge_summaries;
TRUNCATE TABLE knowledge_base;

-- ================================
-- Process Panel (dados de processo)
-- ================================
TRUNCATE TABLE judicial_appeals;
TRUNCATE TABLE judicial_sentence_analysis;

TRUNCATE TABLE judicial_process_cited_benefits;
TRUNCATE TABLE judicial_process_benefit_legal_theses;
TRUNCATE TABLE judicial_process_benefits;

TRUNCATE TABLE judicial_documents;
TRUNCATE TABLE judicial_movements;
TRUNCATE TABLE judicial_process_phase_history;
TRUNCATE TABLE judicial_events;
TRUNCATE TABLE judicial_process_notes;
TRUNCATE TABLE judicial_processes;

SET FOREIGN_KEY_CHECKS = 1;
```
