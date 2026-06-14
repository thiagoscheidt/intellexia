# FAP Review Dashboard Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Melhorar visualmente o dashboard `/fap-review/` adicionando busca, filtros por status, codificação visual de urgência nas linhas e botões de ação com texto claro.

**Architecture:** Todas as mudanças ficam em dois arquivos: o template `index.html` (HTML + CSS + JS inline) e a rota `index()` no blueprint (ajuste na ordenação da query). Filtros e busca são client-side (sem novo endpoint). Nenhum novo arquivo é criado.

**Tech Stack:** Flask/Jinja2, Bootstrap 5, Bootstrap Icons, SQLAlchemy, JavaScript vanilla.

---

## Arquivos modificados

| Arquivo | O que muda |
|---------|-----------|
| `app/blueprints/fap_review.py` | Query de `index()`: ordenação por prioridade de status |
| `templates/fap_review/index.html` | Refatoração completa do template |

---

## Task 1: Atualizar ordenação da query no backend

**Files:**
- Modify: `app/blueprints/fap_review.py:24` (import) e `:841-846` (query)

- [ ] **Step 1.1: Adicionar `case` ao import do SQLAlchemy**

Linha 24 atual:
```python
from sqlalchemy import and_, func
```
Substituir por:
```python
from sqlalchemy import and_, func, case
```

- [ ] **Step 1.2: Substituir a query de petições em `index()`**

Localizar o bloco nas linhas 841–846:
```python
    petitions = FapReviewPetition.query.filter_by(
        law_firm_id=law_firm_id,
    ).order_by(
        FapReviewPetition.updated_at.desc(),
        FapReviewPetition.id.desc(),
    ).limit(20).all()
```
Substituir por:
```python
    _priority_order = case(
        (FapReviewPetition.workflow_status == 'awaiting_adjustments', 0),
        (FapReviewPetition.workflow_status.in_(['new', 'in_review']), 1),
        (FapReviewPetition.workflow_status == 'ready_for_filing', 2),
        else_=3
    )

    petitions = FapReviewPetition.query.filter_by(
        law_firm_id=law_firm_id,
    ).order_by(
        _priority_order,
        FapReviewPetition.updated_at.desc(),
        FapReviewPetition.id.desc(),
    ).limit(20).all()
```

- [ ] **Step 1.3: Verificar que a aplicação inicia sem erro**

```bash
uv run python main.py
```
Esperado: servidor sobe sem traceback. Abrir `http://localhost:5001/fap-review/` e confirmar que a página carrega.

- [ ] **Step 1.4: Commit**

```bash
git add app/blueprints/fap_review.py
git commit -m "feat(fap-review): ordenar petições no dashboard por prioridade de status"
```

---

## Task 2: Substituir o bloco `{% block extra_css %}` em `index.html`

O template atual tem ~170 linhas de CSS. Vamos substituir completamente pelo novo conjunto de estilos que suporta o novo layout de lista.

**Files:**
- Modify: `templates/fap_review/index.html` (bloco `extra_css`)

- [ ] **Step 2.1: Substituir todo o `{% block extra_css %}` pelo novo CSS**

Localizar o bloco que começa em `{% block extra_css %}` (linha 9) e termina em `{% endblock %}` (linha 170). Substituir **tudo** entre essas tags por:

