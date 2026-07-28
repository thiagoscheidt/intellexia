# Passo "Documentos" no Wizard de Geração — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar e deixar o usuário confirmar, no wizard de geração, os documentos que alimentam o agente (contestação, anexos, peças-modelo) e restringir a geração ao que foi confirmado.

**Architecture:** Preview server-side reusa o retriever em camadas e agrega trechos por peça; a confirmação vai no form e é persistida em `confirmed_documents_json` na versão; o worker repassa `allowed_reference_ids` ao gerador/enriquecimento (filtro `MatchAny` no Qdrant) e filtra anexos por id. Wizard ganha o passo 3 "Documentos" com fetch + checkboxes.

**Tech Stack:** Flask, SQLAlchemy, Qdrant (`qdrant_client`), Jinja2/Bootstrap 5, JS nativo.

**Spec:** `docs/superpowers/specs/2026-07-28-wizard-documentos-confirmacao-design.md` (leia antes).

## Global Constraints

- `uv run python ...`; nunca pip. Migrations = script standalone idempotente em `database/`.
- Multi-tenancy: toda query filtra `law_firm_id`; o preview valida o processo como a rota de criação.
- Degradação graciosa: falha de Qdrant/embeddings no preview → `referencias: null` + `referencias_erro: true`, nunca 500; `confirmed_documents_json` malformado no worker → tratar como NULL com log.
- `NULL` em `confirmed_documents_json` = fluxo legado sem restrição; `reference_ids: []` = sem referências e sem enriquecimento.
- Sem serviços externos nos testes automatizados (Qdrant/OpenAI/DB stubados); NÃO rodar a app nem escrever em Qdrant/Meilisearch (checkout aponta para produção).
- UI em português no padrão do template atual; commits em português com trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; não fazer push.

---

### Task 1: Migration e coluna `confirmed_documents_json`

**Files:**
- Modify: `app/models.py` (classe `JudicialProcessGeneratedDocumentVersion` — procure `generation_status` nela; adicionar a coluna junto dos campos de geração)
- Create: `database/add_generated_document_confirmed_documents.py`

**Interfaces:**
- Produces: `JudicialProcessGeneratedDocumentVersion.confirmed_documents_json` (db.JSON, nullable) — consumida pelas Tasks 2 e 3.

- [ ] **Step 1: Adicionar a coluna ao modelo**

Em `app/models.py`, na classe `JudicialProcessGeneratedDocumentVersion`, após o campo `generation_status` (ou o vizinho `error_message`):

```python
    confirmed_documents_json = db.Column(db.JSON)  # {"reference_ids": [], "attachment_ids": []}; NULL = sem restrição
```

- [ ] **Step 2: Migration standalone**

```python
# database/add_generated_document_confirmed_documents.py
"""Migration: coluna confirmed_documents_json em
judicial_process_generated_document_versions (ids de peças-modelo e anexos
confirmados no wizard; NULL = fluxo legado sem restrição)."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text

with app.app_context():
    with db.engine.connect() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE judicial_process_generated_document_versions "
                "ADD COLUMN confirmed_documents_json JSON"
            ))
            conn.commit()
            print("  ✓ confirmed_documents_json adicionado")
        except Exception as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                print("  – confirmed_documents_json já existe, pulando")
            else:
                raise

    print("Migration concluída.")
```

- [ ] **Step 3: Rodar 2x (idempotência) — AUTORIZADO pelo usuário no banco compartilhado**

Run: `uv run python database/add_generated_document_confirmed_documents.py && uv run python database/add_generated_document_confirmed_documents.py`
Expected: 1ª execução `✓ ... adicionado`; 2ª `– ... já existe, pulando`.

- [ ] **Step 4: Verificar carga do modelo**

Run: `uv run python -c "from main import app; from app.models import JudicialProcessGeneratedDocumentVersion as V; app.app_context().push(); V.query.first(); print('coluna ok')"`
Expected: `coluna ok`.

