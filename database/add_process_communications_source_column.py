#!/usr/bin/env python3
"""
Adiciona a coluna source em process_communications (fonte da informação,
extensível a novas origens além do Comunica PJe/DJEN) e faz backfill
das linhas existentes com 'comunica_pje'.

Idempotente. Uso: uv run python database/add_process_communications_source_column.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db
from sqlalchemy import inspect, text

with app.app_context():
    try:
        inspector = inspect(db.engine)
        columns = [c['name'] for c in inspector.get_columns('process_communications')]
        if 'source' in columns:
            print("✓ Coluna source já existe — nada a fazer")
        else:
            db.session.execute(text(
                "ALTER TABLE process_communications "
                "ADD COLUMN source VARCHAR(30) NOT NULL DEFAULT 'comunica_pje'"
            ))
            db.session.execute(text(
                "CREATE INDEX ix_process_communications_source ON process_communications (source)"
            ))
            db.session.commit()
            print("✓ Coluna source criada (backfill via DEFAULT) + índice")
        print("✓ Migração concluída com sucesso!")
    except Exception as e:
        db.session.rollback()
        print(f"✗ Erro durante migração: {e}")
        sys.exit(1)
