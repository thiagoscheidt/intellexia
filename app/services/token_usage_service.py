from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import requests
from flask import session, has_request_context
from app.models import AgentTokenUsage, db


logger = logging.getLogger(__name__)


@dataclass
class TokenUsageEntry:
    message_index: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    message_role: str
    request_id: str
    finish_reason: str
    estimated_cost_usd: Decimal
    pricing_input_per_1k: Decimal
    pricing_output_per_1k: Decimal
    pricing_source: str
    usage_payload: dict[str, Any]


class TokenUsageService:
    """Serviço central para extrair, imprimir e persistir uso de tokens retornado por agentes LangChain."""

    _DEFAULT_PRICING_PER_1K: dict[str, tuple[Decimal, Decimal]] = {
        "gpt-5-mini": (Decimal("0.00025"), Decimal("0.00200")),
        "gpt-5-nano": (Decimal("0.00005"), Decimal("0.00040")),
        "gpt-4o-mini": (Decimal("0.00015"), Decimal("0.00060")),
    }
    _OPENROUTER_MODELS_URL = os.getenv("OPENROUTER_MODELS_URL", "https://openrouter.ai/api/v1/models")
    _OPENROUTER_PRICING_TTL_SECONDS = int(os.getenv("TOKEN_PRICING_CACHE_TTL_SECONDS", "3600"))
    _openrouter_pricing_cache: dict[str, tuple[Decimal, Decimal]] = {}
    _openrouter_pricing_cached_at: float = 0.0

    @staticmethod
    def _get_session_user_data() -> tuple[int | None, int | None]:
        """
        Extrai user_id e law_firm_id da sessão Flask.
        
        Returns:
            Tupla (user_id, law_firm_id) ou (None, None) se não estiver em contexto de request
        """
        if not has_request_context():
            return None, None
        
        try:
            user_id = session.get('user_id')
            law_firm_id = session.get('law_firm_id')
            return user_id, law_firm_id
        except Exception:
            return None, None

    def _normalize_usage(self, usage: dict[str, Any] | None) -> tuple[int, int, int]:
        if not usage or not isinstance(usage, dict):
            return 0, 0, 0

        if isinstance(usage.get("input_tokens"), int) or isinstance(usage.get("output_tokens"), int):
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))
            return input_tokens, output_tokens, total_tokens

        if isinstance(usage.get("prompt_tokens"), int) or isinstance(usage.get("completion_tokens"), int):
            input_tokens = int(usage.get("prompt_tokens") or 0)
            output_tokens = int(usage.get("completion_tokens") or 0)
            total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))
            return input_tokens, output_tokens, total_tokens

        if isinstance(usage.get("total_tokens"), int):
            total_tokens = int(usage.get("total_tokens") or 0)
            return 0, 0, total_tokens

        return 0, 0, 0

    def _extract_usage_from_message(self, message: Any) -> dict[str, Any] | None:
        usage = getattr(message, "usage_metadata", None)
        if isinstance(usage, dict):
            return usage

        if isinstance(message, dict):
            usage = message.get("usage_metadata")
            if isinstance(usage, dict):
                return usage

            response_metadata = message.get("response_metadata") or {}
            token_usage = response_metadata.get("token_usage")
            if isinstance(token_usage, dict):
                return token_usage

        response_metadata = getattr(message, "response_metadata", None)
        if isinstance(response_metadata, dict):
            token_usage = response_metadata.get("token_usage")
            if isinstance(token_usage, dict):
                return token_usage

        return None

    @staticmethod
    def _extract_message_role(message: Any) -> str:
        role = getattr(message, "type", None)
        if isinstance(role, str) and role.strip():
            return role.strip().lower()

        if isinstance(message, dict):
            role = message.get("role") or message.get("type")
            if isinstance(role, str) and role.strip():
                return role.strip().lower()

        return "unknown"

    @staticmethod
    def _extract_message_request_id(message: Any) -> str:
        request_id = getattr(message, "id", None)
        if isinstance(request_id, str) and request_id.strip():
            return request_id.strip()

        if isinstance(message, dict):
            request_id = message.get("id")
            if isinstance(request_id, str) and request_id.strip():
                return request_id.strip()

        response_metadata = getattr(message, "response_metadata", None)
        if isinstance(response_metadata, dict):
            request_id = response_metadata.get("id") or response_metadata.get("request_id")
            if isinstance(request_id, str) and request_id.strip():
                return request_id.strip()

        if isinstance(message, dict):
            response_metadata = message.get("response_metadata") or {}
            request_id = response_metadata.get("id") or response_metadata.get("request_id")
            if isinstance(request_id, str) and request_id.strip():
                return request_id.strip()

        return ""

    @staticmethod
    def _extract_finish_reason(message: Any) -> str:
        response_metadata = getattr(message, "response_metadata", None)
        if isinstance(response_metadata, dict):
            finish_reason = response_metadata.get("finish_reason")
            if isinstance(finish_reason, str) and finish_reason.strip():
                return finish_reason.strip().lower()

        if isinstance(message, dict):
            response_metadata = message.get("response_metadata") or {}
            finish_reason = response_metadata.get("finish_reason")
            if isinstance(finish_reason, str) and finish_reason.strip():
                return finish_reason.strip().lower()

        return ""

    def _estimate_cost_usd(
        self,
        *,
        model_name: str | None,
        input_tokens: int,
        output_tokens: int,
    ) -> tuple[Decimal, Decimal, Decimal, str]:
        name = (model_name or "").strip().lower()
        # Strip provider prefix from OpenRouter-style names (e.g. "openai/gpt-4o-mini" -> "gpt-4o-mini")
        short_name = name.rsplit("/", 1)[-1] if "/" in name else name

        input_price, output_price, pricing_source = self._resolve_pricing_per_1k(name, short_name)

        if input_price == 0 and output_price == 0:
            return Decimal("0"), input_price, output_price, pricing_source

        input_cost = (Decimal(input_tokens) / Decimal(1000)) * input_price
        output_cost = (Decimal(output_tokens) / Decimal(1000)) * output_price
        return (input_cost + output_cost).quantize(Decimal("0.00000001")), input_price, output_price, pricing_source

    def _resolve_pricing_per_1k(self, full_name: str, short_name: str) -> tuple[Decimal, Decimal, str]:
        env_key = short_name.upper().replace('-', '_') if short_name else ""
        configured_input = os.getenv(f"TOKEN_PRICE_INPUT_1K_{env_key}") if env_key else None
        configured_output = os.getenv(f"TOKEN_PRICE_OUTPUT_1K_{env_key}") if env_key else None

        if configured_input and configured_output:
            try:
                input_price = Decimal(configured_input)
                output_price = Decimal(configured_output)
                return input_price, output_price, "env"
            except Exception:
                pass

        openrouter_prices = self._get_openrouter_prices_for_model(full_name, short_name)
        if openrouter_prices:
            return openrouter_prices[0], openrouter_prices[1], "openrouter"

        input_price, output_price = self._DEFAULT_PRICING_PER_1K.get(short_name, (Decimal("0"), Decimal("0")))
        if input_price or output_price:
            return input_price, output_price, "default"

        return Decimal("0"), Decimal("0"), "none"

    def _get_openrouter_prices_for_model(
        self,
        full_name: str,
        short_name: str,
    ) -> tuple[Decimal, Decimal] | None:
        pricing_map = self._get_openrouter_pricing_map()
        if not pricing_map:
            return None

        for key in [full_name, short_name]:
            normalized = (key or "").strip().lower()
            if normalized and normalized in pricing_map:
                return pricing_map[normalized]

        return None

    def _get_openrouter_pricing_map(self) -> dict[str, tuple[Decimal, Decimal]]:
        now = time.time()
        if (
            self._openrouter_pricing_cache
            and self._openrouter_pricing_cached_at
            and (now - self._openrouter_pricing_cached_at) < self._OPENROUTER_PRICING_TTL_SECONDS
        ):
            return self._openrouter_pricing_cache

        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            return self._openrouter_pricing_cache

        try:
            response = requests.get(
                self._OPENROUTER_MODELS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                params={"output_modalities": "text"},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json() or {}
        except Exception as exc:
            logger.debug("TokenUsageService: falha ao atualizar pricing OpenRouter: %s", exc)
            return self._openrouter_pricing_cache

        pricing_map: dict[str, tuple[Decimal, Decimal]] = {}
        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue

            model_id = str(item.get("id") or "").strip().lower()
            if not model_id:
                continue

            pricing = item.get("pricing") or {}
            prompt_raw = pricing.get("prompt")
            completion_raw = pricing.get("completion")

            try:
                # OpenRouter retorna preço por token; convertemos para preço por 1k tokens.
                prompt_per_1k = (Decimal(str(prompt_raw)) * Decimal(1000)).quantize(Decimal("0.00000001"))
                completion_per_1k = (Decimal(str(completion_raw)) * Decimal(1000)).quantize(Decimal("0.00000001"))
            except Exception:
                continue

            pricing_map[model_id] = (prompt_per_1k, completion_per_1k)
            if "/" in model_id:
                pricing_map[model_id.rsplit("/", 1)[-1]] = (prompt_per_1k, completion_per_1k)

            canonical_slug = str(item.get("canonical_slug") or "").strip().lower()
            if canonical_slug and canonical_slug not in pricing_map:
                pricing_map[canonical_slug] = (prompt_per_1k, completion_per_1k)

        if pricing_map:
            self._openrouter_pricing_cache = pricing_map
            self._openrouter_pricing_cached_at = now

        return self._openrouter_pricing_cache

    def extract_entries(
        self,
        response_payload: dict[str, Any] | None,
        *,
        model_name: str | None = None,
    ) -> list[TokenUsageEntry]:
        if not isinstance(response_payload, dict):
            return []

        messages = response_payload.get("messages")
        if not isinstance(messages, list):
            return []

        entries: list[TokenUsageEntry] = []
        for index, message in enumerate(messages):
            usage = self._extract_usage_from_message(message)
            if not usage:
                continue

            input_tokens, output_tokens, total_tokens = self._normalize_usage(usage)
            message_role = self._extract_message_role(message)
            request_id = self._extract_message_request_id(message)
            finish_reason = self._extract_finish_reason(message)
            estimated_cost_usd, pricing_input_per_1k, pricing_output_per_1k, pricing_source = self._estimate_cost_usd(
                model_name=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

            entries.append(
                TokenUsageEntry(
                    message_index=index,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    message_role=message_role,
                    request_id=request_id,
                    finish_reason=finish_reason,
                    estimated_cost_usd=estimated_cost_usd,
                    pricing_input_per_1k=pricing_input_per_1k,
                    pricing_output_per_1k=pricing_output_per_1k,
                    pricing_source=pricing_source,
                    usage_payload=usage,
                )
            )

        return entries

    def print_entries(self, entries: list[TokenUsageEntry], prefix: str) -> None:
        if not entries:
            print(f"{prefix} nenhum usage_metadata recebido")
            return

        for entry in entries:
            print(
                f"{prefix} msg[{entry.message_index}] input={entry.input_tokens} "
                f"output={entry.output_tokens} total={entry.total_tokens} "
                f"role={entry.message_role} finish={entry.finish_reason or '-'} "
                f"cost_usd={entry.estimated_cost_usd} "
                f"pricing_source={entry.pricing_source}"
            )

        total = sum(item.total_tokens for item in entries)
        total_cost = sum((item.estimated_cost_usd for item in entries), Decimal("0"))
        print(f"{prefix} total_geral={total} cost_usd_total={total_cost}")

    def persist_entries(
        self,
        entries: list[TokenUsageEntry],
        *,
        agent_name: str,
        action_name: str,
        model_name: str | None = None,
        model_provider: str | None = None,
        user_id: int | None = None,
        law_firm_id: int | None = None,
        chat_session_id: int | None = None,
        latency_ms: int | None = None,
        status: str = "success",
        error_message: str | None = None,
        metadata_payload: dict[str, Any] | None = None,
        return_rows: bool = False,
    ) -> list[Any] | None:
        if not entries:
            print(f"[TokenUsageService] persist_entries: sem entries para salvar")
            return [] if return_rows else None

        # Buscar user_id e law_firm_id da sessão se não foram fornecidos
        if user_id is None or law_firm_id is None:
            session_user_id, session_law_firm_id = self._get_session_user_data()
            if user_id is None:
                user_id = session_user_id
            if law_firm_id is None:
                law_firm_id = session_law_firm_id

        print(f"[TokenUsageService] persist_entries: salvando {len(entries)} registros no banco...")
        print(f"[TokenUsageService] agent={agent_name} action={action_name} user_id={user_id} law_firm_id={law_firm_id}")

        try:
            rows = []
            for entry in entries:
                row_metadata = dict(metadata_payload or {})
                row_metadata.update(
                    {
                        "pricing_source": entry.pricing_source,
                        "pricing_input_per_1k": str(entry.pricing_input_per_1k),
                        "pricing_output_per_1k": str(entry.pricing_output_per_1k),
                    }
                )

                rows.append(
                    AgentTokenUsage(
                        user_id=user_id,
                        law_firm_id=law_firm_id,
                        chat_session_id=chat_session_id,
                        agent_name=agent_name,
                        action_name=action_name,
                        model_name=model_name,
                        model_provider=model_provider,
                        request_id=entry.request_id or None,
                        message_role=entry.message_role,
                        finish_reason=entry.finish_reason or None,
                        status=status,
                        error_message=error_message,
                        message_index=entry.message_index,
                        latency_ms=latency_ms,
                        input_tokens=entry.input_tokens,
                        output_tokens=entry.output_tokens,
                        total_tokens=entry.total_tokens,
                        estimated_cost_usd=entry.estimated_cost_usd,
                        currency="USD",
                        usage_payload=entry.usage_payload,
                        metadata_payload=row_metadata,
                    )
                )

            db.session.add_all(rows)
            db.session.commit()
            print(f"[TokenUsageService] ✓ {len(rows)} registros salvos com sucesso no banco!")
            return rows if return_rows else None
        except Exception as exc:
            db.session.rollback()
            error_msg = f"Falha ao persistir AgentTokenUsage: {exc}"
            logger.error(error_msg)
            print(f"[TokenUsageService] ✗ ERRO ao salvar no banco: {exc}")
            print(f"[TokenUsageService] Tipo do erro: {type(exc).__name__}")
            return [] if return_rows else None

    def capture_and_store(
        self,
        response_payload: dict[str, Any] | None,
        *,
        agent_name: str,
        action_name: str,
        print_prefix: str,
        model_name: str | None = None,
        model_provider: str | None = None,
        user_id: int | None = None,
        law_firm_id: int | None = None,
        chat_session_id: int | None = None,
        latency_ms: int | None = None,
        status: str = "success",
        error_message: str | None = None,
        metadata_payload: dict[str, Any] | None = None,
        return_rows: bool = False,
    ) -> int | tuple[int, list[Any]]:
        entries = self.extract_entries(response_payload, model_name=model_name)
        self.print_entries(entries, print_prefix)
        rows = self.persist_entries(
            entries,
            agent_name=agent_name,
            action_name=action_name,
            model_name=model_name,
            model_provider=model_provider,
            user_id=user_id,
            law_firm_id=law_firm_id,
            chat_session_id=chat_session_id,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
            metadata_payload=metadata_payload,
            return_rows=return_rows,
        )
        total_tokens = sum(entry.total_tokens for entry in entries)
        if return_rows:
            return total_tokens, (rows or [])
        return total_tokens
