"""
Script para adicionar suporte a múltiplas conversas no chat da base de conhecimento.

Cria tabela knowledge_chat_sessions e adiciona coluna chat_session_id em knowledge_chat_history.

Para executar:
    python database/add_knowledge_chat_sessions_table.py
"""

import sys
from pathlib import Path

from sqlalchemy import inspect, text

# Adicionar o diretório raiz ao path do Python
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db
from main import app


def add_knowledge_chat_sessions_table():
    with app.app_context():
        print("Verificando estrutura de chats...")

        # Garante criação da nova tabela pelo metadata
        db.create_all()

        inspector = inspect(db.engine)
        columns = {col["name"] for col in inspector.get_columns("knowledge_chat_history")}

        if "chat_session_id" not in columns:
            print("Adicionando coluna chat_session_id em knowledge_chat_history...")
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE knowledge_chat_history ADD COLUMN chat_session_id INTEGER"))
                conn.commit()
            print("✓ Coluna chat_session_id adicionada")
        else:
            print("✓ Coluna chat_session_id já existe")

        print("\nConcluído!")
        print("- Tabela knowledge_chat_sessions disponível")
        print("- Histórico pronto para vínculo por conversa")


if __name__ == "__main__":
    add_knowledge_chat_sessions_table()