- [ ] **Step 5: Commit**

```bash
git add app/models.py database/add_generated_document_confirmed_documents.py
git commit -m "Coluna confirmed_documents_json nas versões de documentos gerados"
```

---

### Task 2: Plumbing `allowed_reference_ids` (retriever → gerador → enriquecimento → worker/rota)

**Files:**
- Modify: `app/agents/legal_drafting/impugnacao_reference_retriever.py`
- Modify: `app/agents/legal_drafting/agent_generated_document.py`
- Modify: `app/agents/legal_drafting/impugnacao_enrichment_agent.py`
- Modify: `app/blueprints/process_panel.py` (worker `_run_generated_document_generation` e rota `generated_document_create`)
- Test: `scripts/tests/test_impugnacao_layered_retrieval.py` (estender)

**Interfaces:**
- Consumes: coluna da Task 1.
- Produces (consumidas pela Task 3/4):
  - `fetch_style_references(..., allowed_reference_ids: Optional[list[int]] = None)`;
  - `_hit_to_item` passa a incluir `reference_id`, `judge_name_norm`, `orgao_julgador_norm`, `orgao_julgador_origem_norm`;
  - `AgentGeneratedDocument.dispatch(..., allowed_reference_ids=None)` (repassado a `generate_impugnacao_contestacao` → `_build_style_references_block`);
  - `ImpugnacaoEnrichmentAgent.enrich(..., allowed_reference_ids=None)`;
  - form fields lidos na rota: `documents_confirmed`, `confirmed_reference_ids[]`, `confirmed_attachment_ids[]`.

- [ ] **Step 1: Estender o teste stubado (RED)**

Em `scripts/tests/test_impugnacao_layered_retrieval.py`, os `make_point` já aceitam payload arbitrário — adicionar `reference_id` aos pontos existentes (ex.: `p-judge`/`p-vara` → `reference_id=1`, `p-trf`/`p-geral` → `reference_id=2`, pontos juris → `reference_id=3`) e, no `StubQdrant.query_points`, tratar condição cujo match é `MatchAny` (`cond.match.any` → `payload.get(key) in valores`). Acrescentar ao final:

```python
# ── allowed_reference_ids ────────────────────────────────────────────
result_allowed = retriever.fetch_style_references(
    law_firm_id=1, query_text="tese", context=CTX,
    kind_plan=[("merit_by_thesis", 4)], max_chunks=4, max_chars=50_000,
    allowed_reference_ids=[2],
)
allowed_texts = [r["text"] for r in result_allowed]
check("filtro por reference_id", all(
    r.get("reference_id") == 2 for r in result_allowed) and len(result_allowed) > 0,
    f"(veio {allowed_texts})")

result_empty = retriever.fetch_style_references(
    law_firm_id=1, query_text="tese", context=CTX,
    kind_plan=[("merit_by_thesis", 4)], max_chunks=4, max_chars=50_000,
    allowed_reference_ids=[],
)
check("lista vazia -> sem consulta", result_empty == [])

check("item expõe reference_id", all("reference_id" in r for r in result_allowed))
```

Run: `uv run python scripts/tests/test_impugnacao_layered_retrieval.py`
Expected: FAIL (`TypeError: unexpected keyword argument 'allowed_reference_ids'`).

- [ ] **Step 2: Retriever**

Em `impugnacao_reference_retriever.py`:

1. `fetch_style_references` ganha kwarg `allowed_reference_ids: Optional[list[int]] = None`. Logo após os guards do topo:

```python
        if allowed_reference_ids is not None and not allowed_reference_ids:
            return []
```

2. `_build_filter` ganha kwarg `allowed_reference_ids: Optional[list[int]] = None` e, junto das demais condições:

```python
        if allowed_reference_ids:
            must.append(rest.FieldCondition(
                key="reference_id",
                match=rest.MatchAny(any=[int(rid) for rid in allowed_reference_ids]),
            ))
```

