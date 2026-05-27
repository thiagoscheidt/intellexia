"""Adiciona coluna thesis_catalog_ids em impugnacao_reference_models.

Uso:
    uv run python database/add_impugnacao_reference_models_thesis_catalog_ids.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect

from main import app
from app.models import db


TABLE_NAME = 'impugnacao_reference_models'
COLUMN_NAME = 'thesis_catalog_ids'


def add_column() -> None:
    with app.app_context():
        inspector = inspect(db.engine)
        if TABLE_NAME not in inspector.get_table_names():
            print(f"Tabela {TABLE_NAME} não encontrada. Nada a fazer.")
            return

        columns = [col['name'] for col in inspector.get_columns(TABLE_NAME)]
        if COLUMN_NAME in columns:
            print(f"Coluna {COLUMN_NAME} já existe em {TABLE_NAME}.")
            return

        dialect = db.engine.dialect.name.lower()
        with db.engine.connect() as connection:
            if dialect == 'sqlite':
                sql = (
                    f"ALTER TABLE {TABLE_NAME} "
                    f"ADD COLUMN {COLUMN_NAME} TEXT"
                )
            else:
                sql = (
                    f"ALTER TABLE {TABLE_NAME} "
                    f"ADD COLUMN {COLUMN_NAME} JSON"
                )

            connection.execute(db.text(sql))
            connection.commit()

        print(f"Coluna {COLUMN_NAME} adicionada com sucesso em {TABLE_NAME}.")


if __name__ == '__main__':
    try:
        add_column()
    except Exception as error:
        print(f"Erro ao adicionar coluna {COLUMN_NAME}: {error}")
        raise
