"""
Script para adicionar colunas de análise de contestação da União na tabela judicial_process_benefits.

Uso:
    uv run python database/add_judicial_process_benefits_contestation_columns.py
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


def _mysql_has_index(connection, table_name: str, index_name: str) -> bool:
    result = connection.execute(db.text(f"SHOW INDEX FROM {table_name} WHERE Key_name = :index_name"), {
        'index_name': index_name,
    })
    return result.first() is not None


def add_missing_columns():
    with app.app_context():
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        is_mysql = 'mysql' in db_uri

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            table_name = 'judicial_process_benefits'
            existing = _get_existing_columns(connection, table_name, is_mysql)

            statements = {
                'contestation_decision': (
                    f"ALTER TABLE {table_name} ADD COLUMN contestation_decision TEXT"
                ),
                'contestation_status': (
                    f"ALTER TABLE {table_name} ADD COLUMN contestation_status VARCHAR(40)"
                ),
                'contestation_status_label': (
                    f"ALTER TABLE {table_name} ADD COLUMN contestation_status_label VARCHAR(120)"
                ),
                'contestation_fundamento_uniao': (
                    f"ALTER TABLE {table_name} ADD COLUMN contestation_fundamento_uniao TEXT"
                ),
                'contestation_efeito_fap': (
                    f"ALTER TABLE {table_name} ADD COLUMN contestation_efeito_fap TEXT"
                ),
                'contestation_trecho_detectado': (
                    f"ALTER TABLE {table_name} ADD COLUMN contestation_trecho_detectado TEXT"
                ),
                'contestation_trecho_completo': (
                    f"ALTER TABLE {table_name} ADD COLUMN contestation_trecho_completo TEXT"
                ),
                'contestation_resultado_tecnico_json': (
                    f"ALTER TABLE {table_name} ADD COLUMN contestation_resultado_tecnico_json TEXT"
                ),
            }

            for column_name, ddl in statements.items():
                if column_name in existing:
                    print(f"- coluna ja existe: {column_name}")
                    continue
                print(f"+ adicionando coluna: {column_name}")
                connection.execute(db.text(ddl))

            index_name = 'ix_jpb_contestation_status'
            if is_mysql:
                if _mysql_has_index(connection, table_name, index_name):
                    print(f"- indice ja existe: {index_name}")
                else:
                    print(f"+ criando indice: {index_name}")
                    connection.execute(
                        db.text(
                            f"CREATE INDEX {index_name} ON {table_name} (contestation_status)"
                        )
                    )
            else:
                print(f"+ garantindo indice: {index_name}")
                connection.execute(
                    db.text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} (contestation_status)"
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
    add_missing_columns()