3. O `_query` interno repassa `allowed_reference_ids=allowed_reference_ids` ao `_build_filter`.
4. `_hit_to_item` inclui, junto dos campos atuais:

```python
            "reference_id": payload.get("reference_id"),
            "judge_name_norm": payload.get("judge_name_norm") or "",
            "orgao_julgador_norm": payload.get("orgao_julgador_norm") or "",
            "orgao_julgador_origem_norm": payload.get("orgao_julgador_origem_norm") or "",
```

- [ ] **Step 3: Rodar o teste (GREEN)**

Run: `uv run python scripts/tests/test_impugnacao_layered_retrieval.py`
Expected: todos os checks OK.

- [ ] **Step 4: Gerador**

Em `agent_generated_document.py`:
- `dispatch(...)` ganha `allowed_reference_ids=None` e repassa ao handler de `impugnacao_contestacao` (`generate_impugnacao_contestacao`), que repassa a `_build_style_references_block`.
- `_build_style_references_block(self, process, selections, law_firm_id, allowed_reference_ids=None)`: logo no início, após o guard de `law_firm_id`:

```python
        if allowed_reference_ids is not None and not allowed_reference_ids:
            return ""
```

  e as duas chamadas `retriever.fetch_style_references(...)` ganham `allowed_reference_ids=allowed_reference_ids,`.
- Handlers de outros tipos de documento NÃO mudam (aceitar e ignorar via `**kwargs` não é necessário — só o caminho da impugnação repassa).

- [ ] **Step 5: Enriquecimento**

Em `impugnacao_enrichment_agent.py`: `enrich(..., allowed_reference_ids=None)` e `_build_jurisprudence_context(..., allowed_reference_ids=None)`; as duas chamadas do retriever ganham `allowed_reference_ids=allowed_reference_ids,`.

- [ ] **Step 6: Worker e rota**

Em `process_panel.py`:

1. No worker `_run_generated_document_generation`, após carregar `version` (e antes de montar `agent_selections`):

```python
            confirmed = version.confirmed_documents_json
            allowed_reference_ids = None
            allowed_attachment_ids = None
            if isinstance(confirmed, dict):
                raw_refs = confirmed.get('reference_ids')
                if isinstance(raw_refs, list):
                    allowed_reference_ids = [int(r) for r in raw_refs if str(r).isdigit()]
                raw_atts = confirmed.get('attachment_ids')
                if isinstance(raw_atts, list):
                    allowed_attachment_ids = [int(a) for a in raw_atts if str(a).isdigit()]
            elif confirmed is not None:
                print(f'[GeneratedDocument] confirmed_documents_json malformado na versão {version.id} — ignorando')
```

2. No filtro de anexos (`benefit_attachments = [... for att in (benefit.attachments or []) if att.is_active and (att.description or '').strip()]`), acrescentar a condição:

```python
                    if att.is_active and (att.description or '').strip()
                    and (allowed_attachment_ids is None or att.id in allowed_attachment_ids)
```

3. Na chamada `agent.dispatch(...)`, acrescentar `allowed_reference_ids=allowed_reference_ids,`.
4. No bloco de enriquecimento: pular quando `allowed_reference_ids == []`:

```python
                if allowed_reference_ids is not None and not allowed_reference_ids:
                    print('[EnrichmentAgent] pulado — nenhuma peça-modelo confirmada.')
                else:
                    ...chamada atual, acrescentando allowed_reference_ids=allowed_reference_ids,...
```

5. Na rota `generated_document_create`, antes de criar a `version`:

```python
    confirmed_documents = None
    if request.form.get('documents_confirmed') == '1':
        def _int_list(field):
            out = []
            for raw in request.form.getlist(field):
                try:
                    out.append(int(raw))
                except (TypeError, ValueError):
                    continue
            return out
        confirmed_documents = {
            'reference_ids': _int_list('confirmed_reference_ids[]'),
            'attachment_ids': _int_list('confirmed_attachment_ids[]'),
        }
```

   e no construtor da `version`: `confirmed_documents_json=confirmed_documents,`.

