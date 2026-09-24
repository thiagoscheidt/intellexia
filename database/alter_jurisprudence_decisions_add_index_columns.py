"""
Prepara jurisprudence_decisions para o inteiro teor e o índice de busca:

    + texto_integral   MEDIUMTEXT   inteiro teor do PDF, páginas separadas por \\f
    + texto_paginas    INT
    + pdf_error        TEXT         falha ao buscar o PDF no Drive
    + index_status     VARCHAR(20)  pendente | indexada | erro  (+ índice)
    + index_error      TEXT
    + index_chunks     INT
    + indexed_at       DATETIME

O índice (coleção Qdrant e índice Meilisearch "jurisprudence") é derivado do
banco: depois deste script, `scripts/reindex_jurisprudence.py` indexa o que já
existe.

Idempotente: coluna já existente é reportada e pulada.

    uv run python database/alter_jurisprudence_decisions_add_index_columns.py

Rode antes: uv run python database/add_jurisprudence_tables.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from main import app
from app.models import db

TABELA = 'jurisprudence_decisions'


def _colunas(dialeto: str) -> list[tuple[str, str]]:
    longo = 'MEDIUMTEXT' if dialeto == 'mysql' else 'TEXT'
    return [
        ('texto_integral', longo),
        ('texto_paginas', 'INTEGER'),
        ('pdf_error', 'TEXT'),
        ('index_status', 'VARCHAR(20)'),
        ('index_error', 'TEXT'),
        ('index_chunks', 'INTEGER'),
        ('indexed_at', 'DATETIME'),
    ]


def alter_decisions():
    with app.app_context():
        inspector = db.inspect(db.engine)
        if TABELA not in set(inspector.get_table_names()):
            print(f'✗ Tabela {TABELA} não existe.')
            print('  Rode antes: uv run python database/add_jurisprudence_tables.py')
            return

        existentes = {c['name'] for c in inspector.get_columns(TABELA)}
        criadas = []
        for nome, tipo in _colunas(db.engine.dialect.name):
            if nome in existentes:
                print(f'✓ {TABELA}.{nome} já existe — pulando')
                continue
            try:
                with db.engine.begin() as conexao:
                    conexao.execute(text(f'ALTER TABLE {TABELA} ADD COLUMN {nome} {tipo} NULL'))
                    if nome == 'index_status':
                        conexao.execute(text(
                            f'CREATE INDEX ix_{TABELA}_index_status ON {TABELA} (index_status)'))
            except Exception as e:
                print(f'✗ Erro ao criar {TABELA}.{nome}: {e}')
                raise
            criadas.append(nome)
            print(f'✓ {TABELA}.{nome} criada')

        if not criadas:
            print('\nNada a fazer: as colunas já existiam.')
        else:
            print(f"\n✓ {len(criadas)} coluna(s): {', '.join(criadas)}")
            print('\nAgora indexe o que já está na base:')
            print('    uv run python scripts/reindex_jurisprudence.py')


if __name__ == '__main__':
    print('Preparando jurisprudence_decisions para o inteiro teor e o índice...')
    alter_decisions()
