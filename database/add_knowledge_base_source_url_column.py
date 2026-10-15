"""
Adiciona a coluna source_url na tabela knowledge_base:
- source_url (VARCHAR 500): endereço do arquivo original (ex.: o PDF protocolado
  no Google Drive), para o usuário abrir o documento oficial a partir do .md
  guardado na base.

Idempotente: não faz nada se a coluna já existir.

Uso:
    uv run python database/add_knowledge_base_source_url_column.py
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
            existing = _get_existing_columns(connection, 'knowledge_base', is_mysql)

            if 'source_url' in existing:
                print('- coluna já existe: knowledge_base.source_url')
            else:
                print('+ adicionando coluna: knowledge_base.source_url')
                connection.execute(db.text('ALTER TABLE knowledge_base ADD COLUMN source_url VARCHAR(500)'))

            transaction.commit()
            print('Migração concluída com sucesso.')
        except Exception as exc:
            transaction.rollback()
            print(f'Erro durante a migração: {exc}')
            raise


if __name__ == '__main__':
    add_missing_column()