- [ ] **Step 7: Smoke + regressões**

Run: `uv run python -c "import main; print('imports ok')" && uv run python scripts/tests/test_impugnacao_layered_retrieval.py && uv run python scripts/tests/test_impugnacao_process_context.py`
Expected: tudo OK.

- [ ] **Step 8: Commit**

```bash
git add app/agents/legal_drafting/impugnacao_reference_retriever.py \
        app/agents/legal_drafting/agent_generated_document.py \
        app/agents/legal_drafting/impugnacao_enrichment_agent.py \
        app/blueprints/process_panel.py \
        scripts/tests/test_impugnacao_layered_retrieval.py
git commit -m "Geração restrita às peças-modelo e anexos confirmados (allowed_reference_ids)"
```

---

### Task 3: Serviço de preview + endpoint

**Files:**
- Create: `app/services/generated_document_preview_service.py`
- Modify: `app/blueprints/process_panel.py` (rota nova, ao lado de `generated_document_status`)
- Test: `scripts/tests/test_generated_document_preview.py`

**Interfaces:**
- Consumes: `ImpugnacaoReferenceRetriever.fetch_style_references` (com os campos novos de `_hit_to_item` da Task 2), `build_reference_search_context`/`normalize_context_value` (`impugnacao_process_context`), `ImpugnacaoReferenceModel`, helpers `_resolve_latest_contestation_pdf_path` / `_resolve_latest_contestation_summary_payload` (passados como callables pela rota — o serviço NÃO importa o blueprint).
- Produces: `build_documents_preview(...)` e rota `POST /process-panel/<id>/documentos-gerados/preview-documentos` retornando o JSON do spec — consumidos pela Task 4.

- [ ] **Step 1: Escrever o teste (agregação e camada, com retriever stubado) — RED**

```python
# scripts/tests/test_generated_document_preview.py
"""Agregação do preview de documentos (retriever stubado — sem serviços).

Rodar: uv run python scripts/tests/test_generated_document_preview.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.generated_document_preview_service import (
    aggregate_reference_candidates,
)

FAILS = []


def check(label, cond, detail=""):
    if not cond:
        FAILS.append(label)
        print(f"  ✗ {label} {detail}")
    else:
        print(f"  ✓ {label}")


CTX = {
    "trf_region": "TRF4",
    "orgao_julgador_norm": "3A VARA FEDERAL",
    "judge_name_norm": "JOAO DA SILVA",
}

CHUNKS = [
    {"reference_id": 1, "section_kind": "merit_by_thesis", "thesis_catalog_id": "tese_a",
     "judge_name_norm": "JOAO DA SILVA", "orgao_julgador_norm": "3A VARA FEDERAL",
     "orgao_julgador_origem_norm": "", "trf_region": "TRF4", "text": "x"},
    {"reference_id": 1, "section_kind": "requests", "thesis_catalog_id": "tese_b",
     "judge_name_norm": "", "orgao_julgador_norm": "3A VARA FEDERAL",
     "orgao_julgador_origem_norm": "", "trf_region": "TRF4", "text": "y"},
    {"reference_id": 2, "section_kind": "jurisprudence", "thesis_catalog_id": "tese_a",
     "judge_name_norm": "", "orgao_julgador_norm": "OUTRA VARA DO PRECEDENTE",
     "orgao_julgador_origem_norm": "3A VARA FEDERAL", "trf_region": "TRF4", "text": "z"},
    {"reference_id": 3, "section_kind": "merit_by_thesis", "thesis_catalog_id": None,
     "judge_name_norm": "", "orgao_julgador_norm": "", "orgao_julgador_origem_norm": "",
     "trf_region": "TRF1", "text": "w"},
]

agg = aggregate_reference_candidates(CHUNKS, CTX)
by_id = {item["reference_id"]: item for item in agg}

check("3 peças agregadas", len(agg) == 3, f"(veio {len(agg)})")
check("peça 1 camada juiz", by_id[1]["camada"] == "juiz", f"(veio {by_id.get(1)})")
check("peça 1 teses únicas", sorted(by_id[1]["teses"]) == ["tese_a", "tese_b"])
check("peça 1 conta trechos", by_id[1]["trechos"] == 2)
check("juris usa vara de origem", by_id[2]["camada"] == "vara", f"(veio {by_id.get(2)})")
check("sem match -> geral", by_id[3]["camada"] == "geral")
check("ordem por camada", [i["reference_id"] for i in agg] == [1, 2, 3], f"(veio {[i['reference_id'] for i in agg]})")

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
```

