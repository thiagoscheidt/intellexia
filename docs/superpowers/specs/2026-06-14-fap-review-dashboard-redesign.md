# FAP Review — Redesign do Dashboard

**Data:** 2026-06-14  
**Escopo:** `templates/fap_review/index.html` (dashboard principal `/fap-review/`)  
**Abordagem:** Correção cirúrgica — mesma estrutura, melhorias visuais e de organização dentro do template existente.

---

## Problemas identificados

1. **Stat cards (A)** — rótulos pouco expressivos; sem indicação de urgência no card de "Ajustes"
2. **Botões de ação (B)** — "Nova Revisão" e "Configurações" flutuando entre stat cards e tabela, sem contexto
3. **Tabela de petições (C)**:
   - Sem busca ou filtro por status
   - Todas as linhas têm aparência idêntica, independente de urgência
   - Botões `👁` e `+` sem texto — ação não é clara
   - Coluna "ID" (`#5`) desnecessária (Wrike ID já identifica)
   - Coluna "Revisões" (contagem) e coluna "Atualizado" redundantes com outros dados da linha
4. **Cards de agentes + navegação rápida no rodapé** — informação de baixo valor no dashboard; pertencem à tela de Configurações

---

## Design aprovado

### 1. Botão "Nova Revisão" → cabeçalho da página

O botão primário sai da posição flutuante e vai para o `page_hero`, alinhado à direita do título. Fica sempre visível sem scroll. O botão "Configurações" desaparece do dashboard (acesso via menu lateral ou tela de Configurações).

### 2. Stat cards — ajustes de copy e urgência

| Card | Antes | Depois |
|------|-------|--------|
| Total | "Total · Petições · Revisões 38" | "Total de petições · 38 revisões realizadas" |
| Ajustes | label cinza, número preto | label vermelho "⚠ Aguardando ajustes", número vermelho, subtítulo "Requerem atenção agora" |
| Em revisão | sem subtítulo | subtítulo "Processando" |
| Prontas | "Para seguir · X%" | "Para seguir · X% do total" |

Borda esquerda dos cards: mantida. Fonte do valor: ligeiramente maior (`1.8rem`).

### 3. Tabela de petições — reestruturação completa

#### Colunas removidas
- `#ID` — substituído pelo Wrike ID como identificador primário
- `Revisões` (contagem isolada) — número da revisão vai inline no subtítulo da linha
- `Atualizado` (coluna separada) — data vai inline no subtítulo da linha
- `Última Revisão` (status separado) — informação fundida no subtítulo da linha

#### Colunas novas / reorganizadas
| Coluna | Conteúdo | Largura |
|--------|----------|---------|
| **Id Wrike** | Chip colorido (paleta hash atual) com logo Wrike + identificador. **Sempre visível.** | `200px` |
| **Petição** | Título em destaque + subtítulo: `Rx · DD/MM/AAAA` | `flex: 1` |
| **Status** | Badge pill colorido (workflow status) | `140px` |
| **Ações** | Botões `Histórico` (outline) + `Revisar` (primary) | `auto` |

#### Codificação visual por status (borda esquerda + fundo sutil)
| Status | Borda esquerda | Fundo da linha |
|--------|---------------|----------------|
| `awaiting_adjustments` | `#dc3545` (4px) | `rgba(220,53,69,.04)` |
| `in_review` / `new` | `#ffc107` (4px) | `rgba(255,193,7,.04)` |
| `ready_for_filing` | `#198754` (4px) | transparente |
| `filed` | `#0d6efd` (4px) | transparente |
| `archived` | `#6c757d` (2px) | `rgba(108,117,125,.03)` |

**Petições `awaiting_adjustments` aparecem no topo da lista** (ordenação: status urgente primeiro, depois `updated_at desc`).

#### Ordenação no backend (`index()`)
```python
# Ordem: ajustes primeiro, depois updated_at desc
from sqlalchemy import case

priority_order = case(
    (FapReviewPetition.workflow_status == 'awaiting_adjustments', 0),
    (FapReviewPetition.workflow_status.in_(['new', 'in_review']), 1),
    (FapReviewPetition.workflow_status == 'ready_for_filing', 2),
    else_=3
)

petitions = FapReviewPetition.query.filter_by(
    law_firm_id=law_firm_id,
).order_by(
    priority_order,
    FapReviewPetition.updated_at.desc(),
).limit(20).all()
```

#### Busca e filtros (client-side JavaScript)
- **Campo de busca:** filtra por `petition.title` e `petition.office_document_identifier` (case-insensitive, em tempo real)
- **Pills de filtro:** "Todos", "⚠ Ajustes (N)", "⧗ Em revisão (N)", "✓ Prontas (N)", "Outras"
- Contagens nas pills calculadas a partir dos dados já no DOM (sem request adicional)
- Filtro ativo: pill com `background: #0d6efd; color: white`
- Filtro inativo: pill `outline` com cor do status

#### Rodapé da tabela
- Texto "Exibindo X de Y petições" quando há filtro ativo
- Link "Ver todas →" quando existem mais de 20 petições (ainda não implementado — pode ser placeholder)

### 4. Seções removidas do dashboard

- **Cards "Agente Revisor" / "Agente de Treinamento"** — removidos
- **Bloco de navegação rápida** (4 botões no rodapé) — removido

O acesso a Configurações, Treinamento e Auditoria continua disponível via menu lateral existente.

---

## Arquivos modificados

| Arquivo | Tipo de mudança |
|---------|----------------|
| `templates/fap_review/index.html` | Refatoração do template inteiro |
| `app/blueprints/fap_review.py` | Ajuste da query de `index()` para ordenação por prioridade |

Nenhum novo arquivo criado. Nenhuma mudança em outros templates.

---

## Fora do escopo

- Tela `/fap-review/revision` — não alterada neste ciclo
- Paginação real da tabela — link "Ver todas" é placeholder
- Filtro server-side — filtros são client-side neste ciclo
- Qualquer mudança em `revision_result.html`, `petition_detail.html`, `training.html`, `settings.html`
