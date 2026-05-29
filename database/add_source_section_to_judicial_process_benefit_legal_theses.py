"""
Script de migração para adicionar a coluna source_section
na tabela judicial_process_benefit_legal_theses.

Uso:
    uv run python database/add_source_section_to_judicial_process_benefit_legal_theses.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db


def _column_exists(connection, table_name: str, column_name: str, is_mysql: bool = False) -> bool:
    if is_mysql:
        result = connection.execute(
            db.text(
                """
                SELECT 1
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = :table_name
                  AND COLUMN_NAME = :column_name
                LIMIT 1
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        )
        return result.first() is not None

    result = connection.execute(
        db.text(
            f"""
            SELECT 1
            FROM pragma_table_info('{table_name}')
            WHERE name = :column_name
            LIMIT 1
            """
        ),
        {"column_name": column_name},
    )
    return result.first() is not None


def migrate() -> None:
    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        is_mysql = "mysql" in db_uri
        table_name = "judicial_process_benefit_legal_theses"
        column_name = "source_section"

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            if _column_exists(connection, table_name, column_name, is_mysql=is_mysql):
                print(f"- coluna já existe: {table_name}.{column_name}")
            else:
                print(f"+ adicionando coluna: {table_name}.{column_name}")
                connection.execute(
                    db.text(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR(255) NULL"
                    )
                )

            transaction.commit()
            print("✓ Migração concluída")
        except Exception as exc:
            transaction.rollback()
            print(f"Erro na migração: {exc}")
            raise
        finally:
            connection.close()


if __name__ == "__main__":
    migrate()
