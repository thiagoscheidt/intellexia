from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from types import SimpleNamespace
from rich import print

from dotenv import load_dotenv
from meilisearch_python_sdk import Client as MeilisearchClient
from openai import OpenAI
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from langchain_openai import ChatOpenAI
from app.models import db, KnowledgeChatHistory, KnowledgeChatSession


from app.agents.knowledge_base.query_enhancer_agent import QueryEnhancerAgent
from app.agents.knowledge_base.context_retrieval_routing_agent import (
    ContextRetrievalRoutingAgent,
)
from app.agents.knowledge_base.keyword_extraction_agent import KeywordExtractionAgent
from app.agents.knowledge_base.tools import KnowledgeQueryTools
from app.services.token_usage_service import TokenUsageService
from app.agents.config import DEFAULT_MODEL_MINI, DEFAULT_MODEL_NANO


load_dotenv()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", "0"))
DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowledge_base")
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
MEILISEARCH_HOST = os.getenv("MEILISEARCH_HOST", "http://localhost:7700")
MEILISEARCH_API_KEY = os.getenv("MEILISEARCH_API_KEY")
QUERY_MODEL = os.getenv("KB_QUERY_MODEL") or DEFAULT_MODEL_MINI
ROUTER_MODEL = os.getenv("KB_ROUTER_MODEL") or DEFAULT_MODEL_NANO
KB_AGENT_DEBUG = os.getenv("KB_AGENT_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}
KB_MAX_HISTORY_MESSAGES = int(os.getenv("KB_MAX_HISTORY_MESSAGES", "10"))
KB_MAX_HISTORY_CHARS = int(os.getenv("KB_MAX_HISTORY_CHARS", "12000"))
KB_MAX_CONTEXT_RESULTS = int(os.getenv("KB_MAX_CONTEXT_RESULTS", "10"))
KB_MAX_CONTEXT_CHARS_PER_SOURCE = int(os.getenv("KB_MAX_CONTEXT_CHARS_PER_SOURCE", "3000"))
KB_AGENT_RECURSION_LIMIT = int(os.getenv("KB_AGENT_RECURSION_LIMIT", "10"))


logger = logging.getLogger(__name__)


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
        self.meilisearch = MeilisearchClient(MEILISEARCH_HOST, MEILISEARCH_API_KEY)
        self.openai = OpenAI()
        self.query_enhancer = QueryEnhancerAgent()
        self.context_retrieval_routing = ContextRetrievalRoutingAgent()
        self.keyword_extraction = KeywordExtractionAgent()
        self._last_context_data = None
        self._last_context_text = ""
        self._context_search_calls = 0
        self._cached_should_use_context = None
        self.tools_registry = KnowledgeQueryTools()
        self.token_usage_service = TokenUsageService()
        self.router_llm = ChatOpenAI(model=ROUTER_MODEL, temperature=0).with_structured_output(RetrievalDecisionSchema)
        self.response_llm = ChatOpenAI(model=QUERY_MODEL, temperature=0)

    def _build_response_agent(self):
        return create_agent(
            model=self.response_llm,
            system_prompt=(
                "Você é um assistente jurídico especializado que responde perguntas com base na base de "
                "conhecimento da empresa. Use tools quando necessário para melhorar consistência de sugestões."
            ),
            tools=self.tools_registry.get_tools(),
            response_format=ToolStrategy(ResponseSchema),
        )

    def _build_fallback_response_llm(self):
        return self.response_llm.with_structured_output(ResponseSchema)

    def _debug_log(self, message: str, **metadata) -> None:
        print(message)
        if not KB_AGENT_DEBUG:
            return
        if metadata:
            logger.info("[KB_AGENT_DEBUG] %s | %s", message, json.dumps(metadata, ensure_ascii=False))
        else:
            logger.info("[KB_AGENT_DEBUG] %s", message)

    def _normalize_history(self, history: list[dict] | None) -> list[dict]:
        if not history:
            return []

        limited_history = history[-KB_MAX_HISTORY_MESSAGES:] if len(history) > KB_MAX_HISTORY_MESSAGES else history
        normalized: list[dict] = []
        total_chars = 0

        for item in limited_history:
            role = str(item.get("role", "user"))
            content = item.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(part) for part in content)
            content = str(content).strip()
            if not content:
                continue

            remaining = KB_MAX_HISTORY_CHARS - total_chars
            if remaining <= 0:
                break

            if len(content) > remaining:
                content = content[:remaining]

            normalized.append({"role": role, "content": content})
            total_chars += len(content)

        return normalized

    def create_embedding_vector(self, text: str):
        embedding_request = self.openai.embeddings.create(input=text, model=EMBEDDING_MODEL)
        return embedding_request.data[0].embedding

    def ask_knowledge_base(
        self,
        question: str,
        history=None,
        limit: int | None = None,
        search_mode: str = "semantic",
    ) -> dict:
        query_limit = limit if limit is not None else KB_MAX_CONTEXT_RESULTS
        normalized_mode = str(search_mode or "semantic").strip().lower()
        if normalized_mode in {"full-text", "literal"}:
            normalized_mode = "full_text"
        
        if normalized_mode == "semantic":
            improved_question = self.query_enhancer.enhance_question(question, history=history)
            print("pergunta original:", question)
            print("pergunta melhorada:", improved_question)
            vector = self.create_embedding_vector(improved_question)
            results = self.qdrant.query_points(collection_name=self.collection, query=vector, limit=query_limit)
            points = results.points
        elif normalized_mode == "full_text":
            improved_question = question
            print("pergunta original:", question)
            
            # Extrair termos-chave para melhorar a busca full_text
            keywords = self.keyword_extraction.extract_keywords(question)
            search_query = " ".join(keywords) if keywords else question
            
            print(f"termos-chave extraídos: {keywords}")
            print(f"query para busca: {search_query}")
            
            search_results = self.meilisearch.index(self.collection).search(
                search_query,
                limit=query_limit,
                show_ranking_score=True,
            )
            points = [
                SimpleNamespace(payload=hit, score=hit.get("_rankingScore"))
                for hit in (search_results.hits or [])
            ]
            results = SimpleNamespace(points=points)
        else:
            raise ValueError("search_mode inválido. Use 'semantic' ou 'full_text'.")

        context = "\n".join([(item.payload.get("text") or "") for item in points])
        return {
            "original_question": question,
            "improved_question": improved_question,
            "context": context,
            "results": results,
            "search_mode": normalized_mode,
        }

    def _resolve_should_use_context(self, question: str, history_preview: str = "") -> tuple[bool, str]:
        if self._cached_should_use_context is not None:
            self._debug_log("Decisão de contexto em cache", should_use_context=self._cached_should_use_context.get('should_retrieve'))
            return self._cached_should_use_context.get('should_retrieve', False), self._cached_should_use_context.get('search_mode', 'semantic')

        history = [{"role": "user", "content": history_preview}] if history_preview else None
        decision = self.context_retrieval_routing.decide_retrieval_and_mode(question, history=history)
        self._cached_should_use_context = {
            'should_retrieve': bool(decision.should_retrieve_context),
            'search_mode': decision.search_mode
        }
        self._debug_log(
            "Decisão de contexto calculada",
            should_use_context=self._cached_should_use_context['should_retrieve'],
            search_mode=self._cached_should_use_context['search_mode']
        )
        return self._cached_should_use_context['should_retrieve'], self._cached_should_use_context['search_mode']

    def _resolve_context_search(self, question: str, search_mode: str = "semantic", history_preview: str = "") -> str:
        self._context_search_calls += 1
        mode_label = "semântica" if search_mode == "semantic" else "full-text"
        self._debug_log("Busca de contexto iniciada", call_count=self._context_search_calls, search_mode=mode_label)

        if self._context_search_calls > 1:
            return "Contexto já foi buscado nesta rodada. Reutilize o contexto anterior para responder."

        if self._last_context_text:
            return self._last_context_text

        context_data = self.ask_knowledge_base(question, history=None, search_mode=search_mode)
        self._last_context_data = context_data

        points = context_data.get("results").points if context_data and context_data.get("results") else []
        if not points:
            msg = f"Nenhum contexto encontrado na busca {mode_label} para essa pergunta."
            self._last_context_text = msg
            return self._last_context_text

        context_with_sources = []
        for idx, item in enumerate(points):
            source = item.payload.get("source", "Fonte desconhecida")
            text = (item.payload.get("text", "") or "")[:KB_MAX_CONTEXT_CHARS_PER_SOURCE]
            page = item.payload.get("page")
            source_info = f"{source} (Página {page})" if page else source
            context_with_sources.append(f"[Fonte {idx}]: {source_info}\n{text}")

        self._last_context_text = "\n\n---\n\n".join(context_with_sources)
        return self._last_context_text

    def _generate_fallback_response(
        self,
        question: str,
        history=None,
        attachments_context: str = "",
        attachments_file_ids: list[str] | None = None,
        has_attachments: bool = False,
    ) -> ResponseSchema:
        normalized_history = self._normalize_history(history)
        context_text = ""
        search_mode = "semantic"

        if not has_attachments:
            should_use_context, search_mode = self._resolve_should_use_context(question)
            if should_use_context:
                context_text = self._resolve_context_search(question, search_mode=search_mode)

        fallback_messages = []
        if normalized_history:
            fallback_messages.extend(normalized_history)

        fallback_prompt = (
            "Você é um assistente jurídico especializado. "
            "Responda em português do Brasil, sem inventar fatos, e seja objetivo.\n\n"
            "Retorne estritamente no formato estruturado com os campos: answer, sources, suggested_questions.\n"
            "- Em sources, use apenas índices das fontes realmente usadas (ex: ['0','2']).\n"
            "- Se não houver base suficiente, responda com cautela e use sources vazia.\n"
            "- suggested_questions deve conter exatamente 3 perguntas/comandos curtos e prontos para envio.\n\n"
            f"Pergunta do usuário: {question}\n\n"
            f"Contexto disponível (busca {search_mode}):\n{context_text or 'sem contexto'}\n\n"
            f"Conteúdo de anexos enviados na conversa:\n{attachments_context or 'sem anexos'}"
        )
        fallback_messages.append({"role": "user", "content": fallback_prompt})

        fallback_llm = self._build_fallback_response_llm()
        return fallback_llm.invoke(fallback_messages)

    def ask_with_llm(
        self,
        question: str,
        user_id: int = None,
        law_firm_id: int = None,
        history=None,
        chat_session_id: int = None,
        attachments_context: str = "",
        attachments_file_ids: list[str] | None = None,
        has_attachments: bool = False,
    ) -> dict:
        """Consulta a base de conhecimento e usa LLM para gerar resposta."""
        self._last_context_data = None
        self._last_context_text = ""
        self._context_search_calls = 0
        self._cached_should_use_context = None
        sources_map = {}

        start_time = time.time()

        response_agent = self._build_response_agent()

        normalized_history = self._normalize_history(history)
        retrieval_decision = None
        should_use_context = False if has_attachments else None
        search_mode = "semantic"
        context_text = ""

        if has_attachments:
            should_use_context = False
            search_mode = "semantic"
            context_text = ""
        else:
            retrieval_decision = self.context_retrieval_routing.decide_retrieval_and_mode(question, history=normalized_history)
            should_use_context = bool(retrieval_decision.should_retrieve_context)
            search_mode = retrieval_decision.search_mode

        if should_use_context:
            context_text = self._resolve_context_search(question, search_mode=search_mode)
            if (not context_text or not str(context_text).strip()) and self._last_context_text:
                context_text = self._last_context_text

        if should_use_context:
            search_mode_label = "semântica" if search_mode == "semantic" else "full-text"
            context_block = context_text if str(context_text or "").strip() else f"contexto foi buscado ({search_mode_label}), mas retornou vazio"
        else:
            context_block = "sem contexto (roteador decidiu não consultar base)"

        self._debug_log(
            f"Pré-processamento de contexto concluído",
            should_use_context=should_use_context,
            search_mode=search_mode,
            context_search_calls=self._context_search_calls,
            context_chars=len(context_text or ""),
            context_preview=(context_block[:240] if context_block else ""),
        )

        instructions = (
            "IMPORTANTE: A decisão de uso de contexto, tipo de busca e a busca na base já foram executadas antes desta etapa. "
            "Use apenas o campo 'Contexto pré-buscado' fornecido abaixo quando ele existir. "
            "Quando houver anexos enviados na conversa, use também o campo 'Conteúdo de anexos'. "
            "No campo 'sources', liste APENAS os números das fontes que você realmente usou "
            "para responder (ex: ['0', '2']). Se não souber a resposta com base no contexto, informe "
            "claramente que não possui essa informação e retorne sources como lista vazia. "
            "Se a pergunta estiver incompleta, ambígua, ou sem dados suficientes no contexto, "
            "não invente resposta: peça mais detalhes ao usuário com perguntas curtas e objetivas. "
            "Sempre preencha 'suggested_questions' com exatamente 3 perguntas/comandos curtos, em português do Brasil, "
            "prontos para clique e envio direto para a IA, baseados na resposta anterior. "
            "Não use rótulos, prefixos ou metadados."
        )

        final_user_prompt = (
            f"{instructions}\n\n"
            f"Pergunta do usuário: {question}\n\n"
            f"Contexto pré-buscado (modo: {search_mode}):\n{context_block}\n\n"
            f"Conteúdo de anexos:\n{attachments_context or 'sem anexos'}"
        )

        messages = []
        if normalized_history:
            messages.extend(normalized_history)

        print("Final user prompt:", final_user_prompt)  # --- IGNORE ---
        messages.append({"role": "user", "content": final_user_prompt})

        self._debug_log(
            "Invocando create_agent",
            recursion_limit=KB_AGENT_RECURSION_LIMIT,
            history_messages=len(normalized_history),
            history_chars=sum(len(str(item.get("content", ""))) for item in normalized_history),
            question_chars=len(question or ""),
        )

        try:
            total_tokens = 0
            call_started_at = time.time()
            response_payload = response_agent.invoke(
                {"messages": messages},
                config={"recursion_limit": KB_AGENT_RECURSION_LIMIT},
            )
            latency_ms = int((time.time() - call_started_at) * 1000)
            total_tokens = self.token_usage_service.capture_and_store(
                response_payload,
                agent_name="KnowledgeQueryAgent",
                action_name="ask_with_llm.create_agent",
                print_prefix="[KnowledgeQueryAgent][tokens]",
                model_name=QUERY_MODEL,
                model_provider="openai",
                user_id=user_id,
                law_firm_id=law_firm_id,
                chat_session_id=chat_session_id,
                latency_ms=latency_ms,
                status="success",
                metadata_payload={
                    "search_mode": search_mode,
                    "has_attachments": has_attachments,
                },
            )
            structured_response = response_payload.get("structured_response")
            if not structured_response:
                raise RuntimeError("Resposta estruturada não retornada pelo create_agent")
            response = structured_response
        except Exception as exc:
            error_text = str(exc)
            if "Recursion limit" not in error_text and "GRAPH_RECURSION_LIMIT" not in error_text:
                raise

            self._debug_log(
                "Recursion limit atingido, ativando fallback determinístico",
                recursion_limit=KB_AGENT_RECURSION_LIMIT,
                error=error_text,
            )
            response = self._generate_fallback_response(
                question=question,
                history=history,
                attachments_context=attachments_context,
                attachments_file_ids=attachments_file_ids,
                has_attachments=has_attachments,
            )

        response_time_ms = int((time.time() - start_time) * 1000)

        used_sources = []
        sources_detail = []

        context_data = self._last_context_data
        if context_data:
            for idx, item in enumerate(context_data["results"].points):
                source = item.payload["source"]
                page = item.payload.get("page")
                source_info = f"{source} (Página {page})" if page else source
                sources_map[idx] = source_info

        if response.sources and context_data:
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
                    tokens_used=total_tokens,
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