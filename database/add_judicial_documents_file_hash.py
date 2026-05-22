"""
Script de migração: adicionar coluna file_hash em judicial_documents
com unicidade por processo para evitar documentos idênticos duplicados.

Uso:
    uv run python database/add_judicial_documents_file_hash.py
"""

import hashlib
import os
import sys
from pathlib import Path

from sqlalchemy import inspect, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import app
from app.models import db


UNIQUE_INDEX_NAME = "uq_judicial_documents_process_file_hash"


def compute_file_hash(file_path: str) -> str:
    """Calcula hash SHA-256 de um arquivo no disco."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as file_handle:
        while True:
            chunk = file_handle.read(8192)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def migrate() -> bool:
    with app.app_context():
        engine = db.engine
        inspector = inspect(engine)

        print("Iniciando migração: file_hash em judicial_documents")

        if "judicial_documents" not in inspector.get_table_names():
            print("Tabela judicial_documents não encontrada.")
            return False

        columns = {column["name"] for column in inspector.get_columns("judicial_documents")}

        try:
            if "file_hash" not in columns:
                print("Adicionando coluna judicial_documents.file_hash...")
                db.session.execute(
                    text(
                        """
                        ALTER TABLE judicial_documents
                        ADD COLUMN file_hash VARCHAR(64)
                        """
                    )
                )
            else:
                print("Coluna file_hash já existe em judicial_documents.")

            print("Preenchendo file_hash para documentos sem hash...")
            rows = db.session.execute(
                text(
                    """
                    SELECT jd.id, jd.file_path, jd.knowledge_base_id, kb.file_hash
                    FROM judicial_documents jd
                    LEFT JOIN knowledge_base kb ON kb.id = jd.knowledge_base_id
                    WHERE jd.file_hash IS NULL OR TRIM(jd.file_hash) = ''
                    """
                )
            ).fetchall()

            updated_count = 0
            missing_count = 0

            for row in rows:
                doc_id = int(row[0])
                file_path = str(row[1] or "").strip()
                kb_hash = str(row[3] or "").strip()

                resolved_hash = ""
                if kb_hash:
                    resolved_hash = kb_hash
                elif file_path and os.path.exists(file_path):
                    resolved_hash = compute_file_hash(file_path)

                if not resolved_hash:
                    missing_count += 1
                    continue

                db.session.execute(
                    text(
                        """
                        UPDATE judicial_documents
                        SET file_hash = :file_hash
                        WHERE id = :doc_id
                        """
                    ),
                    {"file_hash": resolved_hash, "doc_id": doc_id},
                )
                updated_count += 1

            print(f"Hashes preenchidos: {updated_count}")
            if missing_count:
                print(f"Sem hash por arquivo ausente/dado incompleto: {missing_count}")

            duplicate_groups = db.session.execute(
                text(
                    """
                    SELECT process_id, file_hash, COUNT(*) AS qty
                    FROM judicial_documents
                    WHERE file_hash IS NOT NULL AND TRIM(file_hash) <> ''
                    GROUP BY process_id, file_hash
                    HAVING COUNT(*) > 1
                    """
                )
            ).fetchall()

            duplicate_rows_cleared = 0
            for process_id, file_hash, _qty in duplicate_groups:
                duplicate_ids = db.session.execute(
                    text(
                        """
                        SELECT id
                        FROM judicial_documents
                        WHERE process_id = :process_id
                          AND file_hash = :file_hash
                        ORDER BY id ASC
                        """
                    ),
                    {"process_id": int(process_id), "file_hash": str(file_hash)},
                ).fetchall()

                ids_to_clear = [int(row[0]) for row in duplicate_ids[1:]]
                if not ids_to_clear:
                    continue

                for doc_id in ids_to_clear:
                    db.session.execute(
                        text(
                            """
                            UPDATE judicial_documents
                            SET file_hash = NULL
                            WHERE id = :doc_id
                            """
                        ),
                        {"doc_id": doc_id},
                    )
                    duplicate_rows_cleared += 1

            if duplicate_rows_cleared:
                print(
                    f"Duplicidades legadas tratadas (hash removido de registros repetidos): {duplicate_rows_cleared}"
                )

            indexes = {idx["name"] for idx in inspector.get_indexes("judicial_documents")}
            if UNIQUE_INDEX_NAME not in indexes:
                print(f"Criando índice único {UNIQUE_INDEX_NAME}...")
                db.session.execute(
                    text(
                        f"""
                        CREATE UNIQUE INDEX {UNIQUE_INDEX_NAME}
                        ON judicial_documents(process_id, file_hash)
                        """
                    )
                )
            else:
                print(f"Índice {UNIQUE_INDEX_NAME} já existe.")

            db.session.commit()
            print("Migração concluída com sucesso.")
            return True

        except Exception as error:
            db.session.rollback()
            print(f"Erro durante migração: {error}")
            return False


if __name__ == "__main__":
    success = migrate()
    raise SystemExit(0 if success else 1)
