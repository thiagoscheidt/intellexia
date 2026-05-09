"""
Tools: Base de Conhecimento (RAG)
"""
from __future__ import annotations


def query_knowledge_base_handler(
    question: str,
    law_firm_id: int,
    search_mode: str = "semantic",
) -> dict:
    """Invoca KnowledgeQueryAgent.ask_with_llm e retorna resposta formatada."""
    from app.agents.knowledge_base.knowledge_query_agent import KnowledgeQueryAgent

    agent = KnowledgeQueryAgent()
    result = agent.ask_with_llm(
        question=question,
        law_firm_id=law_firm_id,
    )

    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "sources_detail": result.get("sources_detail", []),
        "suggested_questions": result.get("suggested_questions", []),
    }
