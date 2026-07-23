"""Torna judicial_documents.event_id e .type opcionais (detecção automática de tipo pela IA)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect, text

from main import app
from app.models import db


def run():
    with app.app_context():
        inspector = inspect(db.engine)
        columns = {col['name']: col for col in inspector.get_columns('judicial_documents')}

        changed = 0
        if not columns['event_id']['nullable']:
            db.session.execute(text(
                'ALTER TABLE judicial_documents MODIFY event_id INTEGER NULL'))
            changed += 1
            print('[OK] event_id agora aceita NULL.')
        else:
            print('[OK] event_id já aceita NULL — nada a fazer.')

        if not columns['type']['nullable']:
            db.session.execute(text(
                'ALTER TABLE judicial_documents MODIFY type VARCHAR(100) NULL'))
            changed += 1
            print('[OK] type agora aceita NULL.')
        else:
            print('[OK] type já aceita NULL — nada a fazer.')

        db.session.commit()
        if not changed:
            print('[OK] Nenhuma alteração necessária.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(f'[ERRO] Falha ao afrouxar colunas: {exc}')
        raise
