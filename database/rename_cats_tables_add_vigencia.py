"""Migration: renomeia benefit_fap_vigencia_cnpjs → fap_vigencia_cnpjs
e adiciona colunas vigencia_id / vigencia_year em fap_contestation_cats.

Tabelas renomeadas:
  benefit_fap_vigencia_cnpjs  → fap_vigencia_cnpjs

Novas colunas em `fap_contestation_cats`:
  vigencia_id   INTEGER NULL FK → fap_vigencia_cnpjs.id
  vigencia_year VARCHAR(10) NULL INDEX
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db


def run():
    with app.app_context():
        conn = db.engine.connect()
        dialect = db.engine.dialect.name  # 'sqlite' or 'mysql'

        if dialect == 'sqlite':
            _run_sqlite(conn)
        else:
            _run_mysql(conn)

        conn.close()
        print('Migration completed successfully.')


def _run_sqlite(conn):
    from sqlalchemy import text

    stmts = [
        # Drop the empty table that create_all() may have created
        'DROP TABLE IF EXISTS fap_vigencia_cnpjs',

        # Rename old table (with all data) to new name
        'ALTER TABLE benefit_fap_vigencia_cnpjs RENAME TO fap_vigencia_cnpjs',

        # Add new columns to fap_contestation_cats
        'ALTER TABLE fap_contestation_cats ADD COLUMN vigencia_id INTEGER REFERENCES fap_vigencia_cnpjs(id)',
        'ALTER TABLE fap_contestation_cats ADD COLUMN vigencia_year VARCHAR(10)',

        # Indexes
        'CREATE INDEX IF NOT EXISTS ix_fap_contestation_cats_vigencia_id ON fap_contestation_cats (vigencia_id)',
        'CREATE INDEX IF NOT EXISTS ix_fap_contestation_cats_vigencia_year ON fap_contestation_cats (vigencia_year)',
    ]

    for stmt in stmts:
        try:
            conn.execute(text(stmt))
            conn.commit()
            print(f'  OK: {stmt[:80]}')
        except Exception as e:
            print(f'  SKIP/ERROR ({stmt[:60]}): {e}')


def _run_mysql(conn):
    from sqlalchemy import text

    # Helper to get all FK constraint names on a table referencing a given parent
    def get_fk_names(conn, table, ref_table):
        result = conn.execute(text("""
            SELECT CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :tbl
              AND REFERENCED_TABLE_NAME = :ref
        """), {"tbl": table, "ref": ref_table})
        return [row[0] for row in result.fetchall()]

    # Step 1: Drop all FKs pointing to benefit_fap_vigencia_cnpjs so we can rename/drop
    for parent_table in ('benefits', 'benefit_manual_history', 'fap_contestation_cats'):
        for fk in get_fk_names(conn, parent_table, 'benefit_fap_vigencia_cnpjs'):
            stmt = f'ALTER TABLE {parent_table} DROP FOREIGN KEY `{fk}`'
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f'  OK: {stmt}')
            except Exception as e:
                print(f'  SKIP/ERROR ({stmt}): {e}')

    # Step 2: Drop the empty fap_vigencia_cnpjs table that create_all() may have created
    # (also drop its FKs first if any child tables reference it)
    for parent_table in ('benefits', 'benefit_manual_history', 'fap_contestation_cats'):
        for fk in get_fk_names(conn, parent_table, 'fap_vigencia_cnpjs'):
            stmt = f'ALTER TABLE {parent_table} DROP FOREIGN KEY `{fk}`'
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f'  OK: {stmt}')
            except Exception as e:
                print(f'  SKIP/ERROR ({stmt}): {e}')

    stmts = [
        # Step 3: Drop empty new table, rename old table (with data) to new name
        'DROP TABLE IF EXISTS fap_vigencia_cnpjs',
        'RENAME TABLE benefit_fap_vigencia_cnpjs TO fap_vigencia_cnpjs',

        # Step 4: Re-add FK constraints pointing to new table name
        'ALTER TABLE benefits ADD CONSTRAINT fk_benefits_fap_vigencia FOREIGN KEY (fap_vigencia_cnpj_id) REFERENCES fap_vigencia_cnpjs(id)',
        'ALTER TABLE benefit_manual_history ADD CONSTRAINT fk_bmh_vigencia FOREIGN KEY (vigencia_id) REFERENCES fap_vigencia_cnpjs(id)',

        # Step 5: Add new columns to fap_contestation_cats
        'ALTER TABLE fap_contestation_cats ADD COLUMN vigencia_id INT NULL',
        'ALTER TABLE fap_contestation_cats ADD COLUMN vigencia_year VARCHAR(10) NULL',
        'ALTER TABLE fap_contestation_cats ADD INDEX ix_fap_contestation_cats_vigencia_id (vigencia_id)',
        'ALTER TABLE fap_contestation_cats ADD INDEX ix_fap_contestation_cats_vigencia_year (vigencia_year)',
        'ALTER TABLE fap_contestation_cats ADD CONSTRAINT fk_fcc_vigencia FOREIGN KEY (vigencia_id) REFERENCES fap_vigencia_cnpjs(id)',
    ]

    for stmt in stmts:
        try:
            conn.execute(text(stmt))
            conn.commit()
            print(f'  OK: {stmt[:80]}')
        except Exception as e:
            print(f'  SKIP/ERROR ({stmt[:60]}): {e}')


if __name__ == '__main__':
    run()
