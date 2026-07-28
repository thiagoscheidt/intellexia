"""Migration: campos de contexto (CNJ/vara/juiz) e seções na tabela
impugnacao_reference_models.

Novos campos (nullable, retrocompatíveis):
    process_number, orgao_julgador, judge_name, sections_json
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text

COLUMNS = [
    ("process_number", "VARCHAR(30)"),
    ("orgao_julgador", "VARCHAR(255)"),
    ("judge_name",     "VARCHAR(255)"),
    ("sections_json",  "JSON"),
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
