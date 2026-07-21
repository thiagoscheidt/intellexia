# Visualização Kanban no Revisor FAP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar visão kanban com toggle lista/kanban e drag-and-drop de status à tela `/fap-review/`, reusando o endpoint existente de mudança de status.

**Architecture:** Tudo em `templates/fap_review/index.html` (CSS local, HTML Jinja, JS nativo). O kanban é um contêiner irmão da lista, montado por Jinja a partir dos mesmos `petition_rows`; drag-and-drop HTML5 chama `POST /fap-review/petitions/<id>/status` (endpoint existente, com auditoria) com atualização otimista e rollback em erro. Nenhuma mudança em modelo, serviço, rota ou migration.

**Tech Stack:** Flask/Jinja2, Bootstrap 5 (classes já usadas na página), JS nativo (padrão do projeto — sem libs novas).

**Spec:** `docs/superpowers/specs/2026-07-21-fap-review-kanban-design.md`

## Global Constraints

- Nenhuma dependência frontend nova (drag-and-drop HTML5 nativo).
- Nenhuma rota/modelo/migration novos; reusar `fap_review.petition_update_status`.
- A visão lista atual permanece funcional e visualmente intocada.
- Rótulos de status vêm de `PETITION_WORKFLOW_STATUSES`: `new`=Nova, `in_review`=Em revisão, `awaiting_adjustments`=Aguardando ajustes, `ready_for_filing`=Aprovada pelo revisor, `filed`=Processo iniciado, `archived`=Arquivada.
- Cores por status (paridade com badges/pílulas existentes): new `#6c757d`, in_review `#ffc107`, awaiting_adjustments `#dc3545`, ready_for_filing `#198754`, filed `#0d6efd`, archived `#343a40`.
- Não há framework de testes: verificação via script standalone `tests/test_fap_review_kanban.py` (padrão do projeto: `from main import app` + `test_client()`) + checagem manual no navegador.

---

### Task 1: Script de verificação + toggle Lista/Kanban

**Files:**
- Create: `tests/test_fap_review_kanban.py`
- Modify: `templates/fap_review/index.html` (header da toolbar ~linha 583; wrapper da lista ~linhas 610-734; bloco `extra_js` ~linha 741; bloco `extra_css`)

**Interfaces:**
- Produces: contêiner `#kanbanBoard` (vazio nesta task, populado na Task 2), wrapper `#petitionListView` em volta da visão lista, botões `.view-toggle-btn[data-view]`, função JS `setView(view)` e chave localStorage `fapReviewPetitionView`.

- [ ] **Step 1: Escrever o script de verificação (falhando)**

```python
"""Verificação da visão kanban do Revisor FAP.

Script standalone (padrão do projeto): renderiza /fap-review/ com um usuário
real do banco de dev e confere os marcadores da visão kanban no HTML.

Uso: uv run python tests/test_fap_review_kanban.py
"""
from main import app
from app.models import User

MARKERS = [
    'id="petitionListView"',
    'id="kanbanBoard"',
    'data-view="list"',
    'data-view="kanban"',
    "localStorage.getItem('fapReviewPetitionView')",
]


def run():
    with app.app_context():
        user = (User.query.filter_by(role='admin').first()
                or User.query.first())
        assert user is not None, 'Nenhum usuário no banco de dev'

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['law_firm_id'] = user.law_firm_id

        resp = client.get('/fap-review/')
        assert resp.status_code == 200, f'HTTP {resp.status_code}'
        html = resp.get_data(as_text=True)

        if 'Nenhuma petição registrada ainda' in html:
            print('AVISO: banco sem petições — só o toggle é verificável.')

        missing = [m for m in MARKERS if m not in html]
        assert not missing, f'Marcadores ausentes: {missing}'
        print(f'OK — {len(MARKERS)} marcadores encontrados em /fap-review/')


if __name__ == '__main__':
    run()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run python tests/test_fap_review_kanban.py`
Expected: `AssertionError: Marcadores ausentes: [...]` (todos os 5).

- [ ] **Step 3: Adicionar botões de toggle na toolbar**

