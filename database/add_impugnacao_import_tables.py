"""Migration: tabelas de importação de peças-modelo a partir de planilha (Drive).

Cria:
    impugnacao_import_jobs
    impugnacao_import_items

E adiciona 3 colunas novas (nullable, retrocompatíveis) em
impugnacao_reference_models:
    file_hash, source_drive_file_id, source_theses_json
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, ImpugnacaoImportJob, ImpugnacaoImportItem
from sqlalchemy import text

COLUMNS = [
    ("file_hash", "VARCHAR(64)"),
    ("source_drive_file_id", "VARCHAR(80)"),
    ("source_theses_json", "JSON"),
]

INDEXES = [
    ("ix_impugnacao_reference_models_file_hash", "file_hash"),
    ("ix_impugnacao_reference_models_source_drive_file_id", "source_drive_file_id"),
]

with app.app_context():
    # 1. Tabelas novas
    tables = [ImpugnacaoImportJob.__table__, ImpugnacaoImportItem.__table__]
    db.metadata.create_all(bind=db.engine, tables=tables, checkfirst=True)
    print("  ✓ impugnacao_import_jobs criada/verificada")
    print("  ✓ impugnacao_import_items criada/verificada")

    with db.engine.connect() as conn:
        # 2. Colunas novas em impugnacao_reference_models
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

        # 3. Índices das colunas novas
        for index_name, col_name in INDEXES:
            try:
                conn.execute(text(
                    f"CREATE INDEX {index_name} ON impugnacao_reference_models ({col_name})"
                ))
                conn.commit()
                print(f"  ✓ índice {index_name} criado")
            except Exception as e:
                if "duplicate key name" in str(e).lower() or "already exists" in str(e).lower():
                    print(f"  – índice {index_name} já existe, pulando")
                else:
                    raise

    print("Migration concluída.")
