# Extração Dirigida de Documentos Auxiliares no Revisor FAP — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o Revisor FAP considerar os documentos auxiliares opcionais: um subagente extrai dados estruturados de cada arquivo guiado pelos benefícios/teses da planilha, o revisor cruza esses dados contra a petição, e a tela de resultado ganha um card "Documentos Auxiliares × Benefícios".

**Architecture:** Novo `FapAuxiliaryDocumentExtractorAgent` (uma chamada LLM barata por arquivo, saída Pydantic com trecho-fonte literal) orquestrado por um novo serviço `fap_review_aux_service` (âncoras de benefícios da planilha com fallback por regex na petição, cache por SHA-256 do arquivo em tabela nova). O blueprint passa o resultado ao `FapPetitionReviewerAgent` via parâmetro `auxiliary_documents` (que já existe e nunca era preenchido) e persiste o payload em `result_json` para a tela.

**Tech Stack:** Flask 3.1, SQLAlchemy, LangChain `ChatOpenAI` (com `ainvoke`), Pydantic, openpyxl, Jinja2/AdminLTE.

## Global Constraints

- Multi-tenancy: toda query filtra por `law_firm_id`. A tabela de cache carrega `law_firm_id`.
- Deps via `uv` (nunca `pip`). Nenhuma dependência nova é necessária.
- Migrations = script standalone em `database/` com prefixo `add_*`, `with app.app_context():`, idempotente, mensagens claras (sem Alembic).
- **ATENÇÃO OPERACIONAL:** o checkout de dev usa o MySQL de produção. A migration é aditiva (só cria tabela nova) e idempotente, mas rode-a com o usuário ciente.
- Toda chamada LLM passa por `TokenUsageService` (padrão `capture_and_store` do reviewer_agent).
- Agentes retornam Pydantic models; degradação graciosa em toda falha (extração que falha NUNCA derruba a revisão).
- Testes = scripts standalone (`uv run python tests/<arquivo>.py`), sem pytest.
- Frontend: JS nativo, padrões visuais do próprio `revision_result.html` (cards `info-card`, `summary-stat`, badges `bg-*-subtle`).
- Sem cortes silenciosos: documentos pulados por limite entram em `skipped_documents` e aparecem na tela.
- Datetimes com `datetime.now` (padrão dos modelos existentes em `models.py`).

---

### Task 1: Modelo `FapReviewAuxExtraction` + migration da tabela de cache

**Files:**
- Modify: `app/models.py` (inserir após a classe `FapReviewIgnoredFinding`, ~linha 2930)
- Create: `database/add_fap_review_aux_extractions_table.py`

**Interfaces:**
- Produces: modelo `FapReviewAuxExtraction` com colunas `law_firm_id`, `file_sha256`, `file_name`, `extractor_model`, `anchors_fingerprint`, `extraction_json`, `created_at`. Unique em `(law_firm_id, file_sha256, extractor_model, anchors_fingerprint)`. Tasks 3 e 5 consultam/gravam este modelo.

- [ ] **Step 1: Adicionar o modelo em `app/models.py`**

Localizar o final da classe `FapReviewIgnoredFinding` (procure `class FapReviewIgnoredFinding` e vá até o fim do bloco) e inserir depois dela:

```python
class FapReviewAuxExtraction(db.Model):
    """Cache das extrações de documentos auxiliares do Revisor FAP, por hash do arquivo.

    A mesma CAT/CNIS reutilizada em revisões seguintes não paga nova chamada de IA.
    A extração depende da lista de benefícios-âncora (planilha), então o fingerprint
    das âncoras integra a chave — planilha diferente => extração nova.
    """
    __tablename__ = 'fap_review_aux_extractions'
    __table_args__ = (
        db.UniqueConstraint(
            'law_firm_id',
            'file_sha256',
            'extractor_model',
            'anchors_fingerprint',
            name='uq_fap_review_aux_extractions_scope',
        ),
        db.Index('ix_fap_review_aux_extractions_lookup', 'law_firm_id', 'file_sha256'),
    )

    id = db.Column(db.Integer, primary_key=True)
    law_firm_id = db.Column(db.Integer, db.ForeignKey('law_firms.id'), nullable=False, index=True)
    file_sha256 = db.Column(db.String(64), nullable=False)
    file_name = db.Column(db.String(255))
    extractor_model = db.Column(db.String(100), nullable=False)
    anchors_fingerprint = db.Column(db.String(64), nullable=False, default='')
    extraction_json = db.Column(db.Text, nullable=False, comment='JSON com a extração estruturada do documento')
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    law_firm = db.relationship('LawFirm')

    def __repr__(self):
        return f'<FapReviewAuxExtraction file={self.file_name} sha={self.file_sha256[:8]}>'
```

- [ ] **Step 2: Criar o script de migration**

Criar `database/add_fap_review_aux_extractions_table.py`:

```python
"""
Cria a tabela fap_review_aux_extractions (cache das extrações de documentos
auxiliares do Revisor FAP, por hash de arquivo).

Uso:
    uv run python database/add_fap_review_aux_extractions_table.py
"""

import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from sqlalchemy import inspect

from app.models import db, FapReviewAuxExtraction
from main import app


def create_table():
    with app.app_context():
        inspector = inspect(db.engine)
        if 'fap_review_aux_extractions' in inspector.get_table_names():
            print('- tabela ja existe: fap_review_aux_extractions')
            return

        print('+ criando tabela: fap_review_aux_extractions')
        try:
            FapReviewAuxExtraction.__table__.create(db.engine)
            print('Migracao concluida com sucesso.')
        except Exception as exc:
            print(f'Erro durante a migracao: {exc}')
            raise


if __name__ == '__main__':
    create_table()
```

- [ ] **Step 3: Rodar a migration e verificar idempotência**

Run: `uv run python database/add_fap_review_aux_extractions_table.py`
Expected: `+ criando tabela: fap_review_aux_extractions` seguido de `Migracao concluida com sucesso.`

Run de novo: `uv run python database/add_fap_review_aux_extractions_table.py`
Expected: `- tabela ja existe: fap_review_aux_extractions`

- [ ] **Step 4: Commit**

```bash
git add app/models.py database/add_fap_review_aux_extractions_table.py
git commit -m "feat(fap-review): tabela de cache de extrações de documentos auxiliares"
```

---

### Task 2: Agente extrator `FapAuxiliaryDocumentExtractorAgent`

**Files:**
- Create: `app/agents/fap_review/auxiliary_extractor_agent.py`
- Modify: `app/agents/fap_review/__init__.py`

**Interfaces:**
- Consumes: `FileAgent.build_openrouter_file_part(path) -> dict` (já existe em `app/agents/core/file_agent.py`); `TokenUsageService` (padrão idêntico ao `reviewer_agent.py`).
- Produces:
  - Pydantic: `AuxExtractedFact(label, value, source_excerpt)`, `AuxRelatedBenefit(benefit_number, match_reason, facts)`, `AuxDocumentExtraction(document_type, related_benefits, general_summary, potential_divergences)`.
  - Classe `FapAuxiliaryDocumentExtractorAgent(openai_api_key=None, model=None, temperature=0.0)` com atributo `model_name` e método `async extract(*, file_path: str, file_name: str, document_text: str | None, benefit_anchors: list[dict], law_firm_id: int | None = None) -> AuxDocumentExtraction`. `benefit_anchors` = `[{'benefit_number': str, 'benefit_number_normalized': str, 'theses': list[str]}]`.

