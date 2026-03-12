"""
Script de migracao para adicionar court_id em judicial_processes
vinculando tribunal ao cadastro da tabela courts.

Uso:
    python database/add_court_id_to_judicial_processes.py
"""

import sys
from pathlib import Path

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, Court


def _normalize_name(value):
    return (value or '').strip()


def migrate():
    with app.app_context():
        try:
            inspector = inspect(db.engine)

            columns = {col['name'] for col in inspector.get_columns('judicial_processes')}
            if 'court_id' not in columns:
                print('🔄 Adicionando coluna court_id em judicial_processes...')
                db.session.execute(text('ALTER TABLE judicial_processes ADD COLUMN court_id INTEGER'))
                db.session.commit()
                print('✅ Coluna court_id adicionada com sucesso.')
            else:
                print('ℹ️ Coluna court_id já existe em judicial_processes.')

            inspector = inspect(db.engine)
            index_names = {idx['name'] for idx in inspector.get_indexes('judicial_processes')}
            if 'idx_judicial_processes_court_id' not in index_names:
                try:
                    db.session.execute(
                        text('CREATE INDEX idx_judicial_processes_court_id ON judicial_processes (court_id)')
                    )
                    db.session.commit()
                    print('✅ Índice idx_judicial_processes_court_id criado.')
                except Exception:
                    db.session.rollback()
                    print('ℹ️ Não foi possível criar índice automaticamente (pode já existir).')

            print('🔄 Migrando dados legados de tribunal para court_id...')
            rows = db.session.execute(
                text(
                    """
                    SELECT id, law_firm_id, tribunal
                    FROM judicial_processes
                    WHERE (court_id IS NULL OR court_id = 0)
                      AND tribunal IS NOT NULL
                      AND TRIM(tribunal) <> ''
                    """
                )
            ).fetchall()

            migrated = 0
            created_courts = 0

            for row in rows:
                tribunal_name = _normalize_name(row.tribunal)
                if not tribunal_name:
                    continue

                court = Court.query.filter_by(
                    law_firm_id=row.law_firm_id,
                    orgao_julgador=tribunal_name,
                ).first()

                if not court:
                    court = Court(
                        law_firm_id=row.law_firm_id,
                        tribunal=tribunal_name,
                        secao_judiciaria=tribunal_name,
                        orgao_julgador=tribunal_name,
                    )
                    db.session.add(court)
                    db.session.flush()
                    created_courts += 1

                db.session.execute(
                    text('UPDATE judicial_processes SET court_id = :court_id WHERE id = :process_id'),
                    {'court_id': court.id, 'process_id': row.id}
                )
                migrated += 1

            db.session.commit()
            print(f'✅ Processos migrados: {migrated}')
            print(f'✅ Tribunais (courts) criados: {created_courts}')
            print('✅ Migração concluída com sucesso!')

        except Exception as e:
            db.session.rollback()
            print(f'❌ Erro na migração: {e}')
            raise


if __name__ == '__main__':
    print('=' * 90)
    print('🔧 MIGRACAO: judicial_processes.court_id -> courts')
    print('=' * 90)
    migrate()
    print('=' * 90)
