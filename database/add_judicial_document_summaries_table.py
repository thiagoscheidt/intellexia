"""
Script para criar a tabela judicial_document_summaries.

Uso:
    uv run python database/add_judicial_document_summaries_table.py
"""

import sys
from pathlib import Path

from sqlalchemy import inspect, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import app
from app.models import db


TABLE_NAME = "judicial_document_summaries"


def _table_exists(inspector) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _index_exists_mysql(connection, index_name: str) -> bool:
    result = connection.execute(
        text(
            """
            SELECT 1
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND INDEX_NAME = :index_name
            LIMIT 1
            """
        ),
        {"table_name": TABLE_NAME, "index_name": index_name},
    )
    return result.first() is not None


def _index_exists_sqlite(connection, index_name: str) -> bool:
    result = connection.execute(text("PRAGMA index_list(judicial_document_summaries)"))
    return any(row[1] == index_name for row in result.fetchall())


def create_table() -> bool:
    with app.app_context():
        engine = db.engine
        inspector = inspect(engine)

        if _table_exists(inspector):
            print("Tabela judicial_document_summaries ja existe.")
            return False

        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        is_mysql = "mysql" in db_uri

        if is_mysql:
            create_sql = """
                CREATE TABLE judicial_document_summaries (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    judicial_document_id INT NOT NULL,
                    law_firm_id INT NOT NULL,
                    summary_text TEXT,
                    summary_payload JSON,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    processed_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_judicial_document_summaries_doc (judicial_document_id),
                    INDEX idx_judicial_document_summaries_law_firm_id (law_firm_id),
                    CONSTRAINT fk_judicial_document_summaries_doc
                        FOREIGN KEY (judicial_document_id) REFERENCES judicial_documents(id)
                        ON DELETE CASCADE,
                    CONSTRAINT fk_judicial_document_summaries_law_firm
                        FOREIGN KEY (law_firm_id) REFERENCES law_firms(id)
                        ON DELETE CASCADE
                )
            """
        else:
            create_sql = """
                CREATE TABLE judicial_document_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    judicial_document_id INTEGER NOT NULL,
                    law_firm_id INTEGER NOT NULL,
                    summary_text TEXT,
                    summary_payload TEXT,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    processed_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (judicial_document_id),
                    FOREIGN KEY (judicial_document_id) REFERENCES judicial_documents(id),
                    FOREIGN KEY (law_firm_id) REFERENCES law_firms(id)
                )
            """

        connection = engine.connect()
        transaction = connection.begin()
        try:
            connection.execute(text(create_sql))
            if not is_mysql:
                if not _index_exists_sqlite(connection, "idx_judicial_document_summaries_law_firm_id"):
                    connection.execute(
                        text(
                            "CREATE INDEX idx_judicial_document_summaries_law_firm_id ON judicial_document_summaries(law_firm_id)"
                        )
                    )
            else:
                if not _index_exists_mysql(connection, "idx_judicial_document_summaries_law_firm_id"):
                    connection.execute(
                        text(
                            "CREATE INDEX idx_judicial_document_summaries_law_firm_id ON judicial_document_summaries(law_firm_id)"
                        )
                    )
            transaction.commit()
            print("Tabela judicial_document_summaries criada com sucesso.")
            return True
        except Exception as exc:
            transaction.rollback()
            print(f"Erro ao criar tabela judicial_document_summaries: {exc}")
            raise
        finally:
            connection.close()


if __name__ == "__main__":
    created = create_table()
    raise SystemExit(0 if created else 0)
