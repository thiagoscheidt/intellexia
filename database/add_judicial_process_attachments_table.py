"""
Script de migracao para criar a tabela de anexos auxiliares de processos judiciais.

Uso:
    uv run python database/add_judicial_process_attachments_table.py
"""

import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db
from main import app


def _table_exists(connection, table_name: str, is_mysql: bool = False) -> bool:
    if is_mysql:
        result = connection.execute(
            db.text(
                """
                SELECT 1
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = :table_name
                LIMIT 1
                """
            ),
            {"table_name": table_name},
        )
        return result.first() is not None

    result = connection.execute(
        db.text(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    )
    return result.first() is not None


def _mysql_has_index(connection, table_name: str, index_name: str) -> bool:
    result = connection.execute(
        db.text("SHOW INDEX FROM " + table_name + " WHERE Key_name = :index_name"),
        {"index_name": index_name},
    )
    return result.first() is not None


def migrate() -> None:
    with app.app_context():
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        is_mysql = 'mysql' in db_uri
        table_name = 'judicial_process_attachments'

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            if not _table_exists(connection, table_name, is_mysql=is_mysql):
                print(f"+ criando tabela: {table_name}")
                connection.execute(
                    db.text(
                        f"""
                        CREATE TABLE {table_name} (
                            id INTEGER PRIMARY KEY {'AUTO_INCREMENT' if is_mysql else ''},
                            law_firm_id INTEGER NOT NULL,
                            process_id INTEGER NOT NULL,
                            uploaded_by_user_id INTEGER NOT NULL,
                            original_filename VARCHAR(255) NOT NULL,
                            file_path VARCHAR(500) NOT NULL,
                            file_size INTEGER NULL,
                            file_type VARCHAR(50) NULL,
                            description TEXT NULL,
                            is_active BOOLEAN NOT NULL DEFAULT 1,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NULL,
                            CONSTRAINT fk_jpa_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                            CONSTRAINT fk_jpa_process FOREIGN KEY (process_id) REFERENCES judicial_processes(id),
                            CONSTRAINT fk_jpa_user FOREIGN KEY (uploaded_by_user_id) REFERENCES users(id)
                        )
                        """
                    )
                )
            else:
                print(f"- tabela ja existe: {table_name}")

            index_targets = [
                ('ix_judicial_process_attachments_law_firm_id', 'law_firm_id'),
                ('ix_judicial_process_attachments_process_id', 'process_id'),
                ('ix_judicial_process_attachments_uploaded_by_user_id', 'uploaded_by_user_id'),
                ('ix_judicial_process_attachments_is_active', 'is_active'),
                ('ix_judicial_process_attachments_created_at', 'created_at'),
                ('ix_jpa_process_created_at', 'process_id, created_at'),
            ]

            for index_name, column_name in index_targets:
                if is_mysql:
                    if _mysql_has_index(connection, table_name, index_name):
                        print(f"- indice ja existe: {index_name}")
                    else:
                        print(f"+ criando indice: {index_name}")
                        connection.execute(
                            db.text(f"CREATE INDEX {index_name} ON {table_name} ({column_name})")
                        )
                else:
                    print(f"+ garantindo indice: {index_name}")
                    connection.execute(
                        db.text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})")
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
    migrate()
