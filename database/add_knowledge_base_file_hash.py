"""
Script de migração: adicionar coluna file_hash na tabela knowledge_base

Uso:
    python database/add_knowledge_base_file_hash.py
"""

import sys
from pathlib import Path
import hashlib
import os

from sqlalchemy import inspect, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import app
from app.models import db


def compute_file_hash(file_path: str) -> str:
    """Calcula hash SHA-256 de um arquivo no disco."""
    hasher = hashlib.sha256()
    with open(file_path, 'rb') as file_handle:
        while True:
            chunk = file_handle.read(8192)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def migrate():
    """Executa migração para adicionar hash de arquivo em knowledge_base."""

    with app.app_context():
        engine = db.engine
        inspector = inspect(engine)

        print("🔄 Iniciando migração: adicionar file_hash em knowledge_base")

        if 'knowledge_base' not in inspector.get_table_names():
            print("❌ Tabela 'knowledge_base' não encontrada.")
            return False

        columns = {column['name'] for column in inspector.get_columns('knowledge_base')}

        try:
            if 'file_hash' not in columns:
                print("📝 Adicionando coluna file_hash...")
                db.session.execute(text("""
                    ALTER TABLE knowledge_base
                    ADD COLUMN file_hash VARCHAR(64)
                """))
            else:
                print("⚠️ Coluna file_hash já existe.")

            print("🧮 Preenchendo hash para arquivos já existentes...")
            rows = db.session.execute(text("""
                SELECT id, file_path
                FROM knowledge_base
                WHERE file_hash IS NULL OR TRIM(file_hash) = ''
            """)).fetchall()

            updated_count = 0
            skipped_count = 0

            for row in rows:
                record_id = row[0]
                file_path = row[1]

                if not file_path or not os.path.exists(file_path):
                    skipped_count += 1
                    continue

                file_hash = compute_file_hash(file_path)
                db.session.execute(
                    text("UPDATE knowledge_base SET file_hash = :file_hash WHERE id = :record_id"),
                    {'file_hash': file_hash, 'record_id': record_id}
                )
                updated_count += 1

            print(f"✅ Hash preenchido para {updated_count} registro(s).")
            if skipped_count:
                print(f"⚠️ {skipped_count} registro(s) ignorado(s) por arquivo ausente no disco.")

            existing_indexes = {idx['name'] for idx in inspector.get_indexes('knowledge_base')}
            if 'idx_knowledge_base_file_hash' not in existing_indexes:
                print("📊 Criando índice idx_knowledge_base_file_hash...")
                db.session.execute(text("""
                    CREATE INDEX idx_knowledge_base_file_hash
                    ON knowledge_base(file_hash)
                """))
            else:
                print("⚠️ Índice idx_knowledge_base_file_hash já existe.")

            db.session.commit()
            print("✅ Migração concluída com sucesso!")
            return True

        except Exception as error:
            print(f"❌ Erro durante migração: {error}")
            db.session.rollback()
            return False


if __name__ == '__main__':
    print("=" * 70)
    print("MIGRAÇÃO: adicionar file_hash em knowledge_base")
    print("=" * 70)

    success = migrate()

    if success:
        print("\n✅ Migração executada com sucesso!")
    else:
        print("\n❌ Migração falhou!")

    print("=" * 70)
