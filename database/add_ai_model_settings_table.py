"""Cria a tabela ai_model_settings (modelo de IA por agente e por escritório)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect

from main import app
from app.models import db, AiModelSetting


def run():
    with app.app_context():
        inspector = inspect(db.engine)
        if inspector.has_table('ai_model_settings'):
            print('[OK] Tabela ai_model_settings já existe — nada a fazer.')
            return
        AiModelSetting.__table__.create(db.engine)
        print('[OK] Tabela ai_model_settings criada com sucesso.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print(f'[ERRO] Falha ao criar ai_model_settings: {exc}')
        raise
