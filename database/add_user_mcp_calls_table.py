"""
Migration: cria a tabela user_mcp_calls.

Uso do MCP por usuário, agregado por dia (ferramentas e comandos prontos) —
alimenta a coluna "MCP" e o detalhe de funções usadas na tela de Atividade de
Usuários. Ver o docstring de ``UserMcpCall``.

Cria pelo metadata do SQLAlchemy (SQLite e MySQL), com índices e unicidade dos
modelos. Idempotente.

Executar:
    uv run python database/add_user_mcp_calls_table.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import inspect

from main import app
from app.models import db, UserMcpCall


def run():
    with app.app_context():
        table = UserMcpCall.__table__
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
