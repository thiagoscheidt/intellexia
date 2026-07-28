# Redesign das Referências de Impugnação — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Priorizar peças-modelo do mesmo juiz/vara/TRF na geração de impugnação e tornar as seções de tese pesquisáveis (Qdrant na geração, Meilisearch na tela).

**Architecture:** Um helper único (`impugnacao_process_context`) deriva TRF/vara/juiz do processo (CNJ + snapshot DataJud). O agente de metadados passa a extrair CNJ/vara/juiz das peças; o ingestor grava esses campos (+ `section_normalized`) no payload Qdrant e um resumo de seções (`sections_json`) no modelo. O retriever consulta em camadas (juiz → vara → TRF → geral) com merge no cliente. Um serviço novo sincroniza um índice Meilisearch dedicado para a busca textual da tela.

**Tech Stack:** Flask 3.1, SQLAlchemy (Flask-SQLAlchemy), Qdrant (`qdrant_client`), Meilisearch (`meilisearch_python_sdk`), LangChain + OpenAI, Jinja2/AdminLTE.

**Spec:** `docs/superpowers/specs/2026-07-28-referencias-impugnacao-redesign-design.md`

## Global Constraints

- Dependências via `uv` — rodar tudo com `uv run python ...`; nunca `pip`.
- Sem Alembic: migrations são scripts standalone em `database/`, idempotentes, dentro de `with app.app_context():`.
- Multi-tenancy: toda query e todo documento indexado carrega/filtra `law_firm_id`.
- Degradação graciosa: falha em Qdrant/Meilisearch/LLM nunca aborta o fluxo principal (log + fallback).
- Sem framework de testes: testes são scripts executáveis em `scripts/tests/`, rodados individualmente.
- UI em português, seguindo padrões AdminLTE/Bootstrap existentes; não mexer no fluxo de upload.
- Estilo local: agentes usam `print()` com prefixo `[NomeDaClasse]` para log.

---

### Task 1: Helper de contexto do processo + correção dos bugs de TRF

**Files:**
- Create: `app/agents/legal_drafting/impugnacao_process_context.py`
- Modify: `app/agents/legal_drafting/agent_generated_document.py:1195-1202`
- Modify: `app/blueprints/process_panel.py:3452`
- Test: `scripts/tests/test_impugnacao_process_context.py`

**Interfaces:**
- Consumes: `app/utils/cnj.tribunal_sigla_from_cnj(process_number)`, `app/services/datajud_snapshot_service.get_snapshot(process_id, law_firm_id)`.
- Produces (usado pelas Tasks 4, 6, 7):
  - `normalize_context_value(text) -> str` — caixa alta, sem acentos, espaços colapsados; `''` para vazio.
  - `normalize_section_title(text) -> str` — remove numeração inicial ("6. ", "5.1) ") e aplica `normalize_context_value`.
  - `trf_region_from_process(process) -> Optional[str]` — 'TRF1'..'TRF6' ou None.
  - `build_reference_search_context(process) -> dict` — `{'trf_region', 'orgao_julgador', 'orgao_julgador_norm', 'judge_name', 'judge_name_norm'}` (valores `None` quando ausentes).

- [ ] **Step 1: Escrever o teste que falha**

```python
# scripts/tests/test_impugnacao_process_context.py
"""Teste do helper de contexto de busca de referências de impugnação.

Rodar: uv run python scripts/tests/test_impugnacao_process_context.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.legal_drafting.impugnacao_process_context import (
    normalize_context_value,
    normalize_section_title,
    trf_region_from_process,
    build_reference_search_context,
)
import app.services.datajud_snapshot_service as djs

FAILS = []


def check(label, got, expected):
    if got != expected:
        FAILS.append(f"{label}: esperado {expected!r}, obtido {got!r}")
        print(f"  ✗ {label}: esperado {expected!r}, obtido {got!r}")
    else:
        print(f"  ✓ {label}")


# ── normalização ─────────────────────────────────────────────────────
check("normalize vazio", normalize_context_value(None), "")
# NFKD decompõe 'ª' em 'a' -> caixa alta 'A'
check(
    "normalize vara",
    normalize_context_value("  3ª Vara   Federal de Florianópolis "),
    "3A VARA FEDERAL DE FLORIANOPOLIS",
)
check(
    "normalize_section_title remove numeração",
    normalize_section_title("6. AUXÍLIO-ACIDENTE POR ACIDENTE DE TRABALHO (B94)"),
    "AUXILIO-ACIDENTE POR ACIDENTE DE TRABALHO (B94)",
)
check("normalize_section_title vazio", normalize_section_title(""), "")

# ── TRF pelo CNJ ─────────────────────────────────────────────────────
proc_cnj = SimpleNamespace(
    id=1, law_firm_id=1,
    process_number="5001234-56.2024.4.04.7200",   # segmento 4 (JF), TR 04 -> TRF4
    court=None, tribunal=None, tribunal_name="", section=None, judge_name=None,
)
check("TRF derivado do CNJ", trf_region_from_process(proc_cnj), "TRF4")

# ── TRF por texto (fallback sem CNJ) ─────────────────────────────────
proc_texto = SimpleNamespace(
    id=2, law_firm_id=1, process_number=None,
    court=SimpleNamespace(tribunal="Tribunal Regional Federal da 4ª Região",
                          orgao_julgador=None),
    tribunal=None, tribunal_name="", section=None, judge_name=None,
)
check("TRF por texto do tribunal", trf_region_from_process(proc_texto), "TRF4")

# ── contexto completo com snapshot DataJud stubado ───────────────────
djs.get_snapshot = lambda process_id, law_firm_id: SimpleNamespace(
    payload_json={"instancias": [
        {"grau": "G2", "orgao_julgador": "Gab. Des. Fulano"},
        {"grau": "G1", "orgao_julgador": "3ª Vara Federal de Florianópolis"},
    ]}
)
proc = SimpleNamespace(
    id=3, law_firm_id=1,
    process_number="5001234-56.2024.4.04.7200",
    court=None, tribunal=None, tribunal_name="", section=None,
    judge_name="  João da Silva ",
)
ctx = build_reference_search_context(proc)
check("ctx trf", ctx["trf_region"], "TRF4")
check("ctx vara (menor grau primeiro)", ctx["orgao_julgador"], "3ª Vara Federal de Florianópolis")
check("ctx vara norm", ctx["orgao_julgador_norm"], "3A VARA FEDERAL DE FLORIANOPOLIS")
check("ctx juiz", ctx["judge_name"], "João da Silva")
check("ctx juiz norm", ctx["judge_name_norm"], "JOAO DA SILVA")

# ── snapshot indisponível não pode quebrar ───────────────────────────
def _boom(process_id, law_firm_id):
    raise RuntimeError("banco fora")
djs.get_snapshot = _boom
proc_sem = SimpleNamespace(
    id=4, law_firm_id=1, process_number=None, court=None, tribunal=None,
    tribunal_name="", section="12ª Vara Federal", judge_name=None,
)
ctx2 = build_reference_search_context(proc_sem)
check("fallback vara via process.section", ctx2["orgao_julgador"], "12ª Vara Federal")
check("juiz ausente -> None", ctx2["judge_name_norm"], None)

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `uv run python scripts/tests/test_impugnacao_process_context.py`
Expected: `ModuleNotFoundError`/`ImportError` (módulo `impugnacao_process_context` não existe).

- [ ] **Step 3: Implementar o helper**

```python
# app/agents/legal_drafting/impugnacao_process_context.py
"""Contexto de busca de referências de impugnação a partir do processo.

Fonte única do TRF/vara/juiz usados para priorizar peças-modelo:
- TRF: derivado do número CNJ (fallback: texto do tribunal/órgão julgador)
- vara: snapshot DataJud (menor grau) -> Court.orgao_julgador -> process.section
- juiz: JudicialProcess.judge_name (frequentemente ausente -> None)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from app.utils.cnj import tribunal_sigla_from_cnj

_TRF_TEXT_RE = re.compile(r"\btrf\s*([1-6])\b|([1-6])\D{0,3}regi[aã]o", re.IGNORECASE)
_SECTION_NUMBER_PREFIX_RE = re.compile(r"^\s*\d{1,2}(?:\.\d+)*\s*[\.\)\-:]?\s*")


def normalize_context_value(text) -> str:
    """Caixa alta sem acentos, espaços colapsados — para match exato de vara/juiz."""
    normalized = unicodedata.normalize('NFKD', str(text or ''))
    normalized = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', normalized).strip().upper()


def normalize_section_title(text) -> str:
    """Título de seção sem numeração inicial, caixa alta sem acentos.

    Mesma remoção de numeração usada pelo gerador
    (_normalize_section_label_for_prompt).
    """
    value = _SECTION_NUMBER_PREFIX_RE.sub('', str(text or '').strip())
    return normalize_context_value(value)


def trf_region_from_process(process) -> Optional[str]:
    sigla = tribunal_sigla_from_cnj(getattr(process, 'process_number', None))
    if sigla and sigla.startswith('TRF'):
        return sigla

    court = getattr(process, 'court', None)
    candidates = [
        getattr(court, 'tribunal', None),
        getattr(court, 'orgao_julgador', None),
        getattr(process, 'tribunal', None),
        getattr(process, 'tribunal_name', None),
    ]
    for value in candidates:
        match = _TRF_TEXT_RE.search(str(value or ''))
        if match:
            return f"TRF{match.group(1) or match.group(2)}"
    return None


def orgao_julgador_from_process(process) -> Optional[str]:
    try:
        from app.services import datajud_snapshot_service
        snapshot = datajud_snapshot_service.get_snapshot(process.id, process.law_firm_id)
        instancias = ((snapshot.payload_json or {}).get('instancias') if snapshot else None) or []
        # Menor grau primeiro (G1 antes de G2): vara onde o processo tramita.
        for instancia in sorted(instancias, key=lambda i: str(i.get('grau') or 'Z')):
            nome = str(instancia.get('orgao_julgador') or '').strip()
            if nome:
                return nome
    except Exception as error:
        print(f"[impugnacao_process_context] snapshot DataJud indisponível: {error}")

    court = getattr(process, 'court', None)
    for value in (getattr(court, 'orgao_julgador', None), getattr(process, 'section', None)):
        cleaned = str(value or '').strip()
        if cleaned and cleaned.lower() not in ('none', 'null'):
            return cleaned
    return None


def build_reference_search_context(process) -> dict:
    judge = str(getattr(process, 'judge_name', '') or '').strip() or None
    orgao = orgao_julgador_from_process(process)
    return {
        'trf_region': trf_region_from_process(process),
        'orgao_julgador': orgao,
        'orgao_julgador_norm': normalize_context_value(orgao) or None,
        'judge_name': judge,
        'judge_name_norm': normalize_context_value(judge) or None,
    }
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `uv run python scripts/tests/test_impugnacao_process_context.py`
Expected: `OK: todos os checks passaram`

- [ ] **Step 5: Corrigir a detecção de TRF no gerador**

Em `app/agents/legal_drafting/agent_generated_document.py`, dentro de `_build_style_references_block` (linhas ~1195-1202), substituir:

```python
            trf_region = None
            court_name = getattr(getattr(process, 'court', None), 'name', '') or ''
            if not court_name:
                court_name = str(getattr(process, 'tribunal_name', '') or '')
            for region in ('TRF1', 'TRF2', 'TRF3', 'TRF4', 'TRF5', 'TRF6'):
                if region.lower() in court_name.lower():
                    trf_region = region
                    break
```

por:

```python
            from app.agents.legal_drafting.impugnacao_process_context import (
                build_reference_search_context,
            )
            search_context = build_reference_search_context(process)
            trf_region = search_context.get('trf_region')
```

(`search_context` será passado ao retriever na Task 7; aqui só corrige o TRF.)

- [ ] **Step 6: Corrigir o TRF do enriquecimento**

Em `app/blueprints/process_panel.py` linha ~3452, substituir:

```python
                    trf_region = getattr(process, 'trf_region', None) or ''
```

por:

```python
                    from app.agents.legal_drafting.impugnacao_process_context import (
                        trf_region_from_process,
                    )
                    trf_region = trf_region_from_process(process) or ''
```

- [ ] **Step 7: Smoke test dos imports**

Run: `uv run python -c "import main; print('imports ok')"`
Expected: `imports ok` (sem traceback).

- [ ] **Step 8: Commit**

```bash
git add app/agents/legal_drafting/impugnacao_process_context.py \
        app/agents/legal_drafting/agent_generated_document.py \
        app/blueprints/process_panel.py \
        scripts/tests/test_impugnacao_process_context.py
git commit -m "Contexto de busca de referências (TRF/vara/juiz) + correção dos bugs de TRF"
```

---

### Task 2: Migration e colunas novas no modelo

**Files:**
- Modify: `app/models.py:3183-3199` (classe `ImpugnacaoReferenceModel`)
- Create: `database/add_impugnacao_reference_context_fields.py`

**Interfaces:**
- Produces: colunas `ImpugnacaoReferenceModel.process_number` (String(30)), `.orgao_julgador` (String(255)), `.judge_name` (String(255)), `.sections_json` (JSON) — consumidas pelas Tasks 3, 5, 8, 9.

- [ ] **Step 1: Adicionar colunas ao modelo**

Em `app/models.py`, na classe `ImpugnacaoReferenceModel`, logo após a linha `quality_score = db.Column(db.Numeric(3, 2), default=Decimal('3.00'))`:

```python
    process_number = db.Column(db.String(30))     # número CNJ da peça de origem
    orgao_julgador = db.Column(db.String(255))    # vara/órgão julgador de origem
    judge_name = db.Column(db.String(255))        # magistrado, quando identificado
    sections_json = db.Column(db.JSON)            # seções detectadas na ingestão
```

- [ ] **Step 2: Escrever a migration standalone**

```python
# database/add_impugnacao_reference_context_fields.py
"""Migration: campos de contexto (CNJ/vara/juiz) e seções na tabela
impugnacao_reference_models.

