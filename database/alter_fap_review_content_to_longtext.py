"""
Altera colunas de conteúdo do FAP Review para LONGTEXT no MySQL.

Uso:
  uv run python database/alter_fap_review_content_to_longtext.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from main import app, db


def run() -> None:
    with app.app_context():
        dialect = db.engine.dialect.name
        if dialect != "mysql":
            print(f"Dialeto atual: {dialect}. Migração LONGTEXT aplicada apenas em MySQL. Nada a fazer.")
            return

        statements = [
            "ALTER TABLE fap_review_reference_versions MODIFY COLUMN content LONGTEXT NOT NULL",
            "ALTER TABLE fap_review_prompt_versions MODIFY COLUMN content LONGTEXT NOT NULL",
        ]

        for stmt in statements:
            print(f"Executando: {stmt}")
            db.session.execute(text(stmt))

        db.session.commit()
        print("Migração concluída com sucesso.")


if __name__ == "__main__":
    run()