Em `index.html`, na `petition-toolbar` (após as pílulas, ~linha 606, antes do `</div>` da toolbar), adicionar:

```html
<div class="view-toggle ms-auto" id="viewToggle" role="group" aria-label="Modo de exibição">
    <button type="button" class="view-toggle-btn active" data-view="list" title="Visão em lista">
        <i class="bi bi-list-ul"></i> Lista
    </button>
    <button type="button" class="view-toggle-btn" data-view="kanban" title="Visão kanban">
        <i class="bi bi-kanban"></i> Kanban
    </button>
</div>
```

- [ ] **Step 4: Envolver a visão lista e criar o contêiner kanban**

Ainda em `index.html`, dentro do `{% if petition_rows %}`: envolver o bloco existente — `petition-list-header` + `#petitionList` + `#petitionEmptyState` + rodapé `#petitionCount` (linhas ~611-727) — em um wrapper, e criar o irmão kanban vazio logo após:

```html
{% if petition_rows %}
<div id="petitionListView">
    <!-- (conteúdo existente inalterado: header, lista, empty state, rodapé) -->
</div>

<!-- Visão kanban (populada na Task 2) -->
<div class="kanban-board" id="kanbanBoard" style="display:none;"></div>
{% else %}
```

- [ ] **Step 5: CSS do toggle**

No bloco `extra_css` (junto aos estilos de `.filter-pill`):

```css
/* ── Toggle lista/kanban ─────────────────────────────── */
.view-toggle {
    display: inline-flex;
    border: 1px solid var(--fr-border);
    border-radius: 999px;
    overflow: hidden;
    flex-shrink: 0;
}

.view-toggle-btn {
    border: 0;
    background: transparent;
    padding: .3rem .8rem;
    font-size: .8rem;
    font-weight: 600;
    color: var(--fr-slate-500);
    cursor: pointer;
    transition: background .15s ease, color .15s ease;
}

.view-toggle-btn.active {
    background: var(--fr-slate-900);
    color: #fff;
}
```

- [ ] **Step 6: JS do toggle com persistência**

No `extra_js`, dentro do `DOMContentLoaded` existente (após o bloco de busca/filtro):

```javascript
// ── Toggle lista/kanban ───────────────────────────────
const VIEW_STORAGE_KEY = 'fapReviewPetitionView';
const viewButtons = document.querySelectorAll('.view-toggle-btn');
const listView = document.getElementById('petitionListView');
const kanbanBoard = document.getElementById('kanbanBoard');

function setView(view) {
    if (!listView || !kanbanBoard) return;
    const isKanban = view === 'kanban';
    listView.style.display = isKanban ? 'none' : '';
    kanbanBoard.style.display = isKanban ? '' : 'none';
    // As colunas já agrupam por status: pílulas só fazem sentido na lista.
    filterPills.forEach(function (p) { p.style.display = isKanban ? 'none' : ''; });
    viewButtons.forEach(function (b) {
        b.classList.toggle('active', b.dataset.view === view);
    });
    try { localStorage.setItem(VIEW_STORAGE_KEY, view); } catch (e) { /* modo privado */ }
    applyFilters();
}

viewButtons.forEach(function (btn) {
    btn.addEventListener('click', function () { setView(this.dataset.view); });
});

let savedView = 'list';
try { savedView = localStorage.getItem('fapReviewPetitionView') || 'list'; } catch (e) { /* modo privado */ }
if (savedView === 'kanban') setView('kanban');
```

- [ ] **Step 7: Rodar o script e confirmar que passa**

Run: `uv run python tests/test_fap_review_kanban.py`
Expected: `OK — 5 marcadores encontrados em /fap-review/`

- [ ] **Step 8: Commit**

```bash
git add templates/fap_review/index.html tests/test_fap_review_kanban.py
git commit -m "feat(fap-review): toggle lista/kanban na tela de petições"
```

---

### Task 2: Colunas e cards do kanban (Jinja)

**Files:**
- Modify: `templates/fap_review/index.html` (`#kanbanBoard` criado na Task 1; blocos `extra_css` e `extra_js`)
- Modify: `tests/test_fap_review_kanban.py` (novos marcadores)