Novos campos (nullable, retrocompatíveis):
    process_number, orgao_julgador, judge_name, sections_json
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text

COLUMNS = [
    ("process_number", "VARCHAR(30)"),
    ("orgao_julgador", "VARCHAR(255)"),
    ("judge_name",     "VARCHAR(255)"),
    ("sections_json",  "JSON"),
]

with app.app_context():
    with db.engine.connect() as conn:
        for col_name, col_type in COLUMNS:
            try:
                conn.execute(text(
                    f"ALTER TABLE impugnacao_reference_models ADD COLUMN {col_name} {col_type}"
                ))
                conn.commit()
                print(f"  ✓ {col_name} adicionado")
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print(f"  – {col_name} já existe, pulando")
                else:
                    raise

    print("Migration concluída.")
```

- [ ] **Step 3: Rodar a migration (duas vezes, para provar idempotência)**

Run: `uv run python database/add_impugnacao_reference_context_fields.py && uv run python database/add_impugnacao_reference_context_fields.py`
Expected: primeira execução imprime `✓ ... adicionado` para as 4 colunas; segunda imprime `– ... já existe, pulando`.

- [ ] **Step 4: Verificar que o modelo carrega**

Run: `uv run python -c "from main import app; from app.models import ImpugnacaoReferenceModel; app.app_context().push(); print(ImpugnacaoReferenceModel.query.count(), 'refs; colunas ok')"`
Expected: contagem + `colunas ok`, sem erro.

- [ ] **Step 5: Commit**

```bash
git add app/models.py database/add_impugnacao_reference_context_fields.py
git commit -m "Colunas de contexto (CNJ/vara/juiz) e sections_json nas peças-modelo"
```

---

### Task 3: Agente de metadados extrai CNJ/vara/juiz

**Files:**
- Modify: `app/agents/legal_drafting/impugnacao_reference_metadata_agent.py`
- Test: `scripts/tests/test_impugnacao_reference_metadata.py`

**Interfaces:**
- Consumes: `app/utils/cnj.cnj_digits`, `app/utils/cnj.tribunal_sigla_from_cnj`.
- Produces: `ImpugnacaoReferenceMetadata` ganha `process_number: Optional[str]`, `orgao_julgador: Optional[str]`, `judge_name: Optional[str]`. Regra: CNJ válido (20 dígitos) sobrepõe o `trf_region` do LLM. Consumido pela Task 5.

- [ ] **Step 1: Escrever o teste que falha (só a parte determinística — `_sanitize` e `_fallback`, sem LLM)**

```python
# scripts/tests/test_impugnacao_reference_metadata.py
"""Teste da sanitização de metadados de peças-modelo (sem chamada LLM).

Rodar: uv run python scripts/tests/test_impugnacao_reference_metadata.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.legal_drafting.impugnacao_reference_metadata_agent import (
    ImpugnacaoReferenceMetadata,
    ImpugnacaoReferenceMetadataAgent,
)

FAILS = []


def check(label, got, expected):
    if got != expected:
        FAILS.append(label)
        print(f"  ✗ {label}: esperado {expected!r}, obtido {got!r}")
    else:
        print(f"  ✓ {label}")


san = ImpugnacaoReferenceMetadataAgent._sanitize

# CNJ válido deriva TRF e sobrepõe o palpite do LLM
meta = san(
    ImpugnacaoReferenceMetadata(
        title="Peça X", process_number="5001234-56.2024.4.04.7200",
        trf_region="TRF1", orgao_julgador="  3ª Vara Federal de Florianópolis  ",
        judge_name=" João da Silva ", quality_score=3.0,
    ),
    "peca.pdf", "texto qualquer",
)
check("CNJ mantido", meta.process_number, "5001234-56.2024.4.04.7200")
check("TRF derivado do CNJ vence o LLM", meta.trf_region, "TRF4")
check("vara com trim", meta.orgao_julgador, "3ª Vara Federal de Florianópolis")
check("juiz com trim", meta.judge_name, "João da Silva")

# CNJ inválido é descartado; TRF do LLM permanece
meta2 = san(
    ImpugnacaoReferenceMetadata(
        title="Peça Y", process_number="12345", trf_region="TRF2",
        quality_score=3.0,
    ),
    "peca.pdf", "texto",
)
check("CNJ inválido -> None", meta2.process_number, None)
check("TRF do LLM mantido sem CNJ", meta2.trf_region, "TRF2")

# Campos ausentes seguem None; fallback não quebra
fb = ImpugnacaoReferenceMetadataAgent._fallback("minha_peca.pdf", "")
check("fallback process_number", fb.process_number, None)
check("fallback orgao_julgador", fb.orgao_julgador, None)
check("fallback judge_name", fb.judge_name, None)

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `uv run python scripts/tests/test_impugnacao_reference_metadata.py`
Expected: erro de validação Pydantic (`process_number` não existe no schema).

- [ ] **Step 3: Implementar**

Em `impugnacao_reference_metadata_agent.py`:

1. Import: `from app.utils.cnj import cnj_digits, tribunal_sigla_from_cnj`.
2. Campos novos no `ImpugnacaoReferenceMetadata`, após `case_name`:

```python
    process_number: Optional[str] = Field(
        None,
        description=(
            "Número CNJ do processo de origem da peça (formato "
            "NNNNNNN-DD.AAAA.J.TR.OOOO), se constar no texto. Null caso contrário."
        ),
    )
    orgao_julgador: Optional[str] = Field(
        None,
        description=(
            "Vara/órgão julgador do endereçamento da peça (ex.: '3ª Vara Federal "
            "de Florianópolis'). Null se não constar."
        ),
    )
    judge_name: Optional[str] = Field(
        None,
        description=(
            "Nome do(a) magistrado(a), somente se citado nominalmente no texto. "
            "Null caso contrário — nunca deduza."
        ),
    )
```

3. No `_SYSTEM_PROMPT`, adicionar às regras (antes da linha final "Em qualquer dúvida..."):

```
- process_number: número CNJ completo do processo, se aparecer (formato
  NNNNNNN-DD.AAAA.J.TR.OOOO). Copie exatamente como está; null se não constar.
- orgao_julgador: vara/órgão julgador do endereçamento (ex.: "3ª Vara Federal
  de Florianópolis"). Null se não constar.
- judge_name: nome do(a) juiz(a) SOMENTE se citado nominalmente. Null caso
  contrário — nunca deduza a partir da vara.
```

4. No `_sanitize`, após o bloco do `case_name` e ANTES do bloco do `trf_region`:

```python
        if meta.process_number is not None:
            candidate = meta.process_number.strip()
            meta.process_number = candidate[:30] if len(cnj_digits(candidate)) == 20 else None

        for attr in ("orgao_julgador", "judge_name"):
            value = getattr(meta, attr)
            if value is not None:
                cleaned = value.strip()
                setattr(meta, attr, cleaned[:250] if cleaned else None)

        # CNJ válido é fonte determinística de TRF — sobrepõe o palpite do LLM.
        cnj_sigla = tribunal_sigla_from_cnj(meta.process_number) if meta.process_number else None
        if cnj_sigla and cnj_sigla.startswith("TRF"):
            meta.trf_region = cnj_sigla
```

(Como o Pydantic model ganhou defaults `None`, `_fallback` já retorna os campos novos como `None` sem mudança.)

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `uv run python scripts/tests/test_impugnacao_reference_metadata.py`
Expected: `OK: todos os checks passaram`

- [ ] **Step 5: Commit**

```bash
git add app/agents/legal_drafting/impugnacao_reference_metadata_agent.py \
        scripts/tests/test_impugnacao_reference_metadata.py
git commit -m "Agente de metadados extrai CNJ/vara/juiz; TRF derivado do CNJ"
```

---

### Task 4: Ingestor grava contexto e seções no payload Qdrant

**Files:**
- Modify: `app/agents/legal_drafting/impugnacao_reference_ingestor.py`

**Interfaces:**
- Consumes: `normalize_context_value`, `normalize_section_title` (Task 1).
- Produces (consumido pelas Tasks 5, 6, 8):
  - `ingest_file(...)` aceita kwargs novos `process_number=None, orgao_julgador=None, judge_name=None`.
  - Payload Qdrant de todo chunk ganha: `section_normalized`, `process_number`, `orgao_julgador`, `orgao_julgador_norm`, `judge_name`, `judge_name_norm`.
  - `chunk_records` (retorno) passam a incluir `"heading"` e `"section"`.
  - Atributo `self.last_sections_summary: list[dict]` — `[{titulo, titulo_normalizado, section_kind, teses, qtd_chunks}]`.

- [ ] **Step 1: Adicionar import e estado**

No topo, junto aos imports de agentes:

```python
from app.agents.legal_drafting.impugnacao_process_context import (
    normalize_context_value,
    normalize_section_title,
)
```

No `__init__`, após `self.last_document_thesis_catalog_ids = []`:

```python
        self.last_sections_summary: list[dict] = []
```

- [ ] **Step 2: Ampliar a assinatura de `ingest_file`**

Adicionar aos kwargs (após `quality_score`):

```python
        process_number: Optional[str] = None,
        orgao_julgador: Optional[str] = None,
        judge_name: Optional[str] = None,
```

Logo no início do corpo (antes de `provided_text = ...`):

```python
        self.last_sections_summary = []
        orgao_julgador_norm = normalize_context_value(orgao_julgador) or None
        judge_name_norm = normalize_context_value(judge_name) or None
        context_payload = {
            "process_number": (process_number or "").strip() or None,
            "orgao_julgador": (orgao_julgador or "").strip() or None,
            "orgao_julgador_norm": orgao_julgador_norm,
            "judge_name": (judge_name or "").strip() or None,
            "judge_name_norm": judge_name_norm,
        }
```

- [ ] **Step 3: Enriquecer o payload dos chunks principais e acumular seções**

No loop `for order, seg in enumerate(segments):`, logo antes de `points.append(...)`, o dict `payload` ganha (após `"section": seg.get("section"),`):

```python
                "section_normalized": normalize_section_title(
                    seg.get("section") or seg.get("heading") or ""
                ) or None,
                **context_payload,
```

Após `chunk_records.append({...})` do chunk principal, incluir no dict registrado as chaves novas `"heading": seg.get("heading", "")` e `"section": seg.get("section")`, e acumular a seção:

```python
            section_title_raw = str(seg.get("section") or seg.get("heading") or "").strip()
            section_key = payload["section_normalized"] or section_title_raw or "(sem seção)"
            entry = sections_map.setdefault(section_key, {
                "titulo": section_title_raw or "(sem seção)",
                "titulo_normalizado": payload["section_normalized"] or "",
                "section_kind": payload["section_kind"],
                "teses": [],
                "qtd_chunks": 0,
            })
            entry["qtd_chunks"] += 1
            for thesis_key in chunk_thesis_catalog_ids:
                if thesis_key not in entry["teses"]:
                    entry["teses"].append(thesis_key)
```

com `sections_map: dict[str, dict] = {}` declarado antes do loop (junto de `chunk_records`/`points`), e após o loop dos chunks principais:

```python
        self.last_sections_summary = list(sections_map.values())
```

- [ ] **Step 4: Enriquecer o payload dos chunks de jurisprudência**

No dict `jpayload`, após `"reference_title": title,` adicionar `**context_payload,` — **atenção**: `jpayload` já tem chave `"orgao_julgador"` própria (órgão do precedente extraído). Para não colidir, nos chunks de jurisprudência aplicar somente:

```python
                "process_number": context_payload["process_number"],
                "judge_name": context_payload["judge_name"],
                "judge_name_norm": context_payload["judge_name_norm"],
                "orgao_julgador_origem": context_payload["orgao_julgador"],
                "orgao_julgador_origem_norm": context_payload["orgao_julgador_norm"],
```

Regra para a Task 6: o filtro de camada "mesma vara" usa `orgao_julgador_norm` nos chunks principais e `orgao_julgador_origem_norm` nos de jurisprudência — o retriever filtra com `should` interno dessas duas chaves? Não: para manter simplicidade, o filtro de vara usa **somente** `orgao_julgador_norm` (chunks principais) e, para `section_kind='jurisprudence'`, usa `orgao_julgador_origem_norm`. A Task 6 implementa essa troca de chave por kind.

- [ ] **Step 5: Smoke test**

Run: `uv run python -c "from app.agents.legal_drafting.impugnacao_reference_ingestor import ImpugnacaoReferenceIngestor; import inspect; sig = inspect.signature(ImpugnacaoReferenceIngestor.ingest_file); assert 'judge_name' in sig.parameters and 'orgao_julgador' in sig.parameters and 'process_number' in sig.parameters; print('assinatura ok')"`
Expected: `assinatura ok`

- [ ] **Step 6: Commit**

```bash
git add app/agents/legal_drafting/impugnacao_reference_ingestor.py
git commit -m "Ingestor grava contexto (CNJ/vara/juiz) e seções normalizadas no Qdrant"
```

---

### Task 5: Blueprint persiste os campos novos (criação e reindexação)

**Files:**
- Modify: `app/blueprints/impugnacao_references.py:137-258` (new_reference) e `:361-425` (reindex_reference)

**Interfaces:**
- Consumes: Tasks 2, 3, 4.
- Produces: `ImpugnacaoReferenceModel` criado/reindexado com `process_number`, `orgao_julgador`, `judge_name`, `sections_json` preenchidos.

- [ ] **Step 1: `new_reference` captura e persiste os campos novos**

No bloco de extração de metadados (após `quality_score = meta.quality_score`):

```python
        process_number = meta.process_number
        orgao_julgador = meta.orgao_julgador
        judge_name = meta.judge_name
```

Inicializar `process_number = orgao_julgador = judge_name = None` junto das outras variáveis default (linhas ~140-143), para o caminho de exceção.

No construtor `ImpugnacaoReferenceModel(...)`, após `quality_score=quality_score,`:

```python
        process_number=process_number,
        orgao_julgador=orgao_julgador,
        judge_name=judge_name,
```

Na chamada `ingestor.ingest_file(...)`, após `quality_score=quality_score,`:

```python
            process_number=process_number,
            orgao_julgador=orgao_julgador,
            judge_name=judge_name,
```

Após `reference.thesis_catalog_ids = ...`:

```python
        reference.sections_json = ingestor.last_sections_summary or []
```

- [ ] **Step 2: `reindex_reference` preenche campos vazios e atualiza seções**

Após `thesis_catalog = _load_thesis_catalog(law_firm_id)` e antes do delete dos vetores:

```python
        processed_document = ingestor._process_document(reference.file_path)

        # Backfill: peças antigas ganham os campos de contexto na reindexação.
        if not any([reference.process_number, reference.orgao_julgador, reference.judge_name]):
            try:
                from app.agents.legal_drafting.impugnacao_reference_metadata_agent import (
                    ImpugnacaoReferenceMetadataAgent,
                )
                extracted_text = str(getattr(processed_document, 'full_text', '') or '').strip()
                if extracted_text:
                    meta = ImpugnacaoReferenceMetadataAgent().extract(
                        extracted_text, original_filename=reference.original_filename,
                    )
                    reference.process_number = meta.process_number
                    reference.orgao_julgador = meta.orgao_julgador
                    reference.judge_name = meta.judge_name
                    if not reference.trf_region and meta.trf_region:
                        reference.trf_region = meta.trf_region
            except Exception as error:
                print(f'[impugnacao_references.reindex] backfill de metadados falhou: {error}')
```

Na chamada `ingest_file` da reindexação, trocar `processed_document=ingestor._process_document(reference.file_path)` por `processed_document=processed_document` e adicionar:

```python
            process_number=reference.process_number,
            orgao_julgador=reference.orgao_julgador,
            judge_name=reference.judge_name,
```

Após `reference.thesis_catalog_ids = ...` da reindexação:

```python
        reference.sections_json = ingestor.last_sections_summary or []
```

- [ ] **Step 3: Smoke test dos imports**

Run: `uv run python -c "import main; print('imports ok')"`
Expected: `imports ok`

- [ ] **Step 4: Teste manual guiado (requer Qdrant + OpenAI ativos)**

Com a app rodando (`uv run python main.py`), em outra shell:

Run: `uv run python -c "
from main import app
from app.models import ImpugnacaoReferenceModel
app.app_context().push()
ref = ImpugnacaoReferenceModel.query.order_by(ImpugnacaoReferenceModel.id.desc()).first()
print('última ref:', ref.id if ref else None, '| cnj:', ref.process_number if ref else '-', '| vara:', ref.orgao_julgador if ref else '-', '| seções:', len(ref.sections_json or []) if ref else 0)
"`

Depois reindexar uma peça existente pela tela (`/referencias-impugnacao/<id>` → Reindexar) e rodar o comando de novo.
Expected: após reindexar, `seções: N > 0`; `cnj`/`vara` preenchidos se constarem na peça.

- [ ] **Step 5: Commit**

```bash
git add app/blueprints/impugnacao_references.py
git commit -m "Criação e reindexação persistem contexto e sections_json das peças-modelo"
```

---

### Task 6: Retriever com camadas juiz → vara → TRF → geral

**Files:**
- Modify: `app/agents/legal_drafting/impugnacao_reference_retriever.py`
- Test: `scripts/tests/test_impugnacao_layered_retrieval.py`

**Interfaces:**
- Consumes: payload Qdrant da Task 4 (`orgao_julgador_norm`, `orgao_julgador_origem_norm`, `judge_name_norm`, `trf_region`).
- Produces (consumido pela Task 7): `fetch_style_references(..., context: Optional[dict] = None)` — `context` no formato de `build_reference_search_context`. O kwarg `trf_region` continua aceito (vira contexto mínimo quando `context` é None). Remoção do `should` no filtro.

- [ ] **Step 1: Escrever o teste que falha (Qdrant stubado — sem infra)**

```python
# scripts/tests/test_impugnacao_layered_retrieval.py
"""Teste da busca em camadas do retriever, com Qdrant e embedding stubados.

