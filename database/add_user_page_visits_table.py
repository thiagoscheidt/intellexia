#!/usr/bin/env python3
"""
Cria a tabela user_page_visits (agregado diário de telas acessadas por usuário).

Idempotente: verifica existência prévia da tabela antes de criar.
Uso: uv run python database/add_user_page_visits_table.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db, UserPageVisit
from sqlalchemy import inspect

with app.app_context():
    try:
        inspector = inspect(db.engine)
        if inspector.has_table('user_page_visits'):
            print("✓ Tabela user_page_visits já existe — nada a fazer")
        else:
            UserPageVisit.__table__.create(db.engine)
            print("✓ Tabela user_page_visits criada com sucesso (índices incluídos)")
        print("✓ Migração concluída com sucesso!")
    except Exception as e:
        print(f"✗ Erro durante migração: {e}")
        sys.exit(1)
