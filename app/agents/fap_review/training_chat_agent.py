"""
Agente do treinamento interativo do Revisor FAP.

Conversa com o administrador sobre o manual e os casos de referência. A cada
resposta pode devolver zero ou mais edições ancoradas — o MESMO contrato
(``ReferenceEdit``) que a comparação de documentos produz, para que o mesmo
card de diff, a mesma conferência de âncora e a mesma gravação sirvam aos dois
modos. A conversa é outro *produtor* de edições; o *consumidor* é um só.

Recebe o manual e os casos inteiros a cada mensagem (~32k tokens), mais o
histórico da conversa. Só lê o que o usuário cola — não roda diff no chat: a
comparação de documentos já existe para isso.
"""

import json
import os
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from .training_apply_agent import ReferenceEdit


class ChatTurn(BaseModel):
    """Uma resposta da IA na conversa."""

    reply: str = Field(..., description="A resposta, em texto corrido, para o usuário")
    edits: list[ReferenceEdit] = Field(
        default_factory=list,
        description="Alterações propostas nesta resposta (pode ser vazio)",
    )


class FapTrainingChatAgent:
    """Conversa sobre o manual e propõe edições ancoradas."""

    _TASK = (
        "Você está numa CONVERSA com o administrador do escritório sobre o manual de "
        "revisão e os casos de referência. Ele pode:\n"
        "- pedir uma regra nova;\n"
        "- questionar ou corrigir uma regra que existe;\n"
        "- colar um trecho de petição e perguntar o que ele ensina;\n"
        "- só perguntar o que o manual diz sobre algo.\n\n"
        "Responda em português, direto, sem enrolação. Quando a conversa pedir uma "
        "mudança no manual ou nos casos, PROPONHA a alteração em `edits` — nunca diga "
        "que 'vai alterar': quem grava é a pessoa, depois de ver o diff. Quando for só "
        "consulta, responda e deixe `edits` vazio.\n\n"
        "Cada alteração em `edits` tem:\n"
        "  target — \"manual_fap\" ou \"casos_referencia\";\n"
        "  kind — \"substitution\" (a regra existe e está errada ou incompleta), "
        "\"refinement\" (está certa e só falta precisão) ou \"addition\" (não existe regra);\n"
        "  section — o nome da seção, como aparece no documento;\n"
        "  anchor — o trecho LITERAL do documento que a alteração toca: em substitution e "
        "refinement, o texto que SAI; em addition, o texto depois do qual inserir. Copie "
        "EXATAMENTE do documento, caractere por caractere — a alteração é RECUSADA se o "
        "trecho não for encontrado ou aparecer mais de uma vez. Vazio só para acrescentar "
        "ao fim do arquivo;\n"
        "  new_text — o texto final que entra, gravado como está; siga a estrutura, os "
        "títulos e o tom do documento;\n"
        "  rationale — por que, em uma frase;\n"
        "  evidence — de onde veio (o que o usuário disse, o trecho colado).\n\n"
        "Prefira MELHORAR um trecho existente a criar mais um. Não proponha regra que o "
        "documento já contém — se já contém, diga onde está.\n\n"
        "Retorne SOMENTE JSON com: reply (string) e edits (array)."
    )

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
    ):
        api_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        self.llm = ChatOpenAI(api_key=api_key, model=model, temperature=temperature)

    def respond(
        self,
        history: list[dict],
        user_message: str,
        manual_content: str = "",
        cases_content: str = "",
        reviewer_identity: str = "",
        reviewer_rules: str = "",
        training_identity: str = "",
        training_rules: str = "",
    ) -> ChatTurn:
        """Responde à mensagem, com o histórico e os documentos inteiros à vista.

        ``history`` é a lista de ``{'role': 'user'|'assistant', 'content': str}``
        das mensagens anteriores, na ordem.
        """
        system_prompt = self._build_system_prompt(
            manual_content, cases_content,
            reviewer_identity, reviewer_rules,
            training_identity, training_rules,
        )

        messages: list = [SystemMessage(content=system_prompt)]
        for turn in history or []:
            texto = str(turn.get('content') or '')
            if turn.get('role') == 'assistant':
                messages.append(AIMessage(content=texto))
            else:
                messages.append(HumanMessage(content=texto))
        messages.append(HumanMessage(content=user_message))

        # Erro de rede/contexto/credencial sobe para a rota devolver o motivo.
        response = self.llm.invoke(messages)

        parsed = self._parse_json(response.content)
        try:
            return ChatTurn(**parsed)
        except Exception:
            pass

        # O JSON veio, mas alguma proposta não validou: aproveita o `reply` e
        # as propostas que validarem uma a uma, em vez de perder o turno inteiro.
        if parsed.get('reply'):
            edits = []
            for raw in parsed.get('edits') or []:
                try:
                    edits.append(ReferenceEdit(**raw))
                except Exception:
                    continue
            return ChatTurn(reply=str(parsed['reply']), edits=edits)

        # Não veio JSON nenhum: devolve o texto como resposta, sem propostas.
        return ChatTurn(reply=str(response.content or '').strip()
                        or "Não consegui estruturar a resposta. Pode reformular?")

    def _build_system_prompt(
        self, manual_content, cases_content,
        reviewer_identity, reviewer_rules,
        training_identity, training_rules,
    ) -> str:
        partes = [
            "Você mantém a base de conhecimento que o Revisor de Petições FAP usa para "
            "revisar: o manual de revisão e os casos de referência.",
            "",
            "IDENTIDADE:",
            training_identity or "Consolidar o que o escritório ensina, sem inventar regra.",
            "",
            "REGRAS DE EVOLUÇÃO:",
            training_rules or "Só proponha o que a conversa sustenta.",
            "",
            self._TASK,
        ]

        if reviewer_identity or reviewer_rules:
            partes += [
                "",
                "=== QUEM VAI USAR O QUE VOCÊ ESCREVER ===",
                "O texto que você propõe será lido pelo agente revisor abaixo. Escreva na "
                "linguagem que ele entende e sem contrariar as regras dele.",
                "",
                "IDENTIDADE DO REVISOR:", reviewer_identity or "(não configurada)",
                "",
                "REGRAS INVIOLÁVEIS DO REVISOR:", reviewer_rules or "(não configuradas)",
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

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        if not content:
            return {}
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            return json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            return {}