```html
{% block extra_css %}
<style>
    .fap-review-page { animation: fadeIn .3s ease-in; }
    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

    /* ── Stat cards ─────────────────────────────────────── */
    .stat-cards {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: .75rem;
        margin-bottom: 1.5rem;
    }
    @media (max-width: 1200px) { .stat-cards { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 600px)  { .stat-cards { grid-template-columns: 1fr; } }

    .stat-card {
        position: relative;
        overflow: hidden;
        background: var(--bs-body-bg);
        border: 1px solid rgba(15,23,42,.07);
        border-radius: .85rem;
        box-shadow: 0 4px 16px rgba(15,23,42,.06);
        padding: .85rem 1rem .85rem 1.2rem;
        transition: transform .2s ease, box-shadow .2s ease;
    }
    .stat-card:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(15,23,42,.10); }
    .stat-card::before {
        content: "";
        position: absolute;
        inset: 0 auto 0 0;
        width: 5px;
        background: var(--sc-color, #0d6efd);
        border-radius: 4px 0 0 4px;
    }
    .stat-card .sc-icon {
        width: 2.1rem; height: 2.1rem;
        background: var(--sc-soft, rgba(13,110,253,.10));
        color: var(--sc-color, #0d6efd);
        border-radius: .55rem;
        display: inline-flex; align-items: center; justify-content: center;
        font-size: .9rem; flex-shrink: 0;
    }
    .stat-card .sc-label {
        font-size: .68rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: .04em; color: #6c7a8d; margin-bottom: .1rem;
    }
    .stat-card .sc-label-urgent { color: #dc3545; }
    .stat-card .sc-value { font-size: 1.55rem; font-weight: 800; line-height: 1; color: var(--bs-emphasis-color); }
    .stat-card .sc-sub-text { font-size: .72rem; color: #9aa5b4; margin-top: .2rem; }

    /* ── Petition list ───────────────────────────────────── */
    .petition-list { display: flex; flex-direction: column; }

    .petition-row {
        display: grid;
        grid-template-columns: 200px 1fr 160px auto;
        align-items: center;
        padding: .75rem 1rem;
        border-bottom: 1px solid rgba(15,23,42,.06);
        transition: filter .15s ease;
    }
    .petition-row:hover { filter: brightness(.97); }
    .petition-row:last-child { border-bottom: none; }

    .pr-wrike { padding-right: .75rem; }

    .pr-title { padding: 0 .75rem; min-width: 0; }
    .pr-title-text {
        font-size: .9rem; font-weight: 600;
        color: var(--bs-emphasis-color);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        margin-bottom: .1rem;
    }
    .pr-title-meta { font-size: .76rem; color: #9aa5b4; }

    .pr-status { padding: 0 .75rem; }

    .pr-actions { display: flex; gap: .4rem; justify-content: flex-end; white-space: nowrap; }

    @media (max-width: 900px) {
        .petition-row { grid-template-columns: 1fr auto; row-gap: .25rem; }
        .pr-wrike { grid-column: 1; }
        .pr-title { grid-column: 1; padding-left: 0; }
        .pr-status { display: none; }
        .pr-actions { grid-row: 1 / 3; grid-column: 2; flex-direction: column; }
    }

    /* ── Search & filter ─────────────────────────────────── */
    .petition-search-bar {
        display: flex; align-items: center; gap: .4rem;
        background: var(--bs-secondary-bg);
        border: 1px solid var(--bs-border-color);
        border-radius: .6rem; padding: .35rem .7rem;
        min-width: 240px; flex: 1; max-width: 340px;
    }
    .petition-search-bar input {
        border: none; background: transparent; font-size: .85rem;
        width: 100%; color: var(--bs-body-color);
    }
    .petition-search-bar input:focus { outline: none; }
    .petition-search-bar input::placeholder { color: #9aa5b4; }

    .filter-pill {
        display: inline-flex; align-items: center; gap: .3rem;
        padding: .3rem .85rem; border-radius: 999px; font-size: .78rem; font-weight: 600;
        cursor: pointer; border: 1px solid var(--bs-border-color);
        background: var(--bs-body-bg); color: var(--bs-secondary-color);
        transition: all .15s ease; user-select: none;
    }
    .filter-pill:hover { border-color: var(--bs-primary); color: var(--bs-primary); }
    .filter-pill.active { background: var(--bs-primary); border-color: var(--bs-primary); color: #fff; }
    .filter-pill.pill-danger  { border-color: #dc3545; color: #dc3545; }
    .filter-pill.pill-danger.active  { background: #dc3545; border-color: #dc3545; color: #fff; }
    .filter-pill.pill-warning { border-color: #9a6700; color: #9a6700; }
    .filter-pill.pill-warning.active { background: #ffc107; border-color: #ffc107; color: #000; }
    .filter-pill.pill-success { border-color: #198754; color: #198754; }
    .filter-pill.pill-success.active { background: #198754; border-color: #198754; color: #fff; }

    /* ── Wrike chip ──────────────────────────────────────── */
    .office-identifier-chip {
        display: inline-flex; align-items: center; gap: .35rem;
        max-width: 190px; padding: .28rem .48rem; border-radius: .55rem;
        background: var(--identifier-chip-bg, rgba(13,110,253,.10));
        border: 1px solid var(--identifier-chip-border, rgba(13,110,253,.18));
        color: var(--identifier-chip-text, #0a58ca);
        font-size: .74rem; font-weight: 700; line-height: 1.25;
    }
    .office-identifier-chip span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .office-identifier-chip .wrike-inline-mark { width: 1.2rem; height: auto; flex-shrink: 0; }
    .office-identifier-chip.is-empty { background: rgba(108,117,125,.10); border-color: rgba(108,117,125,.18); color: #6c7d75; }
</style>
{% endblock %}
```

