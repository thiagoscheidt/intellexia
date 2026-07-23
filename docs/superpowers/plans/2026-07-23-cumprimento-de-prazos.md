# Cumprimento de Prazos + Melhorias da Tela do Processo — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar ao Painel de Processos o núcleo de "Cumprimento de Prazos" (entidade de prazos/audiências, widget com contagem regressiva, criação a partir de intimações DJEN, chip no header) e entregar as melhorias aprovadas da tela de detalhe (responsável, datas, KB, checklist de fase, impacto FAP, aba Atividade).

**Architecture:** Nova tabela `process_deadlines` (prazos e audiências unificados via campo `kind`), serviço `process_deadline_service` como fonte única (tela + chip do header), rotas novas no blueprint `process_panel`, e ampliação do contexto da rota `detail` para os painéis novos. Tudo multi-tenant por `law_firm_id`.

**Tech Stack:** Flask 3.1 + SQLAlchemy (sem Alembic — migrations são scripts standalone em `database/`), Jinja2/AdminLTE 4/Bootstrap 5, sem framework de testes (scripts executáveis).

## Global Constraints

- **Multi-tenancy**: toda query filtra `law_firm_id` (`get_current_law_firm_id()` / `session.get('law_firm_id')`).
- **Migrations**: scripts standalone idempotentes em `database/`, prefixo `add_*`, rodando dentro de `with app.app_context():`, com mensagens claras. **Atenção: o `.env` deste checkout aponta para o MySQL de produção** — só migrations aditivas (CREATE TABLE / ADD COLUMN), nunca DROP/ALTER destrutivo.
- **Sem commits automáticos**: o usuário não pediu commits; cada task termina em *checkpoint* (validação + diff), não em commit. (Deviação consciente do template da skill.)
- **Contagem de prazo sugerida (decisão do usuário)**: disponibilização DJEN → publicação = 1º dia útil seguinte → vencimento = +15 dias úteis (número editável na criação). Feriados não são considerados (limitação documentada).
- **Escopo da 1ª entrega (decisão do usuário)**: tela + widget + chip no header. E-mail/notificação fica de fora.
- **Estilo visual**: seguir o chrome novo da tela (`pp-card`, badges *subtle*, tabelas sem zebra). Deps: nada novo — `uv` já resolve tudo.
- **Card "Benefícios do Processo"**: não alterar estrutura/colunas/lógica (só o que já foi combinado).
- Datetimes no banco em UTC naive; datas exibidas com `strftime`/filtros já usados no template.

---

### Task 1: Modelo `ProcessDeadline` + coluna `responsible_user_id` + migrations

**Files:**
- Modify: `app/models.py` (classe nova após `ProcessCommunication`; coluna nova em `JudicialProcess`)
- Create: `database/add_process_deadlines_table.py`
- Create: `database/add_responsible_user_to_judicial_processes.py`

**Interfaces:**
- Produces: `ProcessDeadline` com constantes `KIND_PRAZO='prazo'`, `KIND_AUDIENCIA='audiencia'`, `STATUS_PENDING='pending'`, `STATUS_DONE='done'`; relacionamento `JudicialProcess.deadlines`; `JudicialProcess.responsible_user_id` + `JudicialProcess.responsible_user`.

- [ ] **Step 1: Adicionar coluna em `JudicialProcess`** — em `app/models.py`, logo após `defendant_id = db.Column(...)`:

```python
    responsible_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)  # Advogado responsável
```

E junto aos relationships existentes da classe:

```python
    responsible_user = db.relationship('User', foreign_keys=[responsible_user_id])
```

- [ ] **Step 2: Criar a classe `ProcessDeadline`** — em `app/models.py`, imediatamente após a classe `ProcessCommunication`:

```python
class ProcessDeadline(db.Model):
    """Tabela process_deadlines - Prazos e audiências do Painel de Processos.

    Unifica prazos processuais e audiências (``kind``). Pode nascer manual ou
    derivado de uma intimação do Monitoramento de Processos (``origin`` +
    ``communication_id``). Fonte única de leitura: process_deadline_service.
    """
    __tablename__ = 'process_deadlines'
    __table_args__ = (
        db.Index('ix_process_deadlines_firm_status_due', 'law_firm_id', 'status', 'due_date'),
    )

    KIND_PRAZO = 'prazo'
    KIND_AUDIENCIA = 'audiencia'
    STATUS_PENDING = 'pending'
    STATUS_DONE = 'done'

    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    process_id = db.Column(db.Integer, db.ForeignKey('judicial_processes.id'), nullable=False, index=True)

    kind = db.Column(db.String(20), nullable=False, default=KIND_PRAZO)
    title = db.Column(db.String(255), nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    due_time = db.Column(db.Time)            # audiências
    location = db.Column(db.String(255))     # audiências

    origin = db.Column(db.String(20), nullable=False, default='manual')  # manual | communication
    communication_id = db.Column(db.Integer, db.ForeignKey('process_communications.id'), index=True)
    responsible_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)

    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING)
    done_at = db.Column(db.DateTime)
    done_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    notes = db.Column(db.Text)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    process = db.relationship('JudicialProcess', backref=db.backref('deadlines', lazy='dynamic'))
    communication = db.relationship('ProcessCommunication')
    responsible_user = db.relationship('User', foreign_keys=[responsible_user_id])
    done_by_user = db.relationship('User', foreign_keys=[done_by_user_id])
    created_by_user = db.relationship('User', foreign_keys=[created_by_user_id])

    def __repr__(self):
        return f'<ProcessDeadline {self.id} {self.kind} {self.due_date}>'
```

- [ ] **Step 3: Migration da tabela** — `database/add_process_deadlines_table.py`:

```python
"""Cria a tabela process_deadlines (prazos e audiências do Painel de Processos)."""
from sqlalchemy import inspect
from main import app
from app.models import db, ProcessDeadline


def run():
    with app.app_context():
        inspector = inspect(db.engine)
        if inspector.has_table('process_deadlines'):
            print('[OK] Tabela process_deadlines já existe — nada a fazer.')
            return
        ProcessDeadline.__table__.create(db.engine)
        print('[OK] Tabela process_deadlines criada com sucesso.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(f'[ERRO] Falha ao criar process_deadlines: {exc}')
        raise
```

- [ ] **Step 4: Migration da coluna** — `database/add_responsible_user_to_judicial_processes.py`:

```python
"""Adiciona judicial_processes.responsible_user_id (advogado responsável)."""
from sqlalchemy import inspect, text
from main import app
from app.models import db


def run():
    with app.app_context():
        inspector = inspect(db.engine)
        columns = {col['name'] for col in inspector.get_columns('judicial_processes')}
        if 'responsible_user_id' in columns:
            print('[OK] Coluna responsible_user_id já existe — nada a fazer.')
            return
        db.session.execute(text(
            'ALTER TABLE judicial_processes ADD COLUMN responsible_user_id INTEGER NULL'
        ))
        db.session.commit()
        print('[OK] Coluna responsible_user_id adicionada.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(f'[ERRO] Falha ao adicionar responsible_user_id: {exc}')
        raise
```

- [ ] **Step 5: Rodar as migrations** (aditivas e idempotentes; o banco é o MySQL compartilhado):

```bash
uv run python database/add_process_deadlines_table.py
uv run python database/add_responsible_user_to_judicial_processes.py
```

Esperado: duas linhas `[OK] ...` (criada / adicionada; ou "já existe" em re-execução).

- [ ] **Step 6: Checkpoint** — `git diff --stat` mostra só `app/models.py` + 2 arquivos novos em `database/`.

---

### Task 2: Serviço `process_deadline_service` + teste standalone

**Files:**
- Create: `app/services/process_deadline_service.py`
- Test: `scripts/tests/test_process_deadline_service.py`

**Interfaces:**
- Consumes: `ProcessDeadline` (Task 1).
- Produces:
  - `add_business_days(start: date, days: int) -> date`
  - `suggest_deadline_from_disponibilizacao(disponibilizacao: date, useful_days: int = 15) -> date`
  - `classify_deadline(deadline, today: date | None = None) -> dict` → `{'state': 'done'|'overdue'|'today'|'soon'|'ok', 'days_left': int}`
  - `list_for_process(process_id, law_firm_id) -> list[ProcessDeadline]` (pendentes por `due_date` asc, depois concluídos por `due_date` desc)
  - `create_deadline(law_firm_id, process_id, *, kind, title, due_date, due_time=None, location=None, origin='manual', communication_id=None, responsible_user_id=None, notes=None, created_by_user_id=None) -> ProcessDeadline`
  - `set_deadline_status(deadline_id, law_firm_id, *, done: bool, user_id=None) -> ProcessDeadline | None`
  - `delete_deadline(deadline_id, law_firm_id) -> bool`
  - `firm_counts(law_firm_id) -> {'overdue': int, 'soon': int}` (pendentes vencidos / vencendo em ≤7 dias)

- [ ] **Step 1: Escrever o serviço** — `app/services/process_deadline_service.py`:

```python
"""Regras de Cumprimento de Prazos do Painel de Processos.

Fonte única para a tela do processo e para o chip do header. Contagem de
prazo sugerida a partir de intimação DJEN (simplificação documentada:
somente fins de semana são pulados; feriados não são considerados):
publicação = 1º dia útil após a disponibilização; vencimento = publicação
+ N dias úteis (padrão 15, editável na criação).
"""
from datetime import date, datetime, timedelta

from app.models import db, ProcessDeadline

SOON_WINDOW_DAYS = 7


def add_business_days(start: date, days: int) -> date:
    """Avança `days` dias úteis (seg-sex) a partir de `start` (exclusivo)."""
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def suggest_deadline_from_disponibilizacao(disponibilizacao: date, useful_days: int = 15) -> date:
    publicacao = add_business_days(disponibilizacao, 1)
    return add_business_days(publicacao, useful_days)


def classify_deadline(deadline, today=None):
    today = today or date.today()
    if deadline.status == ProcessDeadline.STATUS_DONE:
        return {'state': 'done', 'days_left': 0}
    days_left = (deadline.due_date - today).days
    if days_left < 0:
        state = 'overdue'
    elif days_left == 0:
        state = 'today'
    elif days_left <= SOON_WINDOW_DAYS:
        state = 'soon'
    else:
        state = 'ok'
    return {'state': state, 'days_left': days_left}


def list_for_process(process_id, law_firm_id):
    pending = ProcessDeadline.query.filter_by(
        process_id=process_id, law_firm_id=law_firm_id,
        status=ProcessDeadline.STATUS_PENDING,
    ).order_by(ProcessDeadline.due_date.asc(), ProcessDeadline.id.asc()).all()
    done = ProcessDeadline.query.filter_by(
        process_id=process_id, law_firm_id=law_firm_id,
        status=ProcessDeadline.STATUS_DONE,
    ).order_by(ProcessDeadline.due_date.desc(), ProcessDeadline.id.desc()).all()
    return pending + done


def create_deadline(law_firm_id, process_id, *, kind, title, due_date, due_time=None,
                    location=None, origin='manual', communication_id=None,
                    responsible_user_id=None, notes=None, created_by_user_id=None):
    deadline = ProcessDeadline(
        law_firm_id=law_firm_id,
        process_id=process_id,
        kind=kind if kind in (ProcessDeadline.KIND_PRAZO, ProcessDeadline.KIND_AUDIENCIA)
        else ProcessDeadline.KIND_PRAZO,
        title=title.strip(),
        due_date=due_date,
        due_time=due_time,
        location=(location or '').strip() or None,
        origin=origin,
        communication_id=communication_id,
        responsible_user_id=responsible_user_id,
        notes=(notes or '').strip() or None,
        created_by_user_id=created_by_user_id,
    )
    db.session.add(deadline)
    db.session.commit()
    return deadline


def set_deadline_status(deadline_id, law_firm_id, *, done: bool, user_id=None):
    deadline = ProcessDeadline.query.filter_by(id=deadline_id, law_firm_id=law_firm_id).first()
    if not deadline:
        return None
    if done:
        deadline.status = ProcessDeadline.STATUS_DONE
        deadline.done_at = datetime.now()
        deadline.done_by_user_id = user_id
    else:
        deadline.status = ProcessDeadline.STATUS_PENDING
        deadline.done_at = None
        deadline.done_by_user_id = None
    db.session.commit()
    return deadline


def delete_deadline(deadline_id, law_firm_id):
    deadline = ProcessDeadline.query.filter_by(id=deadline_id, law_firm_id=law_firm_id).first()
    if not deadline:
        return False
    db.session.delete(deadline)
    db.session.commit()
    return True


def firm_counts(law_firm_id):
    today = date.today()
    soon_limit = today + timedelta(days=SOON_WINDOW_DAYS)
    base = ProcessDeadline.query.filter_by(
        law_firm_id=law_firm_id, status=ProcessDeadline.STATUS_PENDING)
    overdue = base.filter(ProcessDeadline.due_date < today).count()
    soon = base.filter(ProcessDeadline.due_date >= today,
                       ProcessDeadline.due_date <= soon_limit).count()
    return {'overdue': overdue, 'soon': soon}
```

