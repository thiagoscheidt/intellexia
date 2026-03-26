"""
Script para criar a tabela benefit_fap_vigencia_cnpjs e adicionar vínculo em benefits.

Regras:
- Uma vigência por CNPJ não pode se repetir por escritório (law_firm_id + employer_cnpj + vigencia_year).
- Uma vigência pode ter N benefícios (1:N).

Uso:
    uv run python database/add_benefit_fap_vigencia_cnpjs_table.py
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


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def migrate():
    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        is_mysql = "mysql" in db_uri

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            inspector = db.inspect(db.engine)

            if not _table_exists(connection, "benefit_fap_vigencia_cnpjs", is_mysql):
                print("+ criando tabela: benefit_fap_vigencia_cnpjs")
                if is_mysql:
                    connection.execute(
                        db.text(
                            """
                            CREATE TABLE benefit_fap_vigencia_cnpjs (
                                id INT AUTO_INCREMENT PRIMARY KEY,
                                law_firm_id INT NOT NULL,
                                employer_cnpj VARCHAR(20) NOT NULL,
                                vigencia_year VARCHAR(10) NOT NULL,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                                CONSTRAINT uq_bfvc_law_firm_cnpj_vigencia UNIQUE (law_firm_id, employer_cnpj, vigencia_year),
                                CONSTRAINT fk_bfvc_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id)
                            )
                            """
                        )
                    )
                else:
                    connection.execute(
                        db.text(
                            """
                            CREATE TABLE benefit_fap_vigencia_cnpjs (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                law_firm_id INTEGER NOT NULL,
                                employer_cnpj VARCHAR(20) NOT NULL,
                                vigencia_year VARCHAR(10) NOT NULL,
                                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at DATETIME,
                                CONSTRAINT uq_bfvc_law_firm_cnpj_vigencia UNIQUE (law_firm_id, employer_cnpj, vigencia_year),
                                FOREIGN KEY (law_firm_id) REFERENCES law_firms(id)
                            )
                            """
                        )
                    )
            else:
                print("- tabela já existe: benefit_fap_vigencia_cnpjs")

            if is_mysql:
                existing_indexes = {
                    row[2] for row in connection.execute(db.text("SHOW INDEX FROM benefit_fap_vigencia_cnpjs")).fetchall()
                }
                index_ddls = {
                    "ix_bfvc_law_firm_id": "CREATE INDEX ix_bfvc_law_firm_id ON benefit_fap_vigencia_cnpjs (law_firm_id)",
                    "ix_bfvc_employer_cnpj": "CREATE INDEX ix_bfvc_employer_cnpj ON benefit_fap_vigencia_cnpjs (employer_cnpj)",
                    "ix_bfvc_vigencia_year": "CREATE INDEX ix_bfvc_vigencia_year ON benefit_fap_vigencia_cnpjs (vigencia_year)",
                    "ix_bfvc_created_at": "CREATE INDEX ix_bfvc_created_at ON benefit_fap_vigencia_cnpjs (created_at)",
                }
                for index_name, ddl in index_ddls.items():
                    if index_name not in existing_indexes:
                        connection.execute(db.text(ddl))
            else:
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bfvc_law_firm_id ON benefit_fap_vigencia_cnpjs (law_firm_id)")
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bfvc_employer_cnpj ON benefit_fap_vigencia_cnpjs (employer_cnpj)")
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bfvc_vigencia_year ON benefit_fap_vigencia_cnpjs (vigencia_year)")
                )
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_bfvc_created_at ON benefit_fap_vigencia_cnpjs (created_at)")
                )

            if not _column_exists(inspector, "benefits", "fap_vigencia_cnpj_id"):
                print("+ adicionando coluna: benefits.fap_vigencia_cnpj_id")
                connection.execute(
                    db.text("ALTER TABLE benefits ADD COLUMN fap_vigencia_cnpj_id INTEGER NULL")
                )
            else:
                print("- coluna já existe: benefits.fap_vigencia_cnpj_id")

            if is_mysql:
                existing_benefits_indexes = {
                    row[2] for row in connection.execute(db.text("SHOW INDEX FROM benefits")).fetchall()
                }
                if "ix_benefits_fap_vigencia_cnpj_id" not in existing_benefits_indexes:
                    connection.execute(
                        db.text("CREATE INDEX ix_benefits_fap_vigencia_cnpj_id ON benefits (fap_vigencia_cnpj_id)")
                    )

                fk_exists = connection.execute(
                    db.text(
                        """
                        SELECT CONSTRAINT_NAME
                        FROM information_schema.KEY_COLUMN_USAGE
                        WHERE TABLE_SCHEMA = DATABASE()
                          AND TABLE_NAME = 'benefits'
                          AND COLUMN_NAME = 'fap_vigencia_cnpj_id'
                          AND REFERENCED_TABLE_NAME = 'benefit_fap_vigencia_cnpjs'
                        """
                    )
                ).fetchone()
                if not fk_exists:
                    connection.execute(
                        db.text(
                            """
                            ALTER TABLE benefits
                            ADD CONSTRAINT fk_benefits_fap_vigencia_cnpj
                            FOREIGN KEY (fap_vigencia_cnpj_id)
                            REFERENCES benefit_fap_vigencia_cnpjs(id)
                            """
                        )
                    )
            else:
                connection.execute(
                    db.text("CREATE INDEX IF NOT EXISTS ix_benefits_fap_vigencia_cnpj_id ON benefits (fap_vigencia_cnpj_id)")
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
    migrate()
