#!/usr/bin/env python3
"""
Cria a tabela fap_review_finding_checks — pontos de atenção marcados como
revisados na triagem de uma execução do Revisor FAP (antes o "Marcar como
revisado" vivia só no localStorage do navegador).

Idempotente. Uso: uv run python database/add_fap_review_finding_checks_table.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db, FapReviewFindingCheck
from sqlalchemy import inspect

with app.app_context():
    try:
        inspector = inspect(db.engine)
        if 'fap_review_finding_checks' in inspector.get_table_names():
            print("✓ Tabela fap_review_finding_checks já existe — nada a fazer")
        else:
            FapReviewFindingCheck.__table__.create(db.engine)
            print("✓ Tabela fap_review_finding_checks criada")
        print("✓ Migração concluída com sucesso!")
    except Exception as e:
        db.session.rollback()
        print(f"✗ Erro durante migração: {e}")
        sys.exit(1)
