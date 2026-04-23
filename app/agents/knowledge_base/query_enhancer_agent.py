import os
import time

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from app.agents.config import DEFAULT_MODEL_MINI
from app.services.token_usage_service import TokenUsageService


class QueryEnhancerAgent:
    """Melhora perguntas para busca semântica na base vetorial."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("QUERY_ENHANCER_MODEL") or DEFAULT_MODEL_MINI
        self.llm = ChatOpenAI(model=self.model_name, temperature=0)
        self.token_usage_service = TokenUsageService()

    def enhance_question(self, question: str, history: list[dict] | None = None) -> str:
        cleaned_question = (question or "").strip()
        if not cleaned_question:
            return ""

        history = history or []
        limited_history = history[-10:] if len(history) > 10 else history
        history_lines: list[str] = []
        for item in limited_history:
            role = item.get("role", "")
            content = item.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(part) for part in content)
            content = str(content).strip()
            if role and content:
                history_lines.append(f"{role}: {content}")

        history_block = "\n".join(history_lines) if history_lines else "(sem histórico)"

        system_prompt = (
            "Você é um agente de reformulação de consultas para busca vetorial jurídica. "
            "Reescreva a pergunta para melhorar recall e precisão sem alterar a intenção original. "
            "Mantenha em português, seja objetivo e preserve nomes, números de processo, datas e termos legais relevantes. "
            "Retorne somente a pergunta reformulada, sem explicações."
        )

        user_prompt = (
            "Considere o histórico e reescreva APENAS a pergunta atual para consulta semântica em base jurídica.\n\n"
            f"Histórico recente:\n{history_block}\n\n"
            f"Pergunta atual:\n{cleaned_question}"
        )

        try:
            agent = create_agent(
                model=self.llm,
                system_prompt=system_prompt,
            )
            
            messages = [{"role": "user", "content": user_prompt}]
            
            call_started_at = time.time()
            response_payload = agent.invoke({"messages": messages})
            latency_ms = int((time.time() - call_started_at) * 1000)
            
            # Capturar e salvar uso de tokens
            self.token_usage_service.capture_and_store(
                response_payload,
                agent_name="QueryEnhancerAgent",
                action_name="enhance_question",
                print_prefix="[QueryEnhancerAgent][tokens]",
                model_name=self.model_name,
                model_provider="openai",
                user_id=None,
                law_firm_id=None,
                chat_session_id=None,
                latency_ms=latency_ms,
                status="success",
                metadata_payload={
                    "original_question": cleaned_question[:200],
                    "has_history": len(history_lines) > 0,
                },
            )
            
            # Extrair resposta das mensagens
            messages_result = response_payload.get("messages", [])
            if messages_result:
                last_message = messages_result[-1]
                if hasattr(last_message, "content"):
                    improved_question = (last_message.content or "").strip()
                elif isinstance(last_message, dict):
                    improved_question = (last_message.get("content", "") or "").strip()
                else:
                    improved_question = str(last_message).strip()
            else:
                improved_question = cleaned_question
            
            return improved_question or cleaned_question
        except Exception as e:
            print(f"Erro ao melhorar pergunta para busca: {str(e)}")
            return cleaned_question