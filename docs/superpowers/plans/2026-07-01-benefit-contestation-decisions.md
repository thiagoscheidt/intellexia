# Múltiplas Decisões de Contestação por Benefício — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Passar a salvar, exibir e classificar **cada análise de contestação** de um benefício FAP separadamente, sem quebrar a regra "1 benefício = 1 linha".

**Architecture:** Nova tabela filha `benefit_contestation_decisions` (1:N com `benefits`). A ingestão do relatório cria/atualiza uma decisão por análise (idempotência por fingerprint), mantém os campos planos `first/second_instance_*` do `Benefit` como espelho da análise principal, e a classificação de tópicos passa a rodar por decisão (tópicos do benefício = união). O modal do disputes_center passa a buscar as decisões sob demanda e renderiza sub-abas por instância.

**Tech Stack:** Python 3.11+, Flask 3.1, Flask-SQLAlchemy, MySQL/SQLite, Jinja2 + Bootstrap 5 (JS nativo). Deps via `uv`.

## Global Constraints

- **Multi-tenant:** toda query filtra por `law_firm_id` (sessão). Nunca expor dados de outro escritório.
- **Sem testes automatizados e sem reprocessamento de validação** (decisão do usuário): validação é manual após recriar a base. Verificações do plano limitam-se a `ast.parse`, import de model e boot do app.
- **Sem migração de dados** existentes (base é recriada via truncate / `recreate_database.py`).
- **Datetimes em UTC no banco**; exibição via filtros Jinja (`datetime_sp`).
- **Reutilizar** helpers/serviços existentes; não introduzir novas dependências; JS nativo no padrão atual.
- Commits frequentes; ao commitar, **não** commitar direto na `main` sem branch.

---

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `app/models.py` | Nova classe `BenefitContestationDecision` + relação `Benefit.contestation_decisions` |
| `app/services/fap_contestation_judgment_report_service.py` | Fingerprint/build de decisões; upsert de decisões na ingestão; espelho dos campos planos; classificação por decisão + união; ajuste do log de detalhamento |
| `app/blueprints/disputes_center.py` | Novo endpoint `GET /disputes-center/benefits/<benefit_id>/decisions` |
| `templates/disputes_center/list.html` | Botão passa a usar `data-benefit-id`; modal busca decisões e renderiza sub-abas |
| `database/add_benefit_contestation_decisions_table.py` | Migration standalone (opcional; base é recriada do model) |

---

## Task 1: Modelo `BenefitContestationDecision`

**Files:**
- Modify: `app/models.py` (após a classe `Benefit`, ~linha 1710; e a relação dentro de `Benefit`, ~linha 1707)

**Interfaces:**
- Produces: classe `BenefitContestationDecision` com colunas `id, law_firm_id, benefit_id, report_id, instancia, sequence, status, status_raw, justification, opinion, source_page, fingerprint, fap_contestation_topics_json, created_at, updated_at`; relação `Benefit.contestation_decisions` (list de `BenefitContestationDecision`).

- [ ] **Step 1: Adicionar a relação em `Benefit`**

Em `app/models.py`, dentro de `class Benefit`, logo após o bloco `manual_history = db.relationship(...)` (~linha 1707), inserir:

```python
    contestation_decisions = db.relationship(
        'BenefitContestationDecision',
        back_populates='benefit',
        cascade='all, delete-orphan',
        order_by='BenefitContestationDecision.instancia, BenefitContestationDecision.sequence',
    )
```

- [ ] **Step 2: Criar a classe `BenefitContestationDecision`**

Em `app/models.py`, imediatamente após o fim da classe `Benefit` (após o `__repr__`, ~linha 1711, antes de `class BenefitFapSourceHistory`), inserir:

