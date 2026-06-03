"""
Script de migração: adiciona identificador de documento por escritório em fap_review_executions.

Uso:
    uv run python database/add_fap_review_execution_document_identifier.py
"""

import hashlib
import sys
from pathlib import Path

from sqlalchemy import inspect, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import app
from app.models import db


TABLE_NAME = "fap_review_executions"
COLUMN_NAME = "law_firm_document_identifier"
INDEX_NAME = "ix_fap_review_executions_law_firm_document_identifier"


def compute_file_sha256(file_path: str | Path) -> str:
    """Calcula SHA-256 do arquivo salvo em disco."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as file_handle:
        while True:
            chunk = file_handle.read(8192)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def build_identifier(law_firm_id: int, file_path: str | Path) -> str:
    """Gera identificador determinístico escopado por escritório."""
    return f"lf{law_firm_id}_{compute_file_sha256(file_path)}"


def migrate() -> bool:
    with app.app_context():
        engine = db.engine
        inspector = inspect(engine)

        print("[FAP Review] Iniciando migração do identificador de documento...")

        if TABLE_NAME not in inspector.get_table_names():
            print(f"Tabela {TABLE_NAME} não encontrada.")
            return False

        columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}

        try:
            if COLUMN_NAME not in columns:
                print(f"Adicionando coluna {COLUMN_NAME} em {TABLE_NAME}...")
                db.session.execute(
                    text(
                        f"""
                        ALTER TABLE {TABLE_NAME}
                        ADD COLUMN {COLUMN_NAME} VARCHAR(96)
                        """
                    )
                )
            else:
                print(f"Coluna {COLUMN_NAME} já existe em {TABLE_NAME}.")

            print("Preenchendo identificadores faltantes...")
            rows = db.session.execute(
                text(
                    f"""
                    SELECT id, law_firm_id, main_document_path
                    FROM {TABLE_NAME}
                    WHERE ({COLUMN_NAME} IS NULL OR TRIM({COLUMN_NAME}) = '')
                      AND main_document_path IS NOT NULL
                      AND TRIM(main_document_path) <> ''
                    """
                )
            ).fetchall()

            updated_count = 0
            skipped_count = 0

            for row in rows:
                execution_id = int(row[0])
                law_firm_id = int(row[1])
                file_path = Path(str(row[2]).strip())

                if not file_path.exists() or not file_path.is_file():
                    skipped_count += 1
                    continue

                identifier = build_identifier(law_firm_id, file_path)
                db.session.execute(
                    text(
                        f"""
                        UPDATE {TABLE_NAME}
                        SET {COLUMN_NAME} = :identifier
                        WHERE id = :execution_id
                        """
                    ),
                    {"identifier": identifier, "execution_id": execution_id},
                )
                updated_count += 1

            print(f"Identificadores preenchidos: {updated_count}")
            if skipped_count:
                print(f"Registros ignorados por arquivo ausente: {skipped_count}")

            indexes = {index["name"] for index in inspector.get_indexes(TABLE_NAME)}
            if INDEX_NAME not in indexes:
                print(f"Criando índice {INDEX_NAME}...")
                db.session.execute(
                    text(
                        f"""
                        CREATE INDEX {INDEX_NAME}
                        ON {TABLE_NAME}(law_firm_id, {COLUMN_NAME})
                        """
                    )
                )
            else:
                print(f"Índice {INDEX_NAME} já existe.")

            db.session.commit()
            print("[FAP Review] Migração concluída com sucesso.")
            return True

        except Exception as error:
            db.session.rollback()
            print(f"Erro durante migração: {error}")
            return False


if __name__ == "__main__":
    success = migrate()
    raise SystemExit(0 if success else 1)
