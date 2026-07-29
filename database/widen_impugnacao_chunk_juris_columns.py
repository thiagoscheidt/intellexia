"""Migration: alarga as colunas de jurisprudência em impugnacao_reference_chunks.

O agente extrator devolve listas concatenadas quando o trecho cita vários
precedentes (ex.: "AC 5015482-56...; AC 5004821-26...; AC 5083928-14..."),
estourando os limites originais e derrubando a ingestão inteira da peça com
`DataError (1406) Data too long`.

    tribunal  VARCHAR(60)  -> VARCHAR(120)
    processo  VARCHAR(120) -> VARCHAR(500)
    relator   VARCHAR(255) -> VARCHAR(500)

Idempotente: consulta o tamanho atual em information_schema e só altera o que
ainda estiver estreito. Só alarga — nunca reduz, então não trunca dado algum.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text

TABLE = 'impugnacao_reference_chunks'
COLUMNS = [
    ('tribunal', 120),
    ('processo', 500),
    ('relator', 500),
]

with app.app_context():
    with db.engine.connect() as conn:
        dialect = db.engine.dialect.name

        for col_name, target_len in COLUMNS:
            current_len = None
            if dialect == 'mysql':
                current_len = conn.execute(text(
                    "SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
                ), {'t': TABLE, 'c': col_name}).scalar()

            if current_len is not None and current_len >= target_len:
                print(f"  – {col_name} já tem VARCHAR({current_len}), pulando")
                continue

            if dialect != 'mysql':
                # SQLite não impõe limite de VARCHAR: o modelo já basta.
                print(f"  – {col_name}: dialeto {dialect} não limita VARCHAR, nada a fazer")
                continue

            try:
                conn.execute(text(
                    f"ALTER TABLE {TABLE} MODIFY COLUMN {col_name} VARCHAR({target_len})"
                ))
                conn.commit()
                print(f"  ✓ {col_name} alargado para VARCHAR({target_len})")
            except Exception as error:
                print(f"  ✗ falha ao alargar {col_name}: {error}")
                raise

    print("Migration concluída.")
