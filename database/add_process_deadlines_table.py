"""Cria a tabela process_deadlines (prazos e audiências do Painel de Processos)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect

from main import app
from app.models import db, ProcessDeadline


def run():
    with app.app_context():
        inspector = inspect(db.engine)
        if inspector.has_table('process_deadlines'):
            print('[OK] Tabela process_deadlines já existe — nada a fazer.')
            return
        ProcessDeadline.__table__.create(db.engine)
        print('[OK] Tabela process_deadlines criada com sucesso.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(f'[ERRO] Falha ao criar process_deadlines: {exc}')
        raise