**Interfaces:**
- Consumes: `#kanbanBoard` e `setView()` da Task 1; `petition_rows` já enviados pela rota.
- Produces: `.kanban-col[data-status]` com `.kanban-col-count` e `.kanban-col-body`; `.kanban-card[draggable][data-petition-id][data-status-url][data-search]` (a Task 3 depende exatamente desses atributos); coluna `archived` com classe `kanban-col-archived collapsed` e toggle de expansão.

- [ ] **Step 1: Ampliar o script de verificação (falhando)**

Em `tests/test_fap_review_kanban.py`, acrescentar à lista `MARKERS`:

```python
    'class="kanban-col',
    'data-status="new"',
    'data-status="archived"',
    'kanban-col-archived',
    'class="kanban-card"',
    'data-status-url=',
]
```

Run: `uv run python tests/test_fap_review_kanban.py`
Expected: FAIL — marcadores novos ausentes (se o banco não tiver petições, os marcadores de card não aparecem; o aviso do script indica isso).

- [ ] **Step 2: Renderizar colunas e cards via Jinja**

Substituir o `#kanbanBoard` vazio por:

```jinja
<!-- Visão kanban -->
<div class="kanban-board-wrap" id="kanbanBoardWrap" style="display:none;">
    <div id="kanbanError" class="alert alert-danger py-2 px-3 mx-3 mt-3 mb-0" style="display:none;"></div>
    <div class="kanban-board" id="kanbanBoard">
        {% set kanban_columns = [
            ('new', 'Nova', '#6c757d'),
            ('in_review', 'Em revisão', '#ffc107'),
            ('awaiting_adjustments', 'Aguardando ajustes', '#dc3545'),
            ('ready_for_filing', 'Aprovada pelo revisor', '#198754'),
            ('filed', 'Processo iniciado', '#0d6efd'),
            ('archived', 'Arquivada', '#343a40'),
        ] %}
        {% for status_key, status_label, status_color in kanban_columns %}
        {% set col_rows = petition_rows | selectattr('petition.workflow_status', 'equalto', status_key) | list %}
        <div class="kanban-col{% if status_key == 'archived' %} kanban-col-archived collapsed{% endif %}"
            data-status="{{ status_key }}" style="--col-color: {{ status_color }};">
            <div class="kanban-col-header">
                <span class="kanban-col-dot"></span>
                <span class="kanban-col-title">{{ status_label }}</span>
                <span class="kanban-col-count">{{ col_rows|length }}</span>
                {% if status_key == 'archived' %}
                <i class="bi bi-chevron-down kanban-col-chevron"></i>
                {% endif %}
            </div>
            <div class="kanban-col-body">
                <div class="kanban-col-empty">Sem petições</div>
                {% for row in col_rows %}
                {% set petition = row.petition %}
                {% set latest_revision = row.latest_revision %}
                {% set latest_reviewer_name = row.latest_reviewer_name %}
                <div class="kanban-card" draggable="true"
                    data-petition-id="{{ petition.id }}"
                    data-status-url="{{ url_for('fap_review.petition_update_status', petition_id=petition.id) }}"
                    data-search="{{ (petition.title ~ ' ' ~ (petition.office_document_identifier or '') ~ ' ' ~ (latest_reviewer_name or ''))|lower }}">
                    <a class="kanban-card-title"
                        href="{{ url_for('fap_review.petition_detail', petition_id=petition.id) }}">{{ petition.title }}</a>
                    <div class="kanban-card-meta">
                        {% if petition.office_document_identifier %}
                        <span class="kanban-chip" title="Id Wrike">{{ petition.office_document_identifier }}</span>
                        {% endif %}
                        {% if latest_revision %}<span>R{{ latest_revision.revision_number or '?' }}</span>{% endif %}
                        <span>{{ (petition.last_reviewed_at or petition.updated_at or petition.created_at).strftime('%d/%m/%Y') }}</span>
                    </div>
                    <div class="kanban-card-footer">
                        {% if latest_reviewer_name %}
                        <span class="pr-reviewer-avatar" title="{{ latest_reviewer_name }}">{{ latest_reviewer_name[:1]|upper }}</span>
                        {% else %}
                        <span class="kanban-card-noreviewer">Sem revisão</span>
                        {% endif %}
                        <span class="kanban-card-actions">
                            {% if latest_revision %}
                            <a href="{{ url_for('fap_review.revision_result', execution_id=latest_revision.id) }}"
                                class="btn btn-sm btn-outline-primary" title="Última Revisão"
                                target="_blank" rel="noopener noreferrer"><i class="bi bi-box-arrow-up-right"></i></a>
                            {% endif %}
                            <a href="{{ url_for('fap_review.revision', petition_id=petition.id) }}"
                                class="btn btn-sm btn-primary" title="Nova Revisão"><i class="bi bi-plus-circle"></i></a>
                        </span>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endfor %}
    </div>
</div>
```

