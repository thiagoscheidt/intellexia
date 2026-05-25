"""
Script de migracao para criar a tabela relacional entre anexos e beneficios de processos judiciais.

Uso:
    uv run python database/add_judicial_process_attachment_benefits_table.py
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
        table_name = 'judicial_process_attachment_benefits'

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
                            attachment_id INTEGER NOT NULL,
                            benefit_id INTEGER NOT NULL,
                            created_at DATETIME NOT NULL,
                            CONSTRAINT uq_judicial_process_attachment_benefits UNIQUE (attachment_id, benefit_id),
                            CONSTRAINT fk_jpab_attachment FOREIGN KEY (attachment_id) REFERENCES judicial_process_attachments(id),
                            CONSTRAINT fk_jpab_benefit FOREIGN KEY (benefit_id) REFERENCES judicial_process_benefits(id)
                        )
                        """
                    )
                )
            else:
                print(f"- tabela ja existe: {table_name}")

            index_targets = [
                ('ix_judicial_process_attachment_benefits_attachment_id', 'attachment_id'),
                ('ix_judicial_process_attachment_benefits_benefit_id', 'benefit_id'),
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
