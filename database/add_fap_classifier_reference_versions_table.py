"""Cria a tabela de versões da referência técnico-jurídica do classificador FAP."""

import os
import sys


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import FapContestationClassifierReferenceVersion, db


def create_fap_classifier_reference_versions_table():
    with app.app_context():
        print('=' * 80)
        print('CRIACAO DA TABELA: fap_contestation_classifier_reference_versions')
        print('=' * 80)

        FapContestationClassifierReferenceVersion.__table__.create(bind=db.engine, checkfirst=True)

        print('✅ Tabela criada/validada com sucesso.')


if __name__ == '__main__':
    create_fap_classifier_reference_versions_table()
