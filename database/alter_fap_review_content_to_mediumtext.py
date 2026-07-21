#!/usr/bin/env python3
"""
Altera a coluna content de fap_review_reference_versions e
fap_review_prompt_versions de TEXT (64 KB em bytes) para MEDIUMTEXT (~16 MB).

O manual de revisão FAP com acentuação ultrapassa 64 KB em UTF-8 — o modelo já
declara db.Text(16777215), mas bancos criados antes ficaram com TEXT.

Idempotente. Uso: uv run python database/alter_fap_review_content_to_mediumtext.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db
from sqlalchemy import text

TABLES = ('fap_review_reference_versions', 'fap_review_prompt_versions')

with app.app_context():
    try:
        for table in TABLES:
            row = db.session.execute(text(
                "SELECT DATA_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = 'content'"
            ), {'t': table}).first()
            if row is None:
                print(f"• {table}: tabela/coluna não encontrada (SQLite/dev?) — pulando")
                continue
            if row[0].lower() == 'mediumtext':
                print(f"✓ {table}.content já é MEDIUMTEXT — nada a fazer")
                continue
            db.session.execute(text(
                f"ALTER TABLE {table} MODIFY content MEDIUMTEXT NOT NULL"
            ))
            print(f"✓ {table}.content: {row[0]} → MEDIUMTEXT")
        db.session.commit()
        print("✓ Migração concluída com sucesso!")
    except Exception as e:
        db.session.rollback()
        print(f"✗ Erro durante migração: {e}")
        sys.exit(1)
