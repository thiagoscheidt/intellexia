"""
Migration: adiciona coluna deferimento_descricao na tabela fap_web_contestacoes.

Armazena a descrição do deferimento (campo ``deferimento.descricao`` do
raw_data) em uma coluna dedicada, permitindo agregar direto em SQL — ex.: no
gráfico "Contestações por deferimento" do dashboard.

Sem a coluna, o dashboard tinha de trazer o raw_data das ~11 mil contestações
(~23 MB) a cada carregamento só para contar quantas caem em cada status.

Cria também o índice composto (law_firm_id, cnpj_raiz, deferimento_descricao),
que cobre exatamente o GROUP BY do dashboard: o MySQL resolve a agregação
dentro do índice, sem tocar nas linhas.

Além de criar coluna e índice, faz o backfill dos registros existentes a
partir do JSON ``raw_data``.

Executar:
    uv run python database/add_fap_web_contestacoes_deferimento_column.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json

from main import app
from app.models import db


DDL = "ALTER TABLE fap_web_contestacoes ADD COLUMN deferimento_descricao VARCHAR(255);"
INDEX_NAME = 'ix_fap_web_contestacoes_firm_raiz_deferimento'
DDL_INDEX = (
    f"CREATE INDEX {INDEX_NAME} ON fap_web_contestacoes "
    "(law_firm_id, cnpj_raiz, deferimento_descricao);"
)

# Lê o raw_data em blocos: a coluna tem ~2 KB por linha e o backfill não
# precisa (nem deve) carregar as 11 mil de uma vez.
BATCH_SIZE = 1000


def _parse_deferimento(raw_data):
    """Extrai deferimento.descricao de raw_data e devolve str, ou None."""
    if not raw_data:
        return None
    try:
        from app.models import FapWebContestacao
        return FapWebContestacao.extract_deferimento_descricao(json.loads(raw_data))
    except Exception:
        return None


def run():
    with app.app_context():
        from sqlalchemy import text, inspect

        inspector = inspect(db.engine)
        cols = [c['name'] for c in inspector.get_columns('fap_web_contestacoes')]

        with db.engine.connect() as conn:
            if 'deferimento_descricao' in cols:
                print('Coluna deferimento_descricao já existe em fap_web_contestacoes. Pulando criação.')
            else:
                conn.execute(text(DDL))
                conn.commit()
                print('Coluna deferimento_descricao adicionada com sucesso em fap_web_contestacoes.')

            # Índice (idempotente — verifica existência)
            existing_indexes = {ix['name'] for ix in inspector.get_indexes('fap_web_contestacoes')}
            if INDEX_NAME not in existing_indexes:
                try:
                    conn.execute(text(DDL_INDEX))
                    conn.commit()
                    print(f'Índice {INDEX_NAME} criado.')
                except Exception as e:
                    print(f'Aviso: não foi possível criar o índice ({e}).')
            else:
                print(f'Índice {INDEX_NAME} já existe. Pulando criação.')

        # ── Backfill a partir do raw_data ────────────────────────────────
        from app.models import FapWebContestacao

        updated = 0
        skipped = 0
        last_id = 0

        while True:
            rows = (
                db.session.query(FapWebContestacao.id, FapWebContestacao.raw_data)
                .filter(FapWebContestacao.raw_data.isnot(None))
                .filter(FapWebContestacao.deferimento_descricao.is_(None))
                .filter(FapWebContestacao.id > last_id)
                .order_by(FapWebContestacao.id)
                .limit(BATCH_SIZE)
                .all()
            )
            if not rows:
                break

            mappings = []
            for rec_id, raw_data in rows:
                last_id = rec_id
                desc = _parse_deferimento(raw_data)
                if desc:
                    mappings.append({'id': rec_id, 'deferimento_descricao': desc})
                    updated += 1
                else:
                    skipped += 1

            if mappings:
                db.session.bulk_update_mappings(FapWebContestacao, mappings)
                db.session.commit()
            db.session.expunge_all()

        print(f'Backfill concluído: {updated} registros preenchidos, {skipped} sem deferimento.')


if __name__ == '__main__':
    run()
