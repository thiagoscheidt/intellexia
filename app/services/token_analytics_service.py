from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from app.models import AgentTokenUsage


class TokenAnalyticsService:
    """Agrega métricas de uso de tokens para dashboards."""

    @staticmethod
    def _to_float(value) -> float:
        if value is None:
            return 0.0
        if isinstance(value, Decimal):
            return float(value)
        try:
            return float(value)
        except Exception:
            return 0.0

    def build_dashboard_data(
        self,
        *,
        law_firm_id: int,
        days: int = 30,
        agent_name: str | None = None,
        action_name: str | None = None,
        model_name: str | None = None,
    ) -> dict:
        end_at = datetime.utcnow()
        start_at = end_at - timedelta(days=days)

        query = AgentTokenUsage.query.filter(
            AgentTokenUsage.law_firm_id == law_firm_id,
            AgentTokenUsage.created_at >= start_at,
            AgentTokenUsage.created_at <= end_at,
        )

        if agent_name:
            query = query.filter(AgentTokenUsage.agent_name == agent_name)
        if action_name:
            query = query.filter(AgentTokenUsage.action_name == action_name)
        if model_name:
            query = query.filter(AgentTokenUsage.model_name == model_name)

        rows = query.order_by(AgentTokenUsage.created_at.desc()).all()

        total_calls = len(rows)
        total_input_tokens = sum(int(r.input_tokens or 0) for r in rows)
        total_output_tokens = sum(int(r.output_tokens or 0) for r in rows)
        total_tokens = sum(int(r.total_tokens or 0) for r in rows)
        total_cost_usd = sum((self._to_float(r.estimated_cost_usd) for r in rows), 0.0)
        avg_tokens_per_call = (total_tokens / total_calls) if total_calls else 0
        avg_cost_per_call = (total_cost_usd / total_calls) if total_calls else 0

        grouped_by_day: dict[str, dict[str, float | int]] = defaultdict(lambda: {
            "tokens": 0,
            "calls": 0,
            "cost_usd": 0.0,
        })
        grouped_by_agent: dict[str, dict[str, float | int]] = defaultdict(lambda: {
            "tokens": 0,
            "calls": 0,
            "cost_usd": 0.0,
        })
        grouped_by_model: dict[str, dict[str, float | int]] = defaultdict(lambda: {
            "tokens": 0,
            "calls": 0,
            "cost_usd": 0.0,
        })
        grouped_by_action: dict[str, dict[str, float | int]] = defaultdict(lambda: {
            "tokens": 0,
            "calls": 0,
            "cost_usd": 0.0,
        })

        success_count = 0
        error_count = 0

        for row in rows:
            date_key = row.created_at.strftime("%Y-%m-%d") if row.created_at else "N/A"
            date_bucket = grouped_by_day[date_key]
            date_bucket["tokens"] += int(row.total_tokens or 0)
            date_bucket["calls"] += 1
            date_bucket["cost_usd"] += self._to_float(row.estimated_cost_usd)

            agent_key = row.agent_name or "(sem agente)"
            agent_bucket = grouped_by_agent[agent_key]
            agent_bucket["tokens"] += int(row.total_tokens or 0)
            agent_bucket["calls"] += 1
            agent_bucket["cost_usd"] += self._to_float(row.estimated_cost_usd)

            model_key = row.model_name or "(sem modelo)"
            model_bucket = grouped_by_model[model_key]
            model_bucket["tokens"] += int(row.total_tokens or 0)
            model_bucket["calls"] += 1
            model_bucket["cost_usd"] += self._to_float(row.estimated_cost_usd)

            action_key = row.action_name or "(sem ação)"
            action_bucket = grouped_by_action[action_key]
            action_bucket["tokens"] += int(row.total_tokens or 0)
            action_bucket["calls"] += 1
            action_bucket["cost_usd"] += self._to_float(row.estimated_cost_usd)

            if (row.status or "success") == "success":
                success_count += 1
            else:
                error_count += 1

        date_labels = sorted(grouped_by_day.keys())
        date_tokens = [int(grouped_by_day[d]["tokens"]) for d in date_labels]
        date_calls = [int(grouped_by_day[d]["calls"]) for d in date_labels]
        date_costs = [round(float(grouped_by_day[d]["cost_usd"]), 6) for d in date_labels]

        top_agents = sorted(
            [
                {
                    "name": name,
                    "tokens": int(values["tokens"]),
                    "calls": int(values["calls"]),
                    "cost_usd": round(float(values["cost_usd"]), 6),
                }
                for name, values in grouped_by_agent.items()
            ],
            key=lambda item: item["tokens"],
            reverse=True,
        )[:10]

        top_actions = sorted(
            [
                {
                    "name": name,
                    "tokens": int(values["tokens"]),
                    "calls": int(values["calls"]),
                    "cost_usd": round(float(values["cost_usd"]), 6),
                }
                for name, values in grouped_by_action.items()
            ],
            key=lambda item: item["tokens"],
            reverse=True,
        )[:10]

        model_distribution = sorted(
            [
                {
                    "name": name,
                    "tokens": int(values["tokens"]),
                    "calls": int(values["calls"]),
                    "cost_usd": round(float(values["cost_usd"]), 6),
                }
                for name, values in grouped_by_model.items()
            ],
            key=lambda item: item["tokens"],
            reverse=True,
        )

        recent_entries = [
            {
                "created_at": row.created_at,
                "agent_name": row.agent_name,
                "action_name": row.action_name,
                "model_name": row.model_name,
                "status": row.status,
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0),
                "total_tokens": int(row.total_tokens or 0),
                "latency_ms": int(row.latency_ms or 0),
                "cost_usd": round(self._to_float(row.estimated_cost_usd), 8),
                "finish_reason": row.finish_reason,
                "request_id": row.request_id,
            }
            for row in rows[:120]
        ]

        all_agents = [name for (name,) in AgentTokenUsage.query.with_entities(AgentTokenUsage.agent_name).filter(
            AgentTokenUsage.law_firm_id == law_firm_id
        ).distinct().order_by(AgentTokenUsage.agent_name.asc()).all() if name]

        all_actions = [name for (name,) in AgentTokenUsage.query.with_entities(AgentTokenUsage.action_name).filter(
            AgentTokenUsage.law_firm_id == law_firm_id
        ).distinct().order_by(AgentTokenUsage.action_name.asc()).all() if name]

        all_models = [name for (name,) in AgentTokenUsage.query.with_entities(AgentTokenUsage.model_name).filter(
            AgentTokenUsage.law_firm_id == law_firm_id
        ).distinct().order_by(AgentTokenUsage.model_name.asc()).all() if name]

        return {
            "period_days": days,
            "period_start": start_at,
            "period_end": end_at,
            "total_calls": total_calls,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost_usd, 8),
            "avg_tokens_per_call": round(avg_tokens_per_call, 2),
            "avg_cost_per_call": round(avg_cost_per_call, 8),
            "success_count": success_count,
            "error_count": error_count,
            "date_labels": date_labels,
            "date_tokens": date_tokens,
            "date_calls": date_calls,
            "date_costs": date_costs,
            "top_agents": top_agents,
            "top_actions": top_actions,
            "model_distribution": model_distribution,
            "recent_entries": recent_entries,
            "all_agents": all_agents,
            "all_actions": all_actions,
            "all_models": all_models,
            "selected_agent": agent_name or "",
            "selected_action": action_name or "",
            "selected_model": model_name or "",
        }
