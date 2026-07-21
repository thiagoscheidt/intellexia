#!/usr/bin/env python3
"""
Metadados de versionamento do Revisor FAP:
- change_note em fap_review_prompt_versions e fap_review_reference_versions
  (descrição curta do que mudou na versão);
- used_versions_json em fap_review_executions (versões de prompt/referência
  usadas na execução da revisão).

Idempotente. Uso: uv run python database/add_fap_review_versioning_metadata.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db
from sqlalchemy import inspect, text

CHANGES = [
    ('fap_review_prompt_versions', 'change_note', 'VARCHAR(255)'),
    ('fap_review_reference_versions', 'change_note', 'VARCHAR(255)'),
    ('fap_review_executions', 'used_versions_json', 'TEXT'),
]

with app.app_context():
    try:
        inspector = inspect(db.engine)
        for table, column, ddl_type in CHANGES:
            columns = [c['name'] for c in inspector.get_columns(table)]
            if column in columns:
                print(f"✓ {table}.{column} já existe — nada a fazer")
                continue
            db.session.execute(text(
                f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"
            ))
            print(f"✓ Coluna {table}.{column} criada")
        db.session.commit()
        print("✓ Migração concluída com sucesso!")
    except Exception as e:
        db.session.rollback()
        print(f"✗ Erro durante migração: {e}")
        sys.exit(1)
