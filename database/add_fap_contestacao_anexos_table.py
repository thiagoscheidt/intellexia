"""
Migration: cria a tabela fap_contestacao_anexos (FB-08).

Um registro por documento anexado a uma contestação do FAP, carregado por
``scripts/fap_baixar_anexos.py`` a partir do que foi baixado do portal. Ver o
docstring de ``FapContestacaoAnexo``.

Cria pelo metadata do SQLAlchemy (SQLite e MySQL), com índices e unicidade do
modelo. Idempotente. Nenhuma consulta cruza esta tabela com ``benefits`` por
texto (o vínculo é o ``benefit_id``), então a collation não precisa ser
alinhada como a do cálculo FAP.

Executar:
    uv run python database/add_fap_contestacao_anexos_table.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import inspect

from main import app
from app.models import db, FapContestacaoAnexo


def run():
    with app.app_context():
        table = FapContestacaoAnexo.__table__
        if inspect(db.engine).has_table(table.name):
            print(f'[OK] Tabela {table.name} já existe — nada a fazer.')
            return
        try:
            table.create(db.engine)
        except Exception as e:
            print(f'[ERRO] Não foi possível criar {table.name}: {e}')
            raise
        print(f'[OK] Tabela {table.name} criada.')
        print('Agora carregue o que já foi baixado:')
        print('    uv run python scripts/fap_baixar_anexos.py --registrar')


if __name__ == '__main__':
    run()