Observação: como o wrapper mudou de `#kanbanBoard` para `#kanbanBoardWrap`, atualizar no JS da Task 1: `const kanbanBoard = document.getElementById('kanbanBoardWrap');` (a variável continua controlando o display do bloco todo).

- [ ] **Step 3: CSS das colunas e cards**

```css
/* ── Kanban ──────────────────────────────────────────── */
.kanban-board {
    display: flex;
    gap: .75rem;
    align-items: flex-start;
    padding: 1rem;
    overflow-x: auto;
}

.kanban-col {
    flex: 0 0 250px;
    max-width: 250px;
    background: var(--bs-secondary-bg);
    border: 1px solid var(--fr-border);
    border-top: 3px solid var(--col-color);
    border-radius: .6rem;
    display: flex;
    flex-direction: column;
}

.kanban-col-header {
    display: flex;
    align-items: center;
    gap: .45rem;
    padding: .55rem .7rem;
    font-size: .8rem;
    font-weight: 700;
    color: var(--fr-slate-700);
}

.kanban-col-dot {
    width: .55rem;
    height: .55rem;
    border-radius: 50%;
    background: var(--col-color);
    flex-shrink: 0;
}

.kanban-col-title {
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.kanban-col-count {
    background: rgba(21, 37, 53, .08);
    border-radius: 999px;
    padding: 0 .5rem;
    font-size: .72rem;
}

.kanban-col-body {
    display: flex;
    flex-direction: column;
    gap: .5rem;
    padding: .5rem;
    overflow-y: auto;
    max-height: 62vh;
    min-height: 3rem;
}

.kanban-col-empty {
    border: 1px dashed var(--fr-border);
    border-radius: .5rem;
    padding: .8rem;
    text-align: center;
    font-size: .75rem;
    color: var(--fr-slate-500);
}

.kanban-col-body:has(.kanban-card) .kanban-col-empty { display: none; }

.kanban-card {
    background: var(--bs-body-bg);
    border: 1px solid var(--fr-border);
    border-left: 3px solid var(--col-color);
    border-radius: .5rem;
    padding: .6rem .7rem;
    cursor: grab;
    box-shadow: 0 1px 3px rgba(21, 37, 53, .06);
}

.kanban-card.dragging { opacity: .45; cursor: grabbing; }

.kanban-card-title {
    display: block;
    font-size: .82rem;
    font-weight: 600;
    color: var(--fr-slate-900);
    text-decoration: none;
    margin-bottom: .35rem;
}

.kanban-card-title:hover { text-decoration: underline; }

.kanban-card-meta {
    display: flex;
    flex-wrap: wrap;
    gap: .4rem;
    align-items: center;
    font-size: .72rem;
    color: var(--fr-slate-500);
    margin-bottom: .45rem;
}

.kanban-chip {
    background: rgba(21, 37, 53, .06);
    border-radius: .35rem;
    padding: 0 .35rem;
    font-weight: 600;
    max-width: 9rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.kanban-card-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: .4rem;
}

.kanban-card-noreviewer { font-size: .72rem; color: var(--fr-slate-500); font-style: italic; }

.kanban-card-actions { display: inline-flex; gap: .25rem; }

.kanban-card-actions .btn { padding: .1rem .4rem; font-size: .72rem; }

/* Coluna Arquivada recolhida: só o cabeçalho, na vertical */
.kanban-col-archived .kanban-col-header { cursor: pointer; }

.kanban-col-archived.collapsed { flex-basis: 3rem; max-width: 3rem; }

.kanban-col-archived.collapsed .kanban-col-body { display: none; }

.kanban-col-archived.collapsed .kanban-col-header {
    writing-mode: vertical-rl;
    padding: .7rem .4rem;
}

.kanban-col-archived.collapsed .kanban-col-chevron { transform: rotate(-90deg); }

@media (max-width: 767.98px) {
    .kanban-col { flex-basis: 78vw; max-width: 78vw; }
    .kanban-col-archived.collapsed { flex-basis: 3rem; max-width: 3rem; }
}
```

