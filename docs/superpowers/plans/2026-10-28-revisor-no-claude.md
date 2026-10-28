# Revisor no Claude — plano de implementação

**Spec:** `docs/superpowers/specs/2026-10-28-revisor-no-claude-design.md`

**Goal:** o Claude revisa a petição na conversa com as instruções do agente do
escritório; o IntellexIA só confere (rascunho saneado) e grava, com o selo
"Feita no Claude". Sai o fluxo do RPI-37 (link de envio, Drive, revisão no
servidor pelo MCP, e-mail).

## Tarefas

1. **Agente**: montagem do prompt de sistema, das mensagens da tarefa e do
   parse do resultado viram métodos de classe sem LLM
   (`montar_prompt_sistema`, `montar_resultado`); o agente passa a usá-los.
   Testes: `test_fap_reviewer_output_contract.py`, `test_fap_review_r02.py`,
   `test_fap_review_finding_sanitizer.py`, `test_fap_review_correction_priority.py`.
2. **Modelo e migrations**: `FapReviewExecution.review_origin`; tabela
   `fap_review_drafts` (`FapReviewDraft`); sai `FapReviewUploadLink`;
   `database/add_fap_review_executions_review_origin_column.py`,
   `database/add_fap_review_drafts_table.py`,
   `database/remove_fap_review_upload_links_table.py` (só roda quando o
   Thiago decidir); sai `database/add_fap_review_upload_links_table.py`.
3. **Sai o RPI-37**: blueprint `fap_review_upload` (+ registro, middleware),
   `fap_review_upload_service`, `envio_arquivo.html`, e-mail
   (`send_revision_finished_email`, template, `notify_user`), `open_file_review`,
   `start_text_review`, `_in_progress_payload`, `gdoc_como`,
   `tests/test_fap_review_envio_arquivo.py`.
4. **Serviço `fap_review_claude_service`**: instruções em partes (≤ 40 mil
   caracteres, corte em fim de linha, preferindo parágrafo), conferência
   (chaves de primeiro nível, avisos, "não pertinente" marcado, rascunho 24 h,
   limpeza dos vencidos), gravação (petição existente/nova, recusas, origem,
   modelo, auditoria, idempotente). Pontos de atenção só de revisões do
   IntellexIA.
5. **MCP**: `revisar_peticao_inicial`/`comparar_versoes_peticao` entregam as
   instruções; `conferir_revisao_peticao` e `gravar_revisao_peticao` novas;
   leitura devolve `origem`.
6. **Regras da origem**: fora da pontuação; triagem "versão final" recusada;
   mudança manual para aprovação recusada a não-admin; selo e botões na tela.
7. **Histórico**: casar achados por semelhança (Jaccard ≥ 0,5, mesma
   categoria, trecho igual vale 1).
8. **Testes** (`tests/test_mcp_fap_review.py` reescrito) e **documentação**
   (manuais, `MCP_CONEXAO.md`, `CLAUDE.md`, nota no topo da spec/plano do RPI-37).
9. **Revisão final** do branch inteiro por revisor novo.
