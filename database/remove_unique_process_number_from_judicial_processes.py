"""
Script para remover unicidade global de process_number em judicial_processes.

Uso:
    python database/remove_unique_process_number_from_judicial_processes.py
"""

import sys
from pathlib import Path
from sqlalchemy import text

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db


def _drop_index(conn, index_name: str):
    dialect = db.engine.dialect.name
    if dialect == 'sqlite':
        conn.execute(text(f'DROP INDEX IF EXISTS {index_name}'))
    else:
        conn.execute(text(f'DROP INDEX {index_name} ON judicial_processes'))
    conn.commit()


def _drop_unique_constraint_if_exists(conn, inspector):
    unique_constraints = inspector.get_unique_constraints('judicial_processes')

    # Tenta remover constraints nomeadas (quando aplicável)
    for constraint in unique_constraints:
        name = constraint.get('name')
        cols = constraint.get('column_names') or []
        if not name or 'process_number' not in cols:
            continue

        try:
            conn.execute(text(f'ALTER TABLE judicial_processes DROP INDEX {name}'))
            conn.commit()
            print(f"✅ Constraint/índice único removido: {name}")
        except Exception:
            # Alguns bancos não aceitam esse comando para constraint nomeada.
            pass


def _drop_unique_index_if_exists(conn, inspector):
    indexes = inspector.get_indexes('judicial_processes')

    for idx in indexes:
        name = idx.get('name')
        cols = idx.get('column_names') or []
        unique = idx.get('unique', False)

        if not name:
            continue
        if 'process_number' not in cols or not unique:
            continue

        _drop_index(conn, name)
        print(f"✅ Índice único removido: {name}")


def _ensure_non_unique_index(conn, inspector):
    indexes = inspector.get_indexes('judicial_processes')
    existing = next((i for i in indexes if i.get('name') == 'idx_judicial_processes_process_number'), None)

    if existing:
        if existing.get('unique', False):
            _drop_index(conn, 'idx_judicial_processes_process_number')
            print('✅ Índice único antigo removido: idx_judicial_processes_process_number')
        else:
            print('ℹ️ Índice não único já existe: idx_judicial_processes_process_number')
            return

    conn.execute(text(
        'CREATE INDEX idx_judicial_processes_process_number ON judicial_processes (process_number)'
    ))
    conn.commit()
    print('✅ Índice não único criado: idx_judicial_processes_process_number')


def migrate():
    with app.app_context():
        try:
            print('🔄 Removendo unicidade global de process_number em judicial_processes...')
            inspector = db.inspect(db.engine)

            with db.engine.connect() as conn:
                _drop_unique_constraint_if_exists(conn, inspector)

                # Atualiza inspector após possíveis alterações
                inspector = db.inspect(db.engine)
                _drop_unique_index_if_exists(conn, inspector)

                # Atualiza inspector novamente para criação de índice normal
                inspector = db.inspect(db.engine)
                _ensure_non_unique_index(conn, inspector)

            print('✅ Migração concluída! process_number não é mais único globalmente.')

        except Exception as e:
            print(f'❌ Erro na migração: {str(e)}')
            raise


if __name__ == '__main__':
    migrate()