- [ ] **Step 2.2: Verificar que a página ainda abre sem erro de template**

```bash
uv run python main.py
```
Abrir `http://localhost:5001/fap-review/`. Esperado: sem erro 500. O layout estará quebrado ainda — isso é esperado enquanto o HTML não for atualizado.

---

## Task 3: Mover CTA "Nova Petição / Revisão" para o page hero

**Files:**
- Modify: `templates/fap_review/index.html` (bloco `content`, seção `page_hero` e logo abaixo)

- [ ] **Step 3.1: Atualizar o bloco `{% call page_hero ... %}`**

Localizar o bloco (inicia em `{% call page_hero(title=page_title, ...`) até o primeiro `{% endcall %}`). Substituir por:

```html
    {% call page_hero(title=page_title, subtitle='Revisão e análise de petições iniciais FAP com agentes de IA',
    icon='bi bi-file-earmark-check') %}
    <div class="d-flex align-items-center gap-3 flex-wrap">
        <nav aria-label="breadcrumb">
            <ol class="breadcrumb mb-0 bg-transparent small">
                <li class="breadcrumb-item"><a href="{{ url_for('dashboard.dashboard') }}"><i class="bi bi-house"></i> Home</a></li>
                <li class="breadcrumb-item active"><i class="bi bi-file-earmark-check"></i> Revisor de Petições</li>
            </ol>
        </nav>
        <a href="{{ url_for('fap_review.revision') }}" class="btn btn-primary btn-sm">
            <i class="bi bi-folder-plus me-1"></i> Nova Petição / Revisão
        </a>
    </div>
    {% endcall %}
```

- [ ] **Step 3.2: Remover o bloco de botões flutuantes**

Localizar e apagar o bloco abaixo do `{% endcall %}` do hero (atualmente são as linhas com `<!-- Botões de Ação -->`):

```html
        <!-- Botões de Ação -->
        <div class="d-flex flex-wrap gap-2 mb-4">
            <a href="{{ url_for('fap_review.revision') }}" class="btn btn-primary">
                <i class="bi bi-folder-plus me-1"></i> Nova Petição / Revisão
            </a>
            <a href="{{ url_for('fap_review.settings') }}" class="btn btn-outline-secondary">
                <i class="bi bi-sliders me-1"></i> Configurações
            </a>
        </div>
```

Esse bloco inteiro é removido. Não há substituto — o botão já está no hero.

- [ ] **Step 3.3: Verificar que o botão aparece no hero**

```bash
uv run python main.py
```
Abrir `http://localhost:5001/fap-review/`. Esperado: botão "Nova Petição / Revisão" aparece no canto direito do hero, ao lado do breadcrumb.

---

## Task 4: Redesenhar os stat cards

**Files:**
- Modify: `templates/fap_review/index.html` (bloco `<!-- Estatísticas em Grid -->`)

- [ ] **Step 4.1: Substituir o bloco de stat cards**

Localizar o bloco `<!-- Estatísticas em Grid -->` e substituir **todo** o `<div class="stat-cards">...</div>` por:

