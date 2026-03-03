"""
Script de migração: Adicionar colunas de status de processamento em knowledge_base
Criado: 03/03/2026
Descrição: Adiciona status, erro e data de processamento para arquivos da base de conhecimento
"""

import sys
from pathlib import Path

from sqlalchemy import inspect, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import app
from app.models import db


def migrate():
    """Executa a migração no banco configurado pela aplicação (SQLite/MySQL)."""

    with app.app_context():
        engine = db.engine
        inspector = inspect(engine)
        dialect = engine.dialect.name

        print("🔄 Iniciando migração: Adicionar status de processamento em knowledge_base")
        print(f"🗄️ Dialeto detectado: {dialect}")

        if 'knowledge_base' not in inspector.get_table_names():
            print("❌ Tabela 'knowledge_base' não encontrada.")
            return False

        columns = {column['name'] for column in inspector.get_columns('knowledge_base')}

        try:
            if 'processing_status' not in columns:
                print("📝 Adicionando coluna processing_status...")
                db.session.execute(text("""
                    ALTER TABLE knowledge_base
                    ADD COLUMN processing_status VARCHAR(20) DEFAULT 'pending'
                """))

            if 'processing_error_message' not in columns:
                print("📝 Adicionando coluna processing_error_message...")
                db.session.execute(text("""
                    ALTER TABLE knowledge_base
                    ADD COLUMN processing_error_message TEXT
                """))

            if 'processed_at' not in columns:
                print("📝 Adicionando coluna processed_at...")
                db.session.execute(text("""
                    ALTER TABLE knowledge_base
                    ADD COLUMN processed_at DATETIME
                """))

            print("📝 Normalizando registros existentes...")
            db.session.execute(text("""
                UPDATE knowledge_base
                SET processing_status = 'pending'
                WHERE processing_status IS NULL OR TRIM(processing_status) = ''
            """))

            existing_indexes = {idx['name'] for idx in inspector.get_indexes('knowledge_base')}
            if 'idx_knowledge_base_processing_status' not in existing_indexes:
                print("📊 Criando índice idx_knowledge_base_processing_status...")
                db.session.execute(text("""
                    CREATE INDEX idx_knowledge_base_processing_status
                    ON knowledge_base(processing_status)
                """))

            db.session.commit()
            print("✅ Migração concluída com sucesso!")
            return True

        except Exception as e:
            print(f"❌ Erro durante migração: {e}")
            db.session.rollback()
            return False


if __name__ == '__main__':
    print("=" * 70)
    print("MIGRAÇÃO: status de processamento em knowledge_base")
    print("=" * 70)

    success = migrate()

    if success:
        print("\n✅ Migração executada com sucesso!")
    else:
        print("\n❌ Migração falhou!")

    print("=" * 70)
