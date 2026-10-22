"""
Migration: cria as tabelas da Biblioteca de Prompts.

``prompt_library_items`` (prompt, agente ou skill, pessoal ou do escritório),
``prompt_library_versions`` (histórico de versões) e
``prompt_library_favorites`` (estrelas). Ver ``app/services/prompt_library_service.py``.
Idempotente: tabela que já existe é pulada.

Executar:
    uv run python database/add_prompt_library_tables.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import inspect

from main import app
from app.models import db, PromptLibraryFavorite, PromptLibraryItem, PromptLibraryVersion


def run():
    with app.app_context():
        # Ordem importa: as duas últimas têm FK para a primeira.
        for modelo in (PromptLibraryItem, PromptLibraryVersion, PromptLibraryFavorite):
            table = modelo.__table__
            if inspect(db.engine).has_table(table.name):
                print(f'[OK] Tabela {table.name} já existe.')
                continue
            try:
                table.create(db.engine)
            except Exception as e:
                print(f'[ERRO] Falha ao criar {table.name}: {e}')
                raise
            print(f'[OK] Tabela {table.name} criada ({db.engine.dialect.name}).')


if __name__ == '__main__':
    run()
