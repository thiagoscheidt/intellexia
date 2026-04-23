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
