# Ingestão de peças-modelo de impugnação em segundo plano

**Data:** 2026-07-28 · **Motivação:** upload e reindexação rodam síncronos na request
(Docling + 2 agentes LLM + embeddings + Qdrant + Meili) e estouram o timeout de
origem da Cloudflare (erro 524, ~100s) — ex.: `/referencias-impugnacao/2/reindexar`.

## Design (aprovado pelo usuário)

Copiar o padrão de background do gerador de documentos (`process_panel.py`,
`_run_generated_document_generation` + rota `/status` + polling de 4s na tela).

1. **Colunas novas** em `impugnacao_reference_models` (migration aditiva
   standalone, mesmo padrão das anteriores):
   - `ingestion_status` VARCHAR(20) DEFAULT 'completed' — `processing` |
     `completed` | `failed` (peças já indexadas permanecem `completed`);
   - `ingestion_error` TEXT.
2. **Worker** `_run_reference_ingestion(app_obj, law_firm_id, ref_id, is_new)`
   no blueprint, rodado em `threading.Thread` daemon com `app_context`:
   processa documento → metadados IA (upload: sempre; reindexação: só backfill
   quando os 3 campos de contexto estão vazios, `trf_region` só se vazio) →
   limpa vetores/chunks antigos → `ingest_file` → grava chunks, contadores,
   `sections_json` → `completed` → sync Meilisearch. Exceção → rollback +
   `failed` + `ingestion_error`; `db.session.remove()` no finally.
3. **Rotas**: upload cria a peça com título provisório (nome do arquivo) e
   status `processing`, dispara a thread e redireciona na hora; reindexar tem
   guard contra duplo disparo (`processing`) e faz o mesmo; rota nova
   `GET /<id>/status` → JSON `{status, chunks_count}`.
4. **Telas**: detalhe ganha painel "Indexando…" (spinner + polling 4s + reload
   ao concluir — mesmo JS do gerador) e estado `failed` com o erro + orientação
   de reindexar; listagem ganha badge Indexando/Falha ao lado do status.

Fora de escopo: fila/worker externo (Celery etc.) — thread daemon é o padrão
corrente do projeto; se o processo morrer no meio, a peça fica `processing` e a
reindexação manual resolve.
