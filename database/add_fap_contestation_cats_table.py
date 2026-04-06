"""Migration: cria a tabela fap_contestation_cats e remove colunas obsoletas de benefits."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db


def upgrade():
    with app.app_context():
        with db.engine.connect() as conn:
            # Nova tabela para CATs
            conn.execute(db.text("""
                CREATE TABLE IF NOT EXISTS fap_contestation_cats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    law_firm_id INTEGER NOT NULL REFERENCES law_firms(id),
                    report_id INTEGER NOT NULL REFERENCES fap_contestation_judgment_reports(id) ON DELETE CASCADE,
                    cat_number VARCHAR(50) NOT NULL,
                    employer_cnpj VARCHAR(20),
                    employer_cnpj_assigned VARCHAR(20),
                    insured_nit VARCHAR(50),
                    insured_date_of_birth DATE,
                    insured_death_date DATE,
                    accident_date DATE,
                    cat_registration_date DATE,
                    cat_block VARCHAR(20),
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
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(law_firm_id, report_id, cat_number)
                )
            """))
            conn.execute(db.text(
                "CREATE INDEX IF NOT EXISTS ix_fcc_law_firm_id ON fap_contestation_cats(law_firm_id)"
            ))
            conn.execute(db.text(
                "CREATE INDEX IF NOT EXISTS ix_fcc_report_id ON fap_contestation_cats(report_id)"
            ))
            conn.execute(db.text(
                "CREATE INDEX IF NOT EXISTS ix_fcc_cat_number ON fap_contestation_cats(cat_number)"
            ))
            conn.execute(db.text(
                "CREATE INDEX IF NOT EXISTS ix_fcc_status ON fap_contestation_cats(status)"
            ))

            # Remove colunas obsoletas de benefits (SQLite não suporta DROP COLUMN antes de 3.35.0)
            # Para SQLite antigo, pode ser necessário recriar a tabela.
            # Para MySQL/PostgreSQL use os comandos abaixo diretamente.
            try:
                conn.execute(db.text("ALTER TABLE benefits DROP COLUMN tipo"))
            except Exception:
                pass  # coluna pode já não existir ou SQLite antigo
            try:
                conn.execute(db.text("ALTER TABLE benefits DROP COLUMN cat_registration_date"))
            except Exception:
                pass
            try:
                conn.execute(db.text("ALTER TABLE benefits DROP COLUMN insured_death_date"))
            except Exception:
                pass
            try:
                conn.execute(db.text("ALTER TABLE benefits DROP COLUMN cat_block"))
            except Exception:
                pass

            conn.commit()

        print("Tabela 'fap_contestation_cats' criada com sucesso.")
        print("Colunas obsoletas removidas de 'benefits' (se suportado pelo banco).")


if __name__ == '__main__':
    upgrade()
