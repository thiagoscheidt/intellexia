"""
Script para adicionar coluna de múltiplas categorias FAP na tabela benefits:
- fap_contestation_topics_json (JSON serializado em texto)

Uso:
    uv run python database/add_benefit_fap_contestation_topics_json_column.py
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


def add_missing_column():
    with app.app_context():
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        is_mysql = 'mysql' in db_uri

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            existing = _get_existing_columns(connection, 'benefits', is_mysql)

            if 'fap_contestation_topics_json' in existing:
                print('- coluna ja existe: fap_contestation_topics_json')
            else:
                print('+ adicionando coluna: fap_contestation_topics_json')
                if is_mysql:
                    connection.execute(
                        db.text(
                            'ALTER TABLE benefits ADD COLUMN fap_contestation_topics_json LONGTEXT'
                        )
                    )
                else:
                    connection.execute(
                        db.text(
                            'ALTER TABLE benefits ADD COLUMN fap_contestation_topics_json TEXT'
                        )
                    )

            transaction.commit()
            print('Migracao concluida com sucesso.')
        except Exception as exc:
            transaction.rollback()
            print(f'Erro durante a migracao: {exc}')
            raise


if __name__ == '__main__':
    add_missing_column()
