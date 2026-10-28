"""
Adiciona a coluna review_origin na tabela fap_review_executions:
- review_origin (VARCHAR 20): quem fez a revisão. Vazia = o IntellexIA (agente
  do escritório, no servidor); 'claude' = revisão feita no Claude do usuário,
  só conferida e gravada pelo IntellexIA. As revisões que já existem ficam
  vazias: todas rodaram no servidor.

Idempotente: não faz nada se a coluna já existir.

Uso:
    uv run python database/add_fap_review_executions_review_origin_column.py
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
        is_mysql = 'mysql' in app.config.get('SQLALCHEMY_DATABASE_URI', '')

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            existing = _get_existing_columns(connection, 'fap_review_executions', is_mysql)

            if 'review_origin' in existing:
                print('- coluna já existe: fap_review_executions.review_origin')
            else:
                print('+ adicionando coluna: fap_review_executions.review_origin')
                connection.execute(db.text(
                    'ALTER TABLE fap_review_executions ADD COLUMN review_origin VARCHAR(20)'))

            transaction.commit()
            print('Migração concluída com sucesso.')
        except Exception as exc:
            transaction.rollback()
            print(f'Erro durante a migração: {exc}')
            raise


if __name__ == '__main__':
    add_missing_column()
