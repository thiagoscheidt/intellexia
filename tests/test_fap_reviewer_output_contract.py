"""
Teste do contrato de saída do FapPetitionReviewerAgent.

Cobre a regressão em que o modelo respondeu JSON com chaves em português
(titulo/gravidade/descricao), os parsers descartaram tudo silenciosamente e a
execução foi persistida como sucesso com resultado vazio.

Verifica:
1. O system prompt sempre contém o contrato técnico de schema (nomes de campos
   em inglês), mesmo com revisor_output_format vazio.
2. Parsers são por item: um item inválido não derruba os válidos.
3. Itens rejeitados são coletados em parse_errors.
4. Resposta com itens presentes mas nenhum válido gera ReviewOutputParseError.
5. Resposta sem JSON extraível gera ReviewOutputParseError.

Uso: uv run python tests/test_fap_reviewer_output_contract.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')
os.environ.setdefault('OPENAI_BASE_URL', 'https://openrouter.ai/api/v1')

from app.agents.fap_review.reviewer_agent import (  # noqa: E402
    FapPetitionReviewerAgent,
    FindingItem,
    ReviewOutputParseError,
)

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label} {detail}")


def build_agent() -> FapPetitionReviewerAgent:
    return FapPetitionReviewerAgent(openai_api_key='test-key', model='gpt-4o-mini')


def test_system_prompt_contains_schema_contract():
    print("[1] System prompt com contrato de schema mesmo sem output_format configurado")
    agent = build_agent()
    prompt = agent._build_system_prompt("", "", "", focused_review=False)
    for field in ('"thesis"', '"category"', '"severity"', '"description"',
                  '"location_excerpt"', '"missing_documents"', '"executive_summary"', '"total_findings"'):
        check(f"prompt contém {field}", field in prompt)

    comparative_prompt = agent._build_system_prompt("", "", "", focused_review=False, comparative=True)
    for field in ('"comparative_changes"', '"original_excerpt"', '"corrected_excerpt"'):
        check(f"prompt comparativo contém {field}", field in comparative_prompt)


def test_parse_findings_is_per_item():
    print("[2] Parser por item: item inválido não derruba os válidos")
    agent = build_agent()
    data = [
        {"gravidade": "CRÍTICO", "tipo": "x", "descricao": "chaves em português"},
        {"category": "CAT-1", "severity": "CRÍTICO", "description": "item válido"},
    ]
    errors: list[str] = []
    findings = agent._parse_findings(data, errors)
    check("1 item válido preservado", len(findings) == 1, f"(obteve {len(findings)})")
    check("item preservado é o válido", bool(findings) and isinstance(findings[0], FindingItem)
          and findings[0].description == "item válido")
    check("erro do item inválido coletado", len(errors) == 1, f"(obteve {len(errors)})")


def test_all_items_rejected_raises():
    print("[3] Resposta com itens presentes mas nenhum válido → ReviewOutputParseError")
    agent = build_agent()
    result_dict = {
        "theses": [{"titulo": "Acidentes de trajeto", "status": "identificada"}],
        "findings": [{"gravidade": "CRÍTICO", "tipo": "x", "descricao": "y"}],
        "missing_documents": [],
        "executive_summary": {},
    }
    errors: list[str] = []
    theses = agent._parse_theses(result_dict["theses"], errors)
    findings = agent._parse_findings(result_dict["findings"], errors)
    missing = agent._parse_missing_documents(result_dict["missing_documents"], errors)
    try:
        agent._ensure_output_parsed(
            result_dict,
            parsed_items=len(theses) + len(findings) + len(missing),
            list_keys=("theses", "findings", "missing_documents"),
            parse_errors=errors,
        )
        check("levantou ReviewOutputParseError", False, "(não levantou)")
    except ReviewOutputParseError:
        check("levantou ReviewOutputParseError", True)


def test_valid_items_do_not_raise():
    print("[4] Resposta com itens válidos não levanta erro")
    agent = build_agent()
    result_dict = {
        "theses": [],
        "findings": [{"category": "CAT-1", "severity": "CRÍTICO", "description": "ok"}],
        "missing_documents": [],
        "executive_summary": {"total_findings": 1, "critical_findings": 1,
                              "moderate_findings": 0, "formal_findings": 0,
                              "correction_priority": "Alta"},
    }
    errors: list[str] = []
    findings = agent._parse_findings(result_dict["findings"], errors)
    try:
        agent._ensure_output_parsed(
            result_dict,
            parsed_items=len(findings),
            list_keys=("theses", "findings", "missing_documents"),
            parse_errors=errors,
        )
        check("não levantou exceção", True)
    except ReviewOutputParseError as exc:
        check("não levantou exceção", False, f"({exc})")

    print("[4b] Revisão legitimamente vazia (0 achados) não levanta erro")
    empty_dict = {"theses": [], "findings": [], "missing_documents": [],
                  "executive_summary": {"total_findings": 0, "critical_findings": 0,
                                        "moderate_findings": 0, "formal_findings": 0,
                                        "correction_priority": "N/A"}}
    try:
        agent._ensure_output_parsed(empty_dict, parsed_items=0,
                                    list_keys=("theses", "findings", "missing_documents"),
                                    parse_errors=[])
        check("não levantou exceção", True)
    except ReviewOutputParseError as exc:
        check("não levantou exceção", False, f"({exc})")


def test_executive_summary_counts_recomputed():
    print("[6] Totais do resumo executivo recontados dos achados mantidos")
    agent = build_agent()
    findings = agent._parse_findings([
        {"category": "CAT-1", "severity": "MODERADO", "description": "a"},
        {"category": "CAT-2", "severity": "FORMAL", "description": "b"},
        {"category": "CAT-3", "severity": "MODERADO", "description": "c"},
    ])
    # Modelo contou 1 crítico que o filtro de falso-positivo descartou
    model_summary = {"total_findings": 4, "critical_findings": 1, "moderate_findings": 2,
                     "formal_findings": 1, "main_legal_risks": ["risco X"],
                     "correction_priority": "Alta"}
    summary = agent._build_executive_summary(model_summary, findings)
    check("total recontado", summary.total_findings == 3, f"(obteve {summary.total_findings})")
    check("críticos recontados", summary.critical_findings == 0)
    check("moderados recontados", summary.moderate_findings == 2)
    check("formais recontados", summary.formal_findings == 1)
    check("riscos preservados", summary.main_legal_risks == ["risco X"])
    check("prioridade preservada", summary.correction_priority == "Alta")


def test_no_json_raises():
    print("[5] Resposta sem JSON extraível → ReviewOutputParseError")
    agent = build_agent()
    try:
        agent._ensure_output_parsed({}, parsed_items=0,
                                    list_keys=("theses", "findings", "missing_documents"),
                                    parse_errors=[])
        check("levantou ReviewOutputParseError", False, "(não levantou)")
    except ReviewOutputParseError:
        check("levantou ReviewOutputParseError", True)


if __name__ == '__main__':
    test_system_prompt_contains_schema_contract()
    test_parse_findings_is_per_item()
    test_all_items_rejected_raises()
    test_valid_items_do_not_raise()
    test_executive_summary_counts_recomputed()
    test_no_json_raises()
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
