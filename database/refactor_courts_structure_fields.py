"""
Script de migracao para refatorar a estrutura da tabela courts.

Campos-alvo:
- tribunal
- secao_judiciaria
- subsecao_judiciaria
- orgao_julgador

Uso:
    python database/refactor_courts_structure_fields.py
"""

import sys
from pathlib import Path

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db


def _column_exists(inspector, table_name, column_name):
    return any(col['name'] == column_name for col in inspector.get_columns(table_name))


def migrate():
    with app.app_context():
        try:
            inspector = inspect(db.engine)

            required_columns = [
                ('tribunal', 'VARCHAR(255)'),
                ('secao_judiciaria', 'VARCHAR(255)'),
                ('subsecao_judiciaria', 'VARCHAR(255)'),
                ('orgao_julgador', 'VARCHAR(255)'),
            ]

            for col_name, col_type in required_columns:
                if not _column_exists(inspector, 'courts', col_name):
                    print(f'🔄 Adicionando coluna {col_name} em courts...')
                    db.session.execute(text(f'ALTER TABLE courts ADD COLUMN {col_name} {col_type}'))
                    db.session.commit()

            print('🔄 Migrando dados legados para nova estrutura...')
            db.session.execute(
                text(
                    """
                    UPDATE courts
                    SET
                        tribunal = COALESCE(NULLIF(TRIM(tribunal), ''), NULLIF(TRIM(section), '')),
                        secao_judiciaria = COALESCE(NULLIF(TRIM(secao_judiciaria), ''), NULLIF(TRIM(section), '')),
                        orgao_julgador = COALESCE(NULLIF(TRIM(orgao_julgador), ''), NULLIF(TRIM(vara_name), '')),
                        subsecao_judiciaria = COALESCE(NULLIF(TRIM(subsecao_judiciaria), ''), NULLIF(TRIM(city), ''))
                    """
                )
            )
            db.session.commit()

            print('✅ Estrutura de courts refatorada com sucesso!')
        except Exception as e:
            db.session.rollback()
            print(f'❌ Erro na migracao: {e}')
            raise


if __name__ == '__main__':
    print('=' * 90)
    print('🔧 MIGRACAO: refactor courts structure fields')
    print('=' * 90)
    migrate()
    print('=' * 90)
