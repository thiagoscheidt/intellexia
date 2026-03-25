"""
Script para adicionar a coluna publication_datetime na tabela benefit_fap_source_history.

Uso:
    uv run python database/add_publication_datetime_to_benefit_fap_source_history.py
"""

import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.models import db
from main import app


def add_publication_datetime_column():
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            columns = [col["name"] for col in inspector.get_columns("benefit_fap_source_history")]

            if "publication_datetime" in columns:
                print("ℹ️  A coluna 'publication_datetime' já existe em 'benefit_fap_source_history'")
            else:
                with db.engine.connect() as conn:
                    conn.execute(
                        text("ALTER TABLE benefit_fap_source_history ADD COLUMN publication_datetime DATETIME NULL")
                    )
                    conn.commit()
                print("✓ Coluna 'publication_datetime' adicionada com sucesso")

            db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
            is_mysql = "mysql" in db_uri

            if is_mysql:
                with db.engine.connect() as conn:
                    existing_indexes = {
                        row[2]
                        for row in conn.execute(text("SHOW INDEX FROM benefit_fap_source_history")).fetchall()
                    }
                    if "ix_bfsh_publication_datetime" not in existing_indexes:
                        conn.execute(
                            text(
                                "CREATE INDEX ix_bfsh_publication_datetime "
                                "ON benefit_fap_source_history (publication_datetime)"
                            )
                        )
                        conn.commit()
                        print("✓ Índice 'ix_bfsh_publication_datetime' criado")
                    else:
                        print("ℹ️  Índice 'ix_bfsh_publication_datetime' já existe")
            else:
                with db.engine.connect() as conn:
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_bfsh_publication_datetime "
                            "ON benefit_fap_source_history (publication_datetime)"
                        )
                    )
                    conn.commit()
                print("✓ Índice 'ix_bfsh_publication_datetime' garantido")

            print("✅ Migração concluída!")
        except Exception as exc:
            print(f"✗ Erro ao adicionar publication_datetime: {exc}")
            raise


if __name__ == "__main__":
    print("🔄 Adicionando publication_datetime em benefit_fap_source_history...")
    add_publication_datetime_column()
    print("Migração finalizada.")
