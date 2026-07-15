"""
Tools: Base de Conhecimento (RAG)
"""
from __future__ import annotations


def query_knowledge_base_handler(question: str, law_firm_id: int, user_id: int | None = None) -> dict:
    """Invoca KnowledgeQueryAgent.ask_with_llm e retorna resposta formatada.

    O modo de busca (semântico vs. full-text) é decidido automaticamente pelo
    agente de roteamento a partir da pergunta. O user_id alimenta o rastreio
    de tokens/custo por usuário.
    """
    from app.agents.knowledge_base.knowledge_query_agent import KnowledgeQueryAgent

    agent = KnowledgeQueryAgent()
    result = agent.ask_with_llm(
        question=question,
        user_id=user_id,
        law_firm_id=law_firm_id,
    )

    return {
        "resposta": result.get("answer", ""),
        "fontes": result.get("sources", []),
        "fontes_detalhe": result.get("sources_detail", []),
        "perguntas_sugeridas": result.get("suggested_questions", []),
    }
