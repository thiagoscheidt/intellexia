"""
Script para criar a tabela benefit_manual_history.

Armazena o histórico manual de alterações de benefícios executadas por usuários,
incluindo a ação em lote de marcar 1ª instância como deferido.

Uso:
    uv run python database/add_benefit_manual_history_table.py
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
            if _table_exists(connection, "benefit_manual_history", is_mysql):
                print("- tabela ja existe: benefit_manual_history")
            else:
                print("+ criando tabela: benefit_manual_history")

                if is_mysql:
                    connection.execute(
                        db.text(
                            """
                            CREATE TABLE benefit_manual_history (
                                id INT AUTO_INCREMENT PRIMARY KEY,
                                law_firm_id INT NOT NULL,
                                benefit_id INT NOT NULL,
                                vigencia_id INT NULL,
                                performed_by_user_id INT NULL,
                                action VARCHAR(60) NOT NULL DEFAULT 'mark_first_instance_deferred',
                                old_first_instance_status VARCHAR(30) NULL,
                                new_first_instance_status VARCHAR(30) NOT NULL,
                                notes LONGTEXT NULL,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                                CONSTRAINT fk_bmh_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                                CONSTRAINT fk_bmh_benefit FOREIGN KEY (benefit_id) REFERENCES benefits(id),
                                CONSTRAINT fk_bmh_vigencia FOREIGN KEY (vigencia_id) REFERENCES benefit_fap_vigencia_cnpjs(id),
                                CONSTRAINT fk_bmh_user FOREIGN KEY (performed_by_user_id) REFERENCES users(id)
                            )
                            """
                        )
                    )
                else:
                    connection.execute(
                        db.text(
                            """
                            CREATE TABLE benefit_manual_history (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                law_firm_id INTEGER NOT NULL,
                                benefit_id INTEGER NOT NULL,
                                vigencia_id INTEGER,
                                performed_by_user_id INTEGER,
                                action VARCHAR(60) NOT NULL DEFAULT 'mark_first_instance_deferred',
                                old_first_instance_status VARCHAR(30),
                                new_first_instance_status VARCHAR(30) NOT NULL,
                                notes TEXT,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME,
                                FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                                FOREIGN KEY (benefit_id) REFERENCES benefits(id),
                                FOREIGN KEY (vigencia_id) REFERENCES benefit_fap_vigencia_cnpjs(id),
                                FOREIGN KEY (performed_by_user_id) REFERENCES users(id)
                            )
                            """
                        )
                    )

            if is_mysql:
                existing_indexes = {
                    row[2] for row in connection.execute(db.text("SHOW INDEX FROM benefit_manual_history")).fetchall()
                }
                index_ddls = {
                    "ix_bmh_law_firm_id": "CREATE INDEX ix_bmh_law_firm_id ON benefit_manual_history (law_firm_id)",
                    "ix_bmh_benefit_id": "CREATE INDEX ix_bmh_benefit_id ON benefit_manual_history (benefit_id)",
                    "ix_bmh_vigencia_id": "CREATE INDEX ix_bmh_vigencia_id ON benefit_manual_history (vigencia_id)",
                    "ix_bmh_performed_by_user_id": "CREATE INDEX ix_bmh_performed_by_user_id ON benefit_manual_history (performed_by_user_id)",
                    "ix_bmh_action": "CREATE INDEX ix_bmh_action ON benefit_manual_history (action)",
                    "ix_bmh_old_first_instance_status": "CREATE INDEX ix_bmh_old_first_instance_status ON benefit_manual_history (old_first_instance_status)",
                    "ix_bmh_new_first_instance_status": "CREATE INDEX ix_bmh_new_first_instance_status ON benefit_manual_history (new_first_instance_status)",
                    "ix_bmh_created_at": "CREATE INDEX ix_bmh_created_at ON benefit_manual_history (created_at)",
                }

                for index_name, ddl in index_ddls.items():
                    if index_name in existing_indexes:
                        continue
                    connection.execute(db.text(ddl))
            else:
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bmh_law_firm_id ON benefit_manual_history (law_firm_id)")
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bmh_benefit_id ON benefit_manual_history (benefit_id)")
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bmh_vigencia_id ON benefit_manual_history (vigencia_id)")
                )
                connection.execute(
                    db.text(
                        "CREATE INDEX IF NOT EXISTS ix_bmh_performed_by_user_id ON benefit_manual_history (performed_by_user_id)"
                    )
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bmh_action ON benefit_manual_history (action)")
                )
                connection.execute(
                    db.text(
                        "CREATE INDEX IF NOT EXISTS ix_bmh_old_first_instance_status ON benefit_manual_history (old_first_instance_status)"
                    )
                )
                connection.execute(
                    db.text(
                        "CREATE INDEX IF NOT EXISTS ix_bmh_new_first_instance_status ON benefit_manual_history (new_first_instance_status)"
                    )
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bmh_created_at ON benefit_manual_history (created_at)")
                )

            transaction.commit()
            print("+ migracao concluida")
        except Exception as exc:
            transaction.rollback()
            print(f"Erro na migracao: {exc}")
            raise
        finally:
            connection.close()


if __name__ == "__main__":
    add_table()
