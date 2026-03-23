"""
Script para adicionar a coluna knowledge_base_id na tabela fap_contestation_judgment_reports.

Uso:
    uv run python database/add_knowledge_base_id_to_fap_contestation_reports.py
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


def add_knowledge_base_id_column():
    with app.app_context():
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        is_mysql = 'mysql' in db_uri

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            existing = _get_existing_columns(connection, 'fap_contestation_judgment_reports', is_mysql)

            if 'knowledge_base_id' not in existing:
                print('+ adicionando coluna: knowledge_base_id')
                connection.execute(
                    db.text(
                        'ALTER TABLE fap_contestation_judgment_reports ADD COLUMN knowledge_base_id INTEGER'
                    )
                )
            else:
                print('- coluna ja existe: knowledge_base_id')

            if is_mysql:
                existing_indexes = {
                    row[2]
                    for row in connection.execute(
                        db.text('SHOW INDEX FROM fap_contestation_judgment_reports')
                    ).fetchall()
                }
                if 'ix_fap_contestation_judgment_reports_knowledge_base_id' not in existing_indexes:
                    connection.execute(
                        db.text(
                            'CREATE INDEX ix_fap_contestation_judgment_reports_knowledge_base_id '
                            'ON fap_contestation_judgment_reports (knowledge_base_id)'
                        )
                    )
            else:
                connection.execute(
                    db.text(
                        'CREATE INDEX IF NOT EXISTS ix_fap_contestation_judgment_reports_knowledge_base_id '
                        'ON fap_contestation_judgment_reports (knowledge_base_id)'
                    )
                )

            transaction.commit()
            print('✓ Migração concluída')
        except Exception as exc:
            transaction.rollback()
            print(f'Erro na migração: {exc}')
            raise
        finally:
            connection.close()


if __name__ == '__main__':
    add_knowledge_base_id_column()