- [ ] **Step 2: Escrever o teste standalone (só funções puras — não toca no banco)** — `scripts/tests/test_process_deadline_service.py`:

```python
"""Testes das funções puras do process_deadline_service. Não acessa o banco."""
from datetime import date

from app.services.process_deadline_service import (
    add_business_days,
    suggest_deadline_from_disponibilizacao,
)


def main():
    # sexta 2026-07-17 + 1 dia útil = segunda 2026-07-20
    assert add_business_days(date(2026, 7, 17), 1) == date(2026, 7, 20)
    # segunda + 5 dias úteis = segunda seguinte
    assert add_business_days(date(2026, 7, 20), 5) == date(2026, 7, 27)
    # sábado + 1 dia útil = segunda
    assert add_business_days(date(2026, 7, 18), 1) == date(2026, 7, 20)

    # Disponibilização quarta 2026-07-22 → publicação quinta 23 → +15 úteis = 2026-08-13
    assert suggest_deadline_from_disponibilizacao(date(2026, 7, 22)) == date(2026, 8, 13)
    # Disponibilização sexta 2026-07-24 → publicação segunda 27 → +15 úteis = 2026-08-17
    assert suggest_deadline_from_disponibilizacao(date(2026, 7, 24)) == date(2026, 8, 17)

    print('[OK] Todos os testes do process_deadline_service passaram.')


if __name__ == '__main__':
    main()
```

- [ ] **Step 3: Rodar o teste**

```bash
uv run python scripts/tests/test_process_deadline_service.py
```

Esperado: `[OK] Todos os testes do process_deadline_service passaram.`
(Antes de implementar, rodar deve falhar com `ModuleNotFoundError`/`ImportError` — ciclo vermelho→verde.)

- [ ] **Step 4: Checkpoint** — diff contém apenas o serviço e o teste.

---

### Task 3: Rotas de prazos + contexto novo na rota `detail`

**Files:**
- Modify: `app/blueprints/process_panel.py` (rotas novas ao final; rota `detail` ~linha 1776)

**Interfaces:**
- Consumes: todo o `process_deadline_service` (Task 2).
- Produces (para a Task 4): contexto do template com `deadlines` (lista de dicts `{'obj': ProcessDeadline, 'state': str, 'days_left': int}`), `firm_users` (Users ativos do escritório), `comm_deadline_suggestions` (dict `comm.id -> 'YYYY-MM-DD'`), e endpoints `process_panel.create_deadline`, `process_panel.set_deadline_done`, `process_panel.delete_deadline_route`.

- [ ] **Step 1: Imports** — no topo de `process_panel.py`, junto aos imports de serviços:

```python
from app.services import process_deadline_service
```

E garantir `User` no import de `app.models` (adicionar se ausente).

- [ ] **Step 2: Contexto na rota `detail`** — antes do dict `data`, adicionar:

```python
    deadline_rows = process_deadline_service.list_for_process(process.id, law_firm_id)
    deadlines = [
        {'obj': d, **process_deadline_service.classify_deadline(d)}
        for d in deadline_rows
    ]

    firm_users = User.query.filter_by(law_firm_id=law_firm_id, is_active=True) \
        .order_by(User.name.asc()).all()

    comm_deadline_suggestions = {
        comm.id: process_deadline_service.suggest_deadline_from_disponibilizacao(
            comm.data_disponibilizacao).isoformat()
        for comm in (process.communications or [])
        if comm.data_disponibilizacao
    }
```

E no dict `data`: `'deadlines': deadlines, 'firm_users': firm_users, 'comm_deadline_suggestions': comm_deadline_suggestions,`.

- [ ] **Step 3: Rotas novas** — ao final do arquivo:

