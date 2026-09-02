"""
Migration: adiciona file_situacao_codigo na tabela fap_web_contestacoes.

Guarda a que situacao o PDF em disco corresponde. O relatorio da DATAPREV muda
de conteudo conforme o estagio: enquanto "Transmitida" traz so as justificativas;
publicado, traz Status, Parecer e o Sumario dos Elementos Contestados. As filas
de download so olhavam `file_path IS NULL`, entao o arquivo capturado em voo
nunca era rebaixado depois do julgamento.

NULL = origem desconhecida (arquivo anterior a esta coluna). A fila trata NULL
como "nao sei" e nao rebaixa, para nao disparar download em massa; quem preenche
e o backfill `scripts/backfill_fap_file_situacao.py`, lendo a 1a pagina do PDF.

Executar:
    uv run python database/add_fap_web_contestacoes_file_situacao_column.py
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
            if 'file_situacao_codigo' not in cols:
                conn.execute(text(
                    "ALTER TABLE fap_web_contestacoes ADD COLUMN file_situacao_codigo VARCHAR(100) NULL"
                ))
                print('Coluna file_situacao_codigo adicionada em fap_web_contestacoes.')
            else:
                print('Coluna file_situacao_codigo ja existe em fap_web_contestacoes.')

            dialect = db.engine.dialect.name
            if dialect == 'mysql':
                idx_rows = conn.execute(text("SHOW INDEX FROM fap_web_contestacoes")).fetchall()
                idx_names = {row[2] for row in idx_rows}
                if 'ix_fap_web_contestacoes_file_situacao_codigo' not in idx_names:
                    conn.execute(text(
                        "CREATE INDEX ix_fap_web_contestacoes_file_situacao_codigo "
                        "ON fap_web_contestacoes (file_situacao_codigo)"
                    ))
                    print('Indice ix_fap_web_contestacoes_file_situacao_codigo criado.')
                else:
                    print('Indice ix_fap_web_contestacoes_file_situacao_codigo ja existe.')
            else:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_fap_web_contestacoes_file_situacao_codigo "
                    "ON fap_web_contestacoes (file_situacao_codigo)"
                ))
                print('Indice ix_fap_web_contestacoes_file_situacao_codigo verificado.')

            conn.commit()

        print('Migration concluida com sucesso.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(f'ERRO na migration: {exc}')
        raise
