"""
Script para criar as tabelas de Número Médio de Vínculos no sistema de contestação FAP.

Tabelas criadas:
- fap_contestation_employment_links
- fap_contestation_employment_link_source_history
- fap_contestation_employment_link_manual_history

Uso:
    uv run python database/add_employment_link_tables.py
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


def migrate():
    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        is_mysql = "mysql" in db_uri

        connection = db.engine.connect()
        transaction = connection.begin()

        try:
            # ----------------------------------------------------------------
            # Tabela principal: fap_contestation_employment_links
            # ----------------------------------------------------------------
            if not _table_exists(connection, "fap_contestation_employment_links", is_mysql):
                print("+ criando tabela: fap_contestation_employment_links")
                if is_mysql:
                    connection.execute(db.text("""
                        CREATE TABLE fap_contestation_employment_links (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            law_firm_id INT NOT NULL,
                            report_id INT NOT NULL,
                            vigencia_id INT NULL,
                            vigencia_year VARCHAR(10) NULL,
                            employer_cnpj VARCHAR(20) NOT NULL,
                            employer_name VARCHAR(255) NULL,
                            competence VARCHAR(10) NOT NULL,
                            quantity INT NULL,
                            first_instance_requested_quantity INT NULL,
                            second_instance_requested_quantity INT NULL,
                            first_instance_status VARCHAR(30) NULL,
                            first_instance_status_raw VARCHAR(255) NULL,
                            first_instance_justification TEXT NULL,
                            first_instance_opinion TEXT NULL,
                            second_instance_status VARCHAR(30) NULL,
                            second_instance_status_raw VARCHAR(255) NULL,
                            second_instance_justification TEXT NULL,
                            second_instance_opinion TEXT NULL,
                            status VARCHAR(30) NOT NULL DEFAULT 'pending',
                            justification TEXT NULL,
                            opinion TEXT NULL,
                            notes TEXT NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            CONSTRAINT uq_employment_link_law_firm_report_cnpj_competence
                                UNIQUE (law_firm_id, report_id, employer_cnpj, competence),
                            CONSTRAINT fk_el_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                            CONSTRAINT fk_el_report FOREIGN KEY (report_id)
                                REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
                            CONSTRAINT fk_el_vigencia FOREIGN KEY (vigencia_id)
                                REFERENCES fap_vigencia_cnpjs(id)
                        )
                    """))
                else:
                    connection.execute(db.text("""
                        CREATE TABLE fap_contestation_employment_links (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            law_firm_id INTEGER NOT NULL,
                            report_id INTEGER NOT NULL,
                            vigencia_id INTEGER NULL,
                            vigencia_year VARCHAR(10) NULL,
                            employer_cnpj VARCHAR(20) NOT NULL,
                            employer_name VARCHAR(255) NULL,
                            competence VARCHAR(10) NOT NULL,
                            quantity INTEGER NULL,
                            first_instance_requested_quantity INTEGER NULL,
                            second_instance_requested_quantity INTEGER NULL,
                            first_instance_status VARCHAR(30) NULL,
                            first_instance_status_raw VARCHAR(255) NULL,
                            first_instance_justification TEXT NULL,
                            first_instance_opinion TEXT NULL,
                            second_instance_status VARCHAR(30) NULL,
                            second_instance_status_raw VARCHAR(255) NULL,
                            second_instance_justification TEXT NULL,
                            second_instance_opinion TEXT NULL,
                            status VARCHAR(30) NOT NULL DEFAULT 'pending',
                            justification TEXT NULL,
                            opinion TEXT NULL,
                            notes TEXT NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NULL,
                            CONSTRAINT uq_employment_link_law_firm_report_cnpj_competence
                                UNIQUE (law_firm_id, report_id, employer_cnpj, competence),
                            FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                            FOREIGN KEY (report_id)
                                REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
                            FOREIGN KEY (vigencia_id) REFERENCES fap_vigencia_cnpjs(id)
                        )
                    """))
            else:
                print("= tabela fap_contestation_employment_links já existe, pulando.")

            # ----------------------------------------------------------------
            # Tabela de histórico de fonte (arquivo)
            # ----------------------------------------------------------------
            if not _table_exists(connection, "fap_contestation_employment_link_source_history", is_mysql):
                print("+ criando tabela: fap_contestation_employment_link_source_history")
                if is_mysql:
                    connection.execute(db.text("""
                        CREATE TABLE fap_contestation_employment_link_source_history (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            law_firm_id INT NOT NULL,
                            employment_link_id INT NOT NULL,
                            report_id INT NOT NULL,
                            knowledge_base_id INT NULL,
                            action VARCHAR(20) NOT NULL DEFAULT 'updated',
                            transmission_datetime DATETIME NULL,
                            publication_datetime DATETIME NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            CONSTRAINT uq_el_source_history_link_report
                                UNIQUE (employment_link_id, report_id),
                            CONSTRAINT fk_elsh_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                            CONSTRAINT fk_elsh_employment_link FOREIGN KEY (employment_link_id)
                                REFERENCES fap_contestation_employment_links(id),
                            CONSTRAINT fk_elsh_report FOREIGN KEY (report_id)
                                REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
                            CONSTRAINT fk_elsh_kb FOREIGN KEY (knowledge_base_id)
                                REFERENCES knowledge_base(id)
                        )
                    """))
                else:
                    connection.execute(db.text("""
                        CREATE TABLE fap_contestation_employment_link_source_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            law_firm_id INTEGER NOT NULL,
                            employment_link_id INTEGER NOT NULL,
                            report_id INTEGER NOT NULL,
                            knowledge_base_id INTEGER NULL,
                            action VARCHAR(20) NOT NULL DEFAULT 'updated',
                            transmission_datetime DATETIME NULL,
                            publication_datetime DATETIME NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NULL,
                            CONSTRAINT uq_el_source_history_link_report
                                UNIQUE (employment_link_id, report_id),
                            FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                            FOREIGN KEY (employment_link_id)
                                REFERENCES fap_contestation_employment_links(id),
                            FOREIGN KEY (report_id)
                                REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
                            FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(id)
                        )
                    """))
            else:
                print("= tabela fap_contestation_employment_link_source_history já existe, pulando.")

            # ----------------------------------------------------------------
            # Tabela de histórico de edições manuais
            # ----------------------------------------------------------------
            if not _table_exists(connection, "fap_contestation_employment_link_manual_history", is_mysql):
                print("+ criando tabela: fap_contestation_employment_link_manual_history")
                if is_mysql:
                    connection.execute(db.text("""
                        CREATE TABLE fap_contestation_employment_link_manual_history (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            law_firm_id INT NOT NULL,
                            employment_link_id INT NOT NULL,
                            performed_by_user_id INT NULL,
                            action VARCHAR(60) NOT NULL DEFAULT 'edit_employment_link_first_instance_status',
                            old_first_instance_status VARCHAR(30) NULL,
                            new_first_instance_status VARCHAR(30) NOT NULL,
                            notes TEXT NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            CONSTRAINT fk_elmh_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                            CONSTRAINT fk_elmh_employment_link FOREIGN KEY (employment_link_id)
                                REFERENCES fap_contestation_employment_links(id),
                            CONSTRAINT fk_elmh_user FOREIGN KEY (performed_by_user_id)
                                REFERENCES users(id)
                        )
                    """))
                else:
                    connection.execute(db.text("""
                        CREATE TABLE fap_contestation_employment_link_manual_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            law_firm_id INTEGER NOT NULL,
                            employment_link_id INTEGER NOT NULL,
                            performed_by_user_id INTEGER NULL,
                            action VARCHAR(60) NOT NULL DEFAULT 'edit_employment_link_first_instance_status',
                            old_first_instance_status VARCHAR(30) NULL,
                            new_first_instance_status VARCHAR(30) NOT NULL,
                            notes TEXT NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NULL,
                            FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                            FOREIGN KEY (employment_link_id)
                                REFERENCES fap_contestation_employment_links(id),
                            FOREIGN KEY (performed_by_user_id) REFERENCES users(id)
                        )
                    """))
            else:
                print("= tabela fap_contestation_employment_link_manual_history já existe, pulando.")

            transaction.commit()
            print("Migração concluída com sucesso.")

        except Exception as exc:
            transaction.rollback()
            print(f"Erro durante a migração: {exc}")
            raise
        finally:
            connection.close()


if __name__ == "__main__":
    migrate()
