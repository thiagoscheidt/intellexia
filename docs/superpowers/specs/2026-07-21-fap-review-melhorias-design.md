# Melhorias do Revisor FAP: quadro completo, idade no status, resumo da revisão e timeline

**Data:** 2026-07-21
**Módulo:** `fap_review`
**Origem:** itens 1, 4, 5 e 7 da avaliação do módulo aprovados pelo usuário.

## 1. Quadro completo (todas as petições)

A rota `fap_review.index` remove o `.limit(20)`: lista e kanban passam a mostrar **todas** as petições do escritório, mantendo a ordenação por prioridade (aguardando ajustes → em revisão → aprovadas → demais). Com isso os contadores das colunas do kanban ficam consistentes com os cards de estatística.

- `joinedload` de `latest_revision` e do seu `user` para evitar N+1.
- Chip do cabeçalho "Últimas 20 petições atualizadas" vira "Petições priorizadas por status"; manual atualizado no trecho "20 petições mais prioritárias".

## 2. Idade no status (`status_changed_at`)

`updated_at` muda por qualquer edição, então não serve para medir tempo no status. Nova coluna `status_changed_at` (DateTime, nullable) em `fap_review_petitions`:

- **Migration** `database/add_fap_review_status_changed_at.py` (padrão standalone, idempotente), com backfill `COALESCE(updated_at, created_at)`.
- **Pontos de escrita** (todos os lugares onde `workflow_status` muda): endpoint `petition_update_status` e `sync_petition_after_revision` no serviço (só quando o status efetivamente muda). Na criação, default = agora.
- **Exibição**: a rota calcula `status_age_days` por linha (fallback: `updated_at`/`created_at`). Lista: "· há Xd neste status" na meta. Kanban: chip `⏱ Xd` com tooltip. Destaque âmbar quando `awaiting_adjustments` há 7+ dias.

## 3. Resumo da última revisão no card

A rota extrai de `result_json` da última revisão **concluída** o nº de apontamentos (`findings`) via `load_execution_result_payload` e passa `findings_count` por linha (None sem revisão concluída — nada é exibido).

- Lista e kanban: chip `⚠ N` com tooltip "Apontamentos da última revisão".
- Trade-off aceito: parse de JSON por petição a cada render do index; adequado para centenas de petições. Se pesar, evoluir para coluna denormalizada em `FapReviewExecution`.

## 4. Timeline de alterações no detalhe da petição

Nova seção "Histórico de Alterações" em `petition_detail.html` (abaixo do Histórico de Revisões), alimentada pelo audit log existente:

- Query: `FapReviewAuditLog` do escritório onde `(entity_type='petition' AND entity_id=<id>)` OU `(entity_type='execution' AND entity_id IN <ids das execuções da petição>)`, ordem decrescente, limite 50.
- Exibe: ícone por ação (status, revisão, edição, criação), descrição (`change_description`), usuário e data (`datetime_sp`).
- Nenhum registro novo é criado — o drag do kanban e as trocas manuais já são auditados.

## Fora de escopo

Toque/teclado no drag-and-drop (item 2 da avaliação), overflow do header mobile (item 3), notificações por e-mail, extração de CSS/JS para `static/`.

## Verificação

Extensão do script `tests/test_fap_review_kanban.py` (marcadores) + screenshots via Playwright na porta 5051; migration rodada no SQLite dev; teste manual do fluxo de mudança de status atualizando a idade.
