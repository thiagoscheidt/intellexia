"""
Adiciona a coluna ferramentas_ignoradas na tabela prompt_library_items:
- ferramentas_ignoradas (TEXT, JSON): ferramentas do conector citadas no texto
  do item que ele NÃO usa — desmarcadas no editor da Biblioteca de IA. NULL =
  automático (fica de fora a ferramenta citada só em frase de proibição).

Idempotente: não faz nada se a coluna já existir.

Uso:
    uv run python database/add_prompt_library_ferramentas_ignoradas_column.py
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
            existing = _get_existing_columns(connection, 'prompt_library_items', is_mysql)

            if 'ferramentas_ignoradas' in existing:
                print('- coluna já existe: prompt_library_items.ferramentas_ignoradas')
            else:
                print('+ adicionando coluna: prompt_library_items.ferramentas_ignoradas')
                connection.execute(db.text('ALTER TABLE prompt_library_items ADD COLUMN ferramentas_ignoradas TEXT'))

            transaction.commit()
            print('Migração concluída com sucesso.')
        except Exception as exc:
            transaction.rollback()
            print(f'Erro durante a migração: {exc}')
            raise


if __name__ == '__main__':
    add_missing_column()