```html
        <!-- Estatísticas -->
        <div class="stat-cards">
            <div class="stat-card" style="--sc-color: #0d6efd; --sc-soft: rgba(13,110,253,.10);">
                <div class="sc-icon"><i class="bi bi-bar-chart"></i></div>
                <div class="sc-label">Total de petições</div>
                <div class="sc-value">{{ total_petitions }}</div>
                <div class="sc-sub-text">{{ total_revisions }} revisões realizadas</div>
            </div>
            <div class="stat-card" style="--sc-color: #dc3545; --sc-soft: rgba(220,53,69,.10);">
                <div class="sc-icon"><i class="bi bi-exclamation-circle"></i></div>
                <div class="sc-label sc-label-urgent">⚠ Aguardando ajustes</div>
                <div class="sc-value" style="color: #dc3545;">{{ awaiting_adjustments_petitions }}</div>
                <div class="sc-sub-text" style="color: rgba(220,53,69,.7);">Requerem atenção agora</div>
            </div>
            <div class="stat-card" style="--sc-color: #ffc107; --sc-soft: rgba(255,193,7,.10);">
                <div class="sc-icon"><i class="bi bi-hourglass-split"></i></div>
                <div class="sc-label">Em revisão</div>
                <div class="sc-value">{{ in_review_petitions }}</div>
                <div class="sc-sub-text">Processando</div>
            </div>
            <div class="stat-card" style="--sc-color: #198754; --sc-soft: rgba(25,135,84,.10);">
                <div class="sc-icon"><i class="bi bi-check-circle"></i></div>
                <div class="sc-label">Prontas para seguir</div>
                <div class="sc-value" style="color: #198754;">{{ ready_petitions }}</div>
                <div class="sc-sub-text">{{ (ready_petitions / total_petitions * 100)|round if total_petitions else 0 }}% do total</div>
            </div>
        </div>
```

- [ ] **Step 4.2: Verificar os cards visualmente**

Abrir `http://localhost:5001/fap-review/`. Esperado: 4 cards com bordas coloridas, card "Ajustes" com label e número vermelhos, subtítulo "Requerem atenção agora".

---

## Task 5: Substituir a tabela de petições pelo novo layout de lista

**Files:**
- Modify: `templates/fap_review/index.html` (bloco `<!-- Petições -->`)

- [ ] **Step 5.1: Substituir o bloco `<!-- Petições -->` completo**

Localizar o bloco que começa em `<!-- Petições -->` e vai até o `</div>` que fecha o card (logo antes de `<!-- Configuração dos Agentes -->`). Substituir **tudo** por:

```html
        <!-- Petições -->
        <div class="card mb-4">
            <div class="card-header border-0 d-flex align-items-center justify-content-between gap-3 flex-wrap">
                <h5 class="card-title mb-0"><i class="bi bi-collection me-2"></i> Petições em Acompanhamento</h5>
                <div class="petition-search-bar">
                    <i class="bi bi-search text-muted" style="font-size: .85rem; flex-shrink:0;"></i>
                    <input type="text" id="petitionSearch" placeholder="Buscar petição ou Id Wrike..." autocomplete="off">
                </div>
            </div>

            <!-- Filtros por status -->
            <div class="px-3 py-2 d-flex flex-wrap gap-2 align-items-center" style="background: var(--bs-secondary-bg); border-top: 1px solid rgba(15,23,42,.06); border-bottom: 1px solid rgba(15,23,42,.06);">
                <button class="filter-pill active" data-filter="all">
                    Todos ({{ total_petitions }})
                </button>
                {% if awaiting_adjustments_petitions %}
                <button class="filter-pill pill-danger" data-filter="awaiting_adjustments">
                    <i class="bi bi-exclamation-circle"></i> Ajustes ({{ awaiting_adjustments_petitions }})
                </button>
                {% endif %}
                {% if in_review_petitions %}
                <button class="filter-pill pill-warning" data-filter="in_review">
                    <i class="bi bi-hourglass-split"></i> Em revisão ({{ in_review_petitions }})
                </button>
                {% endif %}
                {% if ready_petitions %}
                <button class="filter-pill pill-success" data-filter="ready_for_filing">
                    <i class="bi bi-check-circle"></i> Prontas ({{ ready_petitions }})
                </button>
                {% endif %}
                <button class="filter-pill" data-filter="others">Outras</button>
            </div>

            <!-- Lista de petições -->
            {% if petition_rows %}
            <div class="petition-list" id="petitionList">
                {% for row in petition_rows %}
                {% set petition = row.petition %}
                {% set latest_revision = row.latest_revision %}
                {% set status_badge = row.status_badge %}

                {% if petition.workflow_status == 'awaiting_adjustments' %}
                    {% set row_bg = 'rgba(220,53,69,.04)' %}
                    {% set row_border_color = '#dc3545' %}
                    {% set row_border_width = '4px' %}
                {% elif petition.workflow_status in ['in_review', 'new'] %}
                    {% set row_bg = 'rgba(255,193,7,.04)' %}
                    {% set row_border_color = '#ffc107' %}
                    {% set row_border_width = '4px' %}
                {% elif petition.workflow_status == 'ready_for_filing' %}
                    {% set row_bg = 'transparent' %}
                    {% set row_border_color = '#198754' %}
                    {% set row_border_width = '4px' %}
                {% elif petition.workflow_status == 'filed' %}
                    {% set row_bg = 'transparent' %}
                    {% set row_border_color = '#0d6efd' %}
                    {% set row_border_width = '4px' %}
                {% else %}
                    {% set row_bg = 'rgba(108,117,125,.02)' %}
                    {% set row_border_color = '#dee2e6' %}
                    {% set row_border_width = '2px' %}
                {% endif %}

                <div class="petition-row"
                     style="background: {{ row_bg }}; border-left: {{ row_border_width }} solid {{ row_border_color }};"
                     data-status="{{ petition.workflow_status }}"
                     data-search="{{ (petition.title ~ ' ' ~ (petition.office_document_identifier or ''))|lower }}">

                    <!-- Wrike ID -->
                    <div class="pr-wrike">
                        <div class="office-identifier-chip{% if not petition.office_document_identifier %} is-empty{% endif %}"
                             {% if petition.office_document_identifier %}data-identifier="{{ petition.office_document_identifier }}"{% endif %}
                             title="{{ petition.office_document_identifier or '-' }}">
                            <img src="{{ url_for('static', filename='assets/wrike-logo-light.svg') }}" alt="Wrike" class="wrike-inline-mark">
                            <span>{{ petition.office_document_identifier or '-' }}</span>
                        </div>
                    </div>

                    <!-- Título + meta -->
                    <div class="pr-title">
                        <div class="pr-title-text">{{ petition.title }}</div>
                        <div class="pr-title-meta">
                            {% if latest_revision %}R{{ latest_revision.revision_number or '?' }} · {% endif %}
                            {{ (petition.last_reviewed_at or petition.updated_at or petition.created_at).strftime('%d/%m/%Y') }}
                        </div>
                    </div>

                    <!-- Status -->
                    <div class="pr-status">
                        <span class="badge rounded-pill bg-{{ status_badge.class }}-subtle text-{{ status_badge.class }}-emphasis border border-{{ status_badge.class }}-subtle">
                            <i class="{{ status_badge.icon }} me-1"></i> {{ status_badge.label }}
                        </span>
                    </div>

                    <!-- Ações -->
                    <div class="pr-actions">
                        <a href="{{ url_for('fap_review.petition_detail', petition_id=petition.id) }}"
                           class="btn btn-sm btn-outline-secondary">Histórico</a>
                        <a href="{{ url_for('fap_review.revision', petition_id=petition.id) }}"
                           class="btn btn-sm btn-primary">Revisar</a>
                    </div>
                </div>
                {% endfor %}
            </div>

            <!-- Empty state para filtro sem resultado -->
            <div id="petitionEmptyState" class="text-center py-5" style="display:none;">
                <i class="bi bi-search text-muted" style="font-size: 2rem;"></i>
                <p class="text-muted mt-2 mb-0">Nenhuma petição encontrada para este filtro</p>
            </div>

            <!-- Rodapé -->
            <div class="px-3 py-2 d-flex justify-content-between align-items-center" style="border-top: 1px solid rgba(15,23,42,.06); background: var(--bs-secondary-bg);">
                <small class="text-muted" id="petitionCount">Exibindo {{ petition_rows|length }} petições</small>
                <a href="{{ url_for('fap_review.index') }}" class="small text-primary fw-semibold" style="text-decoration: none;">Ver todas →</a>
            </div>

            {% else %}
            <div class="text-center py-5">
                <i class="bi bi-inbox text-muted" style="font-size: 2rem;"></i>
                <p class="text-muted mt-2 mb-0">Nenhuma petição registrada ainda</p>
            </div>
            {% endif %}
        </div>
```