Run: `uv run python scripts/tests/test_generated_document_preview.py`
Expected: `ModuleNotFoundError` (serviço não existe).

- [ ] **Step 2: Implementar o serviço**

```python
# app/services/generated_document_preview_service.py
"""Preview dos documentos que alimentam a geração (passo "Documentos" do wizard).

Fonte única do endpoint preview-documentos: contestação, anexos por benefício e
peças-modelo candidatas (agregadas dos trechos do retriever em camadas). A
geração NÃO usa este módulo — ela re-executa a busca restrita aos ids
confirmados.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

_LAYER_ORDER = {"juiz": 0, "vara": 1, "trf": 2, "geral": 3}

# Planos de busca do preview: mesmos kinds da geração, caps generosos para
# enumerar candidatos (o preview define o conjunto permitido, não os trechos).
_PREVIEW_SECTION_PLANS = [
    ("INTRODUCAO", [("introduction", 4), ("general", 2), ("preliminary", 2)]),
    ("PRELIMINARES", [("preliminary", 4), ("jurisprudence", 3), ("general", 2)]),
    ("MERITO", [("merit_by_thesis", 6), ("jurisprudence", 4), ("general", 2)]),
    ("PEDIDOS", [("requests", 4), ("general", 2), ("jurisprudence", 2)]),
]
_PREVIEW_THESIS_PLAN = [("merit_by_thesis", 6), ("jurisprudence", 4), ("requests", 2)]
_PREVIEW_MAX_CHUNKS = 20
_PREVIEW_MAX_CHARS = 60_000


def _chunk_layer(chunk: dict, context: dict) -> str:
    judge = (context.get("judge_name_norm") or "").strip()
    vara = (context.get("orgao_julgador_norm") or "").strip()
    trf = (context.get("trf_region") or "").strip().upper()

    if judge and (chunk.get("judge_name_norm") or "") == judge:
        return "juiz"
    vara_key = (
        "orgao_julgador_origem_norm"
        if (chunk.get("section_kind") or "") == "jurisprudence"
        else "orgao_julgador_norm"
    )
    if vara and (chunk.get(vara_key) or "") == vara:
        return "vara"
    if trf and (chunk.get("trf_region") or "").upper() == trf:
        return "trf"
    return "geral"


def aggregate_reference_candidates(chunks: list[dict], context: dict) -> list[dict]:
    """Agrega trechos por peça: melhor camada, teses únicas, contagem.

    Retorna ordenado por camada (juiz primeiro) e, dentro dela, por nº de
    trechos. Metadados de exibição (título, vara, ★) vêm do banco depois.
    """
    by_ref: dict[int, dict] = {}
    for chunk in chunks or []:
        ref_id = chunk.get("reference_id")
        if ref_id is None:
            continue
        ref_id = int(ref_id)
        entry = by_ref.setdefault(ref_id, {
            "reference_id": ref_id,
            "camada": "geral",
            "teses": [],
            "trechos": 0,
        })
        entry["trechos"] += 1
        layer = _chunk_layer(chunk, context or {})
        if _LAYER_ORDER[layer] < _LAYER_ORDER[entry["camada"]]:
            entry["camada"] = layer
        thesis = chunk.get("thesis_catalog_id")
        if thesis and thesis not in entry["teses"]:
            entry["teses"].append(thesis)

    return sorted(
        by_ref.values(),
        key=lambda item: (_LAYER_ORDER[item["camada"]], -item["trechos"], item["reference_id"]),
    )


def build_documents_preview(
    *,
    process,
    law_firm_id: int,
    document_type: str,
    parsed_selections: list[tuple[int, Optional[int]]],
    resolve_contestation_pdf: Callable,
    resolve_contestation_summary: Callable,
) -> dict:
    from app.models import (
        ImpugnacaoReferenceModel,
        JudicialLegalThesis,
        JudicialProcessBenefit,
    )
    from sqlalchemy.orm import selectinload

    is_impugnacao = document_type == "impugnacao_contestacao"

    # ── Contestação ──────────────────────────────────────────────────
    contestacao = {"aplicavel": is_impugnacao, "pdf_encontrado": False,
                   "pdf_nome": None, "resumo_encontrado": False}
    if is_impugnacao:
        try:
            pdf_path = resolve_contestation_pdf(process)
            if pdf_path:
                contestacao["pdf_encontrado"] = True
                contestacao["pdf_nome"] = os.path.basename(str(pdf_path))
            contestacao["resumo_encontrado"] = bool(
                resolve_contestation_summary(process, law_firm_id))
        except Exception as error:
            print(f"[generated_document_preview] contestação: {error}")

    # ── Anexos por benefício (mesmo filtro do worker) ────────────────
    benefit_ids = {b_id for b_id, _ in parsed_selections}
    beneficios = []
    if benefit_ids:
        benefits = (
            JudicialProcessBenefit.query
            .filter(JudicialProcessBenefit.id.in_(benefit_ids),
                    JudicialProcessBenefit.process_id == process.id)
            .options(selectinload(JudicialProcessBenefit.attachments))
            .all()
        )
        for benefit in benefits:
            anexos = [
                {"id": att.id,
                 "arquivo": att.original_filename or "",
                 "titulo": (att.description or att.original_filename or "").strip()}
                for att in (benefit.attachments or [])
                if att.is_active and (att.description or "").strip()
            ]
            beneficios.append({
                "benefit_id": benefit.id,
                "nb": benefit.benefit_number or "",
                "segurado": benefit.insured_name or "",
                "anexos": anexos,
            })

    # ── Peças-modelo candidatas (só impugnação) ──────────────────────
    referencias = None
    referencias_erro = False
    if is_impugnacao:
        try:
            from app.agents.legal_drafting.impugnacao_process_context import (
                build_reference_search_context,
            )
            from app.agents.legal_drafting.impugnacao_reference_retriever import (
                ImpugnacaoReferenceRetriever,
            )

            context = build_reference_search_context(process)
            retriever = ImpugnacaoReferenceRetriever()

            thesis_ids = {t_id for _, t_id in parsed_selections if t_id}
            theses = []
            if thesis_ids:
                theses = (
                    JudicialLegalThesis.query
                    .filter(JudicialLegalThesis.id.in_(thesis_ids),
                            JudicialLegalThesis.law_firm_id == law_firm_id)
                    .all()
                )

            all_chunks: list[dict] = []
            for section_label, kind_plan in _PREVIEW_SECTION_PLANS:
                all_chunks.extend(retriever.fetch_style_references(
                    law_firm_id=law_firm_id,
                    query_text=f"Seção da peça: {section_label} | impugnação à contestação FAP",
                    context=context,
                    kind_plan=kind_plan,
                    max_chunks=_PREVIEW_MAX_CHUNKS,
                    max_chars=_PREVIEW_MAX_CHARS,
                ))
            for thesis in theses:
                all_chunks.extend(retriever.fetch_style_references(
                    law_firm_id=law_firm_id,
                    query_text=f"Tese principal do caso: {thesis.name}",
                    context=context,
                    thesis_catalog_id=(thesis.key or None),
                    kind_plan=_PREVIEW_THESIS_PLAN,
                    max_chunks=_PREVIEW_MAX_CHUNKS,
                    max_chars=_PREVIEW_MAX_CHARS,
                ))

            aggregated = aggregate_reference_candidates(all_chunks, context)

            ref_ids = [item["reference_id"] for item in aggregated]
            refs_by_id = {}
            if ref_ids:
                refs_by_id = {
                    ref.id: ref
                    for ref in ImpugnacaoReferenceModel.query
                    .filter(ImpugnacaoReferenceModel.id.in_(ref_ids),
                            ImpugnacaoReferenceModel.law_firm_id == law_firm_id)
                    .all()
                }

            referencias = []
            for item in aggregated:
                ref = refs_by_id.get(item["reference_id"])
                if ref is None:
                    continue  # peça de outro tenant/apagada — nunca expor
                referencias.append({
                    **item,
                    "titulo": ref.title,
                    "trf_region": ref.trf_region,
                    "orgao_julgador": ref.orgao_julgador,
                    "judge_name": ref.judge_name,
                    "quality_score": float(ref.quality_score) if ref.quality_score is not None else None,
                })
        except Exception as error:
            print(f"[generated_document_preview] referências indisponíveis: {error}")
            referencias = None
            referencias_erro = True

    return {
        "contestacao": contestacao,
        "beneficios": beneficios,
        "referencias": referencias,
        "referencias_erro": referencias_erro,
    }
```

