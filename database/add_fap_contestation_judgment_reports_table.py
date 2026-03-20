"""
Script para adicionar a tabela fap_contestation_judgment_reports ao banco de dados existente.

Uso:
    uv run python database/add_fap_contestation_judgment_reports_table.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import FapContestationJudgmentReport, db


def add_fap_contestation_judgment_reports_table():
    """Cria a tabela fap_contestation_judgment_reports no banco."""
    with app.app_context():
        try:
            print('Criando tabela fap_contestation_judgment_reports...')

            FapContestationJudgmentReport.__table__.create(bind=db.engine, checkfirst=True)

            print('Tabela fap_contestation_judgment_reports criada com sucesso!')
            print('')
            print('Estrutura da tabela:')
            print('  - user_id              (FK -> users.id, NOT NULL)')
            print('  - law_firm_id          (FK -> law_firms.id, NOT NULL)')
            print('  - original_filename')
            print('  - file_path')
            print('  - file_size')
            print('  - file_type')
            print('  - status               (pending, processing, completed, error)')
            print('  - error_message')
            print('  - processed_at')
            print('  - imported_benefits_count')
            print('  - uploaded_at / updated_at')
            print('')
            print('Migração concluída!')

        except Exception as e:
            print(f'Erro ao criar tabela fap_contestation_judgment_reports: {str(e)}')
            raise


if __name__ == '__main__':
    add_fap_contestation_judgment_reports_table()
