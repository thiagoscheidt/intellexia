"""
Migration: adiciona coluna file_path na tabela fap_web_contestacoes.

Armazena o caminho relativo do PDF baixado durante a sincronização
(ex.: uploads/fap_web_contestacoes/{law_firm_id}/{year}/{cnpj14}/{filename}).

Executar:
    uv run python database/add_fap_web_contestacoes_file_path_column.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db


DDL = "ALTER TABLE fap_web_contestacoes ADD COLUMN file_path VARCHAR(500);"


def run():
    with app.app_context():
        with db.engine.connect() as conn:
            # Verifica se a coluna já existe (SQLite não suporta IF NOT EXISTS no ALTER)
            from sqlalchemy import text, inspect
            inspector = inspect(db.engine)
            cols = [c['name'] for c in inspector.get_columns('fap_web_contestacoes')]
            if 'file_path' in cols:
                print('Coluna file_path já existe em fap_web_contestacoes. Nada a fazer.')
                return
            conn.execute(text(DDL))
            conn.commit()
            print('Coluna file_path adicionada com sucesso em fap_web_contestacoes.')


if __name__ == '__main__':
    run()