```python
class BenefitContestationDecision(db.Model):
    """Uma análise/insumo de contestação FAP de um benefício.

    Um mesmo benefício (NB) pode ser analisado várias vezes no relatório —
    uma vez por insumo do cálculo do FAP (ex.: CAT e 'Nexo Técnico sem CAT'),
    cada uma com justificativa, parecer e status próprios, na mesma instância.
    Esta tabela guarda cada análise separadamente; os campos planos em `benefits`
    permanecem como espelho da análise principal (sequence=0) de cada instância.
    """
    __tablename__ = 'benefit_contestation_decisions'
    __table_args__ = (
        db.UniqueConstraint(
            'law_firm_id', 'benefit_id', 'fingerprint',
            name='uq_benefit_decision_fingerprint',
        ),
        db.Index(
            'ix_benefit_decisions_lookup',
            'law_firm_id', 'benefit_id', 'instancia', 'sequence',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    benefit_id = db.Column(db.Integer, db.ForeignKey('benefits.id'), nullable=False, index=True)
    report_id = db.Column(
        db.Integer, db.ForeignKey('fap_contestation_judgment_reports.id'), index=True
    )

    instancia = db.Column(db.SmallInteger, nullable=False)  # 1 ou 2
    sequence = db.Column(db.Integer, nullable=False, default=0)

    status = db.Column(db.String(30), index=True)
    status_raw = db.Column(db.String(255))
    justification = db.Column(db.Text)
    opinion = db.Column(db.Text)

    source_page = db.Column(db.Integer)  # best-effort; pode ser NULL
    fingerprint = db.Column(db.String(64), nullable=False)
    fap_contestation_topics_json = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    benefit = db.relationship('Benefit', back_populates='contestation_decisions')

    def __repr__(self):
        return f'<BenefitContestationDecision benefit={self.benefit_id} inst={self.instancia} seq={self.sequence}>'
```

- [ ] **Step 3: Verificar sintaxe**

Run: `uv run python -c "import ast; ast.parse(open('app/models.py', encoding='utf-8').read()); print('AST OK')"`
Expected: `AST OK`

- [ ] **Step 4: Verificar que o model importa e mapeia**

Run: `uv run python -c "from app.models import BenefitContestationDecision, Benefit; print(BenefitContestationDecision.__tablename__); print('rel:', 'contestation_decisions' in [r.key for r in Benefit.__mapper__.relationships])"`
Expected: `benefit_contestation_decisions` e `rel: True`

- [ ] **Step 5: Commit**

```bash
git add app/models.py
git commit -m "feat(models): add BenefitContestationDecision table"
```

---

## Task 2: Ingestão — criar/atualizar decisões por análise

**Files:**
- Modify: `app/services/fap_contestation_judgment_report_service.py`
  - imports (topo, ~linha 1-32)
  - método `_upsert_benefits_from_report` (loop ~2195-2308 e o bloco de detalhamento ~2311)

**Interfaces:**
- Consumes: `BenefitContestationDecision` (Task 1); `parse_block` já devolve `first_instance_status/status_raw/justification/opinion` e `second_instance_*`.
- Produces: helper `_decision_fingerprint(instancia, justification, opinion) -> str`; helper `_extract_block_decisions(item) -> list[dict]`; método `_upsert_benefit_decisions(report, benefit, item, seq_state) -> tuple[int, int]` (criadas, atualizadas).

- [ ] **Step 1: Importar `BenefitContestationDecision` e `hashlib`**

No topo do arquivo, no bloco `from app.models import (...)` (~linha 17-32), adicionar `BenefitContestationDecision,` à lista de imports. E logo abaixo de `import gc` (~linha inicial), adicionar:

```python
import hashlib
```

- [ ] **Step 2: Adicionar os helpers de decisão (métodos estáticos na classe)**

Inserir antes de `_upsert_benefits_from_report` (~linha 2155):

```python
    @staticmethod
    def _decision_fingerprint(instancia: int, justification: str | None, opinion: str | None) -> str:
        """Impressão estável de uma análise para idempotência (upsert por conteúdo)."""
        norm_just = FapContestationJudgmentReportService._text_fingerprint(justification or '')
        norm_op = FapContestationJudgmentReportService._text_fingerprint(opinion or '')
        raw = f'{int(instancia)}|{norm_just}|{norm_op}'
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    @staticmethod
    def _extract_block_decisions(item: dict) -> list[dict]:
        """Converte um bloco parseado em 0..2 análises (uma por instância presente)."""
        decisions: list[dict] = []
        instances = (
            (1, 'first_instance_status', 'first_instance_status_raw',
             'first_instance_justification', 'first_instance_opinion'),
            (2, 'second_instance_status', 'second_instance_status_raw',
             'second_instance_justification', 'second_instance_opinion'),
        )
        for instancia, status_key, status_raw_key, just_key, op_key in instances:
            status = item.get(status_key)
            status_raw = item.get(status_raw_key)
            justification = item.get(just_key)
            opinion = item.get(op_key)
            # Só cria decisão se a instância tem algum conteúdo real.
            if not any([status, status_raw, justification, opinion]):
                continue
            decisions.append({
                'instancia': instancia,
                'status': status,
                'status_raw': status_raw,
                'justification': justification,
                'opinion': opinion,
            })
        return decisions
```

