"""
Script para adicionar a tabela agent_token_usage ao banco de dados.
Esta tabela armazena uso de tokens por ação dos agentes LangChain.

Para executar:
    python database/add_agent_token_usage_table.py
"""

import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db, AgentTokenUsage
from main import app


def create_agent_token_usage_table():
    """Cria a tabela agent_token_usage"""
    with app.app_context():
        print("Criando tabela agent_token_usage...")

        db.create_all()

        print("✓ Tabela agent_token_usage criada com sucesso!")
        print("\nEstrutura da tabela:")
        print("- id: INTEGER PRIMARY KEY")
        print("- user_id: INTEGER (FK para users, opcional)")
        print("- law_firm_id: INTEGER (FK para law_firms, opcional)")
        print("- chat_session_id: INTEGER (FK para knowledge_chat_sessions, opcional)")
        print("- agent_name: VARCHAR(120)")
        print("- action_name: VARCHAR(160)")
        print("- model_name: VARCHAR(120)")
        print("- model_provider: VARCHAR(80)")
        print("- request_id: VARCHAR(120)")
        print("- message_role: VARCHAR(40)")
        print("- finish_reason: VARCHAR(80)")
        print("- status: VARCHAR(20)")
        print("- error_message: TEXT")
        print("- message_index: INTEGER")
        print("- latency_ms: INTEGER")
        print("- input_tokens: INTEGER")
        print("- output_tokens: INTEGER")
        print("- total_tokens: INTEGER")
        print("- estimated_cost_usd: NUMERIC(14,8)")
        print("- currency: VARCHAR(10)")
        print("- usage_payload: JSON")
        print("- metadata_payload: JSON")
        print("- created_at: DATETIME")


if __name__ == '__main__':
    create_agent_token_usage_table()