```python
@process_panel_bp.route('/process-panel/<int:process_id>/deadlines', methods=['POST'])
@require_law_firm
def create_deadline(process_id):
    """Cria prazo/audiência do processo (manual ou derivado de intimação DJEN)."""
    law_firm_id = get_current_law_firm_id()
    process = JudicialProcess.query.filter_by(id=process_id, law_firm_id=law_firm_id).first_or_404()

    title = (request.form.get('title') or '').strip()
    due_date_raw = (request.form.get('due_date') or '').strip()
    if not title or not due_date_raw:
        flash('Informe título e data-limite do prazo.', 'danger')
        return redirect(url_for('process_panel.detail', process_id=process.id))
    try:
        due_date = datetime.strptime(due_date_raw, '%Y-%m-%d').date()
    except ValueError:
        flash('Data-limite inválida.', 'danger')
        return redirect(url_for('process_panel.detail', process_id=process.id))

    due_time = None
    due_time_raw = (request.form.get('due_time') or '').strip()
    if due_time_raw:
        try:
            due_time = datetime.strptime(due_time_raw, '%H:%M').time()
        except ValueError:
            due_time = None

    responsible_user_id = request.form.get('responsible_user_id', type=int) or None
    if responsible_user_id:
        responsible = User.query.filter_by(id=responsible_user_id, law_firm_id=law_firm_id).first()
        if not responsible:
            responsible_user_id = None

    communication_id = request.form.get('communication_id', type=int) or None
    origin = 'communication' if communication_id else 'manual'

    process_deadline_service.create_deadline(
        law_firm_id, process.id,
        kind=(request.form.get('kind') or 'prazo').strip(),
        title=title,
        due_date=due_date,
        due_time=due_time,
        location=request.form.get('location'),
        origin=origin,
        communication_id=communication_id,
        responsible_user_id=responsible_user_id,
        notes=request.form.get('notes'),
        created_by_user_id=session.get('user_id'),
    )
    flash('Prazo registrado.', 'success')
    return redirect(url_for('process_panel.detail', process_id=process.id))


@process_panel_bp.route('/process-panel/<int:process_id>/deadlines/<int:deadline_id>/status',
                        methods=['POST'])
@require_law_firm
def set_deadline_done(process_id, deadline_id):
    """Conclui ou reabre um prazo."""
    law_firm_id = get_current_law_firm_id()
    done = request.form.get('done') == '1'
    deadline = process_deadline_service.set_deadline_status(
        deadline_id, law_firm_id, done=done, user_id=session.get('user_id'))
    if not deadline or deadline.process_id != process_id:
        flash('Prazo não encontrado.', 'danger')
    else:
        flash('Prazo concluído.' if done else 'Prazo reaberto.', 'success')
    return redirect(url_for('process_panel.detail', process_id=process_id))


@process_panel_bp.route('/process-panel/<int:process_id>/deadlines/<int:deadline_id>/delete',
                        methods=['POST'])
@require_law_firm
def delete_deadline_route(process_id, deadline_id):
    """Exclui um prazo do processo."""
    law_firm_id = get_current_law_firm_id()
    if process_deadline_service.delete_deadline(deadline_id, law_firm_id):
        flash('Prazo excluído.', 'success')
    else:
        flash('Prazo não encontrado.', 'danger')
    return redirect(url_for('process_panel.detail', process_id=process_id))
```

(Observação: `set_deadline_status`/`delete_deadline` filtram por `law_firm_id`; a checagem extra `deadline.process_id != process_id` evita URL cruzada. Seguir os decorators/imports já usados nas outras rotas do arquivo — `require_law_firm` vem de `app.middlewares` como nas demais.)

- [ ] **Step 4: Smoke de import**

```bash
uv run python -c "import app.blueprints.process_panel as m; print('import OK')"
```

Esperado: `import OK` (sem tocar em rota).

- [ ] **Step 5: Checkpoint** — diff apenas em `process_panel.py`.

---

### Task 4: Widget "Prazos" + modal + botão "criar prazo" nas linhas DJEN

**Files:**
- Modify: `templates/process_panel/detail.html`

**Interfaces:**
- Consumes: `deadlines`, `firm_users`, `comm_deadline_suggestions` e endpoints da Task 3.

- [ ] **Step 1: Reorganizar a fileira de widgets** — hoje: Radar `col-lg-7` + Benefícios `col-lg-5`. Passa a: Radar `col-lg-5` + **Prazos `col-lg-4`** + Benefícios `col-lg-3`. O widget Prazos (novo, entre os dois), no padrão `pp-card`:

```html
<div class="col-lg-4">
  <div class="card pp-card h-100">
    <div class="card-header">
      <h3 class="card-title"><i class="bi bi-alarm me-2"></i>Prazos</h3>
      <div class="card-tools">
        <button type="button" class="btn btn-sm btn-primary py-0" data-bs-toggle="modal"
          data-bs-target="#newDeadlineModal"><i class="bi bi-plus-lg me-1"></i>Novo</button>
      </div>
    </div>
    <div class="card-body py-3">
      {% set pending_deadlines = deadlines | selectattr('state', 'ne', 'done') | list %}
      {% set done_deadlines = deadlines | selectattr('state', 'eq', 'done') | list %}
      {% if pending_deadlines %}
      <div class="d-flex flex-column gap-2">
        {% for item in pending_deadlines %}
        {% set d = item.obj %}
        <div class="radar-item">
          {% if item.state == 'overdue' %}
          <span class="badge bg-danger-subtle text-danger-emphasis border border-danger-subtle">
            vencido há {{ -item.days_left }}d</span>
          {% elif item.state == 'today' %}
          <span class="badge bg-danger-subtle text-danger-emphasis border border-danger-subtle">hoje</span>
          {% elif item.state == 'soon' %}
          <span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle">
            {{ item.days_left }}d</span>
          {% else %}
          <span class="badge bg-secondary-subtle text-secondary-emphasis border">
            {{ d.due_date.strftime('%d/%m') }}</span>
          {% endif %}
          <span class="text-truncate" title="{{ d.title }}{% if d.responsible_user %} — {{ d.responsible_user.name }}{% endif %}">
            {% if d.kind == 'audiencia' %}<i class="bi bi-easel2 me-1 text-secondary"></i>{% endif %}
            {{ d.title }}
            {% if d.due_time %}<small class="text-muted">{{ d.due_time.strftime('%H:%M') }}</small>{% endif %}
          </span>
          <span class="ms-date">
            <form method="post" class="d-inline"
              action="{{ url_for('process_panel.set_deadline_done', process_id=process.id, deadline_id=d.id) }}">
              <input type="hidden" name="done" value="1">
              <button type="submit" class="btn btn-sm bg-success-subtle text-success-emphasis border-0 py-0 px-1"
                title="Marcar como cumprido"><i class="bi bi-check-lg"></i></button>
            </form>
            <form method="post" class="d-inline"
              action="{{ url_for('process_panel.delete_deadline_route', process_id=process.id, deadline_id=d.id) }}"
              onsubmit="return confirm('Excluir este prazo?');">
              <button type="submit" class="btn btn-sm bg-danger-subtle text-danger-emphasis border-0 py-0 px-1"
                title="Excluir"><i class="bi bi-trash"></i></button>
            </form>
          </span>
        </div>
        {% endfor %}
      </div>
      {% else %}
      <div class="text-muted small py-2"><i class="bi bi-check2-circle me-1"></i>Nenhum prazo pendente.</div>
      {% endif %}
      {% if done_deadlines %}
      <div class="small text-muted mt-2 pt-2 border-top">
        {{ done_deadlines|length }} cumprido{{ 's' if done_deadlines|length != 1 }}
        {% set last_done = done_deadlines[0].obj %}
        — último: {{ last_done.title }} ({{ last_done.due_date.strftime('%d/%m') }})
      </div>
      {% endif %}
    </div>
  </div>
</div>
```

