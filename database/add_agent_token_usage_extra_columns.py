"""
Script para adicionar colunas novas na tabela agent_token_usage (caso já exista).

Para executar:
    python database/add_agent_token_usage_extra_columns.py
"""

import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db
from main import app


def _get_existing_columns(connection, table_name: str, is_mysql: bool = False) -> set[str]:
    """Obtém colunas existentes na tabela (compatível com SQLite e MySQL)"""
    if is_mysql:
        result = connection.execute(db.text(f"SHOW COLUMNS FROM {table_name}"))
        return {row[0] for row in result.fetchall()}
    else:
        result = connection.execute(db.text(f"PRAGMA table_info({table_name})"))
        return {row[1] for row in result.fetchall()}


def add_missing_columns():
    with app.app_context():
        # Detectar tipo de banco
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        is_mysql = 'mysql' in db_uri
        
        if is_mysql:
            db_type = "MySQL"
            display_uri = db_uri.split('@')[1] if '@' in db_uri else db_uri
        else:
            db_type = "SQLite"
            display_uri = db_uri.replace('sqlite:///', '')
        
        print(f"Banco de dados detectado: {db_type}")
        print(f"Conexão: {display_uri}")
        print("\nVerificando colunas da tabela agent_token_usage...")
        
        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            existing = _get_existing_columns(connection, "agent_token_usage", is_mysql)

            statements = {
                "request_id": "ALTER TABLE agent_token_usage ADD COLUMN request_id VARCHAR(120)",
                "message_role": "ALTER TABLE agent_token_usage ADD COLUMN message_role VARCHAR(40)",
                "finish_reason": "ALTER TABLE agent_token_usage ADD COLUMN finish_reason VARCHAR(80)",
                "status": "ALTER TABLE agent_token_usage ADD COLUMN status VARCHAR(20)",
                "error_message": "ALTER TABLE agent_token_usage ADD COLUMN error_message TEXT",
                "latency_ms": "ALTER TABLE agent_token_usage ADD COLUMN latency_ms INTEGER",
                "estimated_cost_usd": "ALTER TABLE agent_token_usage ADD COLUMN estimated_cost_usd NUMERIC(14,8)",
                "currency": "ALTER TABLE agent_token_usage ADD COLUMN currency VARCHAR(10)",
            }

            for column_name, ddl in statements.items():
                if column_name in existing:
                    print(f"- coluna já existe: {column_name}")
                    continue
                print(f"+ adicionando coluna: {column_name}")
                connection.execute(db.text(ddl))

            transaction.commit()
            print("✓ Migração de colunas concluída")
        except Exception as exc:
            transaction.rollback()
            print(f"Erro ao adicionar colunas: {exc}")
            raise
        finally:
            connection.close()


if __name__ == "__main__":
    add_missing_columns()
