"""
Script de migração: Adicionar coluna request_type em judicial_process_benefits
Criado: 18/03/2026
Descrição: Adiciona a coluna request_type para registrar o tipo de pedido
  classificado pela IA para cada benefício extraído de petições iniciais.
  Valores possíveis: 'exclusao', 'inclusao', 'revisao'

Uso:
    uv run database/add_benefit_request_type.py
"""

import sys
from pathlib import Path
from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db


def migrate():
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            existing_cols = {col["name"] for col in inspector.get_columns("judicial_process_benefits")}

            with db.engine.connect() as conn:
                if "request_type" not in existing_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE judicial_process_benefits "
                            "ADD COLUMN request_type VARCHAR(20) NULL "
                            "COMMENT 'Tipo de pedido classificado pela IA: exclusao, inclusao ou revisao'"
                        )
                    )
                    conn.commit()
                    print("✅ Coluna 'request_type' adicionada.")

                    conn.execute(
                        text(
                            "CREATE INDEX ix_jpb_request_type "
                            "ON judicial_process_benefits (request_type)"
                        )
                    )
                    conn.commit()
                    print("✅ Índice 'ix_jpb_request_type' criado.")
                else:
                    print("ℹ️  Coluna 'request_type' já existe. Pulando.")

            print("✅ Migração concluída com sucesso!")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro na migração: {e}")
            raise


if __name__ == "__main__":
    print("=" * 70)
    print("🔧 MIGRAÇÃO: judicial_process_benefits - coluna request_type")
    print("=" * 70)
    migrate()
    print("=" * 70)
