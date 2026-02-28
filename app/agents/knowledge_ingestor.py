from __future__ import annotations

from pathlib import Path

from app.agents.knowledge_ingestion_agent import KnowledgeIngestionAgent
from app.agents.knowledge_query_agent import KnowledgeQueryAgent


class KnowledgeIngestor:
    """Wrapper de compatibilidade.

    Use preferencialmente:
    - KnowledgeIngestionAgent: upload/processamento/ingestão de arquivos
    - KnowledgeQueryAgent: perguntas e respostas com LLM
    """

    def __init__(self, collection_name: str | None = None):
        if collection_name is None:
            self.ingestion_agent = KnowledgeIngestionAgent()
            self.query_agent = KnowledgeQueryAgent()
        else:
            self.ingestion_agent = KnowledgeIngestionAgent(collection_name=collection_name)
            self.query_agent = KnowledgeQueryAgent(collection_name=collection_name)

    def ingest_document(self, *args, **kwargs):
        return self.ingestion_agent.ingest_document(*args, **kwargs)

    def process_file(self, file_path: Path, *args, **kwargs):
        return self.ingestion_agent.process_file(file_path, *args, **kwargs)

    def create_embedding_vector(self, text: str):
        return self.query_agent.create_embedding_vector(text)

    def ask_knowledge_base(self, question: str, history=None) -> dict:
        return self.query_agent.ask_knowledge_base(question, history=history)

    def ask_with_llm(self, question: str, user_id: int = None, law_firm_id: int = None, history=None) -> dict:
        return self.query_agent.ask_with_llm(
            question=question,
            user_id=user_id,
            law_firm_id=law_firm_id,
            history=history,
        )