- [ ] **Step 3: Adicionar o método de upsert de decisões**

Inserir logo após os helpers do Step 2:

```python
    def _upsert_benefit_decisions(
        self,
        report: FapContestationJudgmentReport,
        benefit: Benefit,
        item: dict,
        seq_state: dict[tuple[int, int], int],
    ) -> tuple[int, int]:
        """Cria/atualiza as decisões de um bloco. Retorna (criadas, atualizadas).

        seq_state mapeia (benefit_id, instancia) -> próximo sequence, garantindo
        ordenação estável das sub-abas entre blocos do mesmo relatório.
        """
        created = 0
        updated = 0
        for dec in self._extract_block_decisions(item):
            fingerprint = self._decision_fingerprint(
                dec['instancia'], dec['justification'], dec['opinion']
            )
            existing = BenefitContestationDecision.query.filter_by(
                law_firm_id=report.law_firm_id,
                benefit_id=benefit.id,
                fingerprint=fingerprint,
            ).first()

            if existing is not None:
                existing.report_id = report.id
                existing.status = dec['status']
                existing.status_raw = dec['status_raw']
                existing.updated_at = datetime.now()
                updated += 1
                continue

            key = (benefit.id, dec['instancia'])
            if key not in seq_state:
                seq_state[key] = (
                    BenefitContestationDecision.query
                    .filter_by(
                        law_firm_id=report.law_firm_id,
                        benefit_id=benefit.id,
                        instancia=dec['instancia'],
                    )
                    .count()
                )
            sequence = seq_state[key]
            seq_state[key] = sequence + 1

            db.session.add(BenefitContestationDecision(
                law_firm_id=report.law_firm_id,
                benefit_id=benefit.id,
                report_id=report.id,
                instancia=dec['instancia'],
                sequence=sequence,
                status=dec['status'],
                status_raw=dec['status_raw'],
                justification=dec['justification'],
                opinion=dec['opinion'],
                fingerprint=fingerprint,
            ))
            created += 1
        return created, updated
```

- [ ] **Step 4: Chamar o upsert de decisões dentro do loop e contabilizar**

Em `_upsert_benefits_from_report`, logo antes do `for item in extracted_benefits:` (onde hoje ficam `empty_number_count`/`number_counts`), adicionar os acumuladores:

```python
        seq_state: dict[tuple[int, int], int] = {}
        decisions_created = 0
        decisions_updated = 0
```

Dentro do loop, **depois** do bloco que insere o `BenefitFapSourceHistory` (após `db.session.execute(history_upsert_stmt)`) e **antes** de `if should_apply_update: imported_count += 1`, inserir:

```python
            d_created, d_updated = self._upsert_benefit_decisions(report, benefit, item, seq_state)
            decisions_created += d_created
            decisions_updated += d_updated
```

- [ ] **Step 5: Atualizar o log de detalhamento**

No bloco de detalhamento (final do método, onde hoje imprime `blocos=... | distintos=... | duplicados=... | sem_número=... | aplicados=...`), trocar a linha do `print` do resumo por:

```python
        print(
            f'Relatório #{report.id} | detalhamento benefícios: '
            f'blocos={total_blocks} | distintos={distinct_numbers} | '
            f'sem_número={empty_number_count} | aplicados={imported_count} | '
            f'decisões(criadas={decisions_created}, atualizadas={decisions_updated})'
        )
```

Manter o bloco `if repeated:` que lista os NBs repetidos (continua útil como diagnóstico).

- [ ] **Step 6: Verificar sintaxe**

Run: `uv run python -c "import ast; ast.parse(open('app/services/fap_contestation_judgment_report_service.py', encoding='utf-8').read()); print('AST OK')"`
Expected: `AST OK`

- [ ] **Step 7: Verificar import do serviço**

Run: `uv run python -c "from app.services.fap_contestation_judgment_report_service import FapContestationJudgmentReportService as S; print(hasattr(S, '_upsert_benefit_decisions'), hasattr(S, '_decision_fingerprint'))"`
Expected: `True True`

- [ ] **Step 8: Commit**

```bash
git add app/services/fap_contestation_judgment_report_service.py
git commit -m "feat(fap): persist one contestation decision per analysis block"
```

