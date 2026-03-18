"""
Script de migração: Adicionar campos extras em judicial_processes
Criado: 17/03/2026
Descrição: Adiciona colunas extraídas automaticamente pela IA:
  - process_class  (VARCHAR 255) - Classe processual
  - valor_causa_texto (VARCHAR 100) - Valor da causa em formato textual original
  - assuntos (TEXT/JSON) - Lista de assuntos/temas do processo
  - segredo_justica (BOOLEAN) - Segredo de justiça
  - justica_gratuita (BOOLEAN) - Justiça gratuita requerida/deferida
  - liminar_tutela (BOOLEAN) - Pedido de liminar ou tutela antecipada

Uso:
    uv run database/add_process_extra_fields.py
"""

import sys
from pathlib import Path
from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db

NEW_COLUMNS = [
    ("process_class",     "VARCHAR(255)"),
    ("valor_causa_texto", "VARCHAR(100)"),
    ("assuntos",          "TEXT"),
    ("segredo_justica",   "BOOLEAN"),
    ("justica_gratuita",  "BOOLEAN"),
    ("liminar_tutela",    "BOOLEAN"),
]


def migrate():
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            existing_cols = {col["name"] for col in inspector.get_columns("judicial_processes")}

            with db.engine.connect() as conn:
                for col_name, col_type in NEW_COLUMNS:
                    if col_name not in existing_cols:
                        conn.execute(
                            text(
                                f"ALTER TABLE judicial_processes ADD COLUMN {col_name} {col_type}"
                            )
                        )
                        conn.commit()
                        print(f"✅ Coluna '{col_name}' adicionada.")
                    else:
                        print(f"ℹ️  Coluna '{col_name}' já existe. Pulando.")

            print("✅ Migração concluída com sucesso!")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro na migração: {e}")
            raise


if __name__ == "__main__":
    print("=" * 70)
    print("🔧 MIGRAÇÃO: judicial_processes - campos extras (IA)")
    print("=" * 70)
    migrate()
    print("=" * 70)
