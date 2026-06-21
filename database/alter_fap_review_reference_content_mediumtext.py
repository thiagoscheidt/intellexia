"""
Migration: altera content em fap_review_reference_versions de TEXT para MEDIUMTEXT.

Necessário pois o manual FAP ultrapassa o limite de 65KB do tipo TEXT no MySQL.

Execute: uv run python database/alter_fap_review_reference_content_mediumtext.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text


def run():
    with app.app_context():
        with db.engine.connect() as conn:
            result = conn.execute(text(
                "SELECT COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'fap_review_reference_versions' "
                "AND COLUMN_NAME = 'content'"
            ))
            row = result.fetchone()

            if row is None:
                print("❌ Tabela ou coluna não encontrada.")
                return

            current_type = row[0].upper()
            if "MEDIUMTEXT" in current_type or "LONGTEXT" in current_type:
                print(f"→ Coluna já é {current_type}, nenhuma alteração necessária.")
                return

            print(f"→ Tipo atual: {current_type} — alterando para MEDIUMTEXT...")
            conn.execute(text(
                "ALTER TABLE fap_review_reference_versions "
                "MODIFY COLUMN content MEDIUMTEXT NOT NULL"
            ))
            conn.commit()
            print("✓ Coluna content alterada para MEDIUMTEXT com sucesso.")


if __name__ == '__main__':
    try:
        run()
    except Exception as e:
        print(f"❌ Erro: {e}")
        raise