---

## Task 3: Classificação por decisão + união no benefício

**Files:**
- Modify: `app/services/fap_contestation_judgment_report_service.py`
  - `_build_benefit_classification_text` (adicionar variante por decisão, ~linha 49)
  - `classify_benefits_contestation_topics` (iterar decisões, ~linha 344)

**Interfaces:**
- Consumes: `BenefitContestationDecision` (Task 1); `self.classifier_agent.classify(text, law_firm_id=...)`; `_extract_topics_from_classifier_result`, `_persist_benefit_topics`.
- Produces: `_build_decision_classification_text(decision, benefit) -> str`; comportamento novo de `classify_benefits_contestation_topics` que grava tópicos em cada decisão e recomputa a união no benefício.

- [ ] **Step 1: Variante de texto de classificação por decisão**

Inserir após `_build_benefit_classification_text` (~linha 87):

```python
    @staticmethod
    def _build_decision_classification_text(decision, benefit: Benefit) -> str:
        """Monta o texto de classificação de UMA decisão (usa o cabeçalho de contexto do benefício)."""
        selected_value = decision.justification or decision.opinion
        if not selected_value or not str(selected_value).strip():
            return ''
        justification_text = FapContestationJudgmentReportService._clean_classification_text_block(
            str(selected_value)
        )
        context_lines = FapContestationJudgmentReportService._build_benefit_context_lines(benefit)
        if context_lines:
            return f"{chr(10).join(context_lines)}\n\n{justification_text}".strip()
        return justification_text
```

- [ ] **Step 2: Reescrever `classify_benefits_contestation_topics` para iterar decisões**

Substituir o corpo do método `classify_benefits_contestation_topics` pela versão que classifica cada decisão e recompõe a união no benefício. Trecho central (após `with self.app.app_context():`, substituindo a montagem de `benefits`/`tasks` e o loop):

```python
        with self.app.app_context():
            effective_batch_size = max(1, int(batch_size))

            dec_query = BenefitContestationDecision.query
            if benefit_id is not None:
                dec_query = dec_query.filter(BenefitContestationDecision.benefit_id == benefit_id)
            if law_firm_id is not None:
                dec_query = dec_query.filter(BenefitContestationDecision.law_firm_id == law_firm_id)
            if not force_reclassify:
                dec_query = dec_query.filter(
                    (BenefitContestationDecision.fap_contestation_topics_json.is_(None))
                    | (BenefitContestationDecision.fap_contestation_topics_json == '')
                )

            decisions = dec_query.order_by(BenefitContestationDecision.id.asc()).all()
            if not decisions:
                print('Nenhuma decisão elegível para classificação.')
                return {'total': 0, 'classified': 0, 'errors': 0, 'updated': 0}

            total = len(decisions)
            classified = 0
            errors = 0
            benefits_touched: set[int] = set()

            for index, decision in enumerate(decisions, start=1):
                try:
                    text = self._build_decision_classification_text(decision, decision.benefit)
                    result = self.classifier_agent.classify(text, law_firm_id=decision.law_firm_id)
                    topics = self._extract_topics_from_classifier_result(result)
                    decision.fap_contestation_topics_json = json.dumps(topics, ensure_ascii=False)
                    benefits_touched.add(decision.benefit_id)
                    classified += 1
                except Exception as exc:
                    errors += 1
                    print(f'Erro ao classificar decisão #{decision.id}: {exc}')

                if index % effective_batch_size == 0:
                    db.session.commit()
                    print(f'Classificação de decisões: {index}/{total} (erros={errors})')

            db.session.commit()

            # Recompõe a união dos tópicos em cada benefício tocado.
            updated = 0
            for b_id in benefits_touched:
                benefit = db.session.get(Benefit, b_id)
                if benefit is None:
                    continue
                merged: list[str] = []
                for dec in benefit.contestation_decisions:
                    for topic in self._parse_topics_json(dec.fap_contestation_topics_json):
                        if topic not in merged:
                            merged.append(topic)
                if self._persist_benefit_topics(benefit, merged):
                    updated += 1
            db.session.commit()

            print(f'Classificação concluída: total={total}, classificados={classified}, erros={errors}, benefícios_atualizados={updated}')
            return {'total': total, 'classified': classified, 'errors': errors, 'updated': updated}
```

- [ ] **Step 3: Adicionar helper `_parse_topics_json`**

