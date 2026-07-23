"""Adiciona movement_ack_at/movement_ack_user_id em process_datajud_snapshots (ciente do radar)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect, text

from main import app
from app.models import db


def run():
    with app.app_context():
        inspector = inspect(db.engine)
        columns = {col['name'] for col in inspector.get_columns('process_datajud_snapshots')}
        statements = {
            'movement_ack_at': 'ALTER TABLE process_datajud_snapshots ADD COLUMN movement_ack_at DATETIME NULL',
            'movement_ack_user_id': 'ALTER TABLE process_datajud_snapshots ADD COLUMN movement_ack_user_id INTEGER NULL',
        }
        added = 0
        for column, ddl in statements.items():
            if column in columns:
                print(f'[OK] Coluna {column} já existe — nada a fazer.')
                continue
            db.session.execute(text(ddl))
            added += 1
            print(f'[OK] Coluna {column} adicionada.')
        db.session.commit()
        if not added:
            print('[OK] Nenhuma alteração necessária.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(f'[ERRO] Falha ao adicionar colunas de ciente: {exc}')
        raise
