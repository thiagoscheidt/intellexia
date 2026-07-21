#!/usr/bin/env python3
"""
Adiciona a coluna status_changed_at em fap_review_petitions (momento da última
mudança de workflow_status, para medir idade da petição no status) e faz
backfill com updated_at/created_at.

Idempotente. Uso: uv run python database/add_fap_review_status_changed_at.py
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
        columns = [c['name'] for c in inspector.get_columns('fap_review_petitions')]
        if 'status_changed_at' in columns:
            print("✓ Coluna status_changed_at já existe — nada a fazer")
        else:
            db.session.execute(text(
                "ALTER TABLE fap_review_petitions ADD COLUMN status_changed_at DATETIME"
            ))
            db.session.execute(text(
                "UPDATE fap_review_petitions "
                "SET status_changed_at = COALESCE(updated_at, created_at) "
                "WHERE status_changed_at IS NULL"
            ))
            db.session.commit()
            print("✓ Coluna status_changed_at criada + backfill com updated_at/created_at")
        print("✓ Migração concluída com sucesso!")
    except Exception as e:
        db.session.rollback()
        print(f"✗ Erro durante migração: {e}")
        sys.exit(1)
