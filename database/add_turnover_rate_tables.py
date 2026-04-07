"""
Script para criar as tabelas de Taxa Média de Rotatividade no sistema de contestação FAP.

Tabelas criadas:
- fap_contestation_turnover_rates
- fap_contestation_turnover_rate_source_history
- fap_contestation_turnover_rate_manual_history

Uso:
    uv run python database/add_turnover_rate_tables.py
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
            # Tabela principal: fap_contestation_turnover_rates
            # ----------------------------------------------------------------
            if not _table_exists(connection, "fap_contestation_turnover_rates", is_mysql):
                print("+ criando tabela: fap_contestation_turnover_rates")
                if is_mysql:
                    connection.execute(db.text("""
                        CREATE TABLE fap_contestation_turnover_rates (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            law_firm_id INT NOT NULL,
                            report_id INT NOT NULL,
                            vigencia_id INT NULL,
                            vigencia_year VARCHAR(10) NULL,
                            employer_cnpj VARCHAR(20) NOT NULL,
                            employer_name VARCHAR(255) NULL,
                            year VARCHAR(10) NOT NULL,
                            turnover_rate DECIMAL(10,4) NULL,
                            admissions INT NULL,
                            dismissals INT NULL,
                            initial_links_count INT NULL,
                            first_instance_requested_admissions INT NULL,
                            first_instance_requested_dismissals INT NULL,
                            first_instance_requested_initial_links INT NULL,
                            second_instance_requested_admissions INT NULL,
                            second_instance_requested_dismissals INT NULL,
                            second_instance_requested_initial_links INT NULL,
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
                            CONSTRAINT uq_turnover_rate_law_firm_report_cnpj_year
                                UNIQUE (law_firm_id, report_id, employer_cnpj, year),
                            CONSTRAINT fk_tr_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                            CONSTRAINT fk_tr_report FOREIGN KEY (report_id)
                                REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
                            CONSTRAINT fk_tr_vigencia FOREIGN KEY (vigencia_id)
                                REFERENCES fap_vigencia_cnpjs(id) ON DELETE SET NULL
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """))
                else:
                    connection.execute(db.text("""
                        CREATE TABLE fap_contestation_turnover_rates (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            law_firm_id INTEGER NOT NULL REFERENCES law_firms(id),
                            report_id INTEGER NOT NULL REFERENCES fap_contestation_judgment_reports(id),
                            vigencia_id INTEGER REFERENCES fap_vigencia_cnpjs(id),
                            vigencia_year VARCHAR(10),
                            employer_cnpj VARCHAR(20) NOT NULL,
                            employer_name VARCHAR(255),
                            year VARCHAR(10) NOT NULL,
                            turnover_rate DECIMAL(10,4),
                            admissions INTEGER,
                            dismissals INTEGER,
                            initial_links_count INTEGER,
                            first_instance_requested_admissions INTEGER,
                            first_instance_requested_dismissals INTEGER,
                            first_instance_requested_initial_links INTEGER,
                            second_instance_requested_admissions INTEGER,
                            second_instance_requested_dismissals INTEGER,
                            second_instance_requested_initial_links INTEGER,
                            first_instance_status VARCHAR(30),
                            first_instance_status_raw VARCHAR(255),
                            first_instance_justification TEXT,
                            first_instance_opinion TEXT,
                            second_instance_status VARCHAR(30),
                            second_instance_status_raw VARCHAR(255),
                            second_instance_justification TEXT,
                            second_instance_opinion TEXT,
                            status VARCHAR(30) NOT NULL DEFAULT 'pending',
                            justification TEXT,
                            opinion TEXT,
                            notes TEXT,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME,
                            UNIQUE (law_firm_id, report_id, employer_cnpj, year)
                        );
                    """))
            else:
                print("= tabela fap_contestation_turnover_rates já existe, pulando.")

            # ----------------------------------------------------------------
            # Tabela de histórico de fonte: fap_contestation_turnover_rate_source_history
            # ----------------------------------------------------------------
            if not _table_exists(connection, "fap_contestation_turnover_rate_source_history", is_mysql):
                print("+ criando tabela: fap_contestation_turnover_rate_source_history")
                if is_mysql:
                    connection.execute(db.text("""
                        CREATE TABLE fap_contestation_turnover_rate_source_history (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            law_firm_id INT NOT NULL,
                            turnover_rate_id INT NOT NULL,
                            report_id INT NOT NULL,
                            knowledge_base_id INT NULL,
                            action VARCHAR(20) NOT NULL DEFAULT 'updated',
                            transmission_datetime DATETIME NULL,
                            publication_datetime DATETIME NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            UNIQUE KEY uq_tr_source_history_rate_report (turnover_rate_id, report_id),
                            CONSTRAINT fk_tr_src_hist_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                            CONSTRAINT fk_tr_src_hist_rate FOREIGN KEY (turnover_rate_id)
                                REFERENCES fap_contestation_turnover_rates(id) ON DELETE CASCADE,
                            CONSTRAINT fk_tr_src_hist_report FOREIGN KEY (report_id)
                                REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
                            CONSTRAINT fk_tr_src_hist_kb FOREIGN KEY (knowledge_base_id)
                                REFERENCES knowledge_base(id) ON DELETE SET NULL
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """))
                else:
                    connection.execute(db.text("""
                        CREATE TABLE fap_contestation_turnover_rate_source_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            law_firm_id INTEGER NOT NULL REFERENCES law_firms(id),
                            turnover_rate_id INTEGER NOT NULL REFERENCES fap_contestation_turnover_rates(id),
                            report_id INTEGER NOT NULL REFERENCES fap_contestation_judgment_reports(id),
                            knowledge_base_id INTEGER REFERENCES knowledge_base(id),
                            action VARCHAR(20) NOT NULL DEFAULT 'updated',
                            transmission_datetime DATETIME,
                            publication_datetime DATETIME,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME,
                            UNIQUE (turnover_rate_id, report_id)
                        );
                    """))
            else:
                print("= tabela fap_contestation_turnover_rate_source_history já existe, pulando.")

            # ----------------------------------------------------------------
            # Tabela de histórico manual: fap_contestation_turnover_rate_manual_history
            # ----------------------------------------------------------------
            if not _table_exists(connection, "fap_contestation_turnover_rate_manual_history", is_mysql):
                print("+ criando tabela: fap_contestation_turnover_rate_manual_history")
                if is_mysql:
                    connection.execute(db.text("""
                        CREATE TABLE fap_contestation_turnover_rate_manual_history (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            law_firm_id INT NOT NULL,
                            turnover_rate_id INT NOT NULL,
                            performed_by_user_id INT NULL,
                            action VARCHAR(60) NOT NULL DEFAULT 'edit_turnover_rate_first_instance_status',
                            old_first_instance_status VARCHAR(30) NULL,
                            new_first_instance_status VARCHAR(30) NOT NULL,
                            notes TEXT NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            CONSTRAINT fk_tr_man_hist_law_firm FOREIGN KEY (law_firm_id) REFERENCES law_firms(id),
                            CONSTRAINT fk_tr_man_hist_rate FOREIGN KEY (turnover_rate_id)
                                REFERENCES fap_contestation_turnover_rates(id) ON DELETE CASCADE,
                            CONSTRAINT fk_tr_man_hist_user FOREIGN KEY (performed_by_user_id)
                                REFERENCES users(id) ON DELETE SET NULL
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """))
                else:
                    connection.execute(db.text("""
                        CREATE TABLE fap_contestation_turnover_rate_manual_history (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            law_firm_id INTEGER NOT NULL REFERENCES law_firms(id),
                            turnover_rate_id INTEGER NOT NULL REFERENCES fap_contestation_turnover_rates(id),
                            performed_by_user_id INTEGER REFERENCES users(id),
                            action VARCHAR(60) NOT NULL DEFAULT 'edit_turnover_rate_first_instance_status',
                            old_first_instance_status VARCHAR(30),
                            new_first_instance_status VARCHAR(30) NOT NULL,
                            notes TEXT,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME
                        );
                    """))
            else:
                print("= tabela fap_contestation_turnover_rate_manual_history já existe, pulando.")

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
