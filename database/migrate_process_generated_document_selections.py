"""
Migração: substitui a tabela M2M judicial_process_generated_document_benefits
pela tabela judicial_process_generated_document_selections, que registra pares
(benefit_id, legal_thesis_id) permitindo seleção granular por benefício+tese.

Uso:
    uv run python database/migrate_process_generated_document_selections.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, JudicialProcessGeneratedDocumentSelection


def migrate():
    with app.app_context():
        try:
            print("🔄 Removendo tabela antiga (judicial_process_generated_document_benefits)...")
            db.engine.execute("DROP TABLE IF EXISTS judicial_process_generated_document_benefits")
        except Exception:
            # SQLAlchemy 2.x não tem .execute() diretamente
            with db.engine.connect() as conn:
                conn.execute(db.text("DROP TABLE IF EXISTS judicial_process_generated_document_benefits"))
                conn.commit()
            print("   Tabela removida.")

        print("🔄 Criando tabela judicial_process_generated_document_selections...")
        JudicialProcessGeneratedDocumentSelection.__table__.create(bind=db.engine, checkfirst=True)
        print("✅ Migração concluída com sucesso!")


if __name__ == '__main__':
    print("=" * 70)
    print("🔧 MIGRAÇÃO: Seleções de Benefício+Tese para Documentos Gerados")
    print("=" * 70)
    migrate()
    print("=" * 70)
