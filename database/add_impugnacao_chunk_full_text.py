"""Adiciona coluna full_text à tabela impugnacao_reference_chunks."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from main import app
from app.models import db

with app.app_context():
    with db.engine.connect() as conn:
        try:
            conn.execute(db.text(
                'ALTER TABLE impugnacao_reference_chunks ADD COLUMN full_text TEXT'
            ))
            conn.commit()
            print('Coluna full_text adicionada com sucesso.')
        except Exception as e:
            if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                print('Coluna full_text já existe, nada a fazer.')
            else:
                raise
