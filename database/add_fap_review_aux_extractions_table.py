"""
Cria a tabela fap_review_aux_extractions (cache das extrações de documentos
auxiliares do Revisor FAP, por hash de arquivo).

Uso:
    uv run python database/add_fap_review_aux_extractions_table.py
"""

import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from sqlalchemy import inspect

from app.models import db, FapReviewAuxExtraction
from main import app


def create_table():
    with app.app_context():
        inspector = inspect(db.engine)
        if 'fap_review_aux_extractions' in inspector.get_table_names():
            print('- tabela ja existe: fap_review_aux_extractions')
            return

        print('+ criando tabela: fap_review_aux_extractions')
        try:
            FapReviewAuxExtraction.__table__.create(db.engine)
            print('Migracao concluida com sucesso.')
        except Exception as exc:
            print(f'Erro durante a migracao: {exc}')
            raise


if __name__ == '__main__':
    create_table()
