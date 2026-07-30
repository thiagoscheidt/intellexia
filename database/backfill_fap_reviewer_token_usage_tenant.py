"""
Backfill do tenant nos registros de token do revisor FAP.

Contexto: desde que a revisão passou a rodar em thread de background (sem
request context), o FapPetitionReviewerAgent gravava AgentTokenUsage sem
user_id/law_firm_id — o TokenUsageService caía no fallback de sessão Flask, que
não existe fora do request. Essas linhas ficaram invisíveis no Dashboard de
Tokens (que filtra por law_firm_id) e sem vínculo com o histórico do agente.

O código já foi corrigido (o agente passa user_id/law_firm_id explicitamente).
Este script repara as linhas antigas.

Como o tenant é recuperado: o AgentExecutionHistory da mesma execução SEMPRE
gravou law_firm_id/user_id corretamente (são passados explicitamente) e é
escrito segundos depois do token usage, no mesmo trecho de código. O pareamento
é por agent_name + action_name + proximidade de created_at. Casos ambíguos
(mais de um histórico candidato na janela) são reportados e NÃO alterados.

Além do tenant, restaura o vínculo agent_execution_history.agent_token_usage_id,
que ficou nulo porque a busca filtrava por law_firm_id.

Idempotente: só toca linhas com law_firm_id NULL.

Uso:
    uv run python database/backfill_fap_reviewer_token_usage_tenant.py           # dry-run
    uv run python database/backfill_fap_reviewer_token_usage_tenant.py --apply   # grava
"""

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import AgentExecutionHistory, AgentTokenUsage, db

AGENT_NAME = 'FapPetitionReviewerAgent'
MATCH_WINDOW_SECONDS = 120


def backfill(apply_changes: bool) -> None:
    with app.app_context():
        orphans = AgentTokenUsage.query.filter(
            AgentTokenUsage.agent_name == AGENT_NAME,
            AgentTokenUsage.law_firm_id.is_(None),
        ).order_by(AgentTokenUsage.id).all()

        if not orphans:
            print("✓ Nenhum registro do revisor com law_firm_id nulo — nada a fazer")
            return

        print(f"Encontrados {len(orphans)} registros sem tenant\n")

        repaired = 0
        linked = 0
        skipped: list[str] = []

        for usage in orphans:
            if not usage.created_at:
                skipped.append(f"id={usage.id}: sem created_at para parear")
                continue

            window = timedelta(seconds=MATCH_WINDOW_SECONDS)
            candidates = AgentExecutionHistory.query.filter(
                AgentExecutionHistory.agent_name == AGENT_NAME,
                AgentExecutionHistory.action_name == usage.action_name,
                AgentExecutionHistory.law_firm_id.isnot(None),
                AgentExecutionHistory.created_at >= usage.created_at - window,
                AgentExecutionHistory.created_at <= usage.created_at + window,
            ).all()

            if not candidates:
                skipped.append(
                    f"id={usage.id} ({usage.created_at}): nenhum histórico na janela de "
                    f"{MATCH_WINDOW_SECONDS}s")
                continue

            firms = {c.law_firm_id for c in candidates}
            if len(firms) > 1:
                skipped.append(
                    f"id={usage.id} ({usage.created_at}): históricos de escritórios "
                    f"diferentes na janela ({sorted(firms)}) — ambíguo")
                continue

            history = min(
                candidates,
                key=lambda c: abs((c.created_at - usage.created_at).total_seconds()),
            )

            print(f"  id={usage.id} {usage.created_at} → law_firm_id={history.law_firm_id} "
                  f"user_id={history.user_id} (histórico id={history.id})")

            usage.law_firm_id = history.law_firm_id
            if usage.user_id is None:
                usage.user_id = history.user_id
            repaired += 1

            if history.agent_token_usage_id is None:
                history.agent_token_usage_id = usage.id
                linked += 1

        print()
        if skipped:
            print(f"⚠ {len(skipped)} registros não puderam ser pareados:")
            for reason in skipped:
                print(f"  - {reason}")
            print()

        if not apply_changes:
            db.session.rollback()
            print(f"DRY-RUN: {repaired} registros seriam corrigidos, "
                  f"{linked} vínculos de histórico restaurados")
            print("Rode novamente com --apply para gravar")
            return

        try:
            db.session.commit()
            print(f"✓ {repaired} registros corrigidos, {linked} vínculos de histórico restaurados")
        except Exception as exc:
            db.session.rollback()
            print(f"✗ Erro ao gravar: {exc}")
            raise


if __name__ == '__main__':
    apply_changes = '--apply' in sys.argv
    print("Backfill do tenant nos tokens do revisor FAP")
    print("=" * 60)
    backfill(apply_changes)