Rodar: uv run python scripts/tests/test_impugnacao_layered_retrieval.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.legal_drafting.impugnacao_reference_retriever import (
    ImpugnacaoReferenceRetriever,
)

FAILS = []


def check(label, cond, detail=""):
    if not cond:
        FAILS.append(label)
        print(f"  ✗ {label} {detail}")
    else:
        print(f"  ✓ {label}")


def make_point(pid, text, **payload):
    payload.setdefault("section_kind", "merit_by_thesis")
    payload["text"] = text
    return SimpleNamespace(id=pid, score=0.9, payload=payload)


POINTS = [
    make_point("p-judge", "trecho do mesmo juiz", judge_name_norm="JOAO DA SILVA",
               orgao_julgador_norm="3A VARA FEDERAL", trf_region="TRF4"),
    make_point("p-vara", "trecho da mesma vara", judge_name_norm=None,
               orgao_julgador_norm="3A VARA FEDERAL", trf_region="TRF4"),
    make_point("p-trf", "trecho do mesmo trf", judge_name_norm=None,
               orgao_julgador_norm="OUTRA VARA", trf_region="TRF4"),
    make_point("p-geral", "trecho geral", judge_name_norm=None,
               orgao_julgador_norm=None, trf_region="TRF1"),
]


class StubQdrant:
    """Aplica as FieldConditions `must` do filtro sobre POINTS em memória."""

    def collection_exists(self, name):
        return True

    def query_points(self, collection_name, query, query_filter, limit, with_payload):
        conditions = []
        for cond in (query_filter.must or []):
            conditions.append((cond.key, cond.match.value))
        hits = []
        for point in POINTS:
            payload = dict(point.payload)
            payload.setdefault("law_firm_id", 1)
            payload.setdefault("status", "active")
            if all(payload.get(k) == v for k, v in conditions):
                hits.append(point)
        return SimpleNamespace(points=hits[:limit])


