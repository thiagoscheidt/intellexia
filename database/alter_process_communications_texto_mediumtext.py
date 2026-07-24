#!/usr/bin/env python3
"""
Altera a coluna texto de process_communications de TEXT (64 KB em bytes)
para MEDIUMTEXT (~16 MB).

O inteiro teor de sentenças publicadas no DJEN ultrapassa 64 KB em UTF-8
(ex.: intimação com sentença de 76 mil caracteres quebrou a sincronização
com DataError 1406). O modelo passa a declarar db.Text(16777215), mas
bancos criados antes ficaram com TEXT.

Idempotente. Uso: uv run python database/alter_process_communications_texto_mediumtext.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db
from sqlalchemy import text

with app.app_context():
    try:
        row = db.session.execute(text(
            "SELECT DATA_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'process_communications' "
            "AND COLUMN_NAME = 'texto'"
        )).first()
        if row is None:
            print("• process_communications.texto: tabela/coluna não encontrada (SQLite/dev?) — nada a fazer")
            sys.exit(0)
        if row[0].lower() == 'mediumtext':
            print("✓ process_communications.texto já é MEDIUMTEXT — nada a fazer")
            sys.exit(0)
        db.session.execute(text(
            "ALTER TABLE process_communications MODIFY texto MEDIUMTEXT"
        ))
        db.session.commit()
        print(f"✓ process_communications.texto: {row[0]} → MEDIUMTEXT")
        print("✓ Migração concluída com sucesso!")
    except Exception as e:
        db.session.rollback()
        print(f"✗ Erro durante migração: {e}")
        sys.exit(1)
