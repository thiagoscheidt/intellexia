"""
Script para criar a tabela fap_web_contestacao_change_history.

Armazena histórico de mudanças detectadas durante a sincronização de
contestações FAP (ex.: mudança de situacao/instancia/protocolo).

Uso:
    uv run python database/add_fap_web_contestacao_change_history_table.py
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
            if _table_exists(connection, "fap_web_contestacao_change_history", is_mysql):
                print("- tabela ja existe: fap_web_contestacao_change_history")
            else:
                print("+ criando tabela: fap_web_contestacao_change_history")

                if is_mysql:
                    connection.execute(
                        db.text(
                            """
                            CREATE TABLE fap_web_contestacao_change_history (
                                id INT AUTO_INCREMENT PRIMARY KEY,
                                law_firm_id INT NOT NULL,
                                contestacao_db_id INT NOT NULL,
                                contestacao_id INT NOT NULL,
                                cnpj VARCHAR(20) NOT NULL,
                                cnpj_raiz VARCHAR(10) NOT NULL,
                                ano_vigencia INT NOT NULL,
                                change_type VARCHAR(30) NOT NULL DEFAULT 'updated',
                                changed_fields LONGTEXT NULL,
                                old_values LONGTEXT NULL,
                                new_values LONGTEXT NULL,
                                synced_at DATETIME NOT NULL,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                                CONSTRAINT fk_fwcch_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                                CONSTRAINT fk_fwcch_contestacao FOREIGN KEY (contestacao_db_id) REFERENCES fap_web_contestacoes(id) ON DELETE CASCADE
                            )
                            """
                        )
                    )
                else:
                    connection.execute(
                        db.text(
                            """
                            CREATE TABLE fap_web_contestacao_change_history (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                law_firm_id INTEGER NOT NULL,
                                contestacao_db_id INTEGER NOT NULL,
                                contestacao_id INTEGER NOT NULL,
                                cnpj VARCHAR(20) NOT NULL,
                                cnpj_raiz VARCHAR(10) NOT NULL,
                                ano_vigencia INTEGER NOT NULL,
                                change_type VARCHAR(30) NOT NULL DEFAULT 'updated',
                                changed_fields TEXT,
                                old_values TEXT,
                                new_values TEXT,
                                synced_at DATETIME NOT NULL,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME,
                                FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                                FOREIGN KEY (contestacao_db_id) REFERENCES fap_web_contestacoes(id) ON DELETE CASCADE
                            )
                            """
                        )
                    )

            if is_mysql:
                existing_indexes = {
                    row[2] for row in connection.execute(
                        db.text("SHOW INDEX FROM fap_web_contestacao_change_history")
                    ).fetchall()
                }
                index_ddls = {
                    "ix_fwcch_law_firm_id": "CREATE INDEX ix_fwcch_law_firm_id ON fap_web_contestacao_change_history (law_firm_id)",
                    "ix_fwcch_contestacao_db_id": "CREATE INDEX ix_fwcch_contestacao_db_id ON fap_web_contestacao_change_history (contestacao_db_id)",
                    "ix_fwcch_contestacao_id": "CREATE INDEX ix_fwcch_contestacao_id ON fap_web_contestacao_change_history (contestacao_id)",
                    "ix_fwcch_cnpj": "CREATE INDEX ix_fwcch_cnpj ON fap_web_contestacao_change_history (cnpj)",
                    "ix_fwcch_cnpj_raiz": "CREATE INDEX ix_fwcch_cnpj_raiz ON fap_web_contestacao_change_history (cnpj_raiz)",
                    "ix_fwcch_ano_vigencia": "CREATE INDEX ix_fwcch_ano_vigencia ON fap_web_contestacao_change_history (ano_vigencia)",
                    "ix_fwcch_change_type": "CREATE INDEX ix_fwcch_change_type ON fap_web_contestacao_change_history (change_type)",
                    "ix_fwcch_synced_at": "CREATE INDEX ix_fwcch_synced_at ON fap_web_contestacao_change_history (synced_at)",
                    "ix_fwcch_created_at": "CREATE INDEX ix_fwcch_created_at ON fap_web_contestacao_change_history (created_at)",
                }
                for index_name, ddl in index_ddls.items():
                    if index_name in existing_indexes:
                        continue
                    connection.execute(db.text(ddl))
            else:
                connection.execute(db.text("CREATE INDEX IF NOT EXISTS ix_fwcch_law_firm_id ON fap_web_contestacao_change_history (law_firm_id)"))
                connection.execute(db.text("CREATE INDEX IF NOT EXISTS ix_fwcch_contestacao_db_id ON fap_web_contestacao_change_history (contestacao_db_id)"))
                connection.execute(db.text("CREATE INDEX IF NOT EXISTS ix_fwcch_contestacao_id ON fap_web_contestacao_change_history (contestacao_id)"))
                connection.execute(db.text("CREATE INDEX IF NOT EXISTS ix_fwcch_cnpj ON fap_web_contestacao_change_history (cnpj)"))
                connection.execute(db.text("CREATE INDEX IF NOT EXISTS ix_fwcch_cnpj_raiz ON fap_web_contestacao_change_history (cnpj_raiz)"))
                connection.execute(db.text("CREATE INDEX IF NOT EXISTS ix_fwcch_ano_vigencia ON fap_web_contestacao_change_history (ano_vigencia)"))
                connection.execute(db.text("CREATE INDEX IF NOT EXISTS ix_fwcch_change_type ON fap_web_contestacao_change_history (change_type)"))
                connection.execute(db.text("CREATE INDEX IF NOT EXISTS ix_fwcch_synced_at ON fap_web_contestacao_change_history (synced_at)"))
                connection.execute(db.text("CREATE INDEX IF NOT EXISTS ix_fwcch_created_at ON fap_web_contestacao_change_history (created_at)"))

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