- [ ] **Step 2: Modal de novo prazo** — junto aos outros modais no final do template:

```html
<div class="modal fade" id="newDeadlineModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <div class="modal-content">
      <form method="post" action="{{ url_for('process_panel.create_deadline', process_id=process.id) }}">
        <div class="modal-header">
          <h5 class="modal-title"><i class="bi bi-alarm me-2"></i>Novo prazo</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Fechar"></button>
        </div>
        <div class="modal-body vstack gap-3">
          <input type="hidden" name="communication_id" id="deadlineCommId" value="">
          <div>
            <label class="form-label">Tipo</label>
            <select class="form-select" name="kind" id="deadlineKind">
              <option value="prazo" selected>Prazo processual</option>
              <option value="audiencia">Audiência</option>
            </select>
          </div>
          <div>
            <label class="form-label">Título <span class="text-danger">*</span></label>
            <input type="text" class="form-control" name="title" id="deadlineTitle" required
              placeholder="Ex.: Contrarrazões de apelação">
          </div>
          <div class="row g-2">
            <div class="col-7">
              <label class="form-label">Data-limite <span class="text-danger">*</span></label>
              <input type="date" class="form-control" name="due_date" id="deadlineDueDate" required>
              <div class="form-text d-none" id="deadlineSuggestionHint">
                Sugerido: disponibilização + 1 dia útil (publicação) + 15 dias úteis. Ajuste se necessário.
              </div>
            </div>
            <div class="col-5 d-none" id="deadlineTimeWrap">
              <label class="form-label">Hora</label>
              <input type="time" class="form-control" name="due_time">
            </div>
          </div>
          <div class="d-none" id="deadlineLocationWrap">
            <label class="form-label">Local</label>
            <input type="text" class="form-control" name="location" placeholder="Vara / sala / link da videoconferência">
          </div>
          <div>
            <label class="form-label">Responsável</label>
            <select class="form-select" name="responsible_user_id">
              <option value="">— sem responsável —</option>
              {% for u in firm_users %}
              <option value="{{ u.id }}">{{ u.name }}</option>
              {% endfor %}
            </select>
          </div>
          <div>
            <label class="form-label">Observações</label>
            <textarea class="form-control" name="notes" rows="2"></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>
          <button type="submit" class="btn btn-primary"><i class="bi bi-check-lg me-1"></i>Salvar prazo</button>
        </div>
      </form>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Botão "criar prazo" nas linhas da aba DJEN** — na coluna Ações de cada comunicação (junto aos botões existentes):

```html
<button type="button" class="btn btn-sm bg-warning-subtle text-warning-emphasis border-0 js-deadline-from-comm"
  title="Criar prazo a partir desta comunicação"
  data-comm-id="{{ comm.id }}"
  data-suggested-due="{{ comm_deadline_suggestions.get(comm.id, '') }}"
  data-comm-title="Intimação DJEN — {{ (comm.tipo_documento or comm.tipo_comunicacao or 'comunicação') | truncate(80, true, '') }}">
  <i class="bi bi-alarm"></i>
</button>
```

- [ ] **Step 4: JS do modal** — no bloco `DOMContentLoaded` existente do template:

```javascript
      // Modal de prazos: campos condicionais de audiência
      const deadlineKind = document.getElementById('deadlineKind');
      if (deadlineKind) {
        deadlineKind.addEventListener('change', function () {
          const isHearing = deadlineKind.value === 'audiencia';
          document.getElementById('deadlineTimeWrap').classList.toggle('d-none', !isHearing);
          document.getElementById('deadlineLocationWrap').classList.toggle('d-none', !isHearing);
        });
      }

      // Criar prazo a partir de uma comunicação DJEN (pré-preenche o modal)
      document.querySelectorAll('.js-deadline-from-comm').forEach(function (btn) {
        btn.addEventListener('click', function () {
          document.getElementById('deadlineCommId').value = btn.dataset.commId || '';
          document.getElementById('deadlineTitle').value = btn.dataset.commTitle || '';
          document.getElementById('deadlineDueDate').value = btn.dataset.suggestedDue || '';
          document.getElementById('deadlineSuggestionHint').classList.toggle(
            'd-none', !btn.dataset.suggestedDue);
          bootstrap.Modal.getOrCreateInstance(
            document.getElementById('newDeadlineModal')).show();
        });
      });

      // Modal aberto pelo botão "Novo" (manual): limpar vínculo/hint
      const newDeadlineModal = document.getElementById('newDeadlineModal');
      if (newDeadlineModal) {
        newDeadlineModal.addEventListener('hidden.bs.modal', function () {
          document.getElementById('deadlineCommId').value = '';
          document.getElementById('deadlineSuggestionHint').classList.add('d-none');
        });
      }