retriever = ImpugnacaoReferenceRetriever.__new__(ImpugnacaoReferenceRetriever)
retriever.collection = "stub"
retriever.qdrant = StubQdrant()
retriever._embed = lambda text: [0.0]

CTX = {
    "trf_region": "TRF4",
    "orgao_julgador": "3ª Vara Federal", "orgao_julgador_norm": "3A VARA FEDERAL",
    "judge_name": "João da Silva", "judge_name_norm": "JOAO DA SILVA",
}

# Com contexto completo: mesmo juiz vem primeiro, depois vara, depois TRF.
result = retriever.fetch_style_references(
    law_firm_id=1, query_text="tese", context=CTX,
    kind_plan=[("merit_by_thesis", 3)], max_chunks=3, max_chars=50_000,
)
texts = [r["text"] for r in result]
check("3 resultados", len(result) == 3, f"(veio {len(result)})")
check("juiz primeiro", texts and texts[0] == "trecho do mesmo juiz", f"(ordem: {texts})")
check("vara em segundo", len(texts) > 1 and texts[1] == "trecho da mesma vara", f"(ordem: {texts})")
check("trf em terceiro", len(texts) > 2 and texts[2] == "trecho do mesmo trf", f"(ordem: {texts})")
check("sem duplicatas", len(set(texts)) == len(texts))

# Sem contexto algum: ainda retorna (camada geral).
result_geral = retriever.fetch_style_references(
    law_firm_id=1, query_text="tese",
    kind_plan=[("merit_by_thesis", 4)], max_chunks=4, max_chars=50_000,
)
check("fallback geral nunca vazio", len(result_geral) == 4, f"(veio {len(result_geral)})")

# Contexto só com TRF (compat: kwarg trf_region antigo).
result_trf = retriever.fetch_style_references(
    law_firm_id=1, query_text="tese", trf_region="TRF4",
    kind_plan=[("merit_by_thesis", 2)], max_chunks=2, max_chars=50_000,
)
trf_texts = [r["text"] for r in result_trf]
check("kwarg trf_region prioriza TRF4", all("geral" not in t for t in trf_texts), f"(ordem: {trf_texts})")

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `uv run python scripts/tests/test_impugnacao_layered_retrieval.py`
Expected: `TypeError` (`fetch_style_references` não aceita `context`) ou falha de ordem (o `should` atual não prioriza).

