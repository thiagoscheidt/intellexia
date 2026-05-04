"""
Migration: adiciona flag de reprocessamento na tabela fap_web_contestacoes.

Adiciona a coluna needs_reprocess para sinalizar quando uma contestacao
ja processada recebeu mudancas no sync e precisa ser reprocessada.

Executar:
    uv run python database/add_fap_web_contestacoes_reprocess_flag_column.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db


def run():
    with app.app_context():
        from sqlalchemy import inspect, text

        inspector = inspect(db.engine)
        cols = [c['name'] for c in inspector.get_columns('fap_web_contestacoes')]

        with db.engine.connect() as conn:
            if 'needs_reprocess' not in cols:
                conn.execute(text("ALTER TABLE fap_web_contestacoes ADD COLUMN needs_reprocess BOOLEAN DEFAULT 0"))
                print('Coluna needs_reprocess adicionada em fap_web_contestacoes.')
            else:
                print('Coluna needs_reprocess ja existe em fap_web_contestacoes.')

            dialect = db.engine.dialect.name
            if dialect == 'mysql':
                idx_rows = conn.execute(text("SHOW INDEX FROM fap_web_contestacoes")).fetchall()
                idx_names = {row[2] for row in idx_rows}
                if 'ix_fap_web_contestacoes_needs_reprocess' not in idx_names:
                    conn.execute(
                        text(
                            "CREATE INDEX ix_fap_web_contestacoes_needs_reprocess "
                            "ON fap_web_contestacoes (needs_reprocess)"
                        )
                    )
                    print('Indice ix_fap_web_contestacoes_needs_reprocess criado.')
                else:
                    print('Indice ix_fap_web_contestacoes_needs_reprocess ja existe.')
            else:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_fap_web_contestacoes_needs_reprocess "
                        "ON fap_web_contestacoes (needs_reprocess)"
                    )
                )
                print('Indice ix_fap_web_contestacoes_needs_reprocess verificado.')

            conn.commit()


if __name__ == '__main__':
    run()
