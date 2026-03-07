"""
Script de migração para criar tabela de polos passivos (réus) e
adicionar colunas de polo ativo/passivo em judicial_processes.

Uso:
    python database/add_judicial_parties_to_processes.py
"""

import sys
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, LawFirm, JudicialDefendant

DEFAULT_DEFENDANT_NAME = 'UNIÃO - FAZENDA NACIONAL'


def _column_exists(inspector, table_name, column_name):
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _index_exists(inspector, table_name, index_name):
    indexes = inspector.get_indexes(table_name)
    return any(index.get('name') == index_name for index in indexes)


def migrate():
    with app.app_context():
        try:
            print('🔄 Garantindo criação da tabela judicial_defendants...')
            JudicialDefendant.__table__.create(bind=db.engine, checkfirst=True)

            inspector = db.inspect(db.engine)

            print('🔄 Verificando colunas em judicial_processes...')
            with db.engine.connect() as conn:
                if not _column_exists(inspector, 'judicial_processes', 'plaintiff_client_id'):
                    conn.execute(text('ALTER TABLE judicial_processes ADD COLUMN plaintiff_client_id INTEGER'))
                    conn.commit()
                    print('✅ Coluna plaintiff_client_id adicionada')
                else:
                    print('ℹ️ Coluna plaintiff_client_id já existe')

            inspector = db.inspect(db.engine)
            with db.engine.connect() as conn:
                if not _column_exists(inspector, 'judicial_processes', 'defendant_id'):
                    conn.execute(text('ALTER TABLE judicial_processes ADD COLUMN defendant_id INTEGER'))
                    conn.commit()
                    print('✅ Coluna defendant_id adicionada')
                else:
                    print('ℹ️ Coluna defendant_id já existe')

            inspector = db.inspect(db.engine)
            with db.engine.connect() as conn:
                if not _index_exists(inspector, 'judicial_processes', 'idx_judicial_processes_plaintiff_client_id'):
                    conn.execute(text('CREATE INDEX idx_judicial_processes_plaintiff_client_id ON judicial_processes (plaintiff_client_id)'))
                    conn.commit()
                    print('✅ Índice idx_judicial_processes_plaintiff_client_id criado')
                else:
                    print('ℹ️ Índice idx_judicial_processes_plaintiff_client_id já existe')

            inspector = db.inspect(db.engine)
            with db.engine.connect() as conn:
                if not _index_exists(inspector, 'judicial_processes', 'idx_judicial_processes_defendant_id'):
                    conn.execute(text('CREATE INDEX idx_judicial_processes_defendant_id ON judicial_processes (defendant_id)'))
                    conn.commit()
                    print('✅ Índice idx_judicial_processes_defendant_id criado')
                else:
                    print('ℹ️ Índice idx_judicial_processes_defendant_id já existe')

            law_firms = LawFirm.query.all()
            created_defaults = 0

            for law_firm in law_firms:
                exists_default = JudicialDefendant.query.filter_by(
                    law_firm_id=law_firm.id,
                    name=DEFAULT_DEFENDANT_NAME
                ).first()
                if exists_default:
                    continue

                db.session.add(
                    JudicialDefendant(
                        law_firm_id=law_firm.id,
                        name=DEFAULT_DEFENDANT_NAME,
                        is_active=True,
                    )
                )
                created_defaults += 1

            db.session.commit()
            print('✅ Migração concluída com sucesso!')
            print(f'✅ Réus padrão criados: {created_defaults}')

        except Exception as e:
            db.session.rollback()
            print(f'❌ Erro na migração: {e}')
            raise


if __name__ == '__main__':
    print('=' * 80)
    print('🔧 MIGRAÇÃO: Tabela de polos passivos + colunas de partes no processo')
    print('=' * 80)
    migrate()
    print('=' * 80)