- [ ] **Step 3: Implementar as camadas**

Em `impugnacao_reference_retriever.py`:

1. `_build_filter` perde `trf_region` e ganha `extra_match`:

```python
    def _build_filter(
        self,
        *,
        law_firm_id: int,
        section_kind: Optional[str],
        generation_mode: Optional[str],
        thesis_catalog_id: Optional[str],
        extra_match: Optional[dict] = None,
    ) -> rest.Filter:
        must: list[rest.FieldCondition] = [
            rest.FieldCondition(key="law_firm_id", match=rest.MatchValue(value=int(law_firm_id))),
            rest.FieldCondition(key="status", match=rest.MatchValue(value="active")),
        ]
        if section_kind:
            must.append(rest.FieldCondition(key="section_kind", match=rest.MatchValue(value=section_kind)))
        if generation_mode:
            must.append(rest.FieldCondition(key="generation_mode", match=rest.MatchValue(value=generation_mode.upper())))
        if thesis_catalog_id:
            must.append(rest.FieldCondition(key="thesis_catalog_id", match=rest.MatchValue(value=thesis_catalog_id)))
        for key, value in (extra_match or {}).items():
            must.append(rest.FieldCondition(key=key, match=rest.MatchValue(value=value)))
        return rest.Filter(must=must)
```

2. Camadas por contexto (método novo):

```python
    @staticmethod
    def _context_layers(context: Optional[dict], section_kind: Optional[str]) -> list[dict]:
        """Filtros extras em ordem de especificidade: juiz > vara > TRF > geral.

        Para chunks de jurisprudência, a vara de ORIGEM da peça fica em
        `orgao_julgador_origem_norm` (o `orgao_julgador` é do precedente).
        """
        context = context or {}
        vara_key = (
            "orgao_julgador_origem_norm"
            if section_kind == "jurisprudence"
            else "orgao_julgador_norm"
        )
        layers: list[dict] = []
        if context.get("judge_name_norm"):
            layers.append({"judge_name_norm": context["judge_name_norm"]})
        if context.get("orgao_julgador_norm"):
            layers.append({vara_key: context["orgao_julgador_norm"]})
        if context.get("trf_region"):
            layers.append({"trf_region": str(context["trf_region"]).upper()})
        layers.append({})
        return layers
```

3. Extrair a montagem do item para um método (remove a duplicação atual entre loop principal e fallback):

```python
    @staticmethod
    def _hit_to_item(payload: dict, default_kind: str) -> dict:
        return {
            "section_kind": payload.get("section_kind") or default_kind,
            "heading": payload.get("heading") or "",
            "section": payload.get("section") or "",
            "section_normalized": payload.get("section_normalized") or "",
            "reference_title": payload.get("reference_title") or "",
            "trf_region": payload.get("trf_region") or "",
            "thesis_catalog_id": payload.get("thesis_catalog_id") or "",
            "thesis_catalog_ids": payload.get("thesis_catalog_ids") or [],
            "quality_score": payload.get("quality_score"),
            "tribunal": payload.get("tribunal") or "",
            "case_number": payload.get("case_number") or "",
            "relator": payload.get("relator") or "",
            "orgao_julgador": payload.get("orgao_julgador") or "",
            "data_julgamento": payload.get("data_julgamento") or "",
            "tipo_juris": payload.get("tipo_juris") or "",
            "secao_origem": payload.get("secao_origem") or "general",
            "fundamento_principal": payload.get("fundamento_principal") or "",
            "text": (payload.get("text") or "").strip(),
        }
```

4. `fetch_style_references` ganha `context: Optional[dict] = None` e o corpo dos loops vira:

```python
        if context is None and trf_region:
            context = {"trf_region": trf_region}

        collected: list[dict] = []
        total_chars = 0
        seen_ids: set = set()

        def _query(kind: Optional[str], extra_match: dict, limit: int):
            try:
                return self.qdrant.query_points(
                    collection_name=self.collection,
                    query=vector,
                    query_filter=self._build_filter(
                        law_firm_id=law_firm_id,
                        section_kind=kind,
                        generation_mode=generation_mode,
                        thesis_catalog_id=thesis_catalog_id,
                        extra_match=extra_match,
                    ),
                    limit=limit,
                    with_payload=True,
                ).points
            except Exception as error:
                print(f"[ImpugnacaoReferenceRetriever] Falha kind={kind} camada={extra_match}: {error}")
                return []

        def _collect(kind: Optional[str], top_k: int) -> None:
            nonlocal total_chars
            taken_for_kind = 0
            for layer in self._context_layers(context, kind):
                if taken_for_kind >= top_k or len(collected) >= cap_chunks or total_chars >= cap_chars:
                    return
                hits = _query(kind, layer, top_k)
                # Dentro da camada, mantém a ordem de score do Qdrant;
                # quality_score desempata.
                hits = sorted(
                    hits,
                    key=lambda h: (
                        -(getattr(h, "score", 0) or 0),
                        -float((h.payload or {}).get("quality_score") or 0),
                    ),
                )
                for hit in hits:
                    if taken_for_kind >= top_k or len(collected) >= cap_chunks or total_chars >= cap_chars:
                        return
                    if hit.id in seen_ids:
                        continue
                    item = self._hit_to_item(hit.payload or {}, kind or "general")
                    if not item["text"]:
                        continue
                    if total_chars + len(item["text"]) > cap_chars and collected:
                        continue
                    collected.append(item)
                    seen_ids.add(hit.id)
                    total_chars += len(item["text"])
                    taken_for_kind += 1

        for kind, top_k in plan:
            if len(collected) >= cap_chunks or total_chars >= cap_chars:
                break
            _collect(kind, top_k)

        # Fallback amplo apenas quando nada foi encontrado no plano principal.
        if not collected and cap_chunks > 0:
            _collect(None, cap_chunks)

        return collected
```

Remover os dois blocos antigos de coleta (loop principal e fallback) substituídos acima; o `should` deixa de existir.

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `uv run python scripts/tests/test_impugnacao_layered_retrieval.py`
Expected: `OK: todos os checks passaram`

- [ ] **Step 5: Rodar também os testes anteriores (regressão)**

Run: `uv run python scripts/tests/test_impugnacao_process_context.py && uv run python scripts/tests/test_impugnacao_reference_metadata.py`
Expected: ambos `OK`.

- [ ] **Step 6: Commit**

```bash
git add app/agents/legal_drafting/impugnacao_reference_retriever.py \
        scripts/tests/test_impugnacao_layered_retrieval.py
git commit -m "Retriever de referências com camadas juiz > vara > TRF > geral"
```

---

### Task 7: Gerador e enriquecimento usam o contexto completo

**Files:**
- Modify: `app/agents/legal_drafting/agent_generated_document.py` (`_build_style_references_block`, chamadas `fetch_style_references` ~linhas 1278 e 1339)
- Modify: `app/agents/legal_drafting/impugnacao_enrichment_agent.py`
- Modify: `app/blueprints/process_panel.py:3449-3460`

**Interfaces:**
- Consumes: `build_reference_search_context` (Task 1), `fetch_style_references(context=...)` (Task 6).
- Produces: `ImpugnacaoEnrichmentAgent.enrich(..., context: Optional[dict] = None)` — `trf_region` segue aceito por compatibilidade.

- [ ] **Step 1: Gerador passa `context` nas duas buscas**

Em `_build_style_references_block` (o `search_context` já existe desde a Task 1), nas duas chamadas `retriever.fetch_style_references(...)` (busca por seção ~1278 e por tese ~1339), adicionar:

```python
                    context=search_context,
```

(mantendo `trf_region=trf_region` — inofensivo, `context` tem precedência).

- [ ] **Step 2: Enrichment agent aceita contexto**

Em `impugnacao_enrichment_agent.py`:

1. `_build_jurisprudence_context(self, selections, law_firm_id, trf_region, context=None)` — nas duas chamadas `self.retriever.fetch_style_references(...)` internas, adicionar `context=context,`.
2. `enrich(self, *, document_text, selections, law_firm_id, trf_region=None, context=None)` — repassar: `self._build_jurisprudence_context(selections, law_firm_id, trf_region, context=context)`.

- [ ] **Step 3: `process_panel` monta o contexto uma vez**

No worker (`_run_generated_document_generation`), substituir o bloco de enriquecimento (o trecho editado na Task 1, ~linha 3452):

```python
                    from app.agents.legal_drafting.impugnacao_process_context import (
                        build_reference_search_context,
                    )
                    search_context = build_reference_search_context(process)
                    full_text = ImpugnacaoEnrichmentAgent(
                        model_name=ai_model_settings_service.get_model(
                            law_firm_id, 'impugnacao_enrichment')).enrich(
                        document_text=full_text,
                        selections=agent_selections,
                        law_firm_id=law_firm_id,
                        trf_region=search_context.get('trf_region') or '',
                        context=search_context,
                    )
```

- [ ] **Step 4: Smoke test + regressão**

