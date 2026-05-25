"""
Script de migração para criar as tabelas de documentos gerados por IA:
  - judicial_process_generated_document_versions
  - judicial_process_generated_documents
  - judicial_process_generated_document_selections  (benefit + legal_thesis por documento)

Uso:
    uv run python database/add_process_generated_documents_tables.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import (
    db,
    JudicialProcessGeneratedDocument,
    JudicialProcessGeneratedDocumentVersion,
    JudicialProcessGeneratedDocumentSelection,
)


def migrate():
    with app.app_context():
        try:
            print("🔄 Criando tabelas de documentos gerados...")

            # versions deve existir antes de generated_documents (FK circular via current_version_id)
            JudicialProcessGeneratedDocumentVersion.__table__.create(bind=db.engine, checkfirst=True)
            JudicialProcessGeneratedDocument.__table__.create(bind=db.engine, checkfirst=True)
            JudicialProcessGeneratedDocumentSelection.__table__.create(bind=db.engine, checkfirst=True)

            print("✅ Tabelas criadas com sucesso!")
        except Exception as e:
            print(f"❌ Erro na migração: {e}")
            raise


if __name__ == '__main__':
    print("=" * 70)
    print("🔧 MIGRAÇÃO: Documentos Gerados por IA")
    print("=" * 70)
    migrate()
    print("=" * 70)
