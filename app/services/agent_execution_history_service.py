"""
Service para persistência de histórico completo de execuções de agentes.
"""

import logging
from typing import Any

from app.models import AgentExecutionHistory, db

logger = logging.getLogger(__name__)


class AgentExecutionHistoryService:
    """Serviço para armazenar e recuperar histórico completo de execução de agentes."""

    @staticmethod
    def _serialize_message(msg: Any) -> dict[str, Any]:
        """Serializa uma mensagem LangChain para dict JSON-compatível."""
        if hasattr(msg, "model_dump"):
            return msg.model_dump()
        if hasattr(msg, "dict"):
            return msg.dict()
        if hasattr(msg, "content") and hasattr(msg, "type"):
            return {
                "type": str(msg.type),
                "content": str(msg.content),
            }
        if isinstance(msg, dict):
            return msg
        return {"content": str(msg)}

    @staticmethod
    def save_execution_history(
        agent_name: str,
        action_name: str,
        agent_type: str,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        model_response: str | None = None,
        full_messages_history: list[Any] | None = None,
        result_data: dict[str, Any] | None = None,
        *,
        model_name: str | None = None,
        model_provider: str | None = None,
        status: str = "success",
        error_message: str | None = None,
        user_id: int | None = None,
        law_firm_id: int | None = None,
        chat_session_id: int | None = None,
        agent_token_usage_id: int | None = None,
    ) -> AgentExecutionHistory | None:
        """
        Persiste histórico completo de execução de agente.

        Args:
            agent_name: Nome do agente (ex: 'FAPContestationClassifierAgent')
            action_name: Nome da ação (ex: 'classify')
            agent_type: Tipo de agente (ex: 'fap_classifier', 'knowledge_query')
            system_prompt: System prompt usado
            user_prompt: User prompt enviado ao agente
            model_response: Resposta bruta do modelo
            full_messages_history: Lista completa de mensagens da conversa
            result_data: Dados estruturados do resultado (ex: topics, confidence)
            model_name: Nome do modelo usado
            model_provider: Provider do modelo (ex: 'openai')
            status: Status da execução ('success' ou 'error')
            error_message: Mensagem de erro se houver
            user_id: ID do usuário
            law_firm_id: ID do escritório
            chat_session_id: ID da sessão de chat (se aplicável)
            agent_token_usage_id: ID do registro de token usage relacionado

        Returns:
            AgentExecutionHistory criado ou None se falhar
        """
        try:
            # Serializar mensagens LangChain para JSON-compatível
            serialized_messages = None
            if full_messages_history:
                try:
                    serialized_messages = [
                        AgentExecutionHistoryService._serialize_message(msg)
                        for msg in full_messages_history
                    ]
                except Exception as e:
                    logger.warning("Erro ao serializar mensagens: %s. Usando None.", e)
                    serialized_messages = None

            execution_history = AgentExecutionHistory(
                agent_name=agent_name,
                action_name=action_name,
                agent_type=agent_type,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_response=model_response,
                full_messages_history=serialized_messages,
                result_data=result_data,
                model_name=model_name,
                model_provider=model_provider,
                status=status,
                error_message=error_message,
                user_id=user_id,
                law_firm_id=law_firm_id,
                chat_session_id=chat_session_id,
                agent_token_usage_id=agent_token_usage_id,
            )

            db.session.add(execution_history)
            db.session.commit()

            logger.info(
                "✓ Histórico de execução persistido: "
                "agent=%s, action=%s, id=%s, token_usage_id=%s",
                agent_name,
                action_name,
                execution_history.id,
                agent_token_usage_id,
            )

            return execution_history

        except Exception as exc:
            logger.exception(
                "✗ Erro ao persistir histórico de execução: %s",
                exc,
            )
            db.session.rollback()
            return None

    @staticmethod
    def get_execution_history_by_id(execution_id: int) -> AgentExecutionHistory | None:
        """Recupera histórico de execução por ID."""
        return AgentExecutionHistory.query.filter_by(id=execution_id).first()

    @staticmethod
    def get_executions_by_token_usage_id(
        token_usage_id: int,
    ) -> list[AgentExecutionHistory]:
        """Recupera históricos de execução relacionados a um token usage."""
        return AgentExecutionHistory.query.filter_by(
            agent_token_usage_id=token_usage_id
        ).all()

    @staticmethod
    def get_recent_executions(
        agent_type: str | None = None,
        law_firm_id: int | None = None,
        limit: int = 50,
    ) -> list[AgentExecutionHistory]:
        """Recupera execuções recentes com filtros opcionais."""
        query = AgentExecutionHistory.query

        if agent_type:
            query = query.filter_by(agent_type=agent_type)

        if law_firm_id:
            query = query.filter_by(law_firm_id=law_firm_id)

        return query.order_by(
            AgentExecutionHistory.created_at.desc()
        ).limit(limit).all()
