"""
Script de migração: Adicionar colunas de status de processamento em knowledge_base
Criado: 03/03/2026
Descrição: Adiciona status, erro e data de processamento para arquivos da base de conhecimento
"""

import sqlite3
import os

DB_PATH = os.path.join('instance', 'intellexia.db')


def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def migrate():
    """Executa a migração do banco de dados"""

    if not os.path.exists(DB_PATH):
        print(f"❌ Banco de dados não encontrado em: {DB_PATH}")
        return False

    print("🔄 Iniciando migração: Adicionar status de processamento em knowledge_base")
    print(f"📁 Banco de dados: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_base'")
        if not cursor.fetchone():
            print("❌ Tabela 'knowledge_base' não encontrada.")
            return False

        if not column_exists(cursor, 'knowledge_base', 'processing_status'):
            print("📝 Adicionando coluna processing_status...")
            cursor.execute("ALTER TABLE knowledge_base ADD COLUMN processing_status VARCHAR(20) DEFAULT 'pending'")

        if not column_exists(cursor, 'knowledge_base', 'processing_error_message'):
            print("📝 Adicionando coluna processing_error_message...")
            cursor.execute("ALTER TABLE knowledge_base ADD COLUMN processing_error_message TEXT")

        if not column_exists(cursor, 'knowledge_base', 'processed_at'):
            print("📝 Adicionando coluna processed_at...")
            cursor.execute("ALTER TABLE knowledge_base ADD COLUMN processed_at DATETIME")

        print("📝 Normalizando registros existentes...")
        cursor.execute("""
            UPDATE knowledge_base
            SET processing_status = 'pending'
            WHERE processing_status IS NULL OR TRIM(processing_status) = ''
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_base_processing_status
            ON knowledge_base(processing_status)
        """)

        conn.commit()

        print("✅ Migração concluída com sucesso!")
        return True

    except sqlite3.Error as e:
        print(f"❌ Erro durante migração: {e}")
        conn.rollback()
        return False

    finally:
        conn.close()


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
