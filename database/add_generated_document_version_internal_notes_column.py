"""Add internal_notes column to judicial_process_generated_document_versions.

Usage:
    uv run python database/add_generated_document_version_internal_notes_column.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db


def _get_existing_columns(connection, table_name: str, is_mysql: bool = False) -> set[str]:
    if is_mysql:
        result = connection.execute(db.text(f"SHOW COLUMNS FROM {table_name}"))
        return {row[0] for row in result.fetchall()}

    result = connection.execute(db.text(f"PRAGMA table_info({table_name})"))
    return {row[1] for row in result.fetchall()}


def run_migration() -> None:
    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        is_mysql = "mysql" in db_uri

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            columns = _get_existing_columns(
                connection,
                "judicial_process_generated_document_versions",
                is_mysql,
            )

            if "internal_notes" not in columns:
                print("+ adicionando coluna internal_notes")
                if is_mysql:
                    connection.execute(
                        db.text(
                            "ALTER TABLE judicial_process_generated_document_versions "
                            "ADD COLUMN internal_notes LONGTEXT NULL"
                        )
                    )
                else:
                    connection.execute(
                        db.text(
                            "ALTER TABLE judicial_process_generated_document_versions "
                            "ADD COLUMN internal_notes TEXT"
                        )
                    )
            else:
                print("- coluna ja existe: internal_notes")

            transaction.commit()
            print("Migracao concluida com sucesso.")
        except Exception as exc:
            transaction.rollback()
            print(f"Erro ao alterar schema: {exc}")
            raise
        finally:
            connection.close()


if __name__ == "__main__":
    run_migration()