- [ ] **Step 1: Criar o agente**

Criar `app/agents/fap_review/auxiliary_extractor_agent.py`:

```python
"""
Agente Extrator de Documentos Auxiliares do Revisor FAP.

Responsabilidade: ler UM documento auxiliar (CAT, CNIS, INFBEN, print do FAP Web,
laudo etc.), vinculá-lo aos benefícios-âncora informados (planilha de benefícios ou
números achados na petição) e extrair somente os dados relevantes às teses, sempre
com o trecho literal de origem para auditoria humana.

Este agente NÃO revisa a petição — ele apenas destila dados para o revisor cruzar.
"""

import base64
import json
import mimetypes
import os
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from app.agents.core.file_agent import FileAgent
from app.services.token_usage_service import TokenUsageService

_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'}


class AuxExtractedFact(BaseModel):
    """Um dado extraído do documento auxiliar."""
    label: str = Field(..., description="Nome do dado (ex.: Data do acidente)")
    value: str = Field(..., description="Valor extraído do documento")
    source_excerpt: Optional[str] = Field(
        None, description="Trecho literal curto do documento de onde o dado saiu")


class AuxRelatedBenefit(BaseModel):
    """Benefício ao qual o documento se refere."""
    benefit_number: str = Field(..., description="Número do benefício como aparece no documento ou na âncora")
    match_reason: str = Field(..., description="Como o vínculo foi identificado (NB citado, NIT, nome do trabalhador...)")
    facts: list[AuxExtractedFact] = Field(default_factory=list)


class AuxDocumentExtraction(BaseModel):
    """Resultado da extração de um documento auxiliar."""
    document_type: str = Field('OUTRO', description="CAT, CNIS, INFBEN, PRINT_FAP, LAUDO, CONTESTACAO ou OUTRO")
    related_benefits: list[AuxRelatedBenefit] = Field(default_factory=list)
    general_summary: str = Field('', description="Resumo objetivo do documento em até 3 frases")
    potential_divergences: list[str] = Field(
        default_factory=list,
        description="Pontos do documento que merecem conferência contra a petição")


class FapAuxiliaryDocumentExtractorAgent:
    """Extrai dados estruturados de um documento auxiliar, guiado pelas teses."""

    _OUTPUT_SCHEMA = """{
  "document_type": "CAT | CNIS | INFBEN | PRINT_FAP | LAUDO | CONTESTACAO | OUTRO",
  "related_benefits": [
    {"benefit_number": "número do benefício",
     "match_reason": "como o vínculo foi identificado (NB citado, NIT, nome do trabalhador...)",
     "facts": [{"label": "nome do dado (ex.: Data do acidente)", "value": "valor extraído", "source_excerpt": "trecho LITERAL curto copiado do documento, ou null"}]}
  ],
  "general_summary": "resumo objetivo do documento em até 3 frases",
  "potential_divergences": ["ponto que merece conferência contra a petição"]
}"""

    def __init__(self,
                 openai_api_key: Optional[str] = None,
                 model: Optional[str] = None,
                 temperature: float = 0.0):
        self.api_key = openai_api_key or os.environ.get('OPENAI_API_KEY')
        self.model_name = model or os.environ.get('FAP_REVIEW_AUX_EXTRACTOR_MODEL', 'gpt-4o-mini')
        self.temperature = temperature
        self.llm = ChatOpenAI(api_key=self.api_key, model=self.model_name, temperature=temperature)
        self.token_usage_service = TokenUsageService()
        self.file_agent = FileAgent()

    async def extract(self, *,
                      file_path: str,
                      file_name: str,
                      document_text: str | None = None,
                      benefit_anchors: list[dict] | None = None,
                      law_firm_id: int | None = None) -> AuxDocumentExtraction:
        """Extrai dados do documento. Levanta exceção só em falha de chamada/parse."""
        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(
            file_name=file_name,
            document_text=document_text,
            benefit_anchors=benefit_anchors or [],
        )

        if document_text:
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
            mode = 'extracted_text'
        else:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=[
                    {"type": "text", "text": user_message},
                    self._build_attachment_part(file_path),
                ]),
            ]
            mode = 'file_attachment'

        start_time = time.time()
        response = await self.llm.ainvoke(messages)
        latency_ms = int((time.time() - start_time) * 1000)

        self.token_usage_service.capture_and_store(
            {"messages": [response]},
            agent_name="FapAuxiliaryDocumentExtractorAgent",
            action_name="extract_auxiliary_document",
            print_prefix="[FapAuxExtractor]",
            model_name=self.model_name,
            model_provider="openai",
            latency_ms=latency_ms,
            metadata_payload={
                "file_name": file_name,
                "mode": mode,
                "anchors_count": len(benefit_anchors or []),
            },
        )

        data = self._extract_json_dict(str(response.content))
        try:
            return AuxDocumentExtraction(
                document_type=str(data.get('document_type') or 'OUTRO'),
                related_benefits=data.get('related_benefits') or [],
                general_summary=str(data.get('general_summary') or ''),
                potential_divergences=[str(item) for item in data.get('potential_divergences') or []],
            )
        except ValidationError:
            # Degradação graciosa: devolve ao menos o resumo bruto para não perder o documento.
            return AuxDocumentExtraction(
                document_type=str(data.get('document_type') or 'OUTRO'),
                general_summary=str(data.get('general_summary') or '')[:1000],
            )

    def _build_system_prompt(self) -> str:
        return f"""Você é um extrator de dados de documentos que instruem petições de Ação Revisional do FAP (CAT, extratos CNIS/INFBEN, prints do FAP Web, laudos, contestações administrativas).

Sua tarefa: identificar a quais benefícios o documento se refere e extrair APENAS os dados relevantes às teses informadas.

O QUE PROCURAR POR TESE (roteiro de relevância):
- ACIDENTE DE TRAJETO: data, local e descrição do acidente na CAT; indicação de trajeto.
- ERRO DE ESTABELECIMENTO: CNPJ/estabelecimento vinculado ao benefício.
- NEXO TÉCNICO PREVIDENCIÁRIO (inclusive pendente de julgamento): espécie do benefício (B91/B94), CID, NTEP, situação do julgamento.
- PRÉ-FAP: datas relevantes (DDB, DER, data do acidente) para aferir a vigência.
- Sem tese informada: NB, NIT, nome do trabalhador, empregador/CNPJ, espécie, datas de início/fim.

REGRAS INVIOLÁVEIS:
1. Extraia SOMENTE o que estiver escrito no documento. NUNCA invente ou deduza valores.
2. Todo fact deve trazer source_excerpt com o trecho LITERAL (5 a 30 palavras) de onde o dado saiu; se impossível (ex.: imagem), use null.
3. Vincule o documento aos benefícios-âncora quando possível (por NB; na falta, por NIT ou nome do trabalhador — explique em match_reason). Se o documento citar um NB fora da lista de âncoras, inclua-o mesmo assim.
4. Se não conseguir vincular a nenhum benefício, deixe related_benefits vazio e preencha general_summary.
5. Registre em potential_divergences tudo que pareça inconsistente ou digno de conferência contra a petição (datas conflitantes, CNPJ divergente, benefício de espécie diferente da alegada etc.).

CONTRATO TÉCNICO DE SAÍDA (OBRIGATÓRIO):
Responda EXCLUSIVAMENTE com um único JSON válido, sem texto fora do JSON e sem cercas de código.
Use EXATAMENTE os nomes de campos abaixo (em inglês); valores em português. Campos opcionais podem ser null.
{self._OUTPUT_SCHEMA}"""

    def _build_user_message(self, *, file_name: str, document_text: str | None,
                            benefit_anchors: list[dict]) -> str:
        if benefit_anchors:
            anchor_lines = []
            for anchor in benefit_anchors:
                theses = ', '.join(anchor.get('theses') or []) or 'sem tese informada'
                anchor_lines.append(f"- NB {anchor.get('benefit_number')} (teses: {theses})")
            anchors_block = "BENEFÍCIOS-ÂNCORA (vincule o documento a eles quando possível):\n" + "\n".join(anchor_lines)
        else:
            anchors_block = ("BENEFÍCIOS-ÂNCORA: nenhum informado. Identifique você mesmo os números "
                             "de benefício citados no documento.")

        source_block = (
            f"CONTEÚDO DO DOCUMENTO:\n{document_text}"
            if document_text else
            "O documento foi enviado como anexo nesta mensagem."
        )

        return f"""Extraia os dados do documento auxiliar "{file_name}".

{anchors_block}

{source_block}"""

    def _build_attachment_part(self, file_path: str) -> dict:
        """Imagens vão como image_url (data URL); demais formatos como file part."""
        extension = Path(file_path).suffix.lower()
        if extension in _IMAGE_EXTENSIONS:
            mime_type = mimetypes.guess_type(file_path)[0] or 'image/png'
            encoded = base64.b64encode(Path(file_path).read_bytes()).decode('utf-8')
            return {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}}
        return self.file_agent.build_openrouter_file_part(file_path)

    def _extract_json_dict(self, response_text: str) -> dict:
        text = str(response_text or '').strip()
        if text.startswith('```'):
            text = re.sub(r'^```[a-zA-Z]*\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, dict):
                return parsed
        raise ValueError('Resposta do extrator não contém JSON válido')
```

- [ ] **Step 2: Exportar no `__init__.py` do pacote**

Em `app/agents/fap_review/__init__.py`, trocar o bloco de imports/`__all__` por:

```python
from .reviewer_agent import FapPetitionReviewerAgent
from .training_agent import FapTrainingEvolutionAgent
from .training_apply_agent import FapTrainingApplySubAgent
from .auxiliary_extractor_agent import (
	AuxDocumentExtraction,
	AuxExtractedFact,
	AuxRelatedBenefit,
	FapAuxiliaryDocumentExtractorAgent,
)

__all__ = [
	'FapPetitionReviewerAgent',
	'FapTrainingEvolutionAgent',
	'FapTrainingApplySubAgent',
	'FapAuxiliaryDocumentExtractorAgent',
	'AuxDocumentExtraction',
	'AuxExtractedFact',
	'AuxRelatedBenefit',
]
```

(Atenção: o arquivo usa TAB para indentação — manter.)

- [ ] **Step 3: Verificar que importa e o parser de JSON funciona**

Run:
```bash
uv run python - <<'EOF'
from app.agents.fap_review import FapAuxiliaryDocumentExtractorAgent, AuxDocumentExtraction
agent = FapAuxiliaryDocumentExtractorAgent(openai_api_key='sk-test')
fence = '`' * 3
raw = fence + 'json\n{"document_type": "CAT", "related_benefits": [], "general_summary": "ok", "potential_divergences": []}\n' + fence
d = agent._extract_json_dict(raw)
assert d['document_type'] == 'CAT'
r = AuxDocumentExtraction(**d)
assert r.general_summary == 'ok'
print('OK')
EOF
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/agents/fap_review/auxiliary_extractor_agent.py app/agents/fap_review/__init__.py
git commit -m "feat(fap-review): agente extrator de documentos auxiliares guiado por teses"
```

---

### Task 3: Serviço de orquestração `fap_review_aux_service` (com teste dos helpers puros)

**Files:**
- Create: `app/services/fap_review_aux_service.py`
- Test: `tests/test_fap_review_aux_service.py`

**Interfaces:**
- Consumes: `FapAuxiliaryDocumentExtractorAgent.extract(...)` (Task 2); modelo `FapReviewAuxExtraction` (Task 1).
- Produces (usadas na Task 5):
  - `build_benefit_anchors(spreadsheet_rows: list[dict] | None, petition_text: str | None) -> tuple[list[dict], str]` — âncoras `{'benefit_number','benefit_number_normalized','theses': list[str]}` + origem `'spreadsheet' | 'petition_text' | 'none'`.
  - `anchors_fingerprint(anchors: list[dict]) -> str` (sha256 hex).
  - `compute_file_sha256(file_path: str) -> str`.
  - `async run_auxiliary_extractions(*, law_firm_id, documents, spreadsheet_rows, petition_text, extract_text_fn, openai_api_key=None) -> tuple[dict, list[dict]]` — retorna `(payload_para_result_json, documentos_para_o_agente_revisor)`; `documents` = lista `{'name','path'}` do `auxiliary_documents_json`; `extract_text_fn` = `_extract_text_from_document` do blueprint (injetado para evitar import circular).
  - `build_review_payload(results, anchors, anchor_source, skipped) -> dict` e `build_agent_documents(results) -> list[dict]` (puros, testáveis; `results` = `[{'file_name','from_cache','extraction': dict|None,'error': str|None}]`).

- [ ] **Step 1: Escrever o teste standalone (falhando) dos helpers puros**

Criar `tests/test_fap_review_aux_service.py`:

```python
#!/usr/bin/env python3
"""Testes standalone dos helpers puros do fap_review_aux_service.

Uso: uv run python tests/test_fap_review_aux_service.py
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.services import fap_review_aux_service as svc  # noqa: E402


def test_anchors_from_spreadsheet_dedupes_and_merges_theses():
    rows = [
        {'benefit_number': '123.456.789-0', 'benefit_number_normalized': '1234567890', 'thesis': 'ACIDENTE DE TRAJETO', 'sheet_name': '2021'},
        {'benefit_number': '1234567890', 'benefit_number_normalized': '1234567890', 'thesis': 'PRÉ-FAP', 'sheet_name': '2022'},
        {'benefit_number': '987.654.321-0', 'benefit_number_normalized': '9876543210', 'thesis': 'ERRO DE ESTABELECIMENTO', 'sheet_name': '2021'},
    ]
    anchors, source = svc.build_benefit_anchors(rows, petition_text='ignorado')
    assert source == 'spreadsheet', source
    assert len(anchors) == 2, anchors
    first = next(a for a in anchors if a['benefit_number_normalized'] == '1234567890')
    assert first['theses'] == ['ACIDENTE DE TRAJETO', 'PRÉ-FAP'], first


def test_anchors_fallback_from_petition_text():
    text = 'O benefício NB 123.456.789-0 foi convertido. CNPJ 12.345.678/0001-99 não é benefício. Processo 0001234-56.2020.4.04.7100.'
    anchors, source = svc.build_benefit_anchors(None, petition_text=text)
    assert source == 'petition_text', source
    numbers = {a['benefit_number_normalized'] for a in anchors}
    assert '1234567890' in numbers, numbers
    assert all(len(n) == 10 for n in numbers), numbers


def test_anchors_none_when_no_source():
    anchors, source = svc.build_benefit_anchors(None, petition_text=None)
    assert anchors == [] and source == 'none'


def test_fingerprint_stable_and_order_insensitive():
    a1 = [{'benefit_number': '1', 'benefit_number_normalized': '1111111111', 'theses': ['A', 'B']},
          {'benefit_number': '2', 'benefit_number_normalized': '2222222222', 'theses': []}]
    a2 = list(reversed([{**a, 'theses': list(reversed(a['theses']))} for a in a1]))
    assert svc.anchors_fingerprint(a1) == svc.anchors_fingerprint(a2)
    assert svc.anchors_fingerprint(a1) != svc.anchors_fingerprint([])


def test_build_review_payload_status_and_theses_enrichment():
    anchors = [{'benefit_number': '123.456.789-0', 'benefit_number_normalized': '1234567890', 'theses': ['ACIDENTE DE TRAJETO']}]
    results = [
        {'file_name': 'CAT_joao.pdf', 'from_cache': False, 'error': None,
         'extraction': {'document_type': 'CAT',
                        'related_benefits': [{'benefit_number': '123.456.789-0', 'match_reason': 'NB citado',
                                              'facts': [{'label': 'Data do acidente', 'value': '12/03/2019', 'source_excerpt': 'ocorrido em 12/03/2019'}]}],
                        'general_summary': 'CAT do trabalhador João.',
                        'potential_divergences': ['Data diverge da petição']}},
        {'file_name': 'foto.jpg', 'from_cache': True, 'error': None,
         'extraction': {'document_type': 'OUTRO', 'related_benefits': [], 'general_summary': 'Print ilegível.', 'potential_divergences': []}},
        {'file_name': 'quebrado.pdf', 'from_cache': False, 'error': 'Arquivo corrompido', 'extraction': None},
    ]
    payload = svc.build_review_payload(results, anchors, 'spreadsheet', skipped=['extra.pdf'])
    assert payload['anchor_source'] == 'spreadsheet'
    assert payload['total_documents'] == 3
    assert payload['matched_documents'] == 1
    assert payload['skipped_documents'] == ['extra.pdf']
    matched, unmatched, errored = payload['documents']
    assert matched['status'] == 'matched'
    assert matched['related_benefits'][0]['theses'] == ['ACIDENTE DE TRAJETO']
    assert matched['related_benefits'][0]['in_anchor_list'] is True
    assert unmatched['status'] == 'unmatched' and unmatched['from_cache'] is True
    assert errored['status'] == 'error' and errored['error'] == 'Arquivo corrompido'


def test_build_agent_documents_renders_content_summary():
    results = [
        {'file_name': 'CAT_joao.pdf', 'from_cache': False, 'error': None,
         'extraction': {'document_type': 'CAT',
                        'related_benefits': [{'benefit_number': '123.456.789-0', 'match_reason': 'NB citado',
                                              'facts': [{'label': 'Data do acidente', 'value': '12/03/2019', 'source_excerpt': 'ocorrido em 12/03/2019'}]}],
                        'general_summary': 'CAT do trabalhador João.',
                        'potential_divergences': ['Data diverge da petição']}},
        {'file_name': 'quebrado.pdf', 'from_cache': False, 'error': 'x', 'extraction': None},
    ]
    docs = svc.build_agent_documents(results)
    assert docs[0]['name'] == 'CAT_joao.pdf'
    summary = docs[0]['content_summary']
    assert 'Data do acidente: 12/03/2019' in summary
    assert 'ocorrido em 12/03/2019' in summary
    assert 'Possível divergência' in summary
    assert docs[1] == {'name': 'quebrado.pdf'}


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for test in tests:
        try:
            test()
            print(f'  OK  {test.__name__}')
        except AssertionError as exc:
            failed += 1
            print(f'FALHOU {test.__name__}: {exc}')
    print(f'\n{len(tests) - failed}/{len(tests)} testes passaram')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `uv run python tests/test_fap_review_aux_service.py`
Expected: `ModuleNotFoundError`/`ImportError` (o serviço ainda não existe).

- [ ] **Step 3: Implementar o serviço**

Criar `app/services/fap_review_aux_service.py`:

```python
"""
Serviço de extração dirigida dos documentos auxiliares do Revisor FAP — fonte única.

Orquestra: âncoras de benefícios (planilha, com fallback por regex na petição),
cache das extrações por SHA-256 do arquivo e montagem do payload da tela e do
bloco de contexto entregue ao agente revisor.

As extrações rodam SEQUENCIALMENTE (não em asyncio.gather): TokenUsageService e o
cache compartilham a sessão SQLAlchemy da thread, e commits intercalados entre
corrotinas corromperiam a transação.
"""

import hashlib
import json
import os
import re
from pathlib import Path

from flask import current_app

from app.agents.fap_review.auxiliary_extractor_agent import FapAuxiliaryDocumentExtractorAgent
from app.models import db, FapReviewAuxExtraction

try:
    from openpyxl import load_workbook
except ImportError:  # openpyxl é dependência do projeto; guarda defensiva
    load_workbook = None

_TEXT_EXTENSIONS = {'.pdf', '.docx', '.txt'}
_SPREADSHEET_EXTENSIONS = {'.xls', '.xlsx'}
_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'}
_MAX_DOCS = int(os.environ.get('FAP_REVIEW_AUX_MAX_DOCS', '10'))
_MAX_TEXT_CHARS = int(os.environ.get('FAP_REVIEW_AUX_MAX_TEXT_CHARS', '40000'))


def _normalize_number(value) -> str:
    return re.sub(r'\D+', '', str(value or ''))


def build_benefit_anchors(spreadsheet_rows: list[dict] | None,
                          petition_text: str | None) -> tuple[list[dict], str]:
    """Monta a lista de benefícios-âncora. Planilha tem prioridade; sem ela,
    tenta achar NBs (10 dígitos) no texto da petição."""
    anchors: list[dict] = []
    seen: dict[str, dict] = {}

    if spreadsheet_rows:
        for row in spreadsheet_rows:
            normalized = str(row.get('benefit_number_normalized') or '').strip()
            if not normalized:
                continue
            thesis = str(row.get('thesis') or '').strip()
            entry = seen.get(normalized)
            if entry:
                if thesis and thesis not in entry['theses']:
                    entry['theses'].append(thesis)
                continue
            entry = {
                'benefit_number': str(row.get('benefit_number') or normalized),
                'benefit_number_normalized': normalized,
                'theses': [thesis] if thesis else [],
            }
            seen[normalized] = entry
            anchors.append(entry)
        if anchors:
            return anchors, 'spreadsheet'

    if petition_text:
        for candidate in re.findall(r'\d[\d\.\s\-\/]{8,18}\d', petition_text):
            normalized = _normalize_number(candidate)
            if len(normalized) != 10 or normalized in seen:
                continue
            entry = {
                'benefit_number': ' '.join(candidate.split()),
                'benefit_number_normalized': normalized,
                'theses': [],
            }
            seen[normalized] = entry
            anchors.append(entry)
        if anchors:
            return anchors, 'petition_text'

    return [], 'none'


def anchors_fingerprint(anchors: list[dict]) -> str:
    """Hash estável (independe de ordem) da lista de âncoras — compõe a chave do cache."""
    parts = sorted(
        f"{a.get('benefit_number_normalized', '')}:{'|'.join(sorted(a.get('theses') or []))}"
        for a in anchors
    )
    return hashlib.sha256(';'.join(parts).encode('utf-8')).hexdigest()


def compute_file_sha256(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def get_cached_extraction(law_firm_id: int, file_sha256: str,
                          extractor_model: str, fingerprint: str) -> dict | None:
    row = FapReviewAuxExtraction.query.filter_by(
        law_firm_id=law_firm_id,
        file_sha256=file_sha256,
        extractor_model=extractor_model,
        anchors_fingerprint=fingerprint,
    ).first()
    if not row:
        return None
    try:
        parsed = json.loads(row.extraction_json)
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, json.JSONDecodeError):
        return None


def store_extraction(law_firm_id: int, file_sha256: str, file_name: str,
                     extractor_model: str, fingerprint: str, extraction: dict) -> None:
    """Grava/atualiza o cache. Faz commit — chamar fora de transação aberta."""
    existing = FapReviewAuxExtraction.query.filter_by(
        law_firm_id=law_firm_id,
        file_sha256=file_sha256,
        extractor_model=extractor_model,
        anchors_fingerprint=fingerprint,
    ).first()
    if existing:
        existing.extraction_json = json.dumps(extraction, ensure_ascii=False)
        existing.file_name = file_name
    else:
        db.session.add(FapReviewAuxExtraction(
            law_firm_id=law_firm_id,
            file_sha256=file_sha256,
            file_name=file_name,
            extractor_model=extractor_model,
            anchors_fingerprint=fingerprint,
            extraction_json=json.dumps(extraction, ensure_ascii=False),
        ))
    db.session.commit()


def _spreadsheet_to_text(file_path: str) -> str:
    if not load_workbook:
        raise ImportError('openpyxl não está instalado')
    workbook = load_workbook(filename=file_path, read_only=True, data_only=True)
    try:
        lines: list[str] = []
        for worksheet in workbook.worksheets:
            lines.append(f'[ABA: {worksheet.title}]')
            for row in worksheet.iter_rows(values_only=True):
                cells = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
                if cells:
                    lines.append(' | '.join(cells))
        return '\n'.join(lines)
    finally:
        workbook.close()


async def run_auxiliary_extractions(*, law_firm_id: int,
                                    documents: list[dict],
                                    spreadsheet_rows: list[dict] | None,
                                    petition_text: str | None,
                                    extract_text_fn,
                                    openai_api_key: str | None = None) -> tuple[dict, list[dict]]:
    """Extrai todos os documentos auxiliares e retorna (payload da tela, docs p/ o revisor)."""
    anchors, anchor_source = build_benefit_anchors(spreadsheet_rows, petition_text)
    fingerprint = anchors_fingerprint(anchors)

    valid_docs = [d for d in documents if isinstance(d, dict) and d.get('path')]
    skipped = [str(d.get('name') or Path(str(d.get('path'))).name) for d in valid_docs[_MAX_DOCS:]]
    if skipped:
        current_app.logger.warning(
            'FAP aux: %s documentos acima do limite FAP_REVIEW_AUX_MAX_DOCS=%s foram pulados: %s',
            len(skipped), _MAX_DOCS, ', '.join(skipped))
    valid_docs = valid_docs[:_MAX_DOCS]

    agent = FapAuxiliaryDocumentExtractorAgent(openai_api_key=openai_api_key)
    results: list[dict] = []

    for doc in valid_docs:
        path = str(doc['path'])
        name = str(doc.get('name') or Path(path).name)
        try:
            if not Path(path).exists():
                raise FileNotFoundError(f'Arquivo não encontrado: {path}')

            sha = compute_file_sha256(path)
            cached = get_cached_extraction(law_firm_id, sha, agent.model_name, fingerprint)
            if cached is not None:
                results.append({'file_name': name, 'from_cache': True, 'extraction': cached, 'error': None})
                continue

            extension = Path(path).suffix.lower()
            document_text = None
            if extension in _SPREADSHEET_EXTENSIONS:
                document_text = _spreadsheet_to_text(path)
            elif extension in _TEXT_EXTENSIONS:
                try:
                    document_text = extract_text_fn(path)
                except Exception as text_error:
                    current_app.logger.warning('FAP aux: extração de texto falhou (%s): %s', name, text_error)
                    document_text = None
            if document_text:
                document_text = document_text[:_MAX_TEXT_CHARS]
            if not document_text and extension not in (_IMAGE_EXTENSIONS | {'.pdf'}):
                raise ValueError('Não foi possível extrair texto do arquivo')

            extraction = await agent.extract(
                file_path=path,
                file_name=name,
                document_text=document_text,
                benefit_anchors=anchors,
                law_firm_id=law_firm_id,
            )
            extraction_dict = extraction.model_dump(mode='json')
            store_extraction(law_firm_id, sha, name, agent.model_name, fingerprint, extraction_dict)
            results.append({'file_name': name, 'from_cache': False, 'extraction': extraction_dict, 'error': None})
        except Exception as exc:
            current_app.logger.warning('FAP aux: extração falhou (%s): %s', name, exc)
            results.append({'file_name': name, 'from_cache': False, 'extraction': None, 'error': str(exc)})

    payload = build_review_payload(results, anchors, anchor_source, skipped)
    agent_documents = build_agent_documents(results)
    return payload, agent_documents


def build_review_payload(results: list[dict], anchors: list[dict],
                         anchor_source: str, skipped: list[str]) -> dict:
    """Payload persistido em result_json['auxiliary_documents_review'] e lido pela tela."""
    theses_map = {a['benefit_number_normalized']: a.get('theses') or [] for a in anchors}
    documents: list[dict] = []
    matched_count = 0

    for item in results:
        extraction = item.get('extraction') or {}
        related: list[dict] = []
        for benefit in extraction.get('related_benefits') or []:
            if not isinstance(benefit, dict):
                continue
            normalized = _normalize_number(benefit.get('benefit_number'))
            related.append({
                'benefit_number': str(benefit.get('benefit_number') or ''),
                'benefit_number_normalized': normalized,
                'theses': theses_map.get(normalized, []),
                'in_anchor_list': normalized in theses_map,
                'match_reason': str(benefit.get('match_reason') or ''),
                'facts': [
                    {
                        'label': str(fact.get('label') or ''),
                        'value': str(fact.get('value') or ''),
                        'source_excerpt': str(fact.get('source_excerpt') or '') or None,
                    }
                    for fact in (benefit.get('facts') or []) if isinstance(fact, dict)
                ],
            })

        if item.get('error'):
            status = 'error'
        elif related:
            status = 'matched'
            matched_count += 1
        else:
            status = 'unmatched'

        documents.append({
            'file_name': item.get('file_name') or '',
            'document_type': str(extraction.get('document_type') or 'OUTRO'),
            'status': status,
            'related_benefits': related,
            'general_summary': str(extraction.get('general_summary') or ''),
            'potential_divergences': [str(d) for d in extraction.get('potential_divergences') or []],
            'from_cache': bool(item.get('from_cache')),
            'error': item.get('error'),
        })

    return {
        'anchor_source': anchor_source,
        'total_documents': len(results),
        'matched_documents': matched_count,
        'documents': documents,
        'skipped_documents': list(skipped or []),
    }


def build_agent_documents(results: list[dict]) -> list[dict]:
    """Converte extrações em [{'name', 'content_summary'}] para o prompt do revisor."""
    agent_docs: list[dict] = []
    for item in results:
        name = item.get('file_name') or 'arquivo_sem_nome'
        extraction = item.get('extraction')
        if not extraction:
            agent_docs.append({'name': name})
            continue

        lines = [f"Tipo: {extraction.get('document_type') or 'OUTRO'}"]
        summary = str(extraction.get('general_summary') or '').strip()
        if summary:
            lines.append(f"Resumo: {summary}")
        for benefit in extraction.get('related_benefits') or []:
            if not isinstance(benefit, dict):
                continue
            lines.append(
                f"Benefício {benefit.get('benefit_number')} — vínculo: {benefit.get('match_reason') or 'não informado'}")
            for fact in benefit.get('facts') or []:
                if not isinstance(fact, dict):
                    continue
                excerpt = fact.get('source_excerpt')
                suffix = f' (trecho: "{excerpt}")' if excerpt else ''
                lines.append(f"  - {fact.get('label')}: {fact.get('value')}{suffix}")
        for divergence in extraction.get('potential_divergences') or []:
            lines.append(f"Possível divergência: {divergence}")

        agent_docs.append({'name': name, 'content_summary': '\n'.join(lines)})
    return agent_docs
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `uv run python tests/test_fap_review_aux_service.py`
Expected: `6/6 testes passaram` (exit code 0).

- [ ] **Step 5: Commit**

```bash
git add app/services/fap_review_aux_service.py tests/test_fap_review_aux_service.py
git commit -m "feat(fap-review): serviço de extração dirigida dos documentos auxiliares"
```

---

### Task 4: Injetar o conteúdo extraído e a instrução de cruzamento no revisor

**Files:**
- Modify: `app/agents/fap_review/reviewer_agent.py` (método `_format_auxiliary_documents`, ~linha 900)

**Interfaces:**
- Consumes: `auxiliary_documents` agora chega como `[{'name': str, 'content_summary': str}]` (produzido por `build_agent_documents`, Task 3). Dicts sem `content_summary` continuam válidos (só o nome é citado).
- Produces: bloco de prompt com dados + instrução de cruzamento, usado por `_build_single_user_message` e `_build_comparative_user_message` (que já chamam `_format_auxiliary_documents` — nenhuma outra mudança neles).

- [ ] **Step 1: Substituir `_format_auxiliary_documents`**

Trocar o método inteiro (linhas ~900–917) por:

```python
    _AUX_CROSS_CHECK_INSTRUCTIONS = """CRUZAMENTO OBRIGATÓRIO COM OS DOCUMENTOS AUXILIARES:
Os dados acima foram extraídos automaticamente dos documentos auxiliares enviados, com o trecho literal de origem.
1. Compare cada dado (razão social, CNPJ, números de benefício, NIT, espécie, datas, vigências, valores) com o que a petição afirma.
2. Divergência entre documento auxiliar e petição = finding, com severidade adequada, localização na petição e citação do documento-fonte na descrição (ex.: 'segundo CAT_fulano.pdf, ...').
3. Se o dado conferir, não gere finding sobre ele.
4. Se um documento auxiliar comprovar a presença de um documento que você apontaria como faltante, NÃO o liste em missing_documents — cite-o como atendido.
5. Trate os dados extraídos como afirmações dos documentos auxiliares, não como verdade absoluta: em caso de conflito, aponte a divergência para conferência humana em vez de presumir qual lado está errado."""

    def _format_auxiliary_documents(self, auxiliary_documents: list[dict] | None) -> str:
        """Monta o bloco dos documentos auxiliares: nomes + dados extraídos + instrução de cruzamento."""
        if not auxiliary_documents:
            return ""

        names: list[str] = []
        blocks: list[str] = []
        for doc in auxiliary_documents:
            if isinstance(doc, dict):
                name = str(doc.get("name") or "arquivo_sem_nome")
                names.append(name)
                content_summary = str(doc.get("content_summary") or "").strip()
                if content_summary:
                    blocks.append(f"--- {name} ---\n{content_summary}")
            else:
                names.append(str(doc))

        preview_names = names[:self._AUX_PREVIEW_LIMIT]
        suffix = ""
        if len(names) > len(preview_names):
            suffix = f" (+{len(names) - len(preview_names)} arquivos)"
        header = (f"DOCUMENTOS AUXILIARES ({len(auxiliary_documents)} arquivos){suffix}: "
                  + ", ".join(preview_names))

        if not blocks:
            return header

        return (header
                + "\n\nDADOS EXTRAÍDOS DOS DOCUMENTOS AUXILIARES:\n"
                + "\n\n".join(blocks)
                + "\n\n" + self._AUX_CROSS_CHECK_INSTRUCTIONS)
```

(`_AUX_CROSS_CHECK_INSTRUCTIONS` entra como atributo de classe imediatamente antes do método; manter a indentação de método/atributo da classe.)

- [ ] **Step 2: Verificar o comportamento nos dois formatos de entrada**

Run:
```bash
uv run python -c "
from app.agents.fap_review.reviewer_agent import FapPetitionReviewerAgent
agent = FapPetitionReviewerAgent(openai_api_key='sk-test')
assert agent._format_auxiliary_documents(None) == ''
legacy = agent._format_auxiliary_documents([{'name': 'a.pdf'}, {'name': 'b.pdf'}])
assert 'DOCUMENTOS AUXILIARES (2 arquivos)' in legacy and 'CRUZAMENTO' not in legacy
rich = agent._format_auxiliary_documents([{'name': 'CAT.pdf', 'content_summary': 'Tipo: CAT\nBenefício 123 — vínculo: NB citado'}])
assert 'DADOS EXTRAÍDOS DOS DOCUMENTOS AUXILIARES' in rich
assert 'CRUZAMENTO OBRIGATÓRIO' in rich and 'CAT.pdf' in rich
msg = agent._build_single_user_message(auxiliary_documents=[{'name': 'CAT.pdf', 'content_summary': 'Tipo: CAT'}], petition_text='texto', prior_attention_points=None)
assert 'CRUZAMENTO OBRIGATÓRIO' in msg
print('OK')
"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/agents/fap_review/reviewer_agent.py
git commit -m "feat(fap-review): revisor cruza dados extraídos dos documentos auxiliares"
```

---

### Task 5: Ligar o fio no blueprint (`_execute_reviewer_agent`)

**Files:**
- Modify: `app/blueprints/fap_review.py` (função `_execute_reviewer_agent`, ~linhas 566–749)

**Interfaces:**
- Consumes: `run_auxiliary_extractions(...)` (Task 3); `execution.auxiliary_documents_json` (`[{'name','path'}]`, já gravado pelo upload); `_parse_benefits_spreadsheet` e `_extract_text_from_document` (já existem no blueprint).
- Produces: `result_payload['auxiliary_documents_review']` (payload da Task 3) persistido em `result_json`; `auxiliary_documents=<agent_docs>` passado às duas chamadas do revisor.

- [ ] **Step 1: Importar o serviço**

No topo de `app/blueprints/fap_review.py`, junto dos imports de serviços (procure `from app.services import fap_review_service as _svc`), adicionar:

```python
from app.services import fap_review_aux_service as _aux_svc
```

- [ ] **Step 2: Rodar as extrações antes da revisão**

Dentro de `_execute_reviewer_agent`, no bloco `try:` do loop asyncio — logo APÓS o cálculo de `compared_text` (procure `compared_text = _extract_text_from_document(compared_file_path)`) e ANTES do `if compared_file_path and execution.comparative_analysis:` — inserir:

```python
            # ===== Extração dirigida dos documentos auxiliares (opcional) =====
            aux_review_payload = None
            auxiliary_agent_docs = None
            try:
                aux_docs = json.loads(execution.auxiliary_documents_json or '[]')
            except (TypeError, json.JSONDecodeError):
                aux_docs = []
            if aux_docs:
                spreadsheet_rows = None
                if benefits_spreadsheet and benefits_spreadsheet.get('path'):
                    try:
                        spreadsheet_rows = _parse_benefits_spreadsheet(str(benefits_spreadsheet['path']))
                    except Exception as spreadsheet_error:
                        current_app.logger.warning(
                            'FAP aux: planilha ilegível para âncoras (execução %s): %s',
                            execution_id, spreadsheet_error)
                anchor_text = (
                    compared_text
                    if compared_file_path and execution.comparative_analysis
                    else petition_text
                )
                try:
                    aux_review_payload, auxiliary_agent_docs = loop.run_until_complete(
                        _aux_svc.run_auxiliary_extractions(
                            law_firm_id=law_firm_id,
                            documents=aux_docs,
                            spreadsheet_rows=spreadsheet_rows,
                            petition_text=anchor_text,
                            extract_text_fn=_extract_text_from_document,
                            openai_api_key=openai_api_key,
                        )
                    )
                except Exception as aux_error:
                    # Falha na extração NUNCA derruba a revisão.
                    current_app.logger.warning(
                        'FAP aux: extração dos auxiliares falhou (execução %s): %s',
                        execution_id, aux_error)
                    aux_review_payload = {
                        'anchor_source': 'none',
                        'total_documents': len(aux_docs),
                        'matched_documents': 0,
                        'documents': [],
                        'skipped_documents': [],
                        'error': str(aux_error),
                    }
                    auxiliary_agent_docs = None
```

- [ ] **Step 3: Passar os documentos ao revisor**

Na chamada `agent.review_petition_comparative(...)`, adicionar o argumento (após `prior_attention_points=prior_attention_points,`):

```python
                        auxiliary_documents=auxiliary_agent_docs,
```

Fazer o mesmo na chamada `agent.review_petition_single_version(...)` (após `prior_attention_points=prior_attention_points,`):

```python
                        auxiliary_documents=auxiliary_agent_docs,
```

- [ ] **Step 4: Persistir o payload no resultado**

Logo após `result_payload = result.model_dump(mode='json')` (antes do bloco `if benefits_spreadsheet and ...`), inserir:

```python
            if aux_review_payload is not None:
                result_payload['auxiliary_documents_review'] = aux_review_payload
```

- [ ] **Step 5: Verificação de sanidade (import + rota)**

Run: `uv run python -c "import app.blueprints.fap_review; print('OK')"`
Expected: `OK`

Run: `uv run python tests/test_fap_review_aux_service.py`
Expected: `6/6 testes passaram`

- [ ] **Step 6: Commit**

```bash
git add app/blueprints/fap_review.py
git commit -m "feat(fap-review): revisão consome documentos auxiliares extraídos"
```

---

### Task 6: Card "Documentos Auxiliares × Benefícios" na tela de resultado

**Files:**
- Modify: `templates/fap_review/revision_result.html` (inserir após o card `benefits_spreadsheet_review`, que termina no `{% endif %}` da ~linha 1183)

**Interfaces:**
- Consumes: `result_data.auxiliary_documents_review` (shape da Task 3: `anchor_source`, `total_documents`, `matched_documents`, `documents[]` com `file_name/document_type/status/related_benefits[]/general_summary/potential_divergences[]/from_cache/error`, `skipped_documents[]`, opcional `error`).

- [ ] **Step 1: Inserir o card**

Após o `{% endif %}` que fecha o bloco `{% if result_data.benefits_spreadsheet_review %}`, inserir:

```html
            {% if result_data.auxiliary_documents_review %}
            {% set aux_review = result_data.auxiliary_documents_review %}
            <div class="col-12">
                <div class="card info-card">
                    <div class="card-header d-flex align-items-center justify-content-between gap-2">
                        <div class="d-flex align-items-center gap-2">
                            <i class="bi bi-paperclip text-primary"></i>
                            Documentos Auxiliares x Beneficios
                        </div>
                        {% if aux_review.anchor_source == 'spreadsheet' %}
                        <span class="badge rounded-pill bg-success-subtle text-success-emphasis border border-success-subtle px-3">
                            Vinculo guiado pela planilha de beneficios
                        </span>
                        {% elif aux_review.anchor_source == 'petition_text' %}
                        <span class="badge rounded-pill bg-warning-subtle text-warning-emphasis border border-warning-subtle px-3">
                            Sem planilha — beneficios localizados na peticao
                        </span>
                        {% endif %}
                    </div>
                    <div class="card-body">
                        {% if aux_review.error %}
                        <div class="alert alert-warning mb-0">
                            <div class="fw-semibold mb-1">Nao foi possivel processar os documentos auxiliares.</div>
                            <div class="small mb-0">{{ aux_review.error }}</div>
                        </div>
                        {% else %}
                        <div class="row g-3 mb-4">
                            <div class="col-sm-6 col-lg-4">
                                <div class="summary-stat" style="border-left: 4px solid #0d6efd;">
                                    <div class="d-flex align-items-center gap-2 mb-2">
                                        <i class="bi bi-files text-primary"></i>
                                        <div class="summary-stat-label" style="margin: 0;">Analisados</div>
                                    </div>
                                    <div class="summary-stat-value text-primary">{{ aux_review.total_documents or 0 }}</div>
                                </div>
                            </div>
                            <div class="col-sm-6 col-lg-4">
                                <div class="summary-stat" style="border-left: 4px solid #198754;">
                                    <div class="d-flex align-items-center gap-2 mb-2">
                                        <i class="bi bi-link-45deg text-success"></i>
                                        <div class="summary-stat-label" style="margin: 0;">Vinculados a beneficios</div>
                                    </div>
                                    <div class="summary-stat-value text-success">{{ aux_review.matched_documents or 0 }}</div>
                                </div>
                            </div>
                            <div class="col-sm-6 col-lg-4">
                                <div class="summary-stat" style="border-left: 4px solid #6c757d;">
                                    <div class="d-flex align-items-center gap-2 mb-2">
                                        <i class="bi bi-question-circle text-secondary"></i>
                                        <div class="summary-stat-label" style="margin: 0;">Sem vinculo / erro</div>
                                    </div>
                                    <div class="summary-stat-value text-secondary">
                                        {{ (aux_review.total_documents or 0) - (aux_review.matched_documents or 0) }}</div>
                                </div>
                            </div>
                        </div>

                        {% if aux_review.get('documents') %}
                        <div class="table-responsive">
                            <table class="table table-hover mb-0 align-middle">
                                <thead class="table-light">
                                    <tr>
                                        <th class="ps-3">Arquivo</th>
                                        <th>Tipo</th>
                                        <th>Beneficios relacionados</th>
                                        <th class="pe-3">Dados extraidos</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for doc in aux_review.documents %}
                                    <tr{% if doc.status == 'error' %} style="background: rgba(220, 53, 69, 0.10);"{% endif %}>
                                        <td class="ps-3">
                                            <div class="fw-semibold">{{ doc.file_name }}</div>
                                            {% if doc.from_cache %}
                                            <span class="badge rounded-pill bg-light text-dark border mt-1">
                                                <i class="bi bi-lightning-charge me-1"></i>Reaproveitado
                                            </span>
                                            {% endif %}
                                        </td>
                                        <td><span class="badge rounded-pill bg-primary-subtle text-primary-emphasis border border-primary-subtle">
                                                {{ doc.document_type or 'OUTRO' }}</span></td>
                                        <td>
                                            {% if doc.status == 'error' %}
                                            <span class="badge rounded-pill bg-danger-subtle text-danger-emphasis border border-danger-subtle">
                                                <i class="bi bi-x-circle me-1"></i>Falha na leitura
                                            </span>
                                            <div class="small text-danger mt-1">{{ doc.error }}</div>
                                            {% elif doc.related_benefits %}
                                            {% for benefit in doc.related_benefits %}
                                            <div class="mb-1">
                                                <span class="badge rounded-pill bg-success-subtle text-success-emphasis border border-success-subtle"
                                                      title="{{ benefit.match_reason }}">
                                                    NB {{ benefit.benefit_number }}
                                                </span>
                                                {% for thesis in benefit.theses %}
                                                <span class="badge rounded-pill bg-light text-dark border">{{ thesis }}</span>
                                                {% endfor %}
                                                {% if not benefit.in_anchor_list %}
                                                <span class="badge rounded-pill bg-warning-subtle text-warning-emphasis border border-warning-subtle"
                                                      title="Beneficio citado no documento mas ausente da planilha/peticao">
                                                    fora da lista
                                                </span>
                                                {% endif %}
                                            </div>
                                            {% endfor %}
                                            {% else %}
                                            <span class="badge rounded-pill bg-secondary-subtle text-secondary-emphasis border border-secondary-subtle">
                                                Sem vinculo identificado
                                            </span>
                                            {% endif %}
                                        </td>
                                        <td class="pe-3">
                                            {% if doc.general_summary %}
                                            <div class="small text-muted mb-1">{{ doc.general_summary }}</div>
                                            {% endif %}
                                            {% for benefit in doc.related_benefits %}
                                            {% for fact in benefit.facts %}
                                            <div class="small">
                                                <span class="fw-semibold">{{ fact.label }}:</span> {{ fact.value }}
                                                {% if fact.source_excerpt %}
                                                <i class="bi bi-quote text-muted" title="{{ fact.source_excerpt }}"></i>
                                                {% endif %}
                                            </div>
                                            {% endfor %}
                                            {% endfor %}
                                            {% for divergence in doc.potential_divergences %}
                                            <div class="small text-warning-emphasis">
                                                <i class="bi bi-exclamation-triangle me-1"></i>{{ divergence }}
                                            </div>
                                            {% endfor %}
                                        </td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                        {% else %}
                        <div class="alert alert-light border mb-0">
                            <div class="fw-semibold mb-1">Nenhum documento auxiliar foi analisado.</div>
                        </div>
                        {% endif %}

                        {% if aux_review.get('skipped_documents') %}
                        <div class="alert alert-warning mt-3 mb-0">
                            <div class="fw-semibold mb-1">Documentos nao analisados por limite de quantidade:</div>
                            <div class="small mb-0">{{ aux_review.skipped_documents | join(', ') }}</div>
                        </div>
                        {% endif %}
                        {% endif %}
                    </div>
                </div>
            </div>
            {% endif %}
```

- [ ] **Step 2: Verificar que o template parseia e contém o card**

Run:
```bash
uv run python -c "
from main import app
source = open('templates/fap_review/revision_result.html').read()
app.jinja_env.parse(source)
assert 'auxiliary_documents_review' in source
print('OK: template parseia e contem o card novo')
"
```
Expected: `OK: template parseia e contem o card novo`

(Validação visual completa acontece na Task 7 com uma revisão de ponta a ponta.)

- [ ] **Step 3: Commit**

```bash
git add templates/fap_review/revision_result.html
git commit -m "feat(fap-review): card Documentos Auxiliares x Beneficios no resultado"
```

---

### Task 7: Manual do usuário + verificação de ponta a ponta

**Files:**
- Modify: `docs/MANUAL_REVISOR_PETICOES.md`

**Interfaces:**
- Consumes: comportamento implementado nas Tasks 1–6 (nomes de card/badges exatamente como na Task 6).

- [ ] **Step 1: Documentar no manual**

Em `docs/MANUAL_REVISOR_PETICOES.md`, localizar a seção que descreve os documentos auxiliares/planilha da tela de revisão (procure por "auxiliares" ou "planilha") e acrescentar ao final dela:

```markdown
### Cruzamento dos documentos auxiliares :claude:

> [!IA]
> Ao enviar documentos auxiliares (CAT, CNIS, INFBEN, prints do FAP Web, laudos), a IA lê cada arquivo, identifica a quais benefícios ele se refere e extrai os dados relevantes às teses da planilha de benefícios. Esses dados são cruzados com a petição: divergências (datas, CNPJ, razão social, espécie do benefício) viram apontamentos na revisão, sempre citando o arquivo de origem.

Como funciona:

| Etapa | Origem |
| --- | --- |
| Identificação dos benefícios e teses | Relatório |
| Leitura e extração dos documentos auxiliares | IA |
| Cruzamento contra a petição | IA |
| Card "Documentos Auxiliares × Benefícios" | Sistema |

- Com a **planilha de benefícios** enviada, a extração é guiada pelas teses de cada benefício (ex.: tese de acidente de trajeto faz a IA buscar data e local do acidente na CAT).
- Sem planilha, os números de benefício são localizados na própria petição.
- Arquivos reenviados em revisões seguintes não são reprocessados (aparecem com o selo "Reaproveitado").
- Documentos que a IA não conseguir vincular a nenhum benefício aparecem como "Sem vínculo identificado" — confira-os manualmente.
```

- [ ] **Step 2: Verificação de ponta a ponta**

Pré-requisito: `.env` com `OPENAI_API_KEY` válida e banco acessível.

1. Subir a aplicação: `uv run python main.py`
2. Em `/fap-review/revision`, enviar uma petição DOCX + planilha de benefícios XLSX + ao menos 1 documento auxiliar (um PDF de CAT ou CNIS real de teste).
3. Aguardar a conclusão (a tela de resultado se atualiza sozinha) e conferir:
   - Card **"Documentos Auxiliares x Beneficios"** presente, com o arquivo vinculado ao NB correto e dados extraídos com trecho-fonte (ícone de aspas com tooltip).
   - Badge do topo indicando "Vinculo guiado pela planilha de beneficios".
   - Se houver divergência plantada de propósito (ex.: data errada na petição), finding citando o arquivo auxiliar.
4. Reenviar a MESMA revisão marcando o reuso de auxiliares e conferir o selo "Reaproveitado" (cache funcionou — sem nova chamada de extração no log).
5. Enviar uma revisão com auxiliar e SEM planilha e conferir a badge "Sem planilha — beneficios localizados na peticao".
6. Rodar `uv run python tests/test_fap_review_aux_service.py` → `6/6 testes passaram`.

Expected: todos os pontos acima confirmados; nenhuma revisão falha por causa dos auxiliares (teste também com um arquivo corrompido: a revisão conclui e o card mostra "Falha na leitura").

- [ ] **Step 3: Commit final**

```bash
git add docs/MANUAL_REVISOR_PETICOES.md
git commit -m "docs(fap-review): manual do cruzamento de documentos auxiliares"
```
