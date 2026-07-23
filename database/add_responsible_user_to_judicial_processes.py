"""Adiciona judicial_processes.responsible_user_id (advogado responsável)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect, text

from main import app
from app.models import db


def run():
    with app.app_context():
        inspector = inspect(db.engine)
        columns = {col['name'] for col in inspector.get_columns('judicial_processes')}
        if 'responsible_user_id' in columns:
            print('[OK] Coluna responsible_user_id já existe — nada a fazer.')
            return
        db.session.execute(text(
            'ALTER TABLE judicial_processes ADD COLUMN responsible_user_id INTEGER NULL'
        ))
        db.session.commit()
        print('[OK] Coluna responsible_user_id adicionada.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(f'[ERRO] Falha ao adicionar responsible_user_id: {exc}')
        raise