- [ ] **Step 4: JS — expandir/recolher Arquivada**

No `DOMContentLoaded`:

```javascript
// ── Coluna Arquivada recolhida ────────────────────────
document.querySelectorAll('.kanban-col-archived .kanban-col-header').forEach(function (header) {
    header.addEventListener('click', function () {
        header.closest('.kanban-col').classList.toggle('collapsed');
    });
});
```

- [ ] **Step 5: Integrar busca à visão kanban**

Em `applyFilters()` (JS existente), após o loop de `rows`, acrescentar:

```javascript
document.querySelectorAll('.kanban-card').forEach(function (card) {
    const matches = !term || (card.dataset.search || '').includes(term);
    card.style.display = matches ? '' : 'none';
});
```

- [ ] **Step 6: Rodar o script e confirmar que passa**

Run: `uv run python tests/test_fap_review_kanban.py`
Expected: `OK — 11 marcadores encontrados em /fap-review/`

- [ ] **Step 7: Verificação visual**

Subir `uv run python main.py`, abrir `/fap-review/`, alternar para Kanban: 5 colunas + Arquivada recolhida à direita; contadores corretos; busca filtra cards; clique no título abre o detalhe; Arquivada expande/recolhe ao clicar no cabeçalho; em janela estreita o quadro rola horizontalmente.

- [ ] **Step 8: Commit**

```bash
git add templates/fap_review/index.html tests/test_fap_review_kanban.py
git commit -m "feat(fap-review): colunas e cards da visão kanban"
```

---

### Task 3: Drag-and-drop com atualização otimista e rollback

**Files:**
- Modify: `templates/fap_review/index.html` (linha ~647: `petition-row` ganha `data-petition-id`; blocos `extra_css` e `extra_js`)
- Modify: `tests/test_fap_review_kanban.py` (novos marcadores)

**Interfaces:**
- Consumes: `.kanban-card[data-petition-id][data-status-url]`, `.kanban-col[data-status]`, `.kanban-col-count`, `#kanbanError` (Task 2); endpoint `POST /fap-review/petitions/<id>/status` com payload `{"workflow_status": "<código>"}` (resposta `{"success": true, ...}` ou erro com `{"error": "..."}`).
- Produces: sincronização da visão lista via `.petition-row[data-petition-id]` (badge, cor da borda e `data-status`).

- [ ] **Step 1: Ampliar o script de verificação (falhando)**

Acrescentar à lista `MARKERS`:

```python
    'data-petition-id=',
    'function moveCard',
    'STATUS_BADGES',
]
```

Run: `uv run python tests/test_fap_review_kanban.py`
Expected: FAIL — 3 marcadores novos ausentes.

- [ ] **Step 2: Adicionar `data-petition-id` à linha da lista**

Na `div.petition-row` (~linha 647), acrescentar o atributo:

```html
<div class="petition-row"
    style="background: {{ row_bg }}; border-left: {{ row_border_width }} solid {{ row_border_color }};"
    data-petition-id="{{ petition.id }}"
    data-status="{{ petition.workflow_status }}"
    data-search="...">
```

- [ ] **Step 3: JS de drag-and-drop**

No `DOMContentLoaded`:

```javascript
// ── Drag-and-drop do kanban ───────────────────────────
// Espelho de _build_petition_status_badge + cores das linhas da lista.
const STATUS_BADGES = {
    new: { label: 'Nova', cls: 'secondary', icon: 'bi bi-plus-circle', border: '#6c757d', bg: 'rgba(255,193,7,.04)', width: '4px' },
    in_review: { label: 'Em revisão', cls: 'warning', icon: 'bi bi-hourglass-split', border: '#ffc107', bg: 'rgba(255,193,7,.04)', width: '4px' },
    awaiting_adjustments: { label: 'Aguardando ajustes', cls: 'danger', icon: 'bi bi-pencil-square', border: '#dc3545', bg: 'rgba(220,53,69,.04)', width: '4px' },
    ready_for_filing: { label: 'Aprovada pelo revisor', cls: 'success', icon: 'bi bi-check-circle', border: '#198754', bg: 'transparent', width: '4px' },
    filed: { label: 'Processo iniciado', cls: 'primary', icon: 'bi bi-send-check', border: '#0d6efd', bg: 'transparent', width: '4px' },
    archived: { label: 'Arquivada', cls: 'dark', icon: 'bi bi-archive', border: '#6c757d', bg: 'rgba(108,117,125,.02)', width: '2px' },
};

const kanbanError = document.getElementById('kanbanError');
let draggedCard = null;

function showKanbanError(message) {
    if (!kanbanError) return;
    kanbanError.textContent = message;
    kanbanError.style.display = '';
    setTimeout(function () { kanbanError.style.display = 'none'; }, 6000);
}

function updateColumnCounts() {
    document.querySelectorAll('.kanban-col').forEach(function (col) {
        const count = col.querySelectorAll('.kanban-card').length;
        const badge = col.querySelector('.kanban-col-count');
        if (badge) badge.textContent = count;
    });
}

function updatePillCounts() {
    // Recalcula os contadores das pílulas a partir das linhas da lista.
    const statuses = Array.from(document.querySelectorAll('.petition-row'))
        .map(function (r) { return r.dataset.status || ''; });
    const counts = {
        all: statuses.length,
        awaiting_adjustments: statuses.filter(function (s) { return s === 'awaiting_adjustments'; }).length,
        in_review: statuses.filter(function (s) { return s === 'in_review' || s === 'new'; }).length,
        ready_for_filing: statuses.filter(function (s) { return s === 'ready_for_filing'; }).length,
        others: statuses.filter(function (s) { return s === 'filed' || s === 'archived'; }).length,
    };
    filterPills.forEach(function (pill) {
        const key = pill.dataset.filter;
        if (!(key in counts)) return;
        pill.innerHTML = pill.innerHTML.replace(/\(\d+\)/, '(' + counts[key] + ')');
    });
}

function syncListRow(petitionId, newStatus) {
    const row = document.querySelector('.petition-row[data-petition-id="' + petitionId + '"]');
    const info = STATUS_BADGES[newStatus];
    if (!row || !info) return;
    row.dataset.status = newStatus;
    row.style.borderLeft = info.width + ' solid ' + info.border;
    row.style.background = info.bg;
    const badge = row.querySelector('.pr-status .badge');
    if (badge) {
        badge.className = 'badge rounded-pill bg-' + info.cls + '-subtle text-' + info.cls +
            '-emphasis border border-' + info.cls + '-subtle';
        badge.innerHTML = '<i class="' + info.icon + ' me-1"></i> ' + info.label;
    }
}

async function moveCard(card, targetCol) {
    const sourceBody = card.parentElement;
    const sourceCol = sourceBody.closest('.kanban-col');
    if (sourceCol === targetCol) return;

    const oldStatus = sourceCol.dataset.status;
    const newStatus = targetCol.dataset.status;
    const nextSibling = card.nextElementSibling;

    // Otimista: move já; desfaz se a API falhar.
    targetCol.querySelector('.kanban-col-body').appendChild(card);
    updateColumnCounts();
    syncListRow(card.dataset.petitionId, newStatus);
    updatePillCounts();

    try {
        const resp = await fetch(card.dataset.statusUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workflow_status: newStatus }),
        });
        if (!resp.ok) {
            const payload = await resp.json().catch(function () { return {}; });
            throw new Error(payload.error || 'Não foi possível atualizar o status da petição.');
        }
    } catch (err) {
        sourceBody.insertBefore(card, nextSibling);
        updateColumnCounts();
        syncListRow(card.dataset.petitionId, oldStatus);
        updatePillCounts();
        showKanbanError(err.message || 'Falha de rede ao atualizar o status.');
    }
}

document.querySelectorAll('.kanban-card').forEach(function (card) {
    card.addEventListener('dragstart', function (e) {
        draggedCard = card;
        card.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
    });
    card.addEventListener('dragend', function () {
        card.classList.remove('dragging');
        draggedCard = null;
        document.querySelectorAll('.kanban-col.drag-over').forEach(function (c) {
            c.classList.remove('drag-over');
        });
    });
});

document.querySelectorAll('.kanban-col').forEach(function (col) {
    col.addEventListener('dragover', function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        col.classList.add('drag-over');
    });
    col.addEventListener('dragleave', function (e) {
        if (!col.contains(e.relatedTarget)) col.classList.remove('drag-over');
    });
    col.addEventListener('drop', function (e) {
        e.preventDefault();
        col.classList.remove('drag-over');
        if (draggedCard) moveCard(draggedCard, col);
    });
});
```

