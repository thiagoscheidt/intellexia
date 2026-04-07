"""Migration: add payroll mass tables (Massa Salarial)

Creates:
  - fap_contestation_payroll_masses
  - fap_contestation_payroll_mass_source_history
  - fap_contestation_payroll_mass_manual_history
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db


DDL_STATEMENTS = [
    # Main payroll mass table
    """
    CREATE TABLE IF NOT EXISTS fap_contestation_payroll_masses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        law_firm_id INTEGER NOT NULL REFERENCES law_firms(id),
        report_id INTEGER NOT NULL REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
        vigencia_id INTEGER REFERENCES fap_vigencia_cnpjs(id),
        vigencia_year VARCHAR(10),
        employer_cnpj VARCHAR(20) NOT NULL,
        employer_name VARCHAR(255),
        competence VARCHAR(10) NOT NULL,
        total_remuneration NUMERIC(18, 2),
        first_instance_requested_value NUMERIC(18, 2),
        second_instance_requested_value NUMERIC(18, 2),
        first_instance_status VARCHAR(30),
        first_instance_status_raw VARCHAR(255),
        first_instance_justification TEXT,
        first_instance_opinion TEXT,
        second_instance_status VARCHAR(30),
        second_instance_status_raw VARCHAR(255),
        second_instance_justification TEXT,
        second_instance_opinion TEXT,
        status VARCHAR(30) DEFAULT 'pending',
        justification TEXT,
        opinion TEXT,
        notes TEXT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (law_firm_id, report_id, employer_cnpj, competence)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_payroll_masses_law_firm ON fap_contestation_payroll_masses(law_firm_id)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_masses_report ON fap_contestation_payroll_masses(report_id)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_masses_vigencia ON fap_contestation_payroll_masses(vigencia_id)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_masses_vigencia_year ON fap_contestation_payroll_masses(vigencia_year)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_masses_employer_cnpj ON fap_contestation_payroll_masses(employer_cnpj)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_masses_competence ON fap_contestation_payroll_masses(competence)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_masses_status ON fap_contestation_payroll_masses(status)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_masses_first_status ON fap_contestation_payroll_masses(first_instance_status)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_masses_second_status ON fap_contestation_payroll_masses(second_instance_status)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_masses_created_at ON fap_contestation_payroll_masses(created_at)",

    # Source history table
    """
    CREATE TABLE IF NOT EXISTS fap_contestation_payroll_mass_source_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        law_firm_id INTEGER NOT NULL REFERENCES law_firms(id),
        payroll_mass_id INTEGER NOT NULL REFERENCES fap_contestation_payroll_masses(id),
        report_id INTEGER NOT NULL REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
        knowledge_base_id INTEGER REFERENCES knowledge_base(id),
        action VARCHAR(20) NOT NULL DEFAULT 'updated',
        transmission_datetime DATETIME,
        publication_datetime DATETIME,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (payroll_mass_id, report_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_pm_src_history_law_firm ON fap_contestation_payroll_mass_source_history(law_firm_id)",
    "CREATE INDEX IF NOT EXISTS ix_pm_src_history_mass ON fap_contestation_payroll_mass_source_history(payroll_mass_id)",
    "CREATE INDEX IF NOT EXISTS ix_pm_src_history_report ON fap_contestation_payroll_mass_source_history(report_id)",
    "CREATE INDEX IF NOT EXISTS ix_pm_src_history_kb ON fap_contestation_payroll_mass_source_history(knowledge_base_id)",
    "CREATE INDEX IF NOT EXISTS ix_pm_src_history_action ON fap_contestation_payroll_mass_source_history(action)",
    "CREATE INDEX IF NOT EXISTS ix_pm_src_history_transmission ON fap_contestation_payroll_mass_source_history(transmission_datetime)",
    "CREATE INDEX IF NOT EXISTS ix_pm_src_history_publication ON fap_contestation_payroll_mass_source_history(publication_datetime)",
    "CREATE INDEX IF NOT EXISTS ix_pm_src_history_created_at ON fap_contestation_payroll_mass_source_history(created_at)",

    # Manual history table
    """
    CREATE TABLE IF NOT EXISTS fap_contestation_payroll_mass_manual_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        law_firm_id INTEGER NOT NULL REFERENCES law_firms(id),
        payroll_mass_id INTEGER NOT NULL REFERENCES fap_contestation_payroll_masses(id),
        performed_by_user_id INTEGER REFERENCES users(id),
        action VARCHAR(60) NOT NULL DEFAULT 'edit_payroll_mass_first_instance_status',
        old_first_instance_status VARCHAR(30),
        new_first_instance_status VARCHAR(30) NOT NULL,
        notes TEXT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_pm_manual_history_law_firm ON fap_contestation_payroll_mass_manual_history(law_firm_id)",
    "CREATE INDEX IF NOT EXISTS ix_pm_manual_history_mass ON fap_contestation_payroll_mass_manual_history(payroll_mass_id)",
    "CREATE INDEX IF NOT EXISTS ix_pm_manual_history_user ON fap_contestation_payroll_mass_manual_history(performed_by_user_id)",
    "CREATE INDEX IF NOT EXISTS ix_pm_manual_history_action ON fap_contestation_payroll_mass_manual_history(action)",
    "CREATE INDEX IF NOT EXISTS ix_pm_manual_history_old_status ON fap_contestation_payroll_mass_manual_history(old_first_instance_status)",
    "CREATE INDEX IF NOT EXISTS ix_pm_manual_history_new_status ON fap_contestation_payroll_mass_manual_history(new_first_instance_status)",
    "CREATE INDEX IF NOT EXISTS ix_pm_manual_history_created_at ON fap_contestation_payroll_mass_manual_history(created_at)",
]


def run():
    with app.app_context():
        conn = db.engine.raw_connection()
        try:
            cursor = conn.cursor()
            for stmt in DDL_STATEMENTS:
                stmt = stmt.strip()
                if stmt:
                    cursor.execute(stmt)
            conn.commit()
            print('Migration add_payroll_mass_tables completed successfully.')
        except Exception as exc:
            conn.rollback()
            print(f'Migration failed: {exc}')
            raise
        finally:
            conn.close()


if __name__ == '__main__':
    run()
