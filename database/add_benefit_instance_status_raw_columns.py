"""
Script para adicionar colunas de status bruto (texto completo) por instância na tabela benefits:
- first_instance_status_raw
- second_instance_status_raw

Uso:
    uv run python database/add_benefit_instance_status_raw_columns.py
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
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        is_mysql = 'mysql' in db_uri

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            existing = _get_existing_columns(connection, 'benefits', is_mysql)

            statements = {
                'first_instance_status_raw': "ALTER TABLE benefits ADD COLUMN first_instance_status_raw VARCHAR(255)",
                'second_instance_status_raw': "ALTER TABLE benefits ADD COLUMN second_instance_status_raw VARCHAR(255)",
            }

            for column_name, ddl in statements.items():
                if column_name in existing:
                    print(f"- coluna ja existe: {column_name}")
                    continue
                print(f"+ adicionando coluna: {column_name}")
                connection.execute(db.text(ddl))

            transaction.commit()
            print("Migracao concluida com sucesso.")
        except Exception as exc:
            transaction.rollback()
            print(f"Erro durante a migracao: {exc}")
            raise


if __name__ == '__main__':
    add_missing_columns()
