"""
Migration: cria as tabelas fap_calculo_estabelecimentos e fap_calculo_itens.

Guardam o que a Consulta do FAP do portal informa por estabelecimento e
vigência: o cálculo atual e todos os benefícios e CATs dele.

Cria as tabelas pelo metadata do SQLAlchemy — funciona igual em SQLite e MySQL,
e já traz índices e unicidades declarados nos modelos. Idempotente.

Os modelos fixam utf8mb4 / utf8mb4_unicode_ci (a collation de ``benefits``) para
comparar ``benefit_number`` com ``identificador`` sem "Illegal mix of
collations". Tabelas já criadas mantêm a collation que tinham (não são
alteradas aqui); confira com ``SHOW TABLE STATUS LIKE 'fap_calculo_%'``.

Executar:
    uv run python database/add_fap_calculo_tables.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import inspect

from main import app
from app.models import db, FapCalculoEstabelecimento, FapCalculoItem


def run():
    with app.app_context():
        for model in (FapCalculoEstabelecimento, FapCalculoItem):
            table = model.__table__

            if inspect(db.engine).has_table(table.name):
                print(f'[OK] Tabela {table.name} já existe — nada a fazer.')
                continue

            try:
                table.create(db.engine)
            except Exception as e:
                print(f'[ERRO] Falha ao criar {table.name}: {e}')
                raise

            print(f'[OK] Tabela {table.name} criada ({db.engine.dialect.name}).')


if __name__ == '__main__':
    run()
