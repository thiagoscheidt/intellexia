"""
Teste de contabilização de tokens do FapPetitionReviewerAgent fora de request.

Regressão: desde que a revisão passou a rodar em segundo plano (thread com
app_context, sem request context), o agente revisor chamava
TokenUsageService.capture_and_store sem user_id/law_firm_id. O serviço caía no
fallback de sessão Flask, que não existe na thread, e gravava AgentTokenUsage
com law_firm_id NULL — invisível no dashboard de tokens (que filtra por
law_firm_id) e sem vínculo com o AgentExecutionHistory.

Verifica, sem request context (como na thread de background):
1. AgentTokenUsage do revisor é gravado com user_id/law_firm_id do escritório.
2. AgentExecutionHistory fica vinculado ao AgentTokenUsage (agent_token_usage_id).

Uso: uv run python tests/test_fap_reviewer_token_usage_tenant.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('OPENAI_API_KEY', 'test-key')
os.environ.setdefault('OPENAI_BASE_URL', 'https://openrouter.ai/api/v1')

from flask import Flask  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

from app.models import AgentExecutionHistory, AgentTokenUsage, db  # noqa: E402
from app.agents.fap_review.reviewer_agent import FapPetitionReviewerAgent  # noqa: E402

LAW_FIRM_ID = 7
USER_ID = 42

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label} {detail}")


def build_app() -> Flask:
    """App isolado em SQLite temporário — nunca toca o banco real."""
    tmp_db = Path(tempfile.mkdtemp(prefix='fap-reviewer-tokens-')) / 'test.db'
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{tmp_db}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def fake_response() -> AIMessage:
    """Resposta do modelo com usage_metadata, como o OpenRouter devolve."""
    return AIMessage(
        content='{"theses": [], "findings": [], "missing_documents": [], '
                '"executive_summary": {"total_findings": 0, "critical_findings": 0, '
                '"moderate_findings": 0, "formal_findings": 0, "main_legal_risks": [], '
                '"correction_priority": "sem achados"}}',
        id='lc_run--teste-token-tenant-0',
        usage_metadata={'input_tokens': 1000, 'output_tokens': 200, 'total_tokens': 1200},
        response_metadata={'finish_reason': 'stop'},
    )


def test_token_usage_carries_tenant_outside_request_context():
    print("[1] Revisão em background grava law_firm_id no AgentTokenUsage")
    app = build_app()

    with app.app_context():
        db.metadata.create_all(
            db.engine,
            tables=[AgentTokenUsage.__table__, AgentExecutionHistory.__table__],
        )

        agent = FapPetitionReviewerAgent(openai_api_key='test-key', model='gpt-4o-mini')
        agent.llm = type('FakeLLM', (), {'invoke': staticmethod(lambda messages: fake_response())})()

        # Sem request context: é assim que a thread de background executa.
        asyncio.run(
            agent.review_petition_single_version(
                petition_file_path='/tmp/peticao.docx',
                petition_text='Texto da petição para revisão.',
                execution_id=1,
                user_id=USER_ID,
                law_firm_id=LAW_FIRM_ID,
            )
        )

        usage = AgentTokenUsage.query.filter_by(
            agent_name='FapPetitionReviewerAgent',
            action_name='review_petition_single_version',
        ).order_by(AgentTokenUsage.id.desc()).first()

        check("AgentTokenUsage foi gravado", usage is not None)
        if usage is None:
            return

        check("law_firm_id preenchido", usage.law_firm_id == LAW_FIRM_ID,
              f"(esperado {LAW_FIRM_ID}, obtido {usage.law_firm_id})")
        check("user_id preenchido", usage.user_id == USER_ID,
              f"(esperado {USER_ID}, obtido {usage.user_id})")
        check("tokens contabilizados", usage.total_tokens == 1200,
              f"(obtido {usage.total_tokens})")

        history = AgentExecutionHistory.query.filter_by(
            agent_name='FapPetitionReviewerAgent',
            action_name='review_petition_single_version',
        ).order_by(AgentExecutionHistory.id.desc()).first()

        check("AgentExecutionHistory foi gravado", history is not None)
        if history is not None:
            check("histórico vinculado ao token usage",
                  history.agent_token_usage_id == usage.id,
                  f"(esperado {usage.id}, obtido {history.agent_token_usage_id})")


def main() -> int:
    print("=" * 70)
    print("Contabilização de tokens do revisor FAP fora de request context")
    print("=" * 70)
    test_token_usage_carries_tenant_outside_request_context()
    print("-" * 70)
    print(f"Passou: {PASSED} | Falhou: {FAILED}")
    return 1 if FAILED else 0


if __name__ == '__main__':
    sys.exit(main())
