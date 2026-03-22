"""
Script para adicionar colunas de decisao administrativa por instancia na tabela benefits:
- first_instance_status
- first_instance_justification
- first_instance_opinion
- second_instance_status
- second_instance_justification
- second_instance_opinion

Uso:
    uv run python database/add_benefits_instance_decision_columns.py
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
                'first_instance_status': "ALTER TABLE benefits ADD COLUMN first_instance_status VARCHAR(30)",
                'first_instance_justification': "ALTER TABLE benefits ADD COLUMN first_instance_justification TEXT",
                'first_instance_opinion': "ALTER TABLE benefits ADD COLUMN first_instance_opinion TEXT",
                'second_instance_status': "ALTER TABLE benefits ADD COLUMN second_instance_status VARCHAR(30)",
                'second_instance_justification': "ALTER TABLE benefits ADD COLUMN second_instance_justification TEXT",
                'second_instance_opinion': "ALTER TABLE benefits ADD COLUMN second_instance_opinion TEXT",
            }

            for column_name, ddl in statements.items():
                if column_name in existing:
                    print(f"- coluna ja existe: {column_name}")
                    continue
                print(f"+ adicionando coluna: {column_name}")
                connection.execute(db.text(ddl))

            if is_mysql:
                existing_indexes = {
                    row[2]
                    for row in connection.execute(db.text("SHOW INDEX FROM benefits")).fetchall()
                }
                if 'ix_benefits_first_instance_status' not in existing_indexes:
                    connection.execute(
                        db.text("CREATE INDEX ix_benefits_first_instance_status ON benefits (first_instance_status)")
                    )
                if 'ix_benefits_second_instance_status' not in existing_indexes:
                    connection.execute(
                        db.text("CREATE INDEX ix_benefits_second_instance_status ON benefits (second_instance_status)")
                    )
            else:
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_benefits_first_instance_status ON benefits (first_instance_status)")
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_benefits_second_instance_status ON benefits (second_instance_status)")
                )

            transaction.commit()
            print("✓ Migração concluída")
        except Exception as exc:
            transaction.rollback()
            print(f"Erro na migração: {exc}")
            raise
        finally:
            connection.close()


if __name__ == '__main__':
    add_missing_columns()