```

- [ ] **Step 5: Validar**

```bash
uv run python -c "
import re
from jinja2 import Environment
src = open('templates/process_panel/detail.html').read()
Environment().parse(src)
print('Jinja OK')
print('div diff:', len(re.findall(r'<div\\b', src)) - len(re.findall(r'</div>', src)), '(esperado: 1)')
"
```

- [ ] **Step 6: Checkpoint** — revisar diff do template.

---

### Task 5: Chip "Prazos" no header global

**Files:**
- Modify: `app/blueprints/process_panel.py` (context processor)
- Modify: `templates/partials/header.html` (chip no `.module-counters`)

**Interfaces:**
- Consumes: `process_deadline_service.firm_counts` (Task 2).
- Produces: variável de template `process_deadline_counts` = `{'overdue': int, 'soon': int}` ou `None`.

- [ ] **Step 1: Context processor** — em `process_panel.py`, seguindo o padrão do `fap_review` (barato, com try/except):

```python
@process_panel_bp.app_context_processor
def inject_process_deadline_counts():
    """Chip de prazos no header (dois COUNTs baratos com índice firm+status+due)."""
    law_firm_id = session.get('law_firm_id')
    if not law_firm_id:
        return {'process_deadline_counts': None}
    try:
        return {'process_deadline_counts': process_deadline_service.firm_counts(law_firm_id)}
    except Exception:
        return {'process_deadline_counts': None}
```

- [ ] **Step 2: Chip no header** — em `templates/partials/header.html`, linha ~18, incluir o flag e o chip (antes do chip de Monitoramento, agrupado no `.module-counters`):

```jinja
{% set show_deadlines_chip = can_view_module('process_panel') and process_deadline_counts
   and (process_deadline_counts.overdue or process_deadline_counts.soon) %}
```

Ajustar a condição do container para `{% if show_communications_chip or show_fap_review_chip or show_deadlines_chip %}` e adicionar dentro do container:

```html
{% if show_deadlines_chip %}
<a class="module-counter-chip" href="{{ url_for('process_panel.list_processes') }}"
  title="Cumprimento de Prazos — {{ process_deadline_counts.overdue }} vencido(s) · {{ process_deadline_counts.soon }} nos próximos 7 dias">
  <i class="bi bi-alarm"></i>
  <span class="mc-label">Prazos</span>
  {% if process_deadline_counts.overdue %}
  <span class="badge rounded-pill text-bg-danger">{{ process_deadline_counts.overdue if
    process_deadline_counts.overdue < 100 else '99+' }}</span>
  {% endif %}
  {% if process_deadline_counts.soon %}
  <span class="badge rounded-pill text-bg-warning">{{ process_deadline_counts.soon if
    process_deadline_counts.soon < 100 else '99+' }}</span>
  {% endif %}
</a>
{% endif %}
```

- [ ] **Step 3: Validar** — Jinja parse de `header.html` (mesmo comando da Task 4 apontando o arquivo). Checkpoint.

---

### Task 6: Advogado responsável do processo

**Files:**
- Modify: `app/blueprints/process_panel.py` (rota `edit` ~linha 2500: ler `responsible_user_id` do form; contexto com `firm_users`)
- Modify: `templates/process_panel/form.html` (select de responsável)
- Modify: `templates/process_panel/detail.html` (capa)

**Interfaces:**
- Consumes: `JudicialProcess.responsible_user_id` (Task 1), `firm_users` (padrão da Task 3).

- [ ] **Step 1: Rota `edit`** — no POST, junto aos outros campos:

```python
        responsible_user_id = request.form.get('responsible_user_id', type=int) or None
        if responsible_user_id and not User.query.filter_by(
                id=responsible_user_id, law_firm_id=law_firm_id).first():
            responsible_user_id = None
        process.responsible_user_id = responsible_user_id
```

No GET, passar `firm_users` (mesma query da Task 3) ao `render_template` do form.

- [ ] **Step 2: Select no form** — em `templates/process_panel/form.html`, junto aos campos de dados do processo (seguir o markup dos selects vizinhos, ex. fase):

```html
<div class="mb-3">
  <label class="form-label">Advogado responsável</label>
  <select class="form-select" name="responsible_user_id">
    <option value="">— sem responsável —</option>
    {% for u in firm_users %}
    <option value="{{ u.id }}" {{ 'selected' if process and process.responsible_user_id == u.id }}>
      {{ u.name }}</option>
    {% endfor %}
  </select>
</div>
```

- [ ] **Step 3: Capa** — em `detail.html`, na `cover-meta`, após o juiz:

```jinja
{% if process.responsible_user %}<span class="sep">·</span>
<span title="Advogado responsável"><i class="bi bi-person-badge me-1"></i>{{ process.responsible_user.name }}</span>{% endif %}
```

- [ ] **Step 4: Validar** — Jinja parse dos dois templates + `import OK` do blueprint. Checkpoint.

---

### Task 7: Capa com datas + `last_update` + documentos da KB + impacto FAP

**Files:**
- Modify: `app/blueprints/process_panel.py` (rota `detail`)
- Modify: `templates/process_panel/detail.html`

- [ ] **Step 1: Rota — tramitação e impacto FAP**. Antes do dict `data`:

```python
    tramitando_ha = None
    if process.filing_date:
        delta_days = (date.today() - process.filing_date).days
        if delta_days >= 365:
            years, rem = divmod(delta_days, 365)
            months = rem // 30
            tramitando_ha = f"{years} ano{'s' if years > 1 else ''}" + (
                f" e {months} mes{'es' if months > 1 else ''}" if months else '')
        elif delta_days >= 30:
            months = delta_days // 30
            tramitando_ha = f"{months} mes{'es' if months > 1 else ''}"
        else:
            tramitando_ha = f'{delta_days} dias'

    fap_impact_count = sum(
        1 for b in process_benefits
        if (b.contestation_efeito_fap or '').strip().lower() not in ('', 'não', 'nao', 'sem efeito')
    )
    fap_vigencias = sorted({b.fap_vigencia_year for b in process_benefits if b.fap_vigencia_year})