Inserir junto aos demais staticmethods (após `_extract_topics_from_classifier_result`, ~linha 306):

```python
    @staticmethod
    def _parse_topics_json(raw_json: str | None) -> list[str]:
        """Lê uma lista de tópicos de um campo JSON, tolerante a valor inválido/vazio."""
        raw = str(raw_json or '').strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except Exception:
            return []
        if not isinstance(parsed, list):
            return []
        result: list[str] = []
        for item in parsed:
            topic = str(item or '').strip()
            if topic and topic not in result:
                result.append(topic)
        return result
```

- [ ] **Step 4: Verificar sintaxe e import**

Run: `uv run python -c "import ast; ast.parse(open('app/services/fap_contestation_judgment_report_service.py', encoding='utf-8').read()); print('AST OK')"`
Expected: `AST OK`

Run: `uv run python -c "from app.services.fap_contestation_judgment_report_service import FapContestationJudgmentReportService as S; print(hasattr(S, '_build_decision_classification_text'), hasattr(S, '_parse_topics_json'))"`
Expected: `True True`

- [ ] **Step 5: Commit**

```bash
git add app/services/fap_contestation_judgment_report_service.py
git commit -m "feat(fap): classify contestation topics per decision, union onto benefit"
```

---

## Task 4: Endpoint de decisões (disputes_center)

**Files:**
- Modify: `app/blueprints/disputes_center.py` (adicionar rota + imports necessários)

**Interfaces:**
- Consumes: `BenefitContestationDecision`, `Benefit` (Task 1); helper de tenant `get_current_law_firm_id()` (padrão do blueprint) ou `session.get('law_firm_id')`.
- Produces: rota `GET /disputes-center/benefits/<int:benefit_id>/decisions` → JSON `{benefit_number, insured_name, decisions: [...]}`.

- [ ] **Step 1: Garantir imports no blueprint**

Em `app/blueprints/disputes_center.py`, confirmar que `jsonify`, `session` estão importados de `flask` e que os models estão acessíveis. Adicionar ao import de models (se ausente) `Benefit, BenefitContestationDecision`. E `import json` no topo, se ainda não houver.

- [ ] **Step 2: Adicionar a rota**

Adicionar (junto às demais rotas do `disputes_center_bp`):

```python
@disputes_center_bp.route('/benefits/<int:benefit_id>/decisions', methods=['GET'])
def benefit_decisions(benefit_id):
    """Retorna as decisões de contestação de um benefício (multi-tenant)."""
    law_firm_id = session.get('law_firm_id')
    if not law_firm_id:
        return jsonify({'error': 'Escritório não identificado na sessão.'}), 401

    benefit = Benefit.query.filter_by(id=benefit_id, law_firm_id=law_firm_id).first()
    if benefit is None:
        return jsonify({'error': 'Benefício não encontrado.'}), 404

    decisions = (
        BenefitContestationDecision.query
        .filter_by(law_firm_id=law_firm_id, benefit_id=benefit_id)
        .order_by(
            BenefitContestationDecision.instancia.asc(),
            BenefitContestationDecision.sequence.asc(),
        )
        .all()
    )

    def _topics(raw):
        raw = str(raw or '').strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return [str(t).strip() for t in parsed if str(t).strip()] if isinstance(parsed, list) else []
        except Exception:
            return []

    return jsonify({
        'benefit_number': benefit.benefit_number,
        'insured_name': benefit.insured_name or '',
        'decisions': [
            {
                'instancia': d.instancia,
                'sequence': d.sequence,
                'status': d.status or '',
                'status_raw': d.status_raw or '',
                'justification': d.justification or '',
                'opinion': d.opinion or '',
                'source_page': d.source_page,
                'topics': _topics(d.fap_contestation_topics_json),
            }
            for d in decisions
        ],
    })
```

- [ ] **Step 3: Verificar sintaxe e boot do app**

Run: `uv run python -c "import ast; ast.parse(open('app/blueprints/disputes_center.py', encoding='utf-8').read()); print('AST OK')"`
Expected: `AST OK`