- [ ] **Step 3: Rodar o teste (GREEN)**

Run: `uv run python scripts/tests/test_generated_document_preview.py`
Expected: `OK: todos os checks passaram`.

- [ ] **Step 4: Rota no blueprint**

Em `process_panel.py`, após `generated_document_status`:

```python
@process_panel_bp.route('/<int:process_id>/documentos-gerados/preview-documentos', methods=['POST'])
@require_law_firm
def generated_document_preview(process_id):
    """Preview dos insumos da geração — consumido pelo passo Documentos do wizard."""
    law_firm_id = get_current_law_firm_id()
    process = JudicialProcess.query.filter_by(
        id=process_id, law_firm_id=law_firm_id
    ).first_or_404()

    payload = request.get_json(silent=True) or {}
    document_type = str(payload.get('document_type') or '').strip()
    if document_type not in DOCUMENT_TYPE_LABELS:
        return jsonify({'error': 'Tipo de documento inválido.'}), 400

    parsed = []
    for raw in payload.get('selections') or []:
        parts = str(raw).split(':', 1)
        try:
            b_id = int(parts[0])
            t_id = int(parts[1]) if len(parts) > 1 and parts[1] else None
            parsed.append((b_id, t_id))
        except (ValueError, IndexError):
            continue

    from app.services.generated_document_preview_service import build_documents_preview
    preview = build_documents_preview(
        process=process,
        law_firm_id=law_firm_id,
        document_type=document_type,
        parsed_selections=parsed,
        resolve_contestation_pdf=_resolve_latest_contestation_pdf_path,
        resolve_contestation_summary=_resolve_latest_contestation_summary_payload,
    )
    return jsonify(preview)
```

