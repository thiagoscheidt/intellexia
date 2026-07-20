"""
Migração: Monitoramento de Comunicações (Comunica PJe / DJEN).

- Adiciona coluna `oab_uf` em `lawyers`
- Adiciona colunas `origin` e `discovery_status` em `judicial_processes`
- Cria tabelas `process_communications` e `communication_sync_states`

Idempotente: verifica existência prévia de colunas/tabelas antes de alterar.

Execute com:
    uv run python database/add_communications_monitoring.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect

from main import app
from app.models import db, ProcessCommunication, CommunicationSyncState


def _existing_columns(inspector, table):
    return {col['name'] for col in inspector.get_columns(table)}


def _add_column(conn, table, column_ddl, column_name, existing):
    if column_name in existing:
        print(f"• {table}.{column_name} já existe — nada a fazer.")
        return
    conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {column_ddl}"))
    print(f"✓ Coluna {table}.{column_name} criada.")


def run():
    with app.app_context():
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())

        with db.engine.connect() as conn:
            # lawyers.oab_uf
            lawyers_cols = _existing_columns(inspector, 'lawyers')
            _add_column(conn, 'lawyers', "oab_uf VARCHAR(2)", 'oab_uf', lawyers_cols)

            # judicial_processes.origin / discovery_status
            jp_cols = _existing_columns(inspector, 'judicial_processes')
            _add_column(
                conn, 'judicial_processes',
                "origin VARCHAR(20) NOT NULL DEFAULT 'manual'",
                'origin', jp_cols,
            )
            _add_column(
                conn, 'judicial_processes',
                "discovery_status VARCHAR(20) NOT NULL DEFAULT 'confirmed'",
                'discovery_status', jp_cols,
            )
            conn.commit()

        # Tabelas novas via metadata do SQLAlchemy (respeita dialeto SQLite/MySQL)
        for model in (ProcessCommunication, CommunicationSyncState):
            if model.__tablename__ in tables:
                print(f"• Tabela {model.__tablename__} já existe — nada a fazer.")
            else:
                model.__table__.create(db.engine)
                print(f"✓ Tabela {model.__tablename__} criada.")

        print("✓ Migração concluída: Monitoramento de Comunicações pronto.")


if __name__ == '__main__':
    run()