Run: `uv run python -c "import main; print('imports ok')" && uv run python scripts/tests/test_impugnacao_layered_retrieval.py`
Expected: `imports ok` e teste `OK` (garante que a assinatura nova não quebrou o teste com stub).

- [ ] **Step 5: Commit**

```bash
git add app/agents/legal_drafting/agent_generated_document.py \
        app/agents/legal_drafting/impugnacao_enrichment_agent.py \
        app/blueprints/process_panel.py
git commit -m "Geração e enriquecimento de impugnação usam contexto juiz/vara/TRF"
```

---

### Task 8: Serviço Meilisearch + sincronização no blueprint

**Files:**
- Create: `app/services/impugnacao_reference_search.py`
- Modify: `app/blueprints/impugnacao_references.py` (new, reindex, arquivar, reativar, excluir)
- Test: `scripts/tests/test_impugnacao_meilisearch_sync.py`

**Interfaces:**
- Consumes: `chunk_records` do ingestor (Task 4), modelo com campos novos (Task 2). Env: `MEILISEARCH_HOST`, `MEILISEARCH_API_KEY`, `IMPUGNACAO_REFERENCES_MEILI_INDEX` (default `impugnacao_references`).
- Produces (consumido pela Task 9):
  - `index_reference_chunks(reference, chunk_records) -> bool`
  - `delete_reference(reference_id) -> bool`
  - `update_reference_status(reference) -> bool` (usa o status atual do objeto)
  - `search_chunks(law_firm_id, query, *, status='active', trf_region=None, limit=30) -> list[dict] | None` — hits com `_formatted` para highlight; `[]` = busca ok sem resultados; **`None` = Meilisearch indisponível** (a tela usa isso para decidir aviso + fallback SQL).
  - Demais funções com degradação graciosa: exceção → log + `False`.

- [ ] **Step 1: Implementar o serviço**

```python
# app/services/impugnacao_reference_search.py
"""Busca textual das peças-modelo de impugnação (Meilisearch).

Índice dedicado, sincronizado nos mesmos pontos que o Qdrant (ingestão,
reindexação, arquivar/reativar, exclusão). Papel: busca por termo exato /
texto livre na TELA — a geração continua 100% Qdrant. Falhas aqui nunca
abortam o fluxo principal (a fonte crítica é o Qdrant).
"""
from __future__ import annotations

import os

from meilisearch_python_sdk import Client as MeilisearchClient

MEILISEARCH_HOST = os.getenv("MEILISEARCH_HOST", "http://localhost:7700")
MEILISEARCH_API_KEY = os.getenv("MEILISEARCH_API_KEY")
IMPUGNACAO_REFERENCES_MEILI_INDEX = os.getenv(
    "IMPUGNACAO_REFERENCES_MEILI_INDEX", "impugnacao_references"
)

_FILTERABLE = ["law_firm_id", "status", "trf_region", "section_kind",
               "thesis_catalog_id", "reference_id"]
_SEARCHABLE = ["text", "section", "heading", "reference_title",
               "judge_name", "orgao_julgador", "process_number"]


def _get_index():
    client = MeilisearchClient(MEILISEARCH_HOST, MEILISEARCH_API_KEY)
    index = client.get_or_create_index(uid=IMPUGNACAO_REFERENCES_MEILI_INDEX, primary_key="id")
    task = index.update_filterable_attributes(_FILTERABLE)
    client.wait_for_task(task.task_uid, timeout_in_ms=10000)
    task = index.update_searchable_attributes(_SEARCHABLE)
    client.wait_for_task(task.task_uid, timeout_in_ms=10000)
    return client, index


def _build_documents(reference, chunk_records) -> list[dict]:
    documents = []
    for record in chunk_records or []:
        point_id = record.get("qdrant_point_id")
        if not point_id:
            continue
        documents.append({
            "id": str(point_id).replace("-", ""),
            "law_firm_id": int(reference.law_firm_id),
            "reference_id": int(reference.id),
            "reference_title": reference.title or "",
            "trf_region": reference.trf_region or None,
            "orgao_julgador": reference.orgao_julgador or None,
            "judge_name": reference.judge_name or None,
            "process_number": reference.process_number or None,
            "status": reference.status or "active",
            "heading": record.get("heading") or "",
            "section": record.get("section") or "",
            "section_kind": record.get("section_kind") or "general",
            "thesis_catalog_id": record.get("thesis_catalog_id"),
            "order_in_doc": record.get("order_in_doc", 0),
            "text": record.get("full_text") or record.get("preview_text") or "",
        })
    return documents


def index_reference_chunks(reference, chunk_records) -> bool:
    try:
        client, index = _get_index()
        task = index.delete_documents_by_filter(f"reference_id = {int(reference.id)}")
        client.wait_for_task(task.task_uid, timeout_in_ms=10000)
        documents = _build_documents(reference, chunk_records)
        if documents:
            task = index.add_documents(documents)
            client.wait_for_task(task.task_uid, timeout_in_ms=30000)
        return True
    except Exception as error:
        print(f"[impugnacao_reference_search] Falha ao indexar ref {reference.id}: {error}")
        return False


def delete_reference(reference_id: int) -> bool:
    try:
        client, index = _get_index()
        task = index.delete_documents_by_filter(f"reference_id = {int(reference_id)}")
        client.wait_for_task(task.task_uid, timeout_in_ms=10000)
        return True
    except Exception as error:
        print(f"[impugnacao_reference_search] Falha ao remover ref {reference_id}: {error}")
        return False


def update_reference_status(reference) -> bool:
    """Propaga o status atual (active/archived) para os documentos da peça."""
    try:
        from app.models import ImpugnacaoReferenceChunk
        client, index = _get_index()
        chunk_ids = [
            str(chunk.qdrant_point_id).replace("-", "")
            for chunk in ImpugnacaoReferenceChunk.query
            .filter_by(reference_id=reference.id).all()
            if chunk.qdrant_point_id
        ]
        if not chunk_ids:
            return True
        task = index.update_documents(
            [{"id": chunk_id, "status": reference.status} for chunk_id in chunk_ids]
        )
        client.wait_for_task(task.task_uid, timeout_in_ms=30000)
        return True
    except Exception as error:
        print(f"[impugnacao_reference_search] Falha ao atualizar status da ref {reference.id}: {error}")
        return False


def search_chunks(law_firm_id: int, query: str, *, status: str = "active",
                  trf_region: str | None = None, limit: int = 30) -> list[dict] | None:
    """Busca textual multi-tenant. Retorna hits crus do Meilisearch.

    [] = busca ok sem resultados; None = Meilisearch indisponível.
    """
    if not law_firm_id or not (query or "").strip():
        return []
    try:
        _, index = _get_index()
        filters = [f"law_firm_id = {int(law_firm_id)}"]
        if status in ("active", "archived"):
            filters.append(f"status = '{status}'")
        if trf_region:
            filters.append(f"trf_region = '{trf_region.upper()}'")
        result = index.search(
            query.strip(),
            filter=" AND ".join(filters),
            limit=limit,
            attributes_to_highlight=["text", "section", "reference_title"],
            attributes_to_crop=["text"],
            crop_length=40,
        )
        return result.hits or []
    except Exception as error:
        print(f"[impugnacao_reference_search] Falha na busca: {error}")
        return None
```

Nota de compatibilidade: verifique a API do `meilisearch_python_sdk` instalada espelhando `app/agents/knowledge_base/knowledge_ingestion_agent.py:72-92` — se lá `wait_for_task` for chamado como `self.meilisearch.wait_for_task(task_uid, timeout_in_ms=...)` e `get_or_create_index` sem kwargs diferentes, use exatamente o mesmo estilo (inclusive extração do `task_uid` via `getattr(task_info, "task_uid", None)` se for esse o padrão local).

- [ ] **Step 2: Escrever o teste de sincronização**

