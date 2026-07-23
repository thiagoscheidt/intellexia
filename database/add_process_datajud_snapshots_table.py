"""Cria a tabela process_datajud_snapshots (cache da movimentação DataJud)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect

from main import app
from app.models import db, ProcessDatajudSnapshot


def run():
    with app.app_context():
        inspector = inspect(db.engine)
        if inspector.has_table('process_datajud_snapshots'):
            print('[OK] Tabela process_datajud_snapshots já existe — nada a fazer.')
            return
        ProcessDatajudSnapshot.__table__.create(db.engine)
        print('[OK] Tabela process_datajud_snapshots criada com sucesso.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(f'[ERRO] Falha ao criar process_datajud_snapshots: {exc}')
        raise
