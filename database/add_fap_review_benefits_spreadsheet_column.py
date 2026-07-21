#!/usr/bin/env python3
"""
Adiciona a coluna benefits_spreadsheet_json em fap_review_executions — nome e
caminho da planilha de benefícios usada na revisão. Antes ela só trafegava em
memória, o que impedia reutilizá-la em uma nova revisão da mesma petição.

Idempotente. Uso: uv run python database/add_fap_review_benefits_spreadsheet_column.py
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
        columns = [c['name'] for c in inspector.get_columns('fap_review_executions')]
        if 'benefits_spreadsheet_json' in columns:
            print("✓ Coluna benefits_spreadsheet_json já existe — nada a fazer")
        else:
            db.session.execute(text(
                "ALTER TABLE fap_review_executions "
                "ADD COLUMN benefits_spreadsheet_json TEXT NULL"
            ))
            db.session.commit()
            print("✓ Coluna benefits_spreadsheet_json criada")
        print("✓ Migração concluída com sucesso!")
    except Exception as e:
        db.session.rollback()
        print(f"✗ Erro durante migração: {e}")
        sys.exit(1)