```python
# scripts/tests/test_impugnacao_meilisearch_sync.py
"""Teste de sincronização do índice Meilisearch das peças-modelo.

Requer Meilisearch rodando (docker compose -f docker/docker-compose.yml up -d).
Usa reference_id sintético 999999 e limpa ao final.

Rodar: uv run python scripts/tests/test_impugnacao_meilisearch_sync.py
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import impugnacao_reference_search as search

FAILS = []


def check(label, cond, detail=""):
    if not cond:
        FAILS.append(label)
        print(f"  ✗ {label} {detail}")
    else:
        print(f"  ✓ {label}")


REF = SimpleNamespace(
    id=999999, law_firm_id=888888, title="Peça teste sync",
    trf_region="TRF4", orgao_julgador="3ª Vara Federal de Florianópolis",
    judge_name="João da Silva", process_number="5001234-56.2024.4.04.7200",
    status="active",
)
RECORDS = [
    {"qdrant_point_id": "11111111-1111-1111-1111-111111111111",
     "heading": "6. AUXÍLIO-ACIDENTE (B94)", "section": "6. AUXÍLIO-ACIDENTE (B94)",
     "section_kind": "merit_by_thesis", "thesis_catalog_id": "apuracao_indice_custo",
     "order_in_doc": 0, "full_text": "Texto sobre apuração do índice de custo xyzsync."},
    {"qdrant_point_id": "22222222-2222-2222-2222-222222222222",
     "heading": "PEDIDOS", "section": "PEDIDOS", "section_kind": "requests",
     "thesis_catalog_id": None, "order_in_doc": 1,
     "full_text": "Requer a procedência total xyzsync."},
]

check("indexação", search.index_reference_chunks(REF, RECORDS))
time.sleep(0.5)

hits = search.search_chunks(REF.law_firm_id, "xyzsync")
check("busca acha os 2 chunks", len(hits) == 2, f"(veio {len(hits)})")

hits_outro_tenant = search.search_chunks(777777, "xyzsync")
check("filtro de tenant", len(hits_outro_tenant) == 0, f"(veio {len(hits_outro_tenant)})")

hits_secao = search.search_chunks(REF.law_firm_id, "auxílio-acidente")
check("busca por título de seção", len(hits_secao) >= 1, f"(veio {len(hits_secao)})")

check("exclusão", search.delete_reference(REF.id))
time.sleep(0.5)
hits_after = search.search_chunks(REF.law_firm_id, "xyzsync")
check("índice limpo após exclusão", len(hits_after) == 0, f"(veio {len(hits_after)})")

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} verificação(ões)")
    sys.exit(1)
print("OK: todos os checks passaram")
```

(`update_reference_status` usa o banco via `ImpugnacaoReferenceChunk`, então fica coberto pelo teste manual do Step 5 — o teste automatizado cobre indexar/buscar/tenant/excluir.)

- [ ] **Step 3: Rodar o teste**

Run: `docker compose -f docker/docker-compose.yml up -d && uv run python scripts/tests/test_impugnacao_meilisearch_sync.py`
Expected: `OK: todos os checks passaram`

- [ ] **Step 4: Sincronizar no blueprint**

Em `app/blueprints/impugnacao_references.py`, import no topo:

```python
from app.services import impugnacao_reference_search
```

1. `new_reference` — após o `db.session.commit()` que grava os chunks (dentro do `try` de ingestão, antes do `flash` de sucesso):

```python
        impugnacao_reference_search.index_reference_chunks(reference, chunks_meta)
```

2. `reindex_reference` — idem, após o commit dos chunks novos:

```python
        impugnacao_reference_search.index_reference_chunks(reference, chunks_meta)
```

3. `archive_reference` e `reactivate_reference` — após o bloco `try/except` do Qdrant:

```python
    impugnacao_reference_search.update_reference_status(reference)
```

4. `delete_reference` — antes de `db.session.delete(reference)`:

```python
    impugnacao_reference_search.delete_reference(ref_id)
```

- [ ] **Step 5: Teste manual guiado**

Com app + Meilisearch rodando: reindexar uma peça na tela, depois:

Run: `uv run python -c "
from app.services.impugnacao_reference_search import search_chunks
hits = search_chunks(1, 'impugnação', limit=5)
print(len(hits), 'hit(s)')
for h in hits[:3]:
    print('-', h.get('reference_title'), '|', (h.get('section') or h.get('heading'))[:60])
"`
(ajuste o `law_firm_id` 1 para o do seu escritório)
Expected: hits da peça reindexada. Arquivar a peça e repetir → 0 hits com `status='active'`.

- [ ] **Step 6: Commit**

```bash
git add app/services/impugnacao_reference_search.py \
        app/blueprints/impugnacao_references.py \
        scripts/tests/test_impugnacao_meilisearch_sync.py
git commit -m "Índice Meilisearch dedicado para busca textual das peças-modelo"
```

---

### Task 9: Tela — colunas, filtros, busca, edição de metadados e seções

**Files:**
- Modify: `app/blueprints/impugnacao_references.py` (`list_references`, rota nova `update_metadata`)
- Modify: `templates/impugnacao_references/list.html`
- Modify: `templates/impugnacao_references/detail.html`

**Interfaces:**
- Consumes: `search_chunks` (Task 8), campos novos do modelo (Task 2), `tribunal_sigla_from_cnj` (para re-derivar TRF na edição).
- Produces: rota `POST /referencias-impugnacao/<id>/metadados` (endpoint `impugnacao_references.update_metadata`).

- [ ] **Step 1: `list_references` com filtros, busca e contadores na rota**

Substituir o corpo por:

```python
@impugnacao_references_bp.route('/')
@require_law_firm
def list_references():
    law_firm_id = get_current_law_firm_id()
    status_filter = (request.args.get('status') or 'active').strip()
    trf_filter = (request.args.get('trf') or '').strip().upper()
    vara_filter = (request.args.get('vara') or '').strip()
    search_query = (request.args.get('q') or '').strip()

    query = ImpugnacaoReferenceModel.query.filter_by(law_firm_id=law_firm_id)
    if status_filter in ('active', 'archived'):
        query = query.filter_by(status=status_filter)
    if trf_filter:
        query = query.filter_by(trf_region=trf_filter)
    if vara_filter:
        query = query.filter(ImpugnacaoReferenceModel.orgao_julgador.ilike(f'%{vara_filter}%'))

    references = query.order_by(ImpugnacaoReferenceModel.created_at.desc()).all()

    # Busca textual: Meilisearch com fallback SQL LIKE nos chunks.
    search_hits_by_ref: dict[int, list[dict]] = {}
    search_error = False
    if search_query:
        from app.services import impugnacao_reference_search
        hits = impugnacao_reference_search.search_chunks(
            law_firm_id, search_query,
            status=status_filter if status_filter in ('active', 'archived') else 'active',
            trf_region=trf_filter or None,
        )
        if hits is None:
            # Meilisearch fora do ar: aviso na tela + fallback SQL LIKE.
            search_error = True
            like = f'%{search_query}%'
            rows = (
                ImpugnacaoReferenceChunk.query
                .filter_by(law_firm_id=law_firm_id)
                .filter(ImpugnacaoReferenceChunk.full_text.ilike(like))
                .limit(30)
                .all()
            )
            for row in rows:
                search_hits_by_ref.setdefault(row.reference_id, []).append({
                    'section': row.secao_origem or '',
                    'section_kind': row.section_kind,
                    'text': (row.preview_text or '')[:200],
                })
        else:
            for hit in hits:
                ref_id = hit.get('reference_id')
                if ref_id is not None:
                    search_hits_by_ref.setdefault(int(ref_id), []).append(hit)
        references = [ref for ref in references if ref.id in search_hits_by_ref]

    trf_options = ['TRF1', 'TRF2', 'TRF3', 'TRF4', 'TRF5', 'TRF6']
    total = len(references)
    total_chunks = sum(ref.chunks_count or 0 for ref in references)

    return render_template(
        'impugnacao_references/list.html',
        references=references,
        status_filter=status_filter,
        trf_filter=trf_filter,
        vara_filter=vara_filter,
        search_query=search_query,
        search_hits_by_ref=search_hits_by_ref,
        search_error=search_error,
        trf_options=trf_options,
        total=total,
        total_chunks=total_chunks,
    )
```

- [ ] **Step 2: Rota de edição de metadados**

Adicionar após `reference_detail`:

```python
@impugnacao_references_bp.route('/<int:ref_id>/metadados', methods=['POST'])
@require_law_firm
def update_metadata(ref_id):
    from app.utils.cnj import cnj_digits, tribunal_sigla_from_cnj

    law_firm_id = get_current_law_firm_id()
    reference = ImpugnacaoReferenceModel.query.filter_by(
        id=ref_id, law_firm_id=law_firm_id
    ).first_or_404()

    def _clean(name, max_len):
        value = (request.form.get(name) or '').strip()
        return value[:max_len] or None

    reference.title = _clean('title', 250) or reference.title
    reference.case_name = _clean('case_name', 250)
    reference.orgao_julgador = _clean('orgao_julgador', 250)
    reference.judge_name = _clean('judge_name', 250)

    process_number = _clean('process_number', 30)
    if process_number and len(cnj_digits(process_number)) != 20:
        flash('Número CNJ inválido — os demais campos foram salvos.', 'warning')
        process_number = reference.process_number
    reference.process_number = process_number

    trf_region = (request.form.get('trf_region') or '').strip().upper() or None
    cnj_sigla = tribunal_sigla_from_cnj(reference.process_number)
    if cnj_sigla and cnj_sigla.startswith('TRF'):
        trf_region = cnj_sigla  # CNJ válido manda no TRF
    reference.trf_region = trf_region if trf_region in (
        'TRF1', 'TRF2', 'TRF3', 'TRF4', 'TRF5', 'TRF6') else None

    db.session.commit()

    # Reflete os metadados no índice de busca da tela.
    chunk_records = [
        {
            'qdrant_point_id': chunk.qdrant_point_id,
            'heading': None, 'section': chunk.secao_origem,
            'section_kind': chunk.section_kind,
            'thesis_catalog_id': chunk.thesis_catalog_id,
            'order_in_doc': chunk.order_in_doc,
            'full_text': chunk.full_text,
        }
        for chunk in ImpugnacaoReferenceChunk.query.filter_by(reference_id=ref_id).all()
    ]
    impugnacao_reference_search.index_reference_chunks(reference, chunk_records)

    flash('Metadados atualizados. Reindexe a peça para propagar ao Qdrant.', 'success')
    return redirect(url_for('impugnacao_references.reference_detail', ref_id=ref_id))
```

