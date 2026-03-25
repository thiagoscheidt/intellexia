"""
Script para criar a tabela benefit_fap_source_history.

Armazena o histórico de arquivos de relatório FAP que adicionaram/alteraram benefícios,
com referência ao report_id e data de transmissão extraída da primeira página.

Uso:
    uv run python database/add_benefit_fap_source_history_table.py
"""

import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db
from main import app


def _table_exists(connection, table_name: str, is_mysql: bool) -> bool:
    if is_mysql:
        result = connection.execute(db.text("SHOW TABLES LIKE :table_name"), {"table_name": table_name})
        return result.fetchone() is not None

    result = connection.execute(
        db.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
        {"table_name": table_name},
    )
    return result.fetchone() is not None


def add_table():
    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        is_mysql = "mysql" in db_uri

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            if _table_exists(connection, "benefit_fap_source_history", is_mysql):
                print("- tabela já existe: benefit_fap_source_history")
            else:
                print("+ criando tabela: benefit_fap_source_history")

                if is_mysql:
                    connection.execute(
                        db.text(
                            """
                            CREATE TABLE benefit_fap_source_history (
                                id INT AUTO_INCREMENT PRIMARY KEY,
                                law_firm_id INT NOT NULL,
                                benefit_id INT NOT NULL,
                                report_id INT NOT NULL,
                                knowledge_base_id INT NULL,
                                action VARCHAR(20) NOT NULL DEFAULT 'updated',
                                transmission_datetime DATETIME NULL,
                                publication_datetime DATETIME NULL,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                                CONSTRAINT uq_bfsh_benefit_report UNIQUE (benefit_id, report_id),
                                CONSTRAINT fk_bfsh_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                                CONSTRAINT fk_bfsh_benefit FOREIGN KEY (benefit_id) REFERENCES benefits(id),
                                CONSTRAINT fk_bfsh_report FOREIGN KEY (report_id) REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
                                CONSTRAINT fk_bfsh_kb FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(id)
                            )
                            """
                        )
                    )
                else:
                    connection.execute(
                        db.text(
                            """
                            CREATE TABLE benefit_fap_source_history (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                law_firm_id INTEGER NOT NULL,
                                benefit_id INTEGER NOT NULL,
                                report_id INTEGER NOT NULL,
                                knowledge_base_id INTEGER,
                                action VARCHAR(20) NOT NULL DEFAULT 'updated',
                                transmission_datetime DATETIME,
                                publication_datetime DATETIME,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME,
                                CONSTRAINT uq_bfsh_benefit_report UNIQUE (benefit_id, report_id),
                                FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                                FOREIGN KEY (benefit_id) REFERENCES benefits(id),
                                FOREIGN KEY (report_id) REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
                                FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(id)
                            )
                            """
                        )
                    )

            if is_mysql:
                existing_indexes = {
                    row[2] for row in connection.execute(db.text("SHOW INDEX FROM benefit_fap_source_history")).fetchall()
                }
                index_ddls = {
                    "ix_bfsh_law_firm_id": "CREATE INDEX ix_bfsh_law_firm_id ON benefit_fap_source_history (law_firm_id)",
                    "ix_bfsh_benefit_id": "CREATE INDEX ix_bfsh_benefit_id ON benefit_fap_source_history (benefit_id)",
                    "ix_bfsh_report_id": "CREATE INDEX ix_bfsh_report_id ON benefit_fap_source_history (report_id)",
                    "ix_bfsh_knowledge_base_id": "CREATE INDEX ix_bfsh_knowledge_base_id ON benefit_fap_source_history (knowledge_base_id)",
                    "ix_bfsh_action": "CREATE INDEX ix_bfsh_action ON benefit_fap_source_history (action)",
                    "ix_bfsh_transmission_datetime": "CREATE INDEX ix_bfsh_transmission_datetime ON benefit_fap_source_history (transmission_datetime)",
                    "ix_bfsh_publication_datetime": "CREATE INDEX ix_bfsh_publication_datetime ON benefit_fap_source_history (publication_datetime)",
                    "ix_bfsh_created_at": "CREATE INDEX ix_bfsh_created_at ON benefit_fap_source_history (created_at)",
                }

                for index_name, ddl in index_ddls.items():
                    if index_name in existing_indexes:
                        continue
                    connection.execute(db.text(ddl))
            else:
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bfsh_law_firm_id ON benefit_fap_source_history (law_firm_id)")
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bfsh_benefit_id ON benefit_fap_source_history (benefit_id)")
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bfsh_report_id ON benefit_fap_source_history (report_id)")
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bfsh_knowledge_base_id ON benefit_fap_source_history (knowledge_base_id)")
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bfsh_action ON benefit_fap_source_history (action)")
                )
                connection.execute(
                    db.text(
                        "CREATE INDEX IF NOT EXISTS ix_bfsh_transmission_datetime ON benefit_fap_source_history (transmission_datetime)"
                    )
                )
                connection.execute(
                    db.text(
                        "CREATE INDEX IF NOT EXISTS ix_bfsh_publication_datetime ON benefit_fap_source_history (publication_datetime)"
                    )
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bfsh_created_at ON benefit_fap_source_history (created_at)")
                )

            transaction.commit()
            print("✓ Migração concluída")
        except Exception as exc:
            transaction.rollback()
            print(f"Erro na migração: {exc}")
            raise
        finally:
            connection.close()


if __name__ == "__main__":
    add_table()
