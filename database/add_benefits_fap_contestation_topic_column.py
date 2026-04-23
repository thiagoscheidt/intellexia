"""
Script para adicionar coluna na tabela benefits:
- fap_contestation_topic

Uso:
    uv run python database/add_benefits_fap_contestation_topic_column.py
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

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            existing = _get_existing_columns(connection, "benefits", is_mysql)

            if "fap_contestation_topic" in existing:
                print("- coluna ja existe: fap_contestation_topic")
            else:
                print("+ adicionando coluna: fap_contestation_topic")
                connection.execute(
                    db.text("ALTER TABLE benefits ADD COLUMN fap_contestation_topic VARCHAR(120)")
                )

            if is_mysql:
                connection.execute(
                    db.text("CREATE INDEX ix_benefits_fap_contestation_topic ON benefits (fap_contestation_topic)")
                )
            else:
                connection.execute(
                    db.text(
                        "CREATE INDEX IF NOT EXISTS ix_benefits_fap_contestation_topic "
                        "ON benefits (fap_contestation_topic)"
                    )
                )

            transaction.commit()
            print("Migracao concluida com sucesso.")
        except Exception as exc:
            transaction.rollback()
            print(f"Erro durante a migracao: {exc}")
            raise
        finally:
            connection.close()


if __name__ == "__main__":
    add_missing_columns()
