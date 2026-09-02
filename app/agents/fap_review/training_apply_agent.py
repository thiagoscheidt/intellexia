"""
Agente que propõe o que a revisão ensina ao manual e aos casos de referência.

Última etapa do treinamento. Recebe os PADRÕES já agrupados (não os documentos)
e, com espaço de contexto sobrando, recebe também o manual e os casos de
referência inteiros — é isso que separa uma regra útil de "confira os dados
numéricos".

Por que os documentos não chegam aqui: os dois somam ~82,6k tokens. Com o
manual (65k caracteres) e os casos (60k) juntos daria ~114k tokens numa
chamada só, que não cabe num modelo de 128k e dilui a atenção em qualquer
modelo. Com o diff determinístico à frente, esta etapa recebe ~39k tokens e
sobra espaço para o agente saber o que o manual JÁ diz — sem isso ele propunha
regra que já existia, ou genérica demais para valer alguma coisa.

O texto que este agente devolve em ``manual_patch_markdown`` e
``case_reference_markdown`` é o que a tela mostra e o que é gravado após a
confirmação humana — sem nova chamada de IA no meio.
"""

import json
import os
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, field_validator


class ReferenceEdit(BaseModel):
    """Uma alteração proposta, ancorada num trecho real do documento.

    ``anchor`` é o texto LITERAL do manual (ou dos casos) que a edição altera —
    em ``addition``, o texto depois do qual inserir. O código confere que ele
    existe e é único antes de oferecer a edição: um modelo que escreve o trecho
    de memória produz uma aproximação, e aplicá-la corromperia o documento em
    silêncio.
    """

    target: str = Field(..., description="manual_fap ou casos_referencia")
    kind: str = Field(..., description="addition | substitution | refinement")
    section: str = Field(default="", description="Seção do documento, como ela se chama lá")
    anchor: str = Field(
        default="",
        description="Trecho LITERAL do documento a alterar (ou depois do qual inserir); "
                    "vazio só para acrescentar ao fim",
    )
    new_text: str = Field(..., description="O texto final que entra, gravado como está")
    rationale: str = Field(default="", description="Por que esta alteração, em uma frase")
    evidence: list[str] = Field(
        default_factory=list,
        description="Rótulos dos padrões da revisão que sustentam esta alteração",
    )

    @field_validator('evidence', mode='before')
    @classmethod
    def _evidence_as_list(cls, value):
        """O modelo devolve `evidence` ora como lista, ora como string solta.

        Uma string recusada pelo validador derrubava a proposta INTEIRA — na
        conversa, o turno degradava para o JSON cru com zero propostas, mesmo
        com âncora literal e texto certos. Aceitar os dois formatos custa nada.
        """
        if value is None:
            return []
        if isinstance(value, str):
            value = value.strip()
            return [value] if value else []
        return list(value)


class ComparisonExtract(BaseModel):
    """A proposta apresentada ao usuário antes de gravar."""

    comparison_summary: str = Field(..., description="O que esta revisão ensina")
    training_ready: bool = Field(default=True, description="Se há o que aprender desta revisão")
    recommendation: str = Field(default="", description="Recomendação final ao usuário")
    edits: list[ReferenceEdit] = Field(
        default_factory=list,
        description="As alterações propostas, uma por trecho",
    )


