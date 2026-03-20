"""
Script para adicionar colunas na tabela benefits:
- justification
- status
- opinion

Uso:
    uv run python database/add_benefits_status_justification_opinion_columns.py
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
                'justification': "ALTER TABLE benefits ADD COLUMN justification TEXT",
                'status': "ALTER TABLE benefits ADD COLUMN status VARCHAR(30)",
                'opinion': "ALTER TABLE benefits ADD COLUMN opinion TEXT",
            }

            for column_name, ddl in statements.items():
                if column_name in existing:
                    print(f"- coluna ja existe: {column_name}")
                    continue
                print(f"+ adicionando coluna: {column_name}")
                connection.execute(db.text(ddl))

            # Garante valor padrao para linhas antigas
            connection.execute(db.text("UPDATE benefits SET status = 'pending' WHERE status IS NULL OR status = ''"))

            # Index em status para filtros futuros
            if is_mysql:
                connection.execute(db.text("CREATE INDEX ix_benefits_status ON benefits (status)"))
            else:
                connection.execute(db.text("CREATE INDEX IF NOT EXISTS ix_benefits_status ON benefits (status)"))

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