- [ ] **Step 5: Smoke**

Run: `uv run python -c "import main; rules=[str(r) for r in main.app.url_map.iter_rules()]; assert any('preview-documentos' in r for r in rules); print('rota ok')"`
Expected: `rota ok`.

- [ ] **Step 6: Commit**

```bash
git add app/services/generated_document_preview_service.py \
        app/blueprints/process_panel.py \
        scripts/tests/test_generated_document_preview.py
git commit -m "Preview dos documentos da geração (contestação, anexos, peças-modelo candidatas)"
```

---

### Task 4: Wizard com passo "Documentos"

**Files:**
- Modify: `templates/process_panel/generated_document_new.html` (leia o arquivo inteiro antes — 835 linhas; passos em `#wizardSteps`/`panel-N`, JS no `extra_js`)

**Interfaces:**
- Consumes: rota `process_panel.generated_document_preview` (Task 3 — JSON `{contestacao, beneficios, referencias, referencias_erro}`), form fields da Task 2 (`documents_confirmed`, `confirmed_reference_ids[]`, `confirmed_attachment_ids[]`).

Requisitos (o implementador integra ao markup/JS existentes, mantendo o estilo):

1. **Indicadores**: 4 passos — Tipo, Benefícios, **Documentos**, Revisão (`step-ind-1..4`). O painel de Revisão atual (`panel-3`) vira `panel-4` (ids internos `goToStep(2)`/botões "Anterior" ajustados).
2. **`goToStep`**: validações 1→2 e 2→3 como hoje; ao entrar no 3 chama `loadDocumentsPreview()`; ao entrar no 4 chama `buildSummary()`; o loop de reset de indicadores vai até 4.
3. **Painel 3 (Documentos)** — novo `panel-3` entre os painéis atuais, com:
   - estado de carregamento (spinner + "Analisando documentos do processo…") e estado de erro com botão "Tentar novamente";
   - card **Contestação** (só quando o tipo é impugnação): verde com nome do PDF quando `pdf_encontrado && resumo_encontrado`; alerta vermelho apontando o que falta caso contrário ("a geração falhará sem a contestação/resumo");
   - bloco **Anexos por benefício**: um grupo por item de `beneficios` (NB + segurado), checkbox pré-marcado por anexo → `<input type="checkbox" name="confirmed_attachment_ids[]" value="{id}" checked>`; sem anexos → linha discreta "Nenhum anexo descrito";
   - bloco **Peças-modelo de referência** (só impugnação): card por item de `referencias` com checkbox pré-marcado `confirmed_reference_ids[]`, título, badge de camada (`juiz`→"Mesmo juiz" bg-success, `vara`→"Mesma vara" bg-primary, `trf`→"Mesmo TRF" bg-info, `geral`→"Acervo geral" bg-secondary-subtle), TRF/vara/juiz quando existirem, teses (badges), ★ quality e "N trechos". `referencias_erro` → aviso âmbar "Busca de referências indisponível — o documento será gerado sem referências de estilo"; lista vazia → aviso neutro equivalente;
   - aviso âmbar dinâmico quando o usuário desmarca todas as peças ("será gerado sem referências de estilo");
   - hidden `<input type="hidden" name="documents_confirmed" value="1">` **dentro do form**, criado junto com o painel (sempre presente — o passo é obrigatório no fluxo novo).
