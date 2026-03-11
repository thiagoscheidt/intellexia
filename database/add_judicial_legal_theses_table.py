"""
Script de migracao para criar tabela judicial_legal_theses e adicionar
vinculo legal_thesis_id em judicial_process_benefits.

Uso:
    python database/add_judicial_legal_theses_table.py
"""

import sys
from pathlib import Path

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, JudicialLegalThesis


def migrate():
    with app.app_context():
        try:
            print("🔄 Garantindo criacao da tabela judicial_legal_theses...")
            JudicialLegalThesis.__table__.create(bind=db.engine, checkfirst=True)

            inspector = inspect(db.engine)
            columns = {col['name'] for col in inspector.get_columns('judicial_process_benefits')}

            if 'legal_thesis_id' not in columns:
                dialect = db.engine.dialect.name
                print("🔄 Adicionando coluna legal_thesis_id em judicial_process_benefits...")

                if dialect == 'mysql':
                    db.session.execute(
                        text(
                            """
                            ALTER TABLE judicial_process_benefits
                            ADD COLUMN legal_thesis_id INT NULL,
                            ADD INDEX ix_jpb_legal_thesis_id (legal_thesis_id),
                            ADD CONSTRAINT fk_jpb_legal_thesis
                                FOREIGN KEY (legal_thesis_id) REFERENCES judicial_legal_theses(id)
                            """
                        )
                    )
                else:
                    # SQLite e outros: adiciona somente a coluna (FK/indice via modelo e futuras migracoes)
                    db.session.execute(
                        text(
                            """
                            ALTER TABLE judicial_process_benefits
                            ADD COLUMN legal_thesis_id INTEGER
                            """
                        )
                    )

                db.session.commit()
                print("✅ Coluna legal_thesis_id adicionada com sucesso.")
            else:
                print("ℹ️ Coluna legal_thesis_id ja existe em judicial_process_benefits.")

            print("✅ Migracao concluida com sucesso!")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro na migracao: {e}")
            raise


if __name__ == '__main__':
    print("=" * 75)
    print("🔧 MIGRACAO: judicial_legal_theses + vinculo em judicial_process_benefits")
    print("=" * 75)
    migrate()
    print("=" * 75)
