"""Cria a tabela de configurações do classificador FAP."""

import os
import sys


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import FapContestationClassifierSetting, db


def create_fap_classifier_settings_table():
    with app.app_context():
        print('=' * 80)
        print('CRIACAO DA TABELA: fap_contestation_classifier_settings')
        print('=' * 80)

        FapContestationClassifierSetting.__table__.create(bind=db.engine, checkfirst=True)

        print('✅ Tabela criada/validada com sucesso.')


if __name__ == '__main__':
    create_fap_classifier_settings_table()