class FapTrainingApplySubAgent:
    """Propõe as adições ao manual e aos casos, sabendo o que eles já dizem."""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
    ):
        api_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        self.llm = ChatOpenAI(api_key=api_key, model=model, temperature=temperature)

    async def propose_updates(
        self,
        grouping: dict,
        manual_content: str = "",
        cases_content: str = "",
        reviewer_identity: str = "",
        reviewer_rules: str = "",
        training_identity: str = "",
        training_rules: str = "",
        training_prompt: str = "",
    ) -> ComparisonExtract:
        """Propõe o que acrescentar ao manual e aos casos, a partir dos padrões."""

        system_prompt = self._build_system_prompt(
            manual_content=manual_content,
            cases_content=cases_content,
            reviewer_identity=reviewer_identity,
            reviewer_rules=reviewer_rules,
            training_identity=training_identity,
            training_rules=training_rules,
        )

        user_prompt = self._build_user_prompt(grouping, training_prompt)

        # Erro de contexto, credencial ou rede sobe para quem chamou; engolir
        # devolveria uma proposta de aparência normal com o motivo perdido.
        response = self.llm.invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )

        parsed = self._parse_json(response.content)
        try:
            return ComparisonExtract(**parsed)
        except Exception:
            return ComparisonExtract(
                comparison_summary="O modelo respondeu fora do formato esperado.",
                training_ready=False,
                recommendation=(
                    "Leia as diferenças e escreva a regra manualmente, ou tente de novo — "
                    "trocar o modelo do treinamento nas Configurações costuma resolver."
                ),
            )

    def _build_system_prompt(
        self,
        manual_content: str,
        cases_content: str,
        reviewer_identity: str,
        reviewer_rules: str,
        training_identity: str,
        training_rules: str,
    ) -> str:
        """Monta o contexto: quem é o agente, e o que manual e casos já dizem.

        O manual e os casos vão INTEIROS. É a diferença entre propor uma regra
        que se encaixa no que já existe e propor a regra genérica que qualquer
        um escreveria sem ler nada.
        """
        partes = [
            "Você mantém a base de conhecimento que o Revisor de Petições FAP usa "
            "para revisar. A cada revisão real feita por um advogado sênior, você "
            "decide o que dela deve virar regra permanente.",
            "",
            "IDENTIDADE:",
            training_identity or "Consolidar o que as revisões ensinam, sem inventar regra.",
            "",
            "REGRAS DE EVOLUÇÃO:",
            training_rules or "Só proponha regra sustentada pelas diferenças observadas.",
        ]

        if reviewer_identity or reviewer_rules:
            partes += [
                "",
                "=== QUEM VAI USAR O QUE VOCÊ ESCREVER ===",
                "O texto que você propõe será lido pelo agente revisor abaixo. "
                "Escreva na linguagem que ele entende e sem contrariar as regras dele.",
                "",
                "IDENTIDADE DO REVISOR:",
                reviewer_identity or "(não configurada)",
                "",
                "REGRAS INVIOLÁVEIS DO REVISOR:",
                reviewer_rules or "(não configuradas)",
            ]

        partes += [
            "",
            "=== MANUAL DE REVISÃO ATUAL (íntegra) ===",
            manual_content or "(o manual ainda está vazio)",
            "",
            "=== CASOS DE REFERÊNCIA ATUAIS (íntegra) ===",
            cases_content or "(ainda não há casos de referência)",
        ]

        return "\n".join(partes)

    def _build_user_prompt(self, grouping: dict, training_prompt: str) -> str:
        """A tarefa: transformar os padrões observados em alterações ancoradas."""
        grouping = grouping or {}

        instrucao = training_prompt or (
            "Proponha apenas o que a revisão sustenta, e nada além dela."
        )

        return (
            "Abaixo estão os PADRÕES de correção de uma revisão real, extraídos das "
            "diferenças literais entre a versão do advogado e a versão do revisor.\n\n"
            f"INSTRUÇÃO DO ESCRITÓRIO:\n{instrucao}\n\n"
            "Decida o que dessa revisão merece virar conhecimento permanente e retorne "
            "SOMENTE JSON com:\n"
            "comparison_summary (string — o que esta revisão ensina),\n"
            "training_ready (boolean — false se não há nada que valha gravar),\n"
            "recommendation (string),\n"
            "edits (array de alterações).\n\n"
            "Cada alteração em `edits` tem:\n"
            "  target — \"manual_fap\" ou \"casos_referencia\";\n"
            "  kind — \"substitution\" quando a regra existe e está errada ou incompleta; "
            "\"refinement\" quando está certa e só falta precisão; \"addition\" quando não "
            "existe regra sobre o assunto;\n"
            "  section — o nome da seção, como ele aparece no documento;\n"
            "  anchor — o trecho LITERAL do documento que a alteração toca. Em "
            "substitution e refinement é o texto que SAI; em addition é o texto depois do "
            "qual inserir. Copie-o EXATAMENTE do documento que você recebeu, caractere por "
            "caractere — ele é procurado no texto e a alteração é RECUSADA se não for "
            "encontrado ou se aparecer mais de uma vez. Só deixe vazio para acrescentar ao "
            "fim do arquivo;\n"
            "  new_text — o texto final que entra no lugar. É gravado COMO ESTÁ depois que "
            "uma pessoa confirmar: escreva o texto, não instruções sobre o texto, e siga a "
            "estrutura, os títulos e o tom do documento que você recebeu;\n"
            "  rationale — por que esta alteração, em uma frase;\n"
            "  evidence — os rótulos dos padrões que a sustentam.\n\n"
            "Prefira MELHORAR um trecho existente a criar mais um: cinco regras sobre "
            "regência espalhadas ensinam menos que uma regra completa. Se todos os padrões "
            "já estiverem cobertos pelo documento, devolva `edits` vazio e diga isso na "
            "recommendation — lista vazia é resposta legítima, e gravar repetição piora as "
            "revisões seguintes.\n\n"
            "PADRÕES DESTA REVISÃO:\n"
            "Em cada padrão, `occurrences` e `examples` foram apurados no código a partir "
            "das diferenças reais — são exatos, não estimativas. `relevant_for_manual` é "
            "falso para o que apareceu uma ou duas vezes e não toca dado factual.\n\n"
            f"{json.dumps(grouping, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        """Extrai o primeiro objeto JSON válido do texto."""
        if not content:
            return {}

        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}

        try:
            return json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            return {}