Run: `uv run python -c "from main import app; print('/disputes-center/benefits/<int:benefit_id>/decisions' in [str(r.rule) for r in app.url_map.iter_rules()])"`
Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add app/blueprints/disputes_center.py
git commit -m "feat(disputes): add benefit decisions endpoint"
```

---

## Task 5: Modal com fetch + sub-abas por instância

**Files:**
- Modify: `templates/disputes_center/list.html`
  - botão da tabela (~linha 1184-1199)
  - função que popula o modal (~linha 2026-2143)

**Interfaces:**
- Consumes: endpoint `GET /disputes-center/benefits/<id>/decisions` (Task 4).
- Produces: modal renderiza sub-abas por instância; botão carrega apenas `data-benefit-id`, `data-benefit-number`, `data-benefit-insured`.

- [ ] **Step 1: Enxugar o botão da tabela**

Substituir o bloco do botão (que hoje injeta `data-first-justification`, `data-second-opinion`, etc.) por um botão leve. O `render` da coluna de ações passa a ser:

```javascript
        render: function (_, __, row) {
          return `
              <div class="d-flex flex-wrap justify-content-center gap-2">
                <button type="button" class="btn btn-outline-primary btn-sm" data-bs-toggle="modal"
                  data-bs-target="#benefitDecisionModal"
                  data-benefit-id="${escapeAttr(row.id || '')}"
                  data-benefit-number="${escapeAttr(row.benefit_number || '')}"
                  data-benefit-insured="${escapeAttr(row.insured_name || '')}"
                  title="Ver decisões" aria-label="Ver decisões">
                  <i class="bi bi-card-list"></i>
                </button>
              </div>`;
        }
```

(Remover as variáveis `firstJustification/firstOpinion/secondJustification/secondOpinion` e `encodeMultilineAttr` associadas a esse render, se não usadas em outro lugar.)

- [ ] **Step 2: Adicionar containers de sub-abas no HTML do modal**

Dentro de cada coluna do modal (1ª e 2ª instância), envolver o conteúdo atual num container que o JS vai preencher. Adicionar, no topo do `card-body` de cada coluna, um ponto de montagem:

```html
                  <ul class="nav nav-tabs nav-tabs-sm mb-2 d-none" id="decisionFirstTabs" role="tablist"></ul>
```

(idem `decisionSecondTabs` na coluna da 2ª instância). O conteúdo Status/Justificativa/Parecer existente é preenchido pela decisão selecionada.

- [ ] **Step 3: Reescrever a função de popular o modal para buscar via fetch**

Na função que hoje lê os `data-*` (`benefitDecisionModal` `show.bs.modal`), trocar a leitura de atributos por um fetch das decisões e renderização por instância:

```javascript
  (function () {
    const modal = document.getElementById('benefitDecisionModal');
    if (!modal) return;

    const numberEl = document.getElementById('benefitDecisionNumber');
    const subtitleEl = document.getElementById('benefitDecisionSubtitle');

    function renderInstance(prefix, decisions) {
      const tabs = document.getElementById(prefix + 'Tabs');
      const statusEl = document.getElementById(prefix + 'Status');
      const statusRawEl = document.getElementById(prefix + 'StatusRaw');
      const justEl = document.getElementById(prefix + 'Justification');
      const opinionEl = document.getElementById(prefix + 'Opinion');

      function show(dec) {
        if (statusEl) statusEl.textContent = dec ? (dec.status || '-') : '-';
        if (statusRawEl) statusRawEl.textContent = dec ? (dec.status_raw || '') : '';
        if (justEl) justEl.textContent = dec ? (dec.justification || 'Não informado') : 'Não informado';
        if (opinionEl) opinionEl.textContent = dec ? (dec.opinion || 'Não informado') : 'Não informado';
      }

      if (!decisions.length) { tabs.classList.add('d-none'); tabs.innerHTML = ''; show(null); return; }

      if (decisions.length === 1) { tabs.classList.add('d-none'); tabs.innerHTML = ''; show(decisions[0]); return; }

      tabs.classList.remove('d-none');
      tabs.innerHTML = '';
      decisions.forEach((dec, i) => {
        const li = document.createElement('li');
        li.className = 'nav-item';
        const btn = document.createElement('button');
        btn.className = 'nav-link' + (i === 0 ? ' active' : '');
        btn.type = 'button';
        btn.textContent = 'Análise ' + (i + 1) + (dec.source_page ? ' (p.' + dec.source_page + ')' : '');
        btn.addEventListener('click', () => {
          tabs.querySelectorAll('.nav-link').forEach(n => n.classList.remove('active'));
          btn.classList.add('active');
          show(dec);
        });
        li.appendChild(btn);
        tabs.appendChild(li);
      });
      show(decisions[0]);
    }

    modal.addEventListener('show.bs.modal', function (event) {
      const trigger = event.relatedTarget;
      const benefitId = trigger ? trigger.getAttribute('data-benefit-id') : null;
      const number = trigger ? (trigger.getAttribute('data-benefit-number') || '') : '';
      const insured = trigger ? (trigger.getAttribute('data-benefit-insured') || '') : '';

      if (numberEl) numberEl.textContent = number;
      if (subtitleEl) subtitleEl.textContent = insured ? (`NB ${number} — ${insured}`) : (`NB ${number}`);

      renderInstance('decisionFirst', []);
      renderInstance('decisionSecond', []);
      if (!benefitId) return;

      fetch(`/disputes-center/benefits/${benefitId}/decisions`, { headers: { 'Accept': 'application/json' } })
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(data => {
          const first = (data.decisions || []).filter(d => d.instancia === 1);
          const second = (data.decisions || []).filter(d => d.instancia === 2);
          renderInstance('decisionFirst', first);
          renderInstance('decisionSecond', second);
        })
        .catch(() => {
          if (subtitleEl) subtitleEl.textContent = 'Não foi possível carregar as decisões.';
        });
    });
  })();
