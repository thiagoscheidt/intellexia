"""
Migration: cria a tabela fap_web_procuracoes_change_history.

Guarda o que mudou em cada procuração a cada sincronização (espelha
fap_web_contestacao_change_history). É a fonte das notificações de
procurações: a janela do e-mail é a coluna ``synced_at``.

Cria a tabela pelo metadata do SQLAlchemy — funciona igual em SQLite e MySQL,
e já traz os índices declarados no modelo.

Executar:
    uv run python database/add_fap_procuracoes_change_history_table.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import inspect

from main import app
from app.models import db, FapWebProcuracaoChangeHistory


def run():
    with app.app_context():
        table = FapWebProcuracaoChangeHistory.__table__

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
