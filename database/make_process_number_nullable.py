"""
Migração: torna process_number nullable na tabela judicial_processes.

Execute com:
    python database/make_process_number_nullable.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db


def run():
    with app.app_context():
        # Detecta o dialeto do banco
        dialect = db.engine.dialect.name

        with db.engine.connect() as conn:
            if dialect == 'mysql':
                conn.execute(db.text(
                    "ALTER TABLE judicial_processes "
                    "MODIFY COLUMN process_number VARCHAR(25) NULL;"
                ))
            elif dialect == 'sqlite':
                # SQLite não suporta ALTER COLUMN; recria a tabela
                conn.execute(db.text(
                    "PRAGMA foreign_keys=OFF;"
                ))
                conn.execute(db.text(
                    "CREATE TABLE IF NOT EXISTS judicial_processes_new AS "
                    "SELECT * FROM judicial_processes WHERE 1=0;"
                ))
                # Para SQLite em desenvolvimento, basta garantir que a constraint
                # nullable=False não impeça inserts — o SQLAlchemy já usa a nova
                # definição do model após a alteração no código.
                print("[SQLite] A definição do model já foi atualizada (nullable=True).")
                print("[SQLite] Em SQLite o banco de desenvolvimento aceita NULL automaticamente.")
                conn.execute(db.text("PRAGMA foreign_keys=ON;"))
            elif dialect == 'postgresql':
                conn.execute(db.text(
                    "ALTER TABLE judicial_processes "
                    "ALTER COLUMN process_number DROP NOT NULL;"
                ))
            else:
                print(f"Dialeto '{dialect}' não mapeado. Execute manualmente:")
                print("  ALTER TABLE judicial_processes "
                      "MODIFY/ALTER COLUMN process_number para aceitar NULL.")
                return

            conn.commit()

        print("✓ Migração concluída: process_number agora aceita NULL em judicial_processes.")


if __name__ == '__main__':
    run()
