"""Migration: recria fap_vigencia_cnpjs e restaura FK constraints.

Situação: a tabela fap_vigencia_cnpjs foi apagada acidentalmente.
Este script:
  1. Recria a tabela fap_vigencia_cnpjs
  2. Zera os IDs de vigência em benefits e benefit_manual_history
     (os vínculos serão refeitos automaticamente na próxima importação)
  3. Restaura FKs em benefits, benefit_manual_history e fap_contestation_cats
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db, FapVigenciaCnpj
from sqlalchemy import text


def run():
    with app.app_context():
        conn = db.engine.connect()
        dialect = db.engine.dialect.name

        # Step 1: create fap_vigencia_cnpjs via SQLAlchemy metadata
        print("1. Criando tabela fap_vigencia_cnpjs...")
        try:
            FapVigenciaCnpj.__table__.create(db.engine, checkfirst=True)
            print("   OK: fap_vigencia_cnpjs criada (ou já existia).")
        except Exception as e:
            print(f"   ERRO ao criar tabela: {e}")
            conn.close()
            return

        # Step 2: NULL out stale vigencia IDs (referenced records no longer exist)
        print("2. Zerando fap_vigencia_cnpj_id em benefits e benefit_manual_history...")
        for stmt in [
            "UPDATE benefits SET fap_vigencia_cnpj_id = NULL WHERE fap_vigencia_cnpj_id IS NOT NULL",
            "UPDATE benefit_manual_history SET vigencia_id = NULL WHERE vigencia_id IS NOT NULL",
            "UPDATE fap_contestation_cats SET vigencia_id = NULL WHERE vigencia_id IS NOT NULL",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f"   OK: {stmt[:70]}")
            except Exception as e:
                print(f"   SKIP/ERROR ({stmt[:60]}): {e}")

        # Step 3: restore FK constraints
        print("3. Restaurando FK constraints...")
        if dialect == 'mysql':
            fk_stmts = [
                ("benefits",
                 "ALTER TABLE benefits ADD CONSTRAINT fk_benefits_fap_vigencia "
                 "FOREIGN KEY (fap_vigencia_cnpj_id) REFERENCES fap_vigencia_cnpjs(id)"),
                ("benefit_manual_history",
                 "ALTER TABLE benefit_manual_history ADD CONSTRAINT fk_bmh_vigencia "
                 "FOREIGN KEY (vigencia_id) REFERENCES fap_vigencia_cnpjs(id)"),
                ("fap_contestation_cats",
                 "ALTER TABLE fap_contestation_cats ADD CONSTRAINT fk_fcc_vigencia "
                 "FOREIGN KEY (vigencia_id) REFERENCES fap_vigencia_cnpjs(id)"),
            ]
            for tbl, stmt in fk_stmts:
                # Drop existing FK first if it exists (idempotent)
                existing = conn.execute(text("""
                    SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = :tbl
                      AND REFERENCED_TABLE_NAME = 'fap_vigencia_cnpjs'
                """), {"tbl": tbl}).fetchall()
                for row in existing:
                    drop = f"ALTER TABLE {tbl} DROP FOREIGN KEY `{row[0]}`"
                    try:
                        conn.execute(text(drop))
                        conn.commit()
                    except Exception:
                        pass
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                    print(f"   OK: {stmt[:80]}")
                except Exception as e:
                    print(f"   SKIP/ERROR ({stmt[:60]}): {e}")
        else:
            print("   (SQLite: FKs gerenciadas via CREATE TABLE, nenhuma ação adicional)")

        conn.close()
        print("Concluído.")


if __name__ == '__main__':
    run()
