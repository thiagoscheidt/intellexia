"""
Script para ampliar colunas textuais da tabela benefits para LONGTEXT no MySQL.

Motivacao:
- Evitar erro (1406) Data too long em importacoes de relatorios FAP com textos extensos.

Uso:
    uv run python database/increase_benefits_text_columns_to_longtext.py
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


def increase_benefits_text_columns():
    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        is_mysql = "mysql" in db_uri

        if not is_mysql:
            print("Banco nao-MySQL detectado. Nenhuma alteracao necessaria.")
            return

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            existing = _get_existing_columns(connection, "benefits", is_mysql=True)

            target_columns = [
                "notes",
                "justification",
                "opinion",
                "first_instance_justification",
                "first_instance_opinion",
                "second_instance_justification",
                "second_instance_opinion",
                "accident_summary",
            ]

            for column_name in target_columns:
                if column_name not in existing:
                    print(f"- coluna nao encontrada, ignorando: {column_name}")
                    continue

                print(f"+ alterando coluna para LONGTEXT: {column_name}")
                connection.execute(
                    db.text(f"ALTER TABLE benefits MODIFY COLUMN {column_name} LONGTEXT")
                )

            transaction.commit()
            print("✓ Migração concluida")
        except Exception as exc:
            transaction.rollback()
            print(f"Erro na migracao: {exc}")
            raise
        finally:
            connection.close()


if __name__ == "__main__":
    increase_benefits_text_columns()
