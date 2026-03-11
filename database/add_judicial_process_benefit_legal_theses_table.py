"""
Script de migracao para criar a tabela relacional entre beneficios
judiciais e teses juridicas, permitindo multiplas teses por beneficio.

Uso:
    python database/add_judicial_process_benefit_legal_theses_table.py
"""

import sys
from pathlib import Path

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, judicial_process_benefit_legal_theses


def migrate():
    with app.app_context():
        try:
            print("🔄 Garantindo criacao da tabela judicial_process_benefit_legal_theses...")
            judicial_process_benefit_legal_theses.create(bind=db.engine, checkfirst=True)

            inspector = inspect(db.engine)
            columns = {col['name'] for col in inspector.get_columns('judicial_process_benefits')}

            if 'legal_thesis_id' not in columns:
                print("ℹ️ Coluna legada legal_thesis_id nao encontrada; nada para migrar.")
                print("✅ Migracao concluida com sucesso!")
                return

            print("🔄 Migrando vinculos legados para a tabela relacional...")
            db.session.execute(
                text(
                    """
                    INSERT INTO judicial_process_benefit_legal_theses (benefit_id, legal_thesis_id, created_at)
                    SELECT jpb.id, jpb.legal_thesis_id, CURRENT_TIMESTAMP
                    FROM judicial_process_benefits jpb
                    INNER JOIN judicial_legal_theses jlt
                        ON jlt.id = jpb.legal_thesis_id
                    WHERE jpb.legal_thesis_id IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1
                          FROM judicial_process_benefit_legal_theses rel
                          WHERE rel.benefit_id = jpb.id
                            AND rel.legal_thesis_id = jpb.legal_thesis_id
                      )
                    """
                )
            )
            db.session.commit()

            total_links = db.session.execute(
                text("SELECT COUNT(*) FROM judicial_process_benefit_legal_theses")
            ).scalar()
            print(f"✅ Vinculos disponiveis na tabela relacional: {total_links}")
            print("✅ Migracao concluida com sucesso!")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro na migracao: {e}")
            raise


if __name__ == '__main__':
    print("=" * 90)
    print("🔧 MIGRACAO: judicial_process_benefit_legal_theses")
    print("=" * 90)
    migrate()
    print("=" * 90)
