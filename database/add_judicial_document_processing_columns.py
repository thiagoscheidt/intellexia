"""
Script para adicionar colunas de processamento na tabela judicial_documents.

Uso:
    uv run python database/add_judicial_document_processing_columns.py
"""

import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db
from main import app


def _get_existing_columns(connection, table_name: str, is_mysql: bool = False) -> set[str]:
    if is_mysql:
        result = connection.execute(db.text(f"SHOW COLUMNS FROM {table_name}"))
        return {row[0] for row in result.fetchall()}

    result = connection.execute(db.text(f"PRAGMA table_info({table_name})"))
    return {row[1] for row in result.fetchall()}


def add_missing_columns():
    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        is_mysql = "mysql" in db_uri

        if is_mysql:
            db_type = "MySQL"
            display_uri = db_uri.split("@", 1)[1] if "@" in db_uri else db_uri
        else:
            db_type = "SQLite"
            display_uri = db_uri.replace("sqlite:///", "")

        print(f"Banco de dados detectado: {db_type}")
        print(f"Conexão: {display_uri}")
        print("\nVerificando colunas da tabela judicial_documents...")

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            existing = _get_existing_columns(connection, "judicial_documents", is_mysql)

            statements = {
                "status": "ALTER TABLE judicial_documents ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'pending'",
                "error_message": "ALTER TABLE judicial_documents ADD COLUMN error_message TEXT",
                "processed_at": "ALTER TABLE judicial_documents ADD COLUMN processed_at DATETIME",
                "updated_at": "ALTER TABLE judicial_documents ADD COLUMN updated_at DATETIME",
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