(A propagação completa ao payload do Qdrant acontece via botão Reindexar — o flash deixa isso explícito.)

- [ ] **Step 3: `list.html` — busca, filtros e colunas novas**

1. Remover as linhas `{% set total = references|length %}` e `{% set total_chunks = ... %}` (agora vêm da rota).
2. No `card-header` dos filtros, após o `</ul>` das pills de status, adicionar o formulário:

```html
                <form method="get" class="d-flex flex-wrap gap-2 mt-2" role="search">
                    <input type="hidden" name="status" value="{{ status_filter }}">
                    <div class="input-group input-group-sm" style="max-width:320px">
                        <span class="input-group-text"><i class="bi bi-search"></i></span>
                        <input type="search" name="q" class="form-control" value="{{ search_query or '' }}"
                            placeholder="Buscar em seções, texto, juiz, processo...">
                    </div>
                    <select name="trf" class="form-select form-select-sm" style="max-width:110px"
                        onchange="this.form.submit()">
                        <option value="">TRF</option>
                        {% for opt in trf_options %}
                        <option value="{{ opt }}" {% if trf_filter == opt %}selected{% endif %}>{{ opt }}</option>
                        {% endfor %}
                    </select>
                    <input type="text" name="vara" class="form-control form-control-sm" style="max-width:220px"
                        value="{{ vara_filter or '' }}" placeholder="Vara / órgão julgador">
                    <button class="btn btn-sm btn-outline-primary" type="submit">Filtrar</button>
                    {% if search_query or trf_filter or vara_filter %}
                    <a class="btn btn-sm btn-outline-secondary"
                        href="{{ url_for('impugnacao_references.list_references', status=status_filter) }}">Limpar</a>
                    {% endif %}
                </form>
                {% if search_error %}
                <div class="small text-warning mt-2">
                    <i class="bi bi-exclamation-triangle me-1"></i>Busca textual indisponível no momento — exibindo resultados do filtro simples.
                </div>
                {% endif %}
```

3. No `<thead>`, após `<th>TRF</th>`, adicionar `<th>Vara</th>`. No `<tbody>`, após a célula do TRF:

```html
                                <td>
                                    {% if ref.orgao_julgador %}
                                    <span class="small">{{ ref.orgao_julgador }}</span>
                                    {% if ref.judge_name %}
                                    <div class="small text-muted"><i class="bi bi-person me-1"></i>{{ ref.judge_name }}</div>
                                    {% endif %}
                                    {% else %}<span class="text-muted small">—</span>{% endif %}
                                </td>
```

4. Ainda no `<tbody>`, após a célula do título, exibir trechos casados quando há busca (dentro da mesma `<td>` do título):

```html
                                    {% if search_query and search_hits_by_ref.get(ref.id) %}
                                    {% for hit in search_hits_by_ref[ref.id][:2] %}
                                    <div class="small text-muted mt-1 border-start ps-2">
                                        {% if hit.get('section') %}<span class="badge bg-light text-dark border me-1">{{ hit['section'][:60] }}</span>{% endif %}
                                        {{ (hit.get('_formatted', {}).get('text') or hit.get('text') or '')[:180]|safe }}
                                    </div>
                                    {% endfor %}
                                    {% endif %}
```

- [ ] **Step 4: `detail.html` — formulário de metadados + bloco de seções**

1. Na área de metadados existente (~linhas 160-270), envolver/complementar com formulário de edição (seguir o estilo de cards da página):

```html
<div class="card border-0 shadow-sm rounded-3 mb-4">
    <div class="card-header bg-light border-0 py-3">
        <span class="fw-medium"><i class="bi bi-geo-alt me-2"></i>Origem da peça</span>
    </div>
    <div class="card-body">
        <form method="post" action="{{ url_for('impugnacao_references.update_metadata', ref_id=reference.id) }}">
            <div class="row g-3">
                <div class="col-md-6">
                    <label class="form-label small text-muted">Título</label>
                    <input type="text" name="title" class="form-control form-control-sm"
                        value="{{ reference.title or '' }}">
                </div>
                <div class="col-md-6">
                    <label class="form-label small text-muted">Empresa (razão social)</label>
                    <input type="text" name="case_name" class="form-control form-control-sm"
                        value="{{ reference.case_name or '' }}">
                </div>
                <div class="col-md-4">
                    <label class="form-label small text-muted">Número CNJ do processo</label>
                    <input type="text" name="process_number" class="form-control form-control-sm"
                        value="{{ reference.process_number or '' }}" placeholder="0000000-00.0000.0.00.0000">
                </div>
                <div class="col-md-2">
                    <label class="form-label small text-muted">TRF</label>
                    <select name="trf_region" class="form-select form-select-sm">
                        <option value="">—</option>
                        {% for opt in ['TRF1','TRF2','TRF3','TRF4','TRF5','TRF6'] %}
                        <option value="{{ opt }}" {% if reference.trf_region == opt %}selected{% endif %}>{{ opt }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label small text-muted">Vara / órgão julgador</label>
                    <input type="text" name="orgao_julgador" class="form-control form-control-sm"
                        value="{{ reference.orgao_julgador or '' }}">
                </div>
                <div class="col-md-3">
                    <label class="form-label small text-muted">Juiz(a)</label>
                    <input type="text" name="judge_name" class="form-control form-control-sm"
                        value="{{ reference.judge_name or '' }}">
                </div>
            </div>
            <div class="d-flex justify-content-between align-items-center mt-3">
                <span class="small text-muted">Com CNJ válido, o TRF é derivado automaticamente do número.</span>
                <button type="submit" class="btn btn-sm btn-primary">
                    <i class="bi bi-check-lg me-1"></i>Salvar metadados
                </button>
            </div>
        </form>
    </div>
</div>
```

2. Bloco "Seções detectadas" (após o card de metadados, antes da lista de chunks):

```html
{% if reference.sections_json %}
<div class="card border-0 shadow-sm rounded-3 mb-4">
    <div class="card-header bg-light border-0 py-3">
        <span class="fw-medium"><i class="bi bi-list-nested me-2"></i>Seções detectadas</span>
        <span class="badge bg-secondary-subtle text-secondary ms-2">{{ reference.sections_json|length }}</span>
    </div>
    <div class="card-body p-0">
        <div class="table-responsive">
            <table class="table table-sm align-middle mb-0">
                <thead class="table-light">
                    <tr>
                        <th class="ps-3">Seção</th>
                        <th>Tipo</th>
                        <th>Teses</th>
                        <th class="text-end pe-3">Trechos</th>
                    </tr>
                </thead>
                <tbody>
                    {% for sec in reference.sections_json %}
                    <tr>
                        <td class="ps-3 small">{{ sec.titulo }}</td>
                        <td><span class="badge bg-light text-dark border">{{ sec.section_kind }}</span></td>
                        <td>
                            {% for tese in sec.teses %}
                            <span class="badge bg-info-subtle text-info border border-info-subtle">{{ tese }}</span>
                            {% else %}<span class="text-muted small">—</span>{% endfor %}
                        </td>
                        <td class="text-end pe-3">{{ sec.qtd_chunks }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endif %}
```

(Se `detail.html` já exibe metadados em outro card estático, remover os campos duplicados de lá — título/TRF/modo ficam no formulário; modo A/B e qualidade permanecem onde estão.)

- [ ] **Step 5: Smoke test + verificação de rotas**

Run: `uv run python -c "
import main
rules = [str(r) for r in main.app.url_map.iter_rules() if 'referencias-impugnacao' in str(r)]
assert any('/metadados' in r for r in rules), rules
print('rotas ok:', len(rules))
"`
Expected: `rotas ok: 8` (7 anteriores + metadados).

- [ ] **Step 6: Teste manual guiado (com app rodando)**

1. `/referencias-impugnacao/` — conferir colunas TRF/Vara, filtro por TRF, busca `q` com trecho conhecido de uma peça (com e sem Meilisearch de pé — sem, deve aparecer o aviso e o fallback LIKE).
2. Detalhe de uma peça — editar vara/juiz, salvar, conferir flash; colar CNJ válido e conferir TRF re-derivado.
3. Bloco "Seções detectadas" visível após reindexar.

- [ ] **Step 7: Rodar todos os testes do plano (regressão final)**

Run: `for t in test_impugnacao_process_context test_impugnacao_reference_metadata test_impugnacao_layered_retrieval test_impugnacao_meilisearch_sync; do uv run python scripts/tests/$t.py || break; done`
Expected: quatro `OK`.

- [ ] **Step 8: Commit**

```bash
git add app/blueprints/impugnacao_references.py \
        templates/impugnacao_references/list.html \
        templates/impugnacao_references/detail.html
git commit -m "Tela de peças-modelo: busca textual, filtros TRF/vara, edição de metadados e seções"
```