```

(Se já existir um IIFE antigo lendo `data-first-justification` etc., **substituí-lo** por este.)

- [ ] **Step 4: Boot do app + carregar a página manualmente**

Run: `uv run python -c "from main import app; c = app.test_client(); print('app OK')"`
Expected: `app OK`

Verificação manual (usuário, após recriar a base e processar): abrir o disputes_center, clicar no botão de decisões de um NB com múltiplas análises e confirmar as sub-abas.

- [ ] **Step 5: Commit**

```bash
git add templates/disputes_center/list.html
git commit -m "feat(disputes): modal fetches decisions and renders sub-tabs per instance"
```

---

## Task 6 (opcional): Migration standalone

**Files:**
- Create: `database/add_benefit_contestation_decisions_table.py`

**Interfaces:**
- Consumes: `main.app`, `app.models.db`, `BenefitContestationDecision`.

> Opcional: a base é recriada do model (dev/`recreate_database.py`). Este script serve apenas para ambientes que não recriam.

- [ ] **Step 1: Criar o script de migration**

```python
#!/usr/bin/env python3
"""Cria a tabela benefit_contestation_decisions (idempotente)."""
from main import app
from app.models import db, BenefitContestationDecision
from sqlalchemy import inspect


def main() -> None:
    with app.app_context():
        inspector = inspect(db.engine)
        table_name = BenefitContestationDecision.__tablename__
        if table_name in inspector.get_table_names():
            print(f'Tabela {table_name} já existe — nada a fazer.')
            return
        BenefitContestationDecision.__table__.create(bind=db.engine)
        print(f'Tabela {table_name} criada com sucesso.')


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Verificar sintaxe**

Run: `uv run python -c "import ast; ast.parse(open('database/add_benefit_contestation_decisions_table.py', encoding='utf-8').read()); print('AST OK')"`
Expected: `AST OK`

- [ ] **Step 3: Commit**

```bash
git add database/add_benefit_contestation_decisions_table.py
git commit -m "chore(db): optional migration for benefit_contestation_decisions"
```

---

## Self-Review (cobertura do spec)

- **§3 Modelo** → Task 1 ✅ (tabela, unique fingerprint, índice, relação, campos planos mantidos).
- **§4 Ingestão** → Task 2 ✅ (decisões por bloco, upsert por fingerprint, sequence, log).
- **§4 Espelho dos campos planos** → **já existe** no `_upsert_benefits_from_report` atual (bloco `should_apply_update` que popula `first/second_instance_*`); Task 2 não o remove — a análise principal continua espelhada. ✅
- **§5 Classificação por decisão + união** → Task 3 ✅.
- **§6 API + Modal** → Tasks 4 e 5 ✅ (endpoint tenant-safe; botão leve; fetch; sub-abas; estados de erro).
- **§7 Migration opcional** → Task 6 ✅.
- **Fora de escopo** (testes, reprocessamento, migração de dados, source_page populado) respeitado; `source_page` fica nullable/best-effort (NULL) conforme decidido.

**Nota de consistência:** `_text_fingerprint`, `_clean_classification_text_block`, `_build_benefit_context_lines`, `_extract_topics_from_classifier_result`, `_persist_benefit_topics` são métodos já existentes no serviço e reutilizados aqui com os nomes corretos.
