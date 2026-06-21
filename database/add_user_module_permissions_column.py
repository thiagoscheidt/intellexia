"""
Script para adicionar coluna de permissoes por modulo na tabela users:
- module_permissions (JSON serializado em texto)

Uso:
    uv run python database/add_user_module_permissions_column.py
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
            existing = _get_existing_columns(connection, 'users', is_mysql)

            if 'module_permissions' in existing:
                print('- coluna ja existe: module_permissions')
            else:
                print('+ adicionando coluna: module_permissions')
                if is_mysql:
                    connection.execute(
                        db.text('ALTER TABLE users ADD COLUMN module_permissions LONGTEXT')
                    )
                else:
                    connection.execute(
                        db.text('ALTER TABLE users ADD COLUMN module_permissions TEXT')
                    )

            transaction.commit()
            print('Migracao concluida com sucesso.')
        except Exception as exc:
            transaction.rollback()
            print(f'Erro durante a migracao: {exc}')
            raise


if __name__ == '__main__':
    add_missing_column()
