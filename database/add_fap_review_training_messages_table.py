"""
Script de migração: cria a tabela de mensagens do treinamento interativo do FAP Review.

A sessão de conversa é uma FapReviewExecution (execution_type='training_chat');
esta tabela guarda as mensagens e as edições propostas em cada uma.

Uso:
    uv run python database/add_fap_review_training_messages_table.py
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import app
from app.models import db, FapReviewTrainingMessage


TABLE_NAME = 'fap_review_training_messages'


def migrate() -> bool:
    with app.app_context():
        try:
            print('[FAP Review] Iniciando migração da tabela de mensagens do treinamento interativo...')
            FapReviewTrainingMessage.__table__.create(bind=db.engine, checkfirst=True)
            db.session.commit()
            print(f'[FAP Review] Tabela {TABLE_NAME} verificada/criada com sucesso.')
            return True
        except Exception as error:
            db.session.rollback()
            print(f'Erro durante migração: {error}')
            return False


if __name__ == '__main__':
    success = migrate()
    raise SystemExit(0 if success else 1)
