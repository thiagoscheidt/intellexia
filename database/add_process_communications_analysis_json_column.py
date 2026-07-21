#!/usr/bin/env python3
"""
Adiciona a coluna analysis_json em process_communications — cache da explicação
gerada pelo CommunicationExplainerAgent (o teor é imutável, a análise é única).

Idempotente. Uso: uv run python database/add_process_communications_analysis_json_column.py
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
        if 'analysis_json' in columns:
            print("✓ Coluna analysis_json já existe — nada a fazer")
        else:
            db.session.execute(text(
                "ALTER TABLE process_communications ADD COLUMN analysis_json JSON"
            ))
            db.session.commit()
            print("✓ Coluna analysis_json criada")
        print("✓ Migração concluída com sucesso!")
    except Exception as e:
        db.session.rollback()
        print(f"✗ Erro durante migração: {e}")
        sys.exit(1)
