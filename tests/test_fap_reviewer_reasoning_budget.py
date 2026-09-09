"""Teste da defesa contra resposta cortada no limite de saída do modelo.

CONTEXTO — o que a medição mostrou, e por que a defesa anterior não servia.

A revisão FAP morria com "A resposta do modelo não contém JSON válido para a
revisão." quando o raciocínio interno do modelo consumia o orçamento de saída e
o JSON chegava cortado no meio. A correção de 04/08/2026 tentou conter isso
enviando `reasoning.max_tokens`. Medido em 09/09/2026 contra o
`anthropic/claude-sonnet-5` no OpenRouter, com prompt que força raciocínio longo:

    orçamento pedido       raciocínio gasto
    1.024 (sem max_tokens)          2.699
    1.024 (com max_tokens)          3.813
    nenhum controle                 2.785

O parâmetro é aceito e **ignorado** — mandar `max_tokens` junto não muda nada.
O que o provedor honra é ligar ou desligar:

    reasoning.effort = low          0
    reasoning.enabled = false       0

Ou seja: raciocínio ligado (quantidade incontrolável) ou desligado. Não existe
meio-termo, e portanto não existe orçamento a calibrar.

Em produção o custo disso apareceu assim (`agent_token_usage`): até 11/08 o
raciocínio ficava entre 8.216 e 13.467 tokens; de 14/08 em diante passou a
35.267–65.536, sem nenhuma mudança nossa e com o mesmo modelo nas 47 execuções.
As falhas começaram em 30/08 (três seguidas, com o raciocínio consumindo os
65.536 tokens inteiros e sobrando ZERO para o texto) e seguiram em 08/09 e 09/09.

A defesa, então, não é prever o tamanho do raciocínio — é detectar o corte
(`finish_reason == 'length'`) e refazer a chamada sem raciocínio estendido,
onde o orçamento inteiro fica disponível para o JSON.

Verifica:
1. Resposta cortada é reconhecida pelo `finish_reason`.
2. Truncamento dispara UMA nova tentativa, com o raciocínio desligado.
3. Resposta normal não gera chamada extra.
4. Segunda tentativa também cortada não vira terceira, e o erro diz a verdade.
5. O construtor não envia mais o orçamento em tokens, que a medição reprovou.

Uso: uv run python tests/test_fap_reviewer_reasoning_budget.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')
os.environ.setdefault('OPENAI_BASE_URL', 'https://openrouter.ai/api/v1')

import app.agents.fap_review.reviewer_agent as reviewer_module  # noqa: E402

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


class RespostaFalsa:
    """Imita o AIMessage do LangChain no que o agente lê dele."""

    def __init__(self, content: str, finish_reason: str):
        self.content = content
        self.response_metadata = {'finish_reason': finish_reason}
        self.additional_kwargs: dict = {}
        self.usage_metadata: dict = {}


class LlmFalso:
    """Registra as invocações e devolve as respostas na ordem programada."""

    def __init__(self, respostas: list, extra_body: dict | None = None):
        self.respostas = list(respostas)
        self.extra_body = extra_body or {}
        self.invocacoes = 0

    def invoke(self, messages):
        self.invocacoes += 1
        return self.respostas.pop(0)


def novo_agente():
    return reviewer_module.FapPetitionReviewerAgent(
        openai_api_key='test-key', model='anthropic/claude-sonnet-5')


def test_deteccao_do_corte():
    print("[1] Resposta cortada é reconhecida pelo finish_reason")
    agente = novo_agente()
    cortada = RespostaFalsa('{"findings": [{"desc', 'length')
    inteira = RespostaFalsa('{"findings": []}', 'stop')

    check("finish_reason=length é truncamento",
          agente._resposta_truncada(cortada) is True)
    check("finish_reason=stop não é truncamento",
          agente._resposta_truncada(inteira) is False)
    check("resposta sem metadata não é truncamento",
          agente._resposta_truncada(RespostaFalsa('{}', '')) is False)


def test_retentativa_sem_raciocinio():
    print("[2] Truncamento dispara UMA nova tentativa, sem raciocínio")
    agente = novo_agente()
    cortada = RespostaFalsa('{"findings": [{"desc', 'length')
    inteira = RespostaFalsa('{"findings": []}', 'stop')

    agente.llm = LlmFalso([cortada])
    segundo = LlmFalso([inteira])
    agente._llm_sem_raciocinio = lambda: segundo

    final, descartada = agente._invocar_com_retomada([])

    check("a resposta usada é a da segunda tentativa", final is inteira)
    check("a tentativa cortada volta para registro de tokens",
          descartada is cortada)
    check("o primeiro modelo foi chamado uma vez", agente.llm.invocacoes == 1,
          f"(obteve {agente.llm.invocacoes})")
    check("o segundo modelo foi chamado uma vez", segundo.invocacoes == 1,
          f"(obteve {segundo.invocacoes})")


def test_llm_de_retomada_desliga_o_raciocinio():
    print("[3] O modelo da retomada desliga o raciocínio")
    agente = novo_agente()
    reserva = agente._llm_sem_raciocinio()
    extra_body = getattr(reserva, 'extra_body', None) or {}
    raciocinio = extra_body.get('reasoning') or {}

    check("envia reasoning.enabled = False", raciocinio.get('enabled') is False,
          f"(obteve {extra_body!r})")
    check("não envia orçamento em tokens, medido como ignorado",
          'max_tokens' not in raciocinio, f"(obteve {raciocinio!r})")
    check("mantém o mesmo modelo da revisão",
          getattr(reserva, 'model_name', None) == agente.model_name)


def test_resposta_normal_nao_gera_chamada_extra():
    print("[4] Resposta normal não paga o custo de uma segunda chamada")
    agente = novo_agente()
    inteira = RespostaFalsa('{"findings": []}', 'stop')
    agente.llm = LlmFalso([inteira])
    chamou_reserva = False

    def reserva():
        nonlocal chamou_reserva
        chamou_reserva = True
        return LlmFalso([inteira])

    agente._llm_sem_raciocinio = reserva
    final, descartada = agente._invocar_com_retomada([])

    check("devolve a resposta original", final is inteira)
    check("nada a descartar", descartada is None)
    check("o modelo de reserva nem é construído", chamou_reserva is False)
    check("uma única invocação", agente.llm.invocacoes == 1)


def test_segunda_tentativa_cortada_nao_vira_terceira():
    print("[5] Segunda tentativa cortada para por aí, com erro honesto")
    agente = novo_agente()
    cortada_1 = RespostaFalsa('{"findings": [{"desc', 'length')
    cortada_2 = RespostaFalsa('{"findings": [{"outra', 'length')

    agente.llm = LlmFalso([cortada_1])
    segundo = LlmFalso([cortada_2])
    agente._llm_sem_raciocinio = lambda: segundo

    final, _ = agente._invocar_com_retomada([])
    check("devolve a segunda tentativa", final is cortada_2)
    check("não houve terceira chamada", segundo.invocacoes == 1)

    # O erro precisa nomear o corte, não culpar o formato da resposta: é a
    # diferença entre o advogado saber que a petição é grande demais e achar
    # que o agente está quebrado.
    try:
        agente._ensure_output_parsed({}, parsed_items=0, list_keys=('findings',),
                                     parse_errors=[], truncada=True)
        check("levanta erro de parse", False, "(não levantou)")
    except reviewer_module.ReviewOutputParseError as erro:
        texto = str(erro).lower()
        check("a mensagem fala em corte no limite de saída",
              'cortada' in texto or 'limite' in texto, f"(obteve {erro})")
        check("a mensagem não atribui o problema ao formato do JSON",
              'não contém json válido' not in texto, f"(obteve {erro})")


def test_construtor_nao_envia_orcamento_reprovado():
    print("[6] O construtor não envia mais o orçamento em tokens")
    agente = novo_agente()
    extra_body = getattr(agente.llm, 'extra_body', None) or {}
    raciocinio = extra_body.get('reasoning') or {}

    check("sem reasoning.max_tokens na chamada normal",
          'max_tokens' not in raciocinio, f"(obteve {extra_body!r})")


if __name__ == '__main__':
    test_deteccao_do_corte()
    test_retentativa_sem_raciocinio()
    test_llm_de_retomada_desliga_o_raciocinio()
    test_resposta_normal_nao_gera_chamada_extra()
    test_segunda_tentativa_cortada_nao_vira_terceira()
    test_construtor_nao_envia_orcamento_reprovado()
    print(f"\nResultado: {PASSED} ok, {FAILED} falhas")
    sys.exit(1 if FAILED else 0)
