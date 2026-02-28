from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from langchain_openai import ChatOpenAI
from app.models import db, KnowledgeChatHistory, KnowledgeChatSession


from app.agents.query_enhancer_agent import QueryEnhancerAgent


load_dotenv()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", "0"))
DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowledge_base")
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QUERY_MODEL = os.getenv("KB_QUERY_MODEL", "gpt-4o-mini")
ROUTER_MODEL = os.getenv("KB_ROUTER_MODEL", "gpt-5-nano")


class ResponseSchema(BaseModel):
    answer: str = Field(description="Resposta gerada para a pergunta")
    sources: list[str] = Field(description="Índices das fontes utilizadas (ex: ['0', '2'])")
    suggested_questions: list[str] = Field(
        default_factory=list,
        description=(
            "Exatamente 3 perguntas/comandos prontos para o usuário enviar à IA como próximo passo, "
            "baseados na resposta anterior e sem rótulos como 'Próxima ação' ou 'Próxima pergunta'."
        ),
    )


class RetrievalDecisionSchema(BaseModel):
    should_retrieve_context: bool = Field(
        description="True se deve consultar base vetorial antes de responder; False se pode responder sem consulta"
    )


class KnowledgeQueryAgent:
    """Consulta a base vetorial e responde perguntas com LLM."""

    def __init__(self, collection_name: str = DEFAULT_COLLECTION):
        if not EMBEDDING_MODEL:
            raise RuntimeError("EMBEDDING_MODEL não definido no .env")
        if VECTOR_SIZE <= 0:
            raise RuntimeError("VECTOR_SIZE inválido ou não definido no .env")

        self.collection = collection_name
        self.qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60)
        self.openai = OpenAI()
        self.query_enhancer = QueryEnhancerAgent()

    def create_embedding_vector(self, text: str):
        embedding_request = self.openai.embeddings.create(input=text, model=EMBEDDING_MODEL)
        return embedding_request.data[0].embedding

    def ask_knowledge_base(self, question: str, history=None) -> dict:
        improved_question = self.query_enhancer.enhance_question(question, history=history)
        print("pergunta original:", question)
        print("pergunta melhorada:", improved_question)
        vector = self.create_embedding_vector(improved_question)

        results = self.qdrant.query_points(collection_name=self.collection, query=vector, limit=10)

        context = "\n".join([item.payload["text"] for item in results.points])
        return {
            "original_question": question,
            "improved_question": improved_question,
            "context": context,
            "results": results,
        }

    def _should_retrieve_context(self, question: str, history=None) -> RetrievalDecisionSchema:
        """Decide se a pergunta precisa buscar contexto na base vetorial antes de responder."""
        router_llm = ChatOpenAI(model=ROUTER_MODEL, temperature=0).with_structured_output(RetrievalDecisionSchema)

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
                    "Você é um roteador de RAG jurídico. Sua única tarefa é decidir se precisa consultar a base vetorial "
                    "antes da resposta final.\n"
                    "Retorne should_retrieve_context=True quando a pergunta depender de documentos internos, políticas, "
                    "normas específicas do escritório, fatos processuais, números, datas, ou quando houver qualquer dúvida.\n"
                    "Retorne should_retrieve_context=False quando a pergunta estiver incompleta, ambígua, "
                    "ou quando forem necessárias mais informações do usuário antes de responder.\n"
                    "Retorne should_retrieve_context=False para cumprimentos, conversa social, ou perguntas genéricas "
                    "que podem ser respondidas sem a base interna."
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
            return router_llm.invoke(messages)
        except Exception:
            return RetrievalDecisionSchema(should_retrieve_context=True)

    def ask_with_llm(
        self,
        question: str,
        user_id: int = None,
        law_firm_id: int = None,
        history=None,
        chat_session_id: int = None,
    ) -> dict:
        """Consulta a base de conhecimento e usa LLM para gerar resposta."""
        decision = self._should_retrieve_context(question, history=history)
        should_retrieve = bool(decision.should_retrieve_context)
        print("deve buscar contexto:", should_retrieve)

        context_data = None
        if should_retrieve:
            context_data = self.ask_knowledge_base(question, history=history)

        context_with_sources = []
        sources_map = {}

        if context_data:
            for idx, item in enumerate(context_data["results"].points):
                source = item.payload["source"]
                text = item.payload["text"]
                page = item.payload.get("page")

                source_info = f"{source} (Página {page})" if page else source
                sources_map[idx] = source_info

                context_with_sources.append(f"[Fonte {idx}]: {source_info}\n{text}")

    
        formatted_context = "\n\n---\n\n".join(context_with_sources) if context_with_sources else ""

        start_time = time.time()

        llm = ChatOpenAI(model=QUERY_MODEL, temperature=0).with_structured_output(ResponseSchema)

        system_message = {
            "role": "system",
            "content": "Você é um assistente jurídico especializado que responde perguntas com base na base de conhecimento da empresa.",
        }

        context_message = {
            "role": "system",
            "content": (
                f"Contexto disponível:\n\n{formatted_context}\n\n"
                "IMPORTANTE: No campo 'sources', liste APENAS os números das fontes que você realmente usou "
                "para responder (ex: ['0', '2']). Se não souber a resposta com base no contexto, informe "
                "claramente que não possui essa informação e retorne sources como lista vazia. "
                "Se a pergunta estiver incompleta, ambígua, ou sem dados suficientes no contexto, "
                "não invente resposta: peça mais detalhes ao usuário com perguntas curtas e objetivas. "
                "Além disso, sempre preencha 'suggested_questions' com exatamente 3 perguntas de continuação, "
                "curtas, específicas ao contexto e em português do Brasil. "
                "Cada sugestão deve ser uma pergunta/comando pronto para clique e envio direto para a IA "
                "(ex.: 'Faça um resumo do processo...'). Não use rótulos, prefixos ou metadados."
            ),
        }

        no_context_message = {
            "role": "system",
            "content": (
                "Você vai responder sem consultar a base vetorial nesta rodada. "
                "No campo 'sources', retorne sempre lista vazia. "
                "Se a pergunta estiver incompleta, ambígua ou faltar informação, peça mais detalhes "
                "ao usuário com perguntas curtas e objetivas antes de responder. "
                "Além disso, sempre preencha 'suggested_questions' com exatamente 3 perguntas de continuação, "
                "curtas, úteis e em português do Brasil. "
                "Cada sugestão deve ser uma pergunta/comando pronto para clique e envio direto para a IA. "
                "Não use rótulos, prefixos ou metadados."
            ),
        }

        if history is None or len(history) == 0:
            messages = [
                system_message,
                context_message if should_retrieve else no_context_message,
                {"role": "user", "content": question},
            ]
        else:
            limited_history = history[-10:] if len(history) > 10 else history
            messages = [system_message] + limited_history + [
                context_message if should_retrieve else no_context_message,
                {"role": "user", "content": question},
            ]

        response = llm.invoke(messages)

        response_time_ms = int((time.time() - start_time) * 1000)

        used_sources = []
        sources_detail = []

        if should_retrieve and response.sources and context_data:
            for source_ref in response.sources:
                try:
                    numbers = re.findall(r"\d+", str(source_ref))
                    if numbers:
                        idx = int(numbers[0])
                        if idx in sources_map:
                            source_info = sources_map[idx]
                            if source_info not in used_sources:
                                used_sources.append(source_info)

                            original_item = context_data["results"].points[idx]
                            source_name = original_item.payload["source"]
                            source_page = original_item.payload.get("page")
                            source_file_id = original_item.payload.get("file_id")

                            sources_detail.append(
                                {
                                    "source": source_name,
                                    "page": source_page,
                                    "file_id": source_file_id,
                                    "display": source_info,
                                }
                            )
                except (ValueError, IndexError):
                    continue

        suggested_questions = []
        for item in (response.suggested_questions or []):
            if not isinstance(item, str):
                continue
            clean = " ".join(item.split()).strip()
            if not clean:
                continue

            clean = re.sub(r"^(próxima\s+pergunta:|proxima\s+pergunta:|próxima\s+ação:|proxima\s+acao:)", "", clean, flags=re.IGNORECASE).strip()

            if clean not in suggested_questions:
                suggested_questions.append(clean)
            if len(suggested_questions) >= 3:
                break

        if len(suggested_questions) < 3:
            fallback_questions = [
                "Faça um resumo objetivo do caso com os principais pontos e status atual.",
                "Liste os próximos passos práticos recomendados para este caso.",
                "Quais documentos ou informações faltam para avançar com segurança?",
            ]
            for fallback in fallback_questions:
                if fallback not in suggested_questions:
                    suggested_questions.append(fallback)
                if len(suggested_questions) >= 3:
                    break

        result = {
            "answer": response.answer,
            "sources": used_sources,
            "sources_detail": sources_detail,
            "suggested_questions": suggested_questions,
            "search_query": context_data.get("improved_question", question) if context_data else question,
            "response_time_ms": response_time_ms,
        }

        if user_id and law_firm_id:
            try:
                history_entry = KnowledgeChatHistory(
                    user_id=user_id,
                    law_firm_id=law_firm_id,
                    chat_session_id=chat_session_id,
                    question=question,
                    answer=response.answer,
                    sources=json.dumps(used_sources, ensure_ascii=False),
                    response_time_ms=response_time_ms,
                )

                db.session.add(history_entry)

                if chat_session_id:
                    chat_session = KnowledgeChatSession.query.filter_by(
                        id=chat_session_id,
                        user_id=user_id,
                        law_firm_id=law_firm_id,
                        is_active=True,
                    ).first()
                    if chat_session:
                        chat_session.updated_at = datetime.utcnow()

                db.session.commit()

                result["history_id"] = history_entry.id
                print(f"Histórico salvo com ID: {history_entry.id}")
            except Exception as e:
                print(f"Erro ao salvar histórico no banco: {str(e)}")
                db.session.rollback()

        return result