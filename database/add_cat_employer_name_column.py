"""
Script para adicionar a coluna employer_name à tabela fap_contestation_cats.

Uso:
    uv run python database/add_cat_employer_name_column.py
"""

import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db
from main import app


def _column_exists(connection, table_name: str, column_name: str, is_mysql: bool) -> bool:
    if is_mysql:
        result = connection.execute(
            db.text("SHOW COLUMNS FROM `{table}` LIKE :col".format(table=table_name)),
            {"col": column_name},
        )
        return result.fetchone() is not None

    result = connection.execute(db.text(f"PRAGMA table_info({table_name})"))
    return any(row[1] == column_name for row in result.fetchall())


def run_migration():
    with app.app_context():
        with db.engine.connect() as conn:
            is_mysql = db.engine.dialect.name == "mysql"

            if _column_exists(conn, "fap_contestation_cats", "employer_name", is_mysql):
                print("Coluna 'employer_name' já existe em fap_contestation_cats. Nada a fazer.")
                return

            print("Adicionando coluna 'employer_name' em fap_contestation_cats...")
            conn.execute(db.text(
                "ALTER TABLE fap_contestation_cats ADD COLUMN employer_name VARCHAR(255)"
            ))
            conn.commit()
            print("Coluna adicionada com sucesso.")


if __name__ == "__main__":
    run_migration()