- [ ] **Step 4: CSS do realce de drop**

```css
.kanban-col.drag-over {
    border-color: var(--col-color);
    box-shadow: 0 0 0 2px var(--col-color);
}
```

- [ ] **Step 5: Rodar o script e confirmar que passa**

Run: `uv run python tests/test_fap_review_kanban.py`
Expected: `OK — 14 marcadores encontrados em /fap-review/`

- [ ] **Step 6: Verificação manual do drag-and-drop**

Com o app rodando: arrastar um card entre colunas (inclusive soltar sobre o cabeçalho da Arquivada recolhida) → card muda, contadores atualizam; recarregar a página → status persistiu; voltar para a visão Lista sem recarregar → badge/cor da linha refletem o novo status; conferir registro em `/fap-review/audit-logs`; simular falha (parar o servidor e arrastar) → card volta + mensagem de erro aparece.

- [ ] **Step 7: Commit**

```bash
git add templates/fap_review/index.html tests/test_fap_review_kanban.py
git commit -m "feat(fap-review): drag-and-drop de status na visão kanban"
```

---

### Task 4: Manual do usuário

**Files:**
- Modify: `docs/MANUAL_REVISOR_PETICOES.md`

**Interfaces:**
- Consumes: comportamento final das Tasks 1-3. A página `/docs/manuais` e o assistente "pergunte ao manual" leem este `.md` em runtime — nada além do markdown precisa mudar.

- [ ] **Step 1: Documentar a visão kanban**

Localizar a seção do manual que descreve a tela de petições em acompanhamento (`grep -n "Petições" docs/MANUAL_REVISOR_PETICOES.md`) e acrescentar, no ponto onde a listagem é descrita:

```markdown
### Visão kanban

Além da lista, a tela oferece uma **visão kanban**: use o seletor **Lista / Kanban** na barra de filtros. Cada coluna corresponde a um status da petição (Nova, Em revisão, Aguardando ajustes, Aprovada pelo revisor, Processo iniciado), e a coluna **Arquivada** fica recolhida à direita — clique no cabeçalho para expandi-la.

- **Arraste um card** para outra coluna para mudar o status da petição — o efeito é o mesmo da troca manual de status na tela da petição, inclusive no registro de auditoria.
- A **busca** filtra os cards normalmente; a preferência de visão fica salva no navegador.
- Se a mudança de status falhar (por exemplo, sem conexão), o card volta para a coluna original e um aviso é exibido.
```

Ajustar o texto ao redor se o manual descrever a listagem como única forma de acompanhamento.

- [ ] **Step 2: Verificar renderização do manual**

Run: `uv run python -c "from app.services.manual_renderer import *; print('render ok')"` e abrir `/docs/manuais` no navegador para conferir a nova seção.
Expected: seção aparece com formatação correta (o índice lateral é gerado dos `##`; `###` não entra no índice — ok).

- [ ] **Step 3: Commit**

```bash
git add docs/MANUAL_REVISOR_PETICOES.md
git commit -m "docs(manual): visão kanban do Revisor de Petições"
```