4. **JS `loadDocumentsPreview()`**: coleta `document_type` + `selections[]` marcadas, faz `fetch` POST JSON na URL do preview (usar `url_for` no template), renderiza os blocos; guarda a "assinatura" da última consulta (tipo + seleções ordenadas) e só refaz o fetch se mudou; falha de rede → estado de erro com retry. Checkboxes do preview são inputs reais dentro do form (o submit já os envia).
5. **Revisão**: linha nova no summary — "Documentos confirmados: X peças-modelo · Y anexos" (contados dos checkboxes marcados) com botão "Alterar" → `goToStep(3)`.
6. Não alterar o backend neste task; nada de `|safe` sobre dados vindos do preview — usar `textContent`/template literals com escape (os dados são do próprio tenant, mas mantenha o padrão seguro: montar nós via `textContent` para título/nomes).

- [ ] **Step 1: Implementar o template/JS conforme os requisitos acima**

- [ ] **Step 2: Verificar compilação e rotas**

Run: `uv run python -c "import main; main.app.jinja_env.get_template('process_panel/generated_document_new.html'); print('template ok')"`
Expected: `template ok`.

- [ ] **Step 3: Commit**

```bash
git add templates/process_panel/generated_document_new.html
git commit -m "Wizard de geração com passo Documentos (confirmação de anexos e peças-modelo)"
```
