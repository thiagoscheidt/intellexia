"""
Script para criar as tabelas de histórico de CATs.

- fap_contestation_cat_source_history: histórico de arquivos FAP que adicionaram/alteraram CATs
- fap_contestation_cat_manual_history: histórico de edições manuais de CATs realizadas por usuários

Uso:
    uv run python database/add_cat_history_tables.py
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


def add_tables():
    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        is_mysql = "mysql" in db_uri

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            # ── fap_contestation_cat_source_history ──────────────────────────────
            if _table_exists(connection, "fap_contestation_cat_source_history", is_mysql):
                print("- tabela já existe: fap_contestation_cat_source_history")
            else:
                print("+ criando tabela: fap_contestation_cat_source_history")

                if is_mysql:
                    connection.execute(
                        db.text(
                            """
                            CREATE TABLE fap_contestation_cat_source_history (
                                id INT AUTO_INCREMENT PRIMARY KEY,
                                law_firm_id INT NOT NULL,
                                cat_id INT NOT NULL,
                                report_id INT NOT NULL,
                                knowledge_base_id INT NULL,
                                action VARCHAR(20) NOT NULL DEFAULT 'updated',
                                transmission_datetime DATETIME NULL,
                                publication_datetime DATETIME NULL,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                                CONSTRAINT uq_fccsh_cat_report UNIQUE (cat_id, report_id),
                                CONSTRAINT fk_fccsh_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                                CONSTRAINT fk_fccsh_cat FOREIGN KEY (cat_id) REFERENCES fap_contestation_cats(id),
                                CONSTRAINT fk_fccsh_report FOREIGN KEY (report_id) REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
                                CONSTRAINT fk_fccsh_kb FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(id)
                            )
                            """
                        )
                    )
                else:
                    connection.execute(
                        db.text(
                            """
                            CREATE TABLE fap_contestation_cat_source_history (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                law_firm_id INTEGER NOT NULL,
                                cat_id INTEGER NOT NULL,
                                report_id INTEGER NOT NULL,
                                knowledge_base_id INTEGER,
                                action VARCHAR(20) NOT NULL DEFAULT 'updated',
                                transmission_datetime DATETIME,
                                publication_datetime DATETIME,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME,
                                CONSTRAINT uq_fccsh_cat_report UNIQUE (cat_id, report_id),
                                FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                                FOREIGN KEY (cat_id) REFERENCES fap_contestation_cats(id),
                                FOREIGN KEY (report_id) REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
                                FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(id)
                            )
                            """
                        )
                    )

            if is_mysql:
                existing = {
                    row[2]
                    for row in connection.execute(
                        db.text("SHOW INDEX FROM fap_contestation_cat_source_history")
                    ).fetchall()
                }
                for name, ddl in {
                    "ix_fccsh_law_firm_id": "CREATE INDEX ix_fccsh_law_firm_id ON fap_contestation_cat_source_history (law_firm_id)",
                    "ix_fccsh_cat_id": "CREATE INDEX ix_fccsh_cat_id ON fap_contestation_cat_source_history (cat_id)",
                    "ix_fccsh_report_id": "CREATE INDEX ix_fccsh_report_id ON fap_contestation_cat_source_history (report_id)",
                    "ix_fccsh_knowledge_base_id": "CREATE INDEX ix_fccsh_knowledge_base_id ON fap_contestation_cat_source_history (knowledge_base_id)",
                    "ix_fccsh_action": "CREATE INDEX ix_fccsh_action ON fap_contestation_cat_source_history (action)",
                    "ix_fccsh_transmission_datetime": "CREATE INDEX ix_fccsh_transmission_datetime ON fap_contestation_cat_source_history (transmission_datetime)",
                    "ix_fccsh_publication_datetime": "CREATE INDEX ix_fccsh_publication_datetime ON fap_contestation_cat_source_history (publication_datetime)",
                    "ix_fccsh_created_at": "CREATE INDEX ix_fccsh_created_at ON fap_contestation_cat_source_history (created_at)",
                }.items():
                    if name not in existing:
                        connection.execute(db.text(ddl))
            else:
                for ddl in [
                    "CREATE INDEX IF NOT EXISTS ix_fccsh_law_firm_id ON fap_contestation_cat_source_history (law_firm_id)",
                    "CREATE INDEX IF NOT EXISTS ix_fccsh_cat_id ON fap_contestation_cat_source_history (cat_id)",
                    "CREATE INDEX IF NOT EXISTS ix_fccsh_report_id ON fap_contestation_cat_source_history (report_id)",
                    "CREATE INDEX IF NOT EXISTS ix_fccsh_knowledge_base_id ON fap_contestation_cat_source_history (knowledge_base_id)",
                    "CREATE INDEX IF NOT EXISTS ix_fccsh_action ON fap_contestation_cat_source_history (action)",
                    "CREATE INDEX IF NOT EXISTS ix_fccsh_transmission_datetime ON fap_contestation_cat_source_history (transmission_datetime)",
                    "CREATE INDEX IF NOT EXISTS ix_fccsh_publication_datetime ON fap_contestation_cat_source_history (publication_datetime)",
                    "CREATE INDEX IF NOT EXISTS ix_fccsh_created_at ON fap_contestation_cat_source_history (created_at)",
                ]:
                    connection.execute(db.text(ddl))

            # ── fap_contestation_cat_manual_history ──────────────────────────────
            if _table_exists(connection, "fap_contestation_cat_manual_history", is_mysql):
                print("- tabela já existe: fap_contestation_cat_manual_history")
            else:
                print("+ criando tabela: fap_contestation_cat_manual_history")

                if is_mysql:
                    connection.execute(
                        db.text(
                            """
                            CREATE TABLE fap_contestation_cat_manual_history (
                                id INT AUTO_INCREMENT PRIMARY KEY,
                                law_firm_id INT NOT NULL,
                                cat_id INT NOT NULL,
                                performed_by_user_id INT NULL,
                                action VARCHAR(60) NOT NULL DEFAULT 'edit_cat_first_instance_status',
                                old_first_instance_status VARCHAR(30) NULL,
                                new_first_instance_status VARCHAR(30) NOT NULL,
                                notes TEXT NULL,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                                CONSTRAINT fk_fccmh_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                                CONSTRAINT fk_fccmh_cat FOREIGN KEY (cat_id) REFERENCES fap_contestation_cats(id),
                                CONSTRAINT fk_fccmh_user FOREIGN KEY (performed_by_user_id) REFERENCES users(id)
                            )
                            """
                        )
                    )
                else:
                    connection.execute(
                        db.text(
                            """
                            CREATE TABLE fap_contestation_cat_manual_history (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                law_firm_id INTEGER NOT NULL,
                                cat_id INTEGER NOT NULL,
                                performed_by_user_id INTEGER,
                                action VARCHAR(60) NOT NULL DEFAULT 'edit_cat_first_instance_status',
                                old_first_instance_status VARCHAR(30),
                                new_first_instance_status VARCHAR(30) NOT NULL,
                                notes TEXT,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME,
                                FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                                FOREIGN KEY (cat_id) REFERENCES fap_contestation_cats(id),
                                FOREIGN KEY (performed_by_user_id) REFERENCES users(id)
                            )
                            """
                        )
                    )

            if is_mysql:
                existing = {
                    row[2]
                    for row in connection.execute(
                        db.text("SHOW INDEX FROM fap_contestation_cat_manual_history")
                    ).fetchall()
                }
                for name, ddl in {
                    "ix_fccmh_law_firm_id": "CREATE INDEX ix_fccmh_law_firm_id ON fap_contestation_cat_manual_history (law_firm_id)",
                    "ix_fccmh_cat_id": "CREATE INDEX ix_fccmh_cat_id ON fap_contestation_cat_manual_history (cat_id)",
                    "ix_fccmh_performed_by_user_id": "CREATE INDEX ix_fccmh_performed_by_user_id ON fap_contestation_cat_manual_history (performed_by_user_id)",
                    "ix_fccmh_action": "CREATE INDEX ix_fccmh_action ON fap_contestation_cat_manual_history (action)",
                    "ix_fccmh_old_first_instance_status": "CREATE INDEX ix_fccmh_old_first_instance_status ON fap_contestation_cat_manual_history (old_first_instance_status)",
                    "ix_fccmh_new_first_instance_status": "CREATE INDEX ix_fccmh_new_first_instance_status ON fap_contestation_cat_manual_history (new_first_instance_status)",
                    "ix_fccmh_created_at": "CREATE INDEX ix_fccmh_created_at ON fap_contestation_cat_manual_history (created_at)",
                }.items():
                    if name not in existing:
                        connection.execute(db.text(ddl))
            else:
                for ddl in [
                    "CREATE INDEX IF NOT EXISTS ix_fccmh_law_firm_id ON fap_contestation_cat_manual_history (law_firm_id)",
                    "CREATE INDEX IF NOT EXISTS ix_fccmh_cat_id ON fap_contestation_cat_manual_history (cat_id)",
                    "CREATE INDEX IF NOT EXISTS ix_fccmh_performed_by_user_id ON fap_contestation_cat_manual_history (performed_by_user_id)",
                    "CREATE INDEX IF NOT EXISTS ix_fccmh_action ON fap_contestation_cat_manual_history (action)",
                    "CREATE INDEX IF NOT EXISTS ix_fccmh_old_first_instance_status ON fap_contestation_cat_manual_history (old_first_instance_status)",
                    "CREATE INDEX IF NOT EXISTS ix_fccmh_new_first_instance_status ON fap_contestation_cat_manual_history (new_first_instance_status)",
                    "CREATE INDEX IF NOT EXISTS ix_fccmh_created_at ON fap_contestation_cat_manual_history (created_at)",
                ]:
                    connection.execute(db.text(ddl))

            transaction.commit()
            print("✓ Migração concluída")
        except Exception as exc:
            transaction.rollback()
            print(f"Erro na migração: {exc}")
            raise
        finally:
            connection.close()


if __name__ == "__main__":
    add_tables()
