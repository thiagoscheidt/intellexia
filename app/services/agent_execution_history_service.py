"""
Service para persistência de histórico completo de execuções de agentes.
"""

import logging
from typing import Any

from app.models import AgentExecutionHistory, db

logger = logging.getLogger(__name__)


class AgentExecutionHistoryService:
    """Serviço para armazenar e recuperar histórico completo de execução de agentes."""

    _MAX_INLINE_STRING_LENGTH = 4000

    @staticmethod
    def _truncate_string(value: str) -> str:
        """Limita strings muito grandes para reduzir risco de overflow no banco."""
        if len(value) <= AgentExecutionHistoryService._MAX_INLINE_STRING_LENGTH:
            return value
        omitted = len(value) - AgentExecutionHistoryService._MAX_INLINE_STRING_LENGTH
        return (
            value[:AgentExecutionHistoryService._MAX_INLINE_STRING_LENGTH]
            + f"\n\n...[truncated {omitted} chars]"
        )

    @staticmethod
    def _sanitize_payload(value: Any) -> Any:
        """Remove payloads binários/base64 gigantes antes de persistir o histórico."""
        if isinstance(value, dict):
            payload_type = str(value.get("type") or "").lower()
            file_info = value.get("file")
            if payload_type == "file" and isinstance(file_info, dict):
                sanitized_file = dict(file_info)
                file_data = sanitized_file.get("file_data")
                if isinstance(file_data, str):
                    sanitized_file["file_data"] = (
                        f"[omitted file payload: {len(file_data)} chars]"
                    )
                return {
                    **value,
                    "file": AgentExecutionHistoryService._sanitize_payload(sanitized_file),
                }

            return {
                key: AgentExecutionHistoryService._sanitize_payload(item)
                for key, item in value.items()
            }

        if isinstance(value, list):
            return [AgentExecutionHistoryService._sanitize_payload(item) for item in value]

        if isinstance(value, str):
            if value.startswith("data:") and ";base64," in value:
                return f"[omitted data-url payload: {len(value)} chars]"
            return AgentExecutionHistoryService._truncate_string(value)

        return value

    @staticmethod
    def _build_execution_history(**kwargs: Any) -> AgentExecutionHistory:
        """Cria a entidade de histórico com payload já sanitizado."""
        return AgentExecutionHistory(**kwargs)

    @staticmethod
    def _serialize_message(msg: Any) -> dict[str, Any]:
        """Serializa uma mensagem LangChain para dict JSON-compatível."""
        if hasattr(msg, "model_dump"):
            return AgentExecutionHistoryService._sanitize_payload(msg.model_dump())
        if hasattr(msg, "dict"):
            return AgentExecutionHistoryService._sanitize_payload(msg.dict())
        if hasattr(msg, "content") and hasattr(msg, "type"):
            return AgentExecutionHistoryService._sanitize_payload({
                "type": str(msg.type),
                "content": str(msg.content),
            })
        if isinstance(msg, dict):
            return AgentExecutionHistoryService._sanitize_payload(msg)
        return AgentExecutionHistoryService._sanitize_payload({"content": str(msg)})

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

            execution_history = AgentExecutionHistoryService._build_execution_history(
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
            db.session.rollback()

            logger.exception(
                "✗ Erro ao persistir histórico de execução com mensagens completas: %s",
                exc,
            )

            try:
                execution_history = AgentExecutionHistoryService._build_execution_history(
                    agent_name=agent_name,
                    action_name=action_name,
                    agent_type=agent_type,
                    system_prompt=AgentExecutionHistoryService._sanitize_payload(system_prompt),
                    user_prompt=AgentExecutionHistoryService._sanitize_payload(user_prompt),
                    model_response=AgentExecutionHistoryService._sanitize_payload(model_response),
                    full_messages_history=None,
                    result_data=AgentExecutionHistoryService._sanitize_payload(result_data),
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

                logger.warning(
                    "✓ Histórico persistido sem full_messages_history: agent=%s, action=%s, id=%s",
                    agent_name,
                    action_name,
                    execution_history.id,
                )
                return execution_history
            except Exception as fallback_exc:
                db.session.rollback()
                logger.exception(
                    "✗ Erro ao persistir histórico de execução mesmo sem mensagens completas: %s",
                    fallback_exc,
                )
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
