"""
Migration: adiciona coluna data_dou_date na tabela fap_web_contestacoes.

Armazena a data de publicação no D.O.U. (campo ``dataDOU`` do raw_data) em
uma coluna Date indexada, permitindo ordenar/filtrar direto em SQL — ex.: no
dashboard de "Últimas Publicações no D.O.U.".

Além de criar a coluna, faz o backfill dos registros existentes a partir do
JSON ``raw_data``.

Executar:
    uv run python database/add_fap_web_contestacoes_data_dou_column.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
from datetime import datetime

from main import app
from app.models import db


DDL = "ALTER TABLE fap_web_contestacoes ADD COLUMN data_dou_date DATE;"
DDL_INDEX = "CREATE INDEX ix_fap_web_contestacoes_data_dou_date ON fap_web_contestacoes (data_dou_date);"


def _parse_dou(raw_data):
    """Extrai dataDOU de raw_data e devolve um date, ou None."""
    if not raw_data:
        return None
    try:
        raw = json.loads(raw_data)
        s = raw.get('dataDOU')
        if not s:
            return None
        return datetime.fromisoformat(str(s)[:10]).date()
    except Exception:
        return None


def run():
    with app.app_context():
        from sqlalchemy import text, inspect

        inspector = inspect(db.engine)
        cols = [c['name'] for c in inspector.get_columns('fap_web_contestacoes')]

        with db.engine.connect() as conn:
            if 'data_dou_date' in cols:
                print('Coluna data_dou_date já existe em fap_web_contestacoes. Pulando criação.')
            else:
                conn.execute(text(DDL))
                conn.commit()
                print('Coluna data_dou_date adicionada com sucesso em fap_web_contestacoes.')

            # Índice (idempotente — verifica existência)
            existing_indexes = {ix['name'] for ix in inspector.get_indexes('fap_web_contestacoes')}
            if 'ix_fap_web_contestacoes_data_dou_date' not in existing_indexes:
                try:
                    conn.execute(text(DDL_INDEX))
                    conn.commit()
                    print('Índice ix_fap_web_contestacoes_data_dou_date criado.')
                except Exception as e:
                    print(f'Aviso: não foi possível criar o índice ({e}).')

        # ── Backfill a partir do raw_data ────────────────────────────────
        from app.models import FapWebContestacao

        updated = 0
        skipped = 0
        rows = (
            FapWebContestacao.query
            .filter(FapWebContestacao.raw_data.isnot(None))
            .filter(FapWebContestacao.data_dou_date.is_(None))
            .all()
        )
        for rec in rows:
            dt = _parse_dou(rec.raw_data)
            if dt:
                rec.data_dou_date = dt
                updated += 1
            else:
                skipped += 1

        if updated:
            db.session.commit()

        print(f'Backfill concluído: {updated} registros preenchidos, {skipped} sem dataDOU.')


if __name__ == '__main__':
    run()
