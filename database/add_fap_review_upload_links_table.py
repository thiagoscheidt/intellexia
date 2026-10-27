"""
Migration: cria a tabela fap_review_upload_links.

Links de envio de uso único do arquivo da petição para a revisão pedida pelo
Claude (RPI-37) — ver ``FapReviewUploadLink`` e
``app/services/fap_review_upload_service.py``. Idempotente.

Executar:
    uv run python database/add_fap_review_upload_links_table.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import inspect

from main import app
from app.models import db, FapReviewUploadLink


def criar_tabela() -> bool:
    """Cria fap_review_upload_links se não existir. True se criou."""
    table = FapReviewUploadLink.__table__
    if inspect(db.engine).has_table(table.name):
        print(f'[OK] Tabela {table.name} já existe.')
        return False
    try:
        table.create(db.engine)
    except Exception as e:
        print(f'[ERRO] Falha ao criar {table.name}: {e}')
        raise
    print(f'[OK] Tabela {table.name} criada ({db.engine.dialect.name}).')
    return True


if __name__ == '__main__':
    with app.app_context():
        criar_tabela()
