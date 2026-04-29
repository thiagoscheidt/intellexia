"""
Migration: corrige FK de benefits.fap_vigencia_cnpj_id

O FK original apontava para benefit_fap_vigencia_cnpjs (tabela antiga).
O modelo FapVigenciaCnpj foi renomeado para usar fap_vigencia_cnpjs.
Este script dropa o FK antigo e cria um novo apontando para fap_vigencia_cnpjs.

Uso:
    uv run python database/fix_benefits_fap_vigencia_cnpj_fk.py
"""

import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db
from main import app


def _count_orphans(conn):
    row = conn.execute(
        db.text(
            """
            SELECT COUNT(*)
            FROM benefits b
            LEFT JOIN fap_vigencia_cnpjs v ON v.id = b.fap_vigencia_cnpj_id
            WHERE b.fap_vigencia_cnpj_id IS NOT NULL
              AND v.id IS NULL
            """
        )
    ).fetchone()
    return int(row[0] or 0)


def migrate():
    with app.app_context():
        db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        is_mysql = "mysql" in db_uri

        if not is_mysql:
            print("Este script aplica-se apenas ao MySQL. Pulando.")
            return

        with db.engine.connect() as conn:
            trans = conn.begin()
            try:
                # 1. Verifica FK atual apontando para benefit_fap_vigencia_cnpjs
                old_fk = conn.execute(
                    db.text(
                        """
                        SELECT CONSTRAINT_NAME
                        FROM information_schema.KEY_COLUMN_USAGE
                        WHERE TABLE_SCHEMA = DATABASE()
                          AND TABLE_NAME = 'benefits'
                          AND COLUMN_NAME = 'fap_vigencia_cnpj_id'
                          AND REFERENCED_TABLE_NAME = 'benefit_fap_vigencia_cnpjs'
                        """
                    )
                ).fetchone()

                if old_fk:
                    constraint_name = old_fk[0]
                    print(f"+ dropando FK antigo: {constraint_name} (-> benefit_fap_vigencia_cnpjs)")
                    conn.execute(
                        db.text(f"ALTER TABLE benefits DROP FOREIGN KEY `{constraint_name}`")
                    )
                else:
                    print("- FK antigo não encontrado (-> benefit_fap_vigencia_cnpjs), pulando drop")

                # 1.5 Corrige referências órfãs antes de criar o novo FK
                # Primeiro tenta remapear IDs antigos -> novos quando a tabela antiga existe.
                orphan_count = _count_orphans(conn)
                if orphan_count > 0:
                    print(f"+ encontrados {orphan_count} registros órfãos em benefits.fap_vigencia_cnpj_id")

                    old_table_exists = conn.execute(
                        db.text(
                            """
                            SELECT COUNT(*)
                            FROM information_schema.TABLES
                            WHERE TABLE_SCHEMA = DATABASE()
                              AND TABLE_NAME = 'benefit_fap_vigencia_cnpjs'
                            """
                        )
                    ).fetchone()
                    old_table_exists = int(old_table_exists[0] or 0) > 0

                    if old_table_exists:
                        print("+ tentando remapear órfãos usando benefit_fap_vigencia_cnpjs -> fap_vigencia_cnpjs")
                        conn.execute(
                            db.text(
                                """
                                UPDATE benefits b
                                JOIN benefit_fap_vigencia_cnpjs old_v ON old_v.id = b.fap_vigencia_cnpj_id
                                JOIN fap_vigencia_cnpjs new_v
                                  ON new_v.law_firm_id = old_v.law_firm_id
                                 AND new_v.employer_cnpj = old_v.employer_cnpj
                                 AND new_v.vigencia_year = old_v.vigencia_year
                                SET b.fap_vigencia_cnpj_id = new_v.id
                                WHERE b.fap_vigencia_cnpj_id IS NOT NULL
                                  AND NOT EXISTS (
                                      SELECT 1
                                      FROM fap_vigencia_cnpjs v
                                      WHERE v.id = b.fap_vigencia_cnpj_id
                                  )
                                """
                            )
                        )

                    orphan_count_after_remap = _count_orphans(conn)
                    if orphan_count_after_remap > 0:
                        print(
                            f"+ ainda há {orphan_count_after_remap} órfãos; definindo fap_vigencia_cnpj_id = NULL para manter integridade"
                        )
                        conn.execute(
                            db.text(
                                """
                                UPDATE benefits b
                                LEFT JOIN fap_vigencia_cnpjs v ON v.id = b.fap_vigencia_cnpj_id
                                SET b.fap_vigencia_cnpj_id = NULL
                                WHERE b.fap_vigencia_cnpj_id IS NOT NULL
                                  AND v.id IS NULL
                                """
                            )
                        )

                    orphan_count_final = _count_orphans(conn)
                    print(f"- órfãos restantes após saneamento: {orphan_count_final}")

                # 2. Verifica se o novo FK já existe apontando para fap_vigencia_cnpjs
                new_fk = conn.execute(
                    db.text(
                        """
                        SELECT CONSTRAINT_NAME
                        FROM information_schema.KEY_COLUMN_USAGE
                        WHERE TABLE_SCHEMA = DATABASE()
                          AND TABLE_NAME = 'benefits'
                          AND COLUMN_NAME = 'fap_vigencia_cnpj_id'
                          AND REFERENCED_TABLE_NAME = 'fap_vigencia_cnpjs'
                        """
                    )
                ).fetchone()

                if not new_fk:
                    print("+ criando novo FK: fk_benefits_fap_vigencia_cnpj (-> fap_vigencia_cnpjs)")
                    conn.execute(
                        db.text(
                            """
                            ALTER TABLE benefits
                            ADD CONSTRAINT fk_benefits_fap_vigencia_cnpj
                            FOREIGN KEY (fap_vigencia_cnpj_id)
                            REFERENCES fap_vigencia_cnpjs(id)
                            """
                        )
                    )
                else:
                    print("- novo FK já existe (-> fap_vigencia_cnpjs), pulando criação")

                trans.commit()
                print("Migração concluída com sucesso.")

            except Exception as e:
                trans.rollback()
                print(f"Erro na migração: {e}")
                raise


if __name__ == "__main__":
    migrate()
