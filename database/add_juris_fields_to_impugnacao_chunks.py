"""Migration: adiciona campos de jurisprudência à tabela impugnacao_reference_chunks.

Novos campos (nullable, retrocompatíveis):
    secao_origem, tribunal, processo, relator, tipo_juris, fundamento_principal
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text

COLUMNS = [
    ("secao_origem",        "VARCHAR(60)"),
    ("tribunal",            "VARCHAR(60)"),
    ("processo",            "VARCHAR(120)"),
    ("relator",             "VARCHAR(255)"),
    ("tipo_juris",          "VARCHAR(60)"),
    ("fundamento_principal","TEXT"),
]

with app.app_context():
    with db.engine.connect() as conn:
        for col_name, col_type in COLUMNS:
            try:
                conn.execute(text(
                    f"ALTER TABLE impugnacao_reference_chunks ADD COLUMN {col_name} {col_type}"
                ))
                conn.commit()
                print(f"  ✓ {col_name} adicionado")
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print(f"  – {col_name} já existe, pulando")
                else:
                    raise

    print("Migration concluída.")
