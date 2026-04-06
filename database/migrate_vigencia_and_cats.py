"""Migration unificada: renomeia benefit_fap_vigencia_cnpjs → fap_vigencia_cnpjs
e adiciona vigencia_id / vigencia_year em fap_contestation_cats.

Idempotente — detecta o estado atual do banco e aplica apenas o que falta.

Cenários cobertos:
  A) Produção "limpa": benefit_fap_vigencia_cnpjs existe, fap_vigencia_cnpjs não existe.
     → Renomeia a tabela, adiciona colunas e FKs.

  B) Dev/acidente: fap_vigencia_cnpjs já existe (create_all a criou vazia),
     benefit_fap_vigencia_cnpjs também existe.
     → Drop da vazia, renomeia a que tem dados, adiciona colunas e FKs.

  C) Migração parcialmente aplicada: fap_vigencia_cnpjs existe e tem dados,
     benefit_fap_vigencia_cnpjs não existe mais.
     → Apenas adiciona colunas/FKs faltantes em fap_contestation_cats.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db
from sqlalchemy import text


# ─── helpers ─────────────────────────────────────────────────────────────────

def _table_exists(conn, table_name):
    dialect = db.engine.dialect.name
    if dialect == 'sqlite':
        row = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table_name},
        ).fetchone()
        return row is not None
    else:
        row = conn.execute(
            text("SELECT COUNT(*) FROM information_schema.TABLES "
                 "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"),
            {"t": table_name},
        ).fetchone()
        return (row[0] or 0) > 0


def _column_exists(conn, table_name, column_name):
    dialect = db.engine.dialect.name
    if dialect == 'sqlite':
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        return any(r[1] == column_name for r in rows)
    else:
        row = conn.execute(
            text("SELECT COUNT(*) FROM information_schema.COLUMNS "
                 "WHERE TABLE_SCHEMA = DATABASE() "
                 "AND TABLE_NAME = :t AND COLUMN_NAME = :c"),
            {"t": table_name, "c": column_name},
        ).fetchone()
        return (row[0] or 0) > 0


def _index_exists(conn, table_name, index_name):
    dialect = db.engine.dialect.name
    if dialect == 'sqlite':
        row = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"),
            {"n": index_name},
        ).fetchone()
        return row is not None
    else:
        row = conn.execute(
            text("SELECT COUNT(*) FROM information_schema.STATISTICS "
                 "WHERE TABLE_SCHEMA = DATABASE() "
                 "AND TABLE_NAME = :t AND INDEX_NAME = :n"),
            {"t": table_name, "n": index_name},
        ).fetchone()
        return (row[0] or 0) > 0


def _fk_names_to(conn, table, ref_table):
    """Return all FK constraint names on `table` that reference `ref_table` (MySQL only)."""
    rows = conn.execute(
        text("""
            SELECT CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = :tbl
              AND REFERENCED_TABLE_NAME = :ref
        """),
        {"tbl": table, "ref": ref_table},
    ).fetchall()
    return [r[0] for r in rows]


def _exec(conn, stmt, label=None):
    try:
        conn.execute(text(stmt))
        conn.commit()
        print(f"  OK:    {(label or stmt)[:90]}")
    except Exception as e:
        print(f"  SKIP:  {(label or stmt)[:80]} → {e}")


# ─── main ─────────────────────────────────────────────────────────────────────

def run():
    with app.app_context():
        conn = db.engine.connect()
        dialect = db.engine.dialect.name

        old_tbl = 'benefit_fap_vigencia_cnpjs'
        new_tbl = 'fap_vigencia_cnpjs'
        cats_tbl = 'fap_contestation_cats'
        child_tables = ('benefits', 'benefit_manual_history', cats_tbl)

        old_exists = _table_exists(conn, old_tbl)
        new_exists = _table_exists(conn, new_tbl)

        # ── Step 1: ensure fap_vigencia_cnpjs exists with data ──────────────
        print(f"\n[1] Verificando tabela {new_tbl}...")

        if old_exists and new_exists:
            # Both exist: new one was created empty by create_all() — drop it, rename old
            print(f"    Ambas existem. Descartando {new_tbl} vazia, renomeando {old_tbl}.")
            if dialect == 'mysql':
                for tbl in child_tables:
                    for fk in _fk_names_to(conn, tbl, new_tbl):
                        _exec(conn, f"ALTER TABLE {tbl} DROP FOREIGN KEY `{fk}`",
                              f"DROP FK {fk} em {tbl}")
                _exec(conn, f"DROP TABLE IF EXISTS {new_tbl}")
                for tbl in child_tables:
                    for fk in _fk_names_to(conn, tbl, old_tbl):
                        _exec(conn, f"ALTER TABLE {tbl} DROP FOREIGN KEY `{fk}`",
                              f"DROP FK {fk} em {tbl}")
                _exec(conn, f"RENAME TABLE {old_tbl} TO {new_tbl}")
            else:
                _exec(conn, f"DROP TABLE IF EXISTS {new_tbl}")
                _exec(conn, f"ALTER TABLE {old_tbl} RENAME TO {new_tbl}")

        elif old_exists and not new_exists:
            # Happy path (production): rename old to new
            print(f"    Renomeando {old_tbl} → {new_tbl}.")
            if dialect == 'mysql':
                for tbl in child_tables:
                    for fk in _fk_names_to(conn, tbl, old_tbl):
                        _exec(conn, f"ALTER TABLE {tbl} DROP FOREIGN KEY `{fk}`",
                              f"DROP FK {fk} em {tbl}")
                _exec(conn, f"RENAME TABLE {old_tbl} TO {new_tbl}")
            else:
                _exec(conn, f"ALTER TABLE {old_tbl} RENAME TO {new_tbl}")

        elif not old_exists and new_exists:
            # Only new exists — already renamed, nothing to do
            print(f"    {new_tbl} já existe. Nenhuma ação necessária.")
        else:
            # Neither exists — create from SQLAlchemy model
            print(f"    Nenhuma das duas existe. Criando {new_tbl} pelo modelo SQLAlchemy.")
            from app.models import FapVigenciaCnpj
            FapVigenciaCnpj.__table__.create(db.engine, checkfirst=True)
            print(f"  OK:    {new_tbl} criada.")

        # ── Step 2: add vigencia_id / vigencia_year to fap_contestation_cats ─
        print(f"\n[2] Adicionando colunas em {cats_tbl}...")

        if not _column_exists(conn, cats_tbl, 'vigencia_id'):
            if dialect == 'mysql':
                _exec(conn, f"ALTER TABLE {cats_tbl} ADD COLUMN vigencia_id INT NULL")
            else:
                _exec(conn, f"ALTER TABLE {cats_tbl} ADD COLUMN vigencia_id INTEGER")
        else:
            print(f"  SKIP:  vigencia_id já existe em {cats_tbl}")

        if not _column_exists(conn, cats_tbl, 'vigencia_year'):
            _exec(conn, f"ALTER TABLE {cats_tbl} ADD COLUMN vigencia_year VARCHAR(10) NULL")
        else:
            print(f"  SKIP:  vigencia_year já existe em {cats_tbl}")

        # ── Step 3: indexes ───────────────────────────────────────────────────
        print(f"\n[3] Criando índices em {cats_tbl}...")

        idx_id = 'ix_fap_contestation_cats_vigencia_id'
        idx_yr = 'ix_fap_contestation_cats_vigencia_year'

        if not _index_exists(conn, cats_tbl, idx_id):
            if dialect == 'mysql':
                _exec(conn, f"ALTER TABLE {cats_tbl} ADD INDEX {idx_id} (vigencia_id)")
            else:
                _exec(conn, f"CREATE INDEX IF NOT EXISTS {idx_id} ON {cats_tbl} (vigencia_id)")
        else:
            print(f"  SKIP:  índice {idx_id} já existe")

        if not _index_exists(conn, cats_tbl, idx_yr):
            if dialect == 'mysql':
                _exec(conn, f"ALTER TABLE {cats_tbl} ADD INDEX {idx_yr} (vigencia_year)")
            else:
                _exec(conn, f"CREATE INDEX IF NOT EXISTS {idx_yr} ON {cats_tbl} (vigencia_year)")
        else:
            print(f"  SKIP:  índice {idx_yr} já existe")

        # ── Step 4: FK constraints (MySQL only) ───────────────────────────────
        if dialect == 'mysql':
            print(f"\n[4] Restaurando FK constraints (MySQL)...")

            fk_defs = [
                ('benefits',             'fap_vigencia_cnpj_id', 'fk_benefits_fap_vigencia'),
                ('benefit_manual_history', 'vigencia_id',         'fk_bmh_vigencia'),
                (cats_tbl,               'vigencia_id',           'fk_fcc_vigencia'),
            ]

            for tbl, col, fk_name in fk_defs:
                # Drop any existing FK on this column pointing to fap_vigencia_cnpjs (idempotent)
                for existing_fk in _fk_names_to(conn, tbl, new_tbl):
                    _exec(conn, f"ALTER TABLE {tbl} DROP FOREIGN KEY `{existing_fk}`",
                          f"DROP FK {existing_fk} em {tbl}")
                _exec(
                    conn,
                    f"ALTER TABLE {tbl} ADD CONSTRAINT {fk_name} "
                    f"FOREIGN KEY ({col}) REFERENCES {new_tbl}(id)",
                )
        else:
            print("\n[4] SQLite: FKs declaradas inline, nenhuma ação adicional.")

        conn.close()
        print("\n✓ Migração concluída com sucesso.")


if __name__ == '__main__':
    run()
