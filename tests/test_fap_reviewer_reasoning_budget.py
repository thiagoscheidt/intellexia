"""
Teste do orçamento de raciocínio do FapPetitionReviewerAgent.

Cobre a falha de produção de 04/08/2026 (execução 53, token usage 1065): a
revisão de uma petição de FAP retornou finish_reason='length' com 65.536 tokens
de saída — o teto do anthropic/claude-sonnet-5. O texto que chegou tinha apenas
26.025 chars (~8k tokens); os ~57k restantes foram consumidos por raciocínio
interno, que sai do MESMO orçamento de saída que o JSON. O JSON veio cortado no
meio, o parser devolveu {} e a revisão morreu com "A resposta do modelo não
contém JSON válido para a revisão."

Não era caso isolado: das 24 execuções anteriores, 3 (12,5%) já passavam de
50.000 tokens de saída e a maior chegou a 56.251 (86% do teto). O tamanho da
petição não prevê a falha — execuções com entrada de 194.399 e 169.924 tokens
concluíram normalmente, enquanto a que quebrou tinha entrada de 143.951.

Verifica:
1. O agente envia reasoning.max_tokens ao OpenRouter por padrão.
2. O orçamento reservado deixa folga confortável para o JSON.
3. O limite é configurável por env e pode ser desligado com 0.

Uso: uv run python tests/test_fap_reviewer_reasoning_budget.py
"""

import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')
os.environ.setdefault('OPENAI_BASE_URL', 'https://openrouter.ai/api/v1')

import app.agents.fap_review.reviewer_agent as reviewer_module  # noqa: E402

PASSED = 0
FAILED = 0

# Teto de saída observado no anthropic/claude-sonnet-5 via OpenRouter.
MODEL_OUTPUT_CEILING = 65536
# Maior JSON de revisão efetivamente observado: 26.025 chars ≈ 8k tokens — e ele
# estava TRUNCADO, então o completo seria maior; estimamos 12-15k tokens para uma
# revisão de 12 teses. (output_tokens do banco NÃO serve de referência aqui:
# inclui o raciocínio, sem separar as duas parcelas.)
# Exigimos folga >= 20k (~60-80k chars), ~2x esse pior caso estimado. O limite
# guarda a invariante que quebrou em produção — raciocínio não pode consumir o
# orçamento a ponto de não sobrar espaço para o JSON.
MIN_JSON_HEADROOM = 20000


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label} {detail}")


def reload_with_env(**env: str):
    """Recarrega o módulo com env alterado (limites são lidos no import)."""
    previous = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return importlib.reload(reviewer_module)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_reasoning_budget_sent_by_default():
    print("[1] Agente envia reasoning.max_tokens ao OpenRouter por padrão")
    module = reload_with_env(FAP_REVIEW_REASONING_MAX_TOKENS='')
    agent = module.FapPetitionReviewerAgent(openai_api_key='test-key',
                                            model='anthropic/claude-sonnet-5')
    extra_body = getattr(agent.llm, 'extra_body', None) or {}
    check("extra_body definido no ChatOpenAI", bool(extra_body),
          f"(obteve {extra_body!r})")

    reasoning = extra_body.get('reasoning') or {}
    budget = reasoning.get('max_tokens')
    check("reasoning.max_tokens presente", isinstance(budget, int),
          f"(obteve {budget!r})")

    if isinstance(budget, int):
        check("orçamento de raciocínio é positivo", budget > 0,
              f"(obteve {budget})")
        # O bug: raciocínio devorou ~57k dos 65.536 e sobraram ~8k para o JSON.
        # O limite tem de reservar folga ampla para a resposta textual.
        folga = MODEL_OUTPUT_CEILING - budget
        check("folga para o JSON com margem sobre o maior caso real",
              folga >= MIN_JSON_HEADROOM,
              f"(folga {folga}, precisa >= {MIN_JSON_HEADROOM})")


def test_reasoning_budget_is_configurable():
    print("[2] Limite configurável por env")
    module = reload_with_env(FAP_REVIEW_REASONING_MAX_TOKENS='4321')
    agent = module.FapPetitionReviewerAgent(openai_api_key='test-key',
                                            model='anthropic/claude-sonnet-5')
    reasoning = (getattr(agent.llm, 'extra_body', None) or {}).get('reasoning') or {}
    check("env sobrescreve o padrão", reasoning.get('max_tokens') == 4321,
          f"(obteve {reasoning.get('max_tokens')!r})")


def test_reasoning_budget_can_be_disabled():
    print("[3] Zero desliga o envio (modelos sem suporte a reasoning)")
    module = reload_with_env(FAP_REVIEW_REASONING_MAX_TOKENS='0')
    agent = module.FapPetitionReviewerAgent(openai_api_key='test-key',
                                            model='openai/gpt-mini-latest')
    extra_body = getattr(agent.llm, 'extra_body', None) or {}
    check("nenhum bloco reasoning enviado", 'reasoning' not in extra_body,
          f"(obteve {extra_body!r})")


if __name__ == '__main__':
    test_reasoning_budget_sent_by_default()
    test_reasoning_budget_is_configurable()
    test_reasoning_budget_can_be_disabled()
    reload_with_env()  # restaura o módulo com o ambiente original
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
