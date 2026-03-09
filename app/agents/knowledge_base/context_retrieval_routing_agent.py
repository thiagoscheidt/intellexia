import os
from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model


class ContextRetrievalDecisionSchema(BaseModel):
    should_retrieve_context: bool = Field(
        description="True se deve consultar base vetorial antes de responder; False se pode responder sem consulta"
    )
    search_mode: str = Field(
        default="semantic",
        description="Tipo de busca a realizar: 'semantic' para busca por contexto/IA ou 'full_text' para busca por palavras-chave"
    )


class ContextRetrievalRoutingAgent:
    """Decide se deve buscar contexto e qual tipo de busca (semantic ou full_text) usar."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("KB_ROUTER_MODEL", "gpt-5-nano")
        self.llm = init_chat_model(self.model_name, temperature=0).with_structured_output(
            ContextRetrievalDecisionSchema
        )

    def decide_retrieval_and_mode(
        self, question: str, history: list[dict] | None = None
    ) -> ContextRetrievalDecisionSchema:
        """
        Decide se deve buscar contexto e qual modo de busca é mais apropriado.
        
        Args:
            question: Pergunta do usuário
            history: Histórico de conversa (opcional)
            
        Returns:
            ContextRetrievalDecisionSchema com should_retrieve_context e search_mode
        """
        history_preview = ""
        if history:
            limited_history = history[-6:] if len(history) > 6 else history
            history_preview = "\n".join(
                [f"{item.get('role', 'user')}: {item.get('content', '')}" for item in limited_history]
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "Você é um roteador inteligente de busca jurídica. Sua tarefa é decidir:\n"
                    "1. SE precisa buscar contexto na base de conhecimento (True/False)\n"
                    "2. QUAL tipo de busca é mais apropriado:\n"
                    "   - 'semantic': para buscas conceituais, jurisprudência, entendimentos legais, análises complexas\n"
                    "   - 'full_text': para buscas por palavras-chave específicas, número de processos, datas exatas, nomes\n\n"
                    "Retorne should_retrieve_context=True quando a pergunta depender de documentos internos, políticas, "
                    "normas, fatos processuais ou quando houver qualquer dúvida.\n"
                    "Retorne should_retrieve_context=False apenas para cumprimentos, conversa social ou perguntas genéricas.\n"
                    "Escolha 'semantic' para análises e 'full_text' para buscas diretas por termos específicos."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Pergunta atual: {question}\n\n"
                    f"Histórico recente (se houver):\n{history_preview or 'sem histórico'}"
                ),
            },
        ]

        try:
            return self.llm.invoke(messages)
        except Exception as e:
            print(f"Erro ao decidir retrieval e modo: {str(e)}")
            return ContextRetrievalDecisionSchema(should_retrieve_context=True, search_mode="semantic")