- [ ] **Step 5.2: Verificar o layout da lista**

```bash
uv run python main.py
```
Abrir `http://localhost:5001/fap-review/`. Esperado:
- Linhas com borda colorida à esquerda (vermelho = ajustes, amarelo = em revisão, verde = prontas)
- Id Wrike na primeira coluna com chip colorido
- Botões "Histórico" e "Revisar" com texto
- Filtros e busca ainda não funcionam (apenas visuais)

---

## Task 6: Remover seções de agentes e navegação rápida

**Files:**
- Modify: `templates/fap_review/index.html`

- [ ] **Step 6.1: Remover `<!-- Configuração dos Agentes -->`**

Localizar e apagar o bloco completo que começa em `<!-- Configuração dos Agentes -->` e vai até o fechamento do `</div>` (2 cards `col-lg-6` com "Agente Revisor" e "Agente de Treinamento").

- [ ] **Step 6.2: Remover `<!-- Navegação Rápida -->`**

Localizar e apagar o bloco completo que começa em `<!-- Navegação Rápida -->` e contém os 4 botões (Revisar Petição, Treinamento, Configurações, Auditoria).

- [ ] **Step 6.3: Verificar que a página não tem seções órfãs**

Abrir `http://localhost:5001/fap-review/`. Esperado: página termina logo após o card de petições. Sem cards de agentes, sem botões de navegação no rodapé.

---

## Task 7: Adicionar JavaScript de busca e filtros

**Files:**
- Modify: `templates/fap_review/index.html` (bloco `extra_js`)

- [ ] **Step 7.1: Substituir o bloco `{% block extra_js %}` completo pelo novo JS**

Localizar o bloco `{% block extra_js %}` (que atualmente só tem o JS das cores do chip Wrike). Substituir **tudo** entre as tags por:

```html
{% block extra_js %}
<script>
    document.addEventListener('DOMContentLoaded', function () {

        // ── Chip de Wrike: paleta de cores por hash ──────────────
        const chips = document.querySelectorAll('.office-identifier-chip[data-identifier]');
        const chipPalette = [
            { bg: '#dbeafe', border: '#93c5fd', text: '#1d4ed8' },
            { bg: '#dcfce7', border: '#86efac', text: '#15803d' },
            { bg: '#fef3c7', border: '#fcd34d', text: '#b45309' },
            { bg: '#fee2e2', border: '#fca5a5', text: '#b91c1c' },
            { bg: '#ede9fe', border: '#c4b5fd', text: '#6d28d9' },
            { bg: '#cffafe', border: '#67e8f9', text: '#0f766e' },
            { bg: '#fce7f3', border: '#f9a8d4', text: '#be185d' },
            { bg: '#ffedd5', border: '#fdba74', text: '#c2410c' },
            { bg: '#e0f2fe', border: '#7dd3fc', text: '#0369a1' },
            { bg: '#ecfccb', border: '#bef264', text: '#4d7c0f' }
        ];
        function hashIdentifier(value) {
            let hash = 0;
            for (let i = 0; i < value.length; i++) {
                hash = ((hash << 5) - hash) + value.charCodeAt(i);
                hash |= 0;
            }
            return Math.abs(hash);
        }
        chips.forEach(function (chip) {
            const id = chip.dataset.identifier || '';
            if (!id) return;
            const entry = chipPalette[hashIdentifier(id) % chipPalette.length];
            chip.style.setProperty('--identifier-chip-bg', entry.bg);
            chip.style.setProperty('--identifier-chip-border', entry.border);
            chip.style.setProperty('--identifier-chip-text', entry.text);
        });

        // ── Busca + filtro por status ─────────────────────────────
        const searchInput = document.getElementById('petitionSearch');
        const filterPills = document.querySelectorAll('.filter-pill');
        const rows = document.querySelectorAll('.petition-row');
        const countDisplay = document.getElementById('petitionCount');
        const emptyState = document.getElementById('petitionEmptyState');
        const totalCount = rows.length;
        let activeFilter = 'all';

        function applyFilters() {
            const term = (searchInput ? searchInput.value : '').toLowerCase().trim();
            let visible = 0;

            rows.forEach(function (row) {
                const matchesSearch = !term || (row.dataset.search || '').includes(term);
                const status = row.dataset.status || '';
                let matchesFilter = true;

                if (activeFilter === 'awaiting_adjustments') {
                    matchesFilter = status === 'awaiting_adjustments';
                } else if (activeFilter === 'in_review') {
                    matchesFilter = status === 'in_review' || status === 'new';
                } else if (activeFilter === 'ready_for_filing') {
                    matchesFilter = status === 'ready_for_filing';
                } else if (activeFilter === 'others') {
                    matchesFilter = status === 'filed' || status === 'archived';
                }

                const show = matchesSearch && matchesFilter;
                row.style.display = show ? '' : 'none';
                if (show) visible++;
            });

            if (countDisplay) {
                if (activeFilter !== 'all' || term) {
                    countDisplay.textContent = 'Exibindo ' + visible + ' de ' + totalCount + ' petições';
                } else {
                    countDisplay.textContent = 'Exibindo ' + totalCount + ' petições';
                }
            }
            if (emptyState) {
                emptyState.style.display = visible === 0 ? '' : 'none';
            }
        }

        filterPills.forEach(function (pill) {
            pill.addEventListener('click', function () {
                filterPills.forEach(function (p) { p.classList.remove('active'); });
                this.classList.add('active');
                activeFilter = this.dataset.filter || 'all';
                applyFilters();
            });
        });

        if (searchInput) {
            searchInput.addEventListener('input', applyFilters);
        }
    });
</script>
{% endblock %}
```

- [ ] **Step 7.2: Testar busca e filtros**

```bash
uv run python main.py
```
Abrir `http://localhost:5001/fap-review/`. Verificar:
1. Digitar parte do nome de uma petição no campo de busca → linhas não correspondentes somem
2. Clicar em "Ajustes" → só aparecem petições com `workflow_status = awaiting_adjustments`
3. Clicar em "Todos" → todas reaparecem
4. O contador "Exibindo X de Y petições" atualiza corretamente
5. Filtrar até não sobrar nenhum → aparece "Nenhuma petição encontrada para este filtro"
6. Chips do Wrike ID têm cores diferentes por hash

- [ ] **Step 7.3: Commit final**

```bash
git add templates/fap_review/index.html
git commit -m "feat(fap-review): redesenho do dashboard — busca, filtros, linhas coloridas por status"
```

---

## Self-review checklist

- [x] **Cobertura da spec:** Todos os 10 pontos da legenda do mockup estão cobertos
- [x] **Sem placeholders:** Código completo em todos os steps
- [x] **Consistência de tipos:** `data-filter` no HTML bate com os valores checados no JS (`awaiting_adjustments`, `in_review`, `ready_for_filing`, `others`, `all`)
- [x] **Id Wrike sempre visível:** chip na coluna `pr-wrike` em toda linha, incluindo estado `is-empty`
- [x] **Variáveis Jinja:** `total_petitions`, `ready_petitions`, `in_review_petitions`, `awaiting_adjustments_petitions`, `total_revisions`, `petition_rows` — todas já passadas pela rota `index()` atual, sem mudança de interface
- [x] **Variável `setting`:** não é mais usada no template após remover os cards de agentes — pode ficar passada pelo backend sem causar erro (variável ignorada)