```

(Import `date` de `datetime` se ainda não houver.) Adicionar ao `data`: `'tramitando_ha': tramitando_ha, 'fap_impact_count': fap_impact_count, 'fap_vigencias': fap_vigencias,` — `kb_documents` já está no contexto.

- [ ] **Step 2: Capa — linha de ajuizamento** (na `cover-meta`, ao final):

```jinja
{% if process.filing_date %}<span class="sep">·</span>
<span>Ajuizado em {{ process.filing_date.strftime('%d/%m/%Y') }}{% if tramitando_ha %} · há {{ tramitando_ha }}{% endif %}</span>{% endif %}
```

- [ ] **Step 3: Aba Dados — `last_update`** (linha nova antes de "Criado em"):

```html
{% if process.last_update %}
<div class="d-flex justify-content-between align-items-start border-bottom pb-2">
  <small class="text-muted"><i class="bi bi-arrow-clockwise me-2 text-secondary"></i>Dados atualizados em</small>
  <strong class="text-end ms-3">{{ process.last_update.strftime('%d/%m/%Y às %H:%M') }}</strong>
</div>
{% endif %}
```

- [ ] **Step 4: Aba Documentos — seção da KB** (após a tabela de documentos, antes de fechar o pane):

```html
{% if kb_documents %}
<div class="mt-4 pt-3 border-top">
  <div class="small text-muted fw-semibold text-uppercase mb-2" style="letter-spacing:.05em;">
    <i class="bi bi-collection me-1"></i>Na Base de Conhecimento com este número de processo
  </div>
  <div class="d-flex flex-column gap-2">
    {% for kb in kb_documents %}
    <div class="radar-item">
      <i class="bi bi-file-earmark-text text-secondary"></i>
      <a href="{{ url_for('knowledge_base.view', file_id=kb.id) }}" target="_blank" rel="noopener noreferrer"
        class="text-decoration-none text-body">{{ kb.original_filename }}</a>
      {% if kb.category %}<span class="badge bg-secondary-subtle text-secondary-emphasis border">{{ kb.category }}</span>{% endif %}
      <span class="ms-date">
        <a href="{{ url_for('knowledge_base.download', file_id=kb.id) }}"
          class="btn btn-sm bg-primary-subtle text-primary-emphasis border-0 py-0 px-1" title="Baixar">
          <i class="bi bi-download"></i></a>
      </span>
    </div>
    {% endfor %}
  </div>
</div>
{% endif %}
```

- [ ] **Step 5: Widget Benefícios — linha de impacto FAP** (após o placar):

```jinja
{% if fap_impact_count %}
<div class="small text-muted mt-1">
  <i class="bi bi-graph-up-arrow me-1"></i>{{ fap_impact_count }} com efeito no FAP{% if fap_vigencias %} ·
  vigências {{ fap_vigencias | join(', ') }}{% endif %}
</div>
{% endif %}
```

- [ ] **Step 6: Validar** (Jinja parse + import). Checkpoint.

---

### Task 8: Checklist da fase atual (aba Documentos)

**Files:**
- Modify: `app/blueprints/process_panel.py` (rota `detail`)
- Modify: `templates/process_panel/detail.html`

- [ ] **Step 1: Rota** — a lista `documents_list` já é construída a partir de `judicial_documents`; incluir a chave do tipo no dict (`'doc_type_key': doc_type_key,`). Depois:

```python
    phase_checklist = []
    if current_phase_key:
        expected_types = JudicialDocumentType.query.join(JudicialPhase).filter(
            JudicialDocumentType.law_firm_id == law_firm_id,
            JudicialDocumentType.is_active.is_(True),
            JudicialPhase.key == current_phase_key,
        ).order_by(JudicialDocumentType.display_order.asc(), JudicialDocumentType.name.asc()).all()
        present_keys = {d['doc_type_key'] for d in documents_list if d.get('doc_type_key')}
        phase_checklist = [
            {'name': dt.name, 'done': dt.key in present_keys}
            for dt in expected_types
        ]
```

Adicionar `'phase_checklist': phase_checklist,` ao `data`.

- [ ] **Step 2: Template** — no topo do pane Documentos (antes do botão "Adicionar Documento"):

```html
{% if phase_checklist %}
<div class="mb-3">
  <div class="small text-muted fw-semibold text-uppercase mb-1" style="letter-spacing:.05em;">
    Documentos esperados na fase {{ current_phase_label }}
  </div>
  <div class="d-flex flex-wrap gap-1">
    {% for item in phase_checklist %}
    {% if item.done %}
    <span class="badge bg-success-subtle text-success-emphasis border border-success-subtle">
      <i class="bi bi-check-lg me-1"></i>{{ item.name }}</span>
    {% else %}
    <span class="badge bg-secondary-subtle text-secondary-emphasis border">
      <i class="bi bi-dash me-1"></i>{{ item.name }}</span>
    {% endif %}
    {% endfor %}
  </div>
