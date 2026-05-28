"""
Script para adicionar a coluna event_identifier na tabela judicial_documents.

Uso:
    uv run python database/add_judicial_documents_event_identifier.py
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


def _index_exists(connection, index_name: str, is_mysql: bool = False) -> bool:
    if is_mysql:
        result = connection.execute(db.text("SHOW INDEX FROM judicial_documents"))
        return any(str(row[2]) == index_name for row in result.fetchall())

    result = connection.execute(db.text("PRAGMA index_list(judicial_documents)"))
    return any(str(row[1]) == index_name for row in result.fetchall())


def add_event_identifier_column() -> None:
    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        is_mysql = "mysql" in db_uri.lower()

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            existing_columns = _get_existing_columns(connection, "judicial_documents", is_mysql)

            if "event_identifier" in existing_columns:
                print("- coluna já existe: event_identifier")
            else:
                print("+ adicionando coluna: event_identifier")
                connection.execute(
                    db.text("ALTER TABLE judicial_documents ADD COLUMN event_identifier VARCHAR(50)")
                )

            index_name = "ix_judicial_documents_event_identifier"
            if _index_exists(connection, index_name, is_mysql):
                print(f"- índice já existe: {index_name}")
            else:
                print(f"+ criando índice: {index_name}")
                connection.execute(
                    db.text(
                        "CREATE INDEX ix_judicial_documents_event_identifier "
                        "ON judicial_documents (event_identifier)"
                    )
                )

            transaction.commit()
            print("✓ Migração concluída: coluna event_identifier disponível em judicial_documents")
        except Exception as exc:
            transaction.rollback()
            print(f"Erro ao aplicar migração: {exc}")
            raise
        finally:
            connection.close()


if __name__ == "__main__":
    add_event_identifier_column()
