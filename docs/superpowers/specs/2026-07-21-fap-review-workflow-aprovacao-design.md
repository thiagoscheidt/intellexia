# Workflow de aprovação do Revisor FAP — triagem persistida, status "Aguardando aprovação" e ações de admin

Data: 2026-07-21 · Status: aprovado pelo usuário (conversa)

## Problema

Hoje o fluxo do Revisor tem lacunas: o "Aprovar Petição" aparece para qualquer
usuário; não há estado entre "usuário terminou de triar os achados" e "admin
aprovou"; o "Marcar como revisado" vive só no `localStorage` (progresso por
navegador, servidor cego); e uma petição aprovada continua aceitando novas
revisões.

## Fluxo aprovado

```
new → in_review ──[usuário concluiu a triagem]──┬→ awaiting_adjustments  "Aguardando ajustes"
                                                │   (vai enviar nova versão → novo ciclo)
                                                └→ awaiting_approval     "Aguardando aprovação"  ← NOVO
                                                        │
                                     [admin] Aprovar ───┴→ ready_for_filing  "Aprovada pelo revisor"
                                     [admin] Devolver p/ ajustes → awaiting_adjustments
[admin] Reabrir petição: ready_for_filing → awaiting_adjustments
```

Mudança de semântica: `awaiting_adjustments` deixa de ser setado automaticamente
quando a IA conclui (passa a `in_review`) e vira decisão humana ("revisei, vou
mandar versão nova"). `derive_petition_workflow_status`: `completed → in_review`.

## Decisões

1. **Triagem persistida no servidor** — nova tabela `fap_review_finding_checks`
   (`execution_id` + `finding_index` únicos, `law_firm_id`, autor, data).
   "Marcar como revisado" chama endpoint próprio; `localStorage` deixa de ser
   fonte. Progresso = checados + não pertinentes (fingerprints já persistidos).
2. **Gate no servidor** — os dois botões de conclusão só aparecem com todos os
   pontos triados, e o endpoint de conclusão revalida antes de mudar status.
   Revisão com zero achados conta como triagem completa.
3. **Botões de conclusão (usuário, status `in_review`)**:
   - "Revisada — enviar nova versão" → `awaiting_adjustments` + redirect para
     Nova Revisão com a petição pré-selecionada.
   - "Versão final — enviar para aprovação" → `awaiting_approval`.
4. **Regra de admin (tela + endpoint, espelhadas)** — exige admin: entrar em
   `ready_for_filing`, sair de `awaiting_approval`, sair de `ready_for_filing`.
   Botões só renderizam para `session.user_role == 'admin'`:
   - "Aprovar Petição" (`awaiting_approval → ready_for_filing`)
   - "Devolver para ajustes" (`awaiting_approval → awaiting_adjustments`)
   - "Reabrir petição" (`ready_for_filing → awaiting_adjustments`)
5. **Trava pós-aprovação** — com status em `ready_for_filing`/`filed`/`archived`,
   "Nova Revisão" some das telas e o POST de criação de revisão recusa.
   Página de detalhes continua acessível a todos (leitura).
6. **Efeitos colaterais** — `PETITION_WORKFLOW_STATUSES` ganha
   `awaiting_approval: "Aguardando aprovação"`; badge própria; contadores e
   ordenação do painel (`awaiting_approval` sobe na fila, é a fila do admin);
   kanban ganha o estado; MCP herda rótulos via service. Auditoria em todas as
   transições.

## Fora de escopo

- Justificativa obrigatória na devolução (opção descartada pelo usuário).
- Restringir a página de detalhes de petição aprovada (continua para todos).
- Notificações por e-mail das transições.

## Testes

Scripts standalone em `tests/` cobrindo: transições permitidas/bloqueadas por
papel, gate de triagem (função pura), derive novo, e render das telas por papel.