</div>
{% endif %}
```

- [ ] **Step 3: Validar** (Jinja parse + import). Checkpoint.

---

### Task 9: Aba "Atividade" (linha do tempo unificada)

**Files:**
- Modify: `app/blueprints/process_panel.py` (rota `detail`)
- Modify: `templates/process_panel/detail.html` (aba + pane)

- [ ] **Step 1: Rota** — montar a lista mesclada (datas normalizadas para `datetime` naive; comunicações têm só `date`):

```python
    from datetime import time as dt_time  # junto aos imports do topo

    activity = []
    for entry in phase_history:
        if entry.occurred_at:
            activity.append({
                'when': entry.occurred_at, 'icon': 'bi-signpost-2', 'kind': 'Fase',
                'label': entry.phase.name if entry.phase else '-',
                'detail': entry.entered_by_user.name if entry.entered_by_user else 'Sistema',
                'url': None,
            })
    for doc in documents_list:
        if doc.get('uploaded_at'):
            activity.append({
                'when': doc['uploaded_at'], 'icon': 'bi-file-earmark', 'kind': 'Documento',
                'label': doc['filename'], 'detail': doc.get('doc_type_label') or '',
                'url': url_for('knowledge_base.view', file_id=doc['knowledge_base_id'])
                if doc.get('knowledge_base_id') else None,
            })
    for comm in (process.communications or []):
        if comm.data_disponibilizacao:
            activity.append({
                'when': datetime.combine(comm.data_disponibilizacao, dt_time.min),
                'icon': 'bi-broadcast', 'kind': 'DJEN',
                'label': comm.tipo_comunicacao or 'Comunicação',
                'detail': comm.nome_orgao or '',
                'url': url_for('communications.communication_detail', communication_id=comm.id),
            })
    for gdoc in generated_documents:
        if gdoc.created_at:
            activity.append({
                'when': gdoc.created_at, 'icon': 'bi-stars', 'kind': 'IA',
                'label': gdoc.title, 'detail': 'Documento gerado',
                'url': url_for('process_panel.generated_document_detail',
                               process_id=process.id, doc_id=gdoc.id),
            })
    activity.sort(key=lambda item: item['when'], reverse=True)
    activity = activity[:50]
```

Adicionar `'activity': activity,` ao `data`.

- [ ] **Step 2: Aba** — na barra, após "Dados":

```html
<li class="nav-item" role="presentation">
  <a class="nav-link" id="activity-tab" data-bs-toggle="tab" href="#activity-pane" role="tab"
    title="Linha do tempo do processo">
    <i class="bi bi-list-ul me-1"></i>Atividade
  </a>
</li>
```

- [ ] **Step 3: Pane** — após o pane "Dados", reutilizando o CSS `.phase-timeline` existente:

```html
<!-- Tab: Atividade (linha do tempo unificada) -->
<div class="tab-pane fade" id="activity-pane" role="tabpanel">
  {% if activity %}
  <div class="phase-timeline">
    {% for item in activity %}
    <div class="phase-timeline-item">
      <span class="phase-timeline-dot"><span class="visually-hidden">Evento</span></span>
      <div class="phase-timeline-card">
        <div class="d-flex flex-wrap justify-content-between align-items-start gap-2">
          <div>
            <span class="badge bg-secondary-subtle text-secondary-emphasis border">
              <i class="bi {{ item.icon }} me-1"></i>{{ item.kind }}</span>
            {% if item.url %}
            <a href="{{ item.url }}" class="ms-1 text-decoration-none">{{ item.label }}</a>
            {% else %}
            <span class="ms-1">{{ item.label }}</span>
            {% endif %}
            {% if item.detail %}<small class="text-muted d-block mt-1">{{ item.detail }}</small>{% endif %}
          </div>
          <small class="text-muted">{{ item.when.strftime('%d/%m/%Y') }}</small>
        </div>
      </div>
    </div>
    {% endfor %}
  </div>
  {% if activity|length == 50 %}
  <p class="text-muted small mt-2 mb-0">Mostrando os 50 eventos mais recentes.</p>
  {% endif %}
  {% else %}
  <div class="text-center py-4">
    <i class="bi bi-list-ul text-muted" style="font-size: 2.5rem;"></i>
    <p class="text-muted mt-3 mb-0">Nenhuma atividade registrada ainda.</p>
  </div>
  {% endif %}
</div>
```

- [ ] **Step 4: Validar** (Jinja parse + div balance + import). Checkpoint.

---

### Task 10: Verificação final

- [ ] **Step 1:** `uv run python -c "import app.blueprints.process_panel; import app.services.process_deadline_service; print('imports OK')"`
- [ ] **Step 2:** Jinja parse de `detail.html`, `form.html`, `header.html`; div balance de `detail.html` (esperado diff = 1, pré-existente).
- [ ] **Step 3:** `uv run python scripts/tests/test_process_deadline_service.py` → `[OK]`.
- [ ] **Step 4:** Roteiro manual para o usuário validar no navegador: abrir um processo → criar prazo manual → criar prazo a partir de intimação DJEN (data sugerida preenchida) → concluir/reabrir/excluir → conferir chip no header com prazo vencido → conferir capa (responsável, ajuizamento), aba Dados (última atualização), aba Documentos (checklist + KB), aba Atividade, widget Benefícios (impacto FAP).
- [ ] **Step 5:** `git status` / `git diff --stat` — apresentar resumo ao usuário (sem commit até ele pedir).

---

## Self-Review

- **Cobertura**: prazos (modelo/serviço/rotas/widget/modal/DJEN/chip) ✓; responsável ✓; capa datas ✓; last_update ✓; kb_documents ✓; checklist ✓; impacto FAP ✓; atividade ✓. E-mail ficou fora (decisão de escopo).
- **Placeholders**: nenhum "TBD"; todo step de código tem o código.
- **Consistência de nomes**: `process_deadline_service.firm_counts` (Tasks 2/5), `create_deadline`/`set_deadline_done`/`delete_deadline_route` (Tasks 3/4), `deadlines` com `{'obj','state','days_left'}` (Tasks 3/4), `firm_users` (Tasks 3/4/6), `comm_deadline_suggestions` (Tasks 3/4), `doc_type_key` (Task 8 adiciona e consome).
