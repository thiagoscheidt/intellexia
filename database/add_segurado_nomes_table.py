"""
Migration: cria a tabela segurado_nomes.

Guarda o nome do segurado obtido pelo botão "Revelar nome" (consulta de CPF) —
o FAP não informa nome. Uma linha por (escritório, CPF), só com o nome; ver o
docstring de ``SeguradoNome``.

Cria pelo metadata do SQLAlchemy (SQLite e MySQL), com índice e unicidade dos
modelos. Idempotente. Nenhuma consulta cruza esta tabela com ``benefits`` por
JOIN de texto — então a collation não precisa ser alinhada como a do cálculo.

Executar:
    uv run python database/add_segurado_nomes_table.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import inspect

from main import app
from app.models import db, SeguradoNome


def run():
    with app.app_context():
        table = SeguradoNome.__table__
        if inspect(db.engine).has_table(table.name):
            print(f'[OK] Tabela {table.name} já existe — nada a fazer.')
            return
        try:
            table.create(db.engine)
        except Exception as e:
            print(f'[ERRO] Falha ao criar {table.name}: {e}')
            raise
        print(f'[OK] Tabela {table.name} criada ({db.engine.dialect.name}).')


if __name__ == '__main__':
    run()
