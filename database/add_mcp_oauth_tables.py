"""
Script para adicionar as tabelas de OAuth do servidor MCP.

Cria:
  - mcp_oauth_clients: clientes registrados via Dynamic Client Registration
  - mcp_oauth_tokens: access/refresh tokens emitidos pelo servidor MCP

Uso:
    uv run python database/add_mcp_oauth_tables.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, McpOAuthClient, McpOAuthToken


def add_mcp_oauth_tables():
    """Cria as tabelas mcp_oauth_clients e mcp_oauth_tokens (idempotente)."""
    with app.app_context():
        try:
            print("🔄 Criando tabelas OAuth do MCP...")

            McpOAuthClient.__table__.create(bind=db.engine, checkfirst=True)
            McpOAuthToken.__table__.create(bind=db.engine, checkfirst=True)

            print("✅ Tabelas mcp_oauth_clients e mcp_oauth_tokens criadas (ou já existentes)!")
        except Exception as e:
            print(f"❌ Erro ao criar tabelas OAuth do MCP: {e}")
            raise


if __name__ == "__main__":
    add_mcp_oauth_tables()
