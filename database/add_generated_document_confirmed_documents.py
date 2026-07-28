"""Migration: coluna confirmed_documents_json em
judicial_process_generated_document_versions (ids de peças-modelo e anexos
confirmados no wizard; NULL = fluxo legado sem restrição)."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text

with app.app_context():
    with db.engine.connect() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE judicial_process_generated_document_versions "
                "ADD COLUMN confirmed_documents_json JSON"
            ))
            conn.commit()
            print("  ✓ confirmed_documents_json adicionado")
        except Exception as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                print("  – confirmed_documents_json já existe, pulando")
            else:
                raise

    print("Migration concluída.")
