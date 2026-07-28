"""Migration: status de ingestão em segundo plano nas peças-modelo de impugnação.

Novos campos em impugnacao_reference_models (retrocompatíveis):
    ingestion_status VARCHAR(20) DEFAULT 'completed'  -- processing|completed|failed
    ingestion_error  TEXT
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text

COLUMNS = [
    ("ingestion_status", "VARCHAR(20) DEFAULT 'completed'"),
    ("ingestion_error",  "TEXT"),
]

with app.app_context():
    with db.engine.connect() as conn:
        for col_name, col_type in COLUMNS:
            try:
                conn.execute(text(
                    f"ALTER TABLE impugnacao_reference_models ADD COLUMN {col_name} {col_type}"
                ))
                conn.commit()
                print(f"  ✓ {col_name} adicionado")
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print(f"  – {col_name} já existe, pulando")
                else:
                    raise

    print("Migration concluída.")
