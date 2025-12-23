"""
Script de migração para adicionar tabela petitions (Petições IA)
"""
import sqlite3
from pathlib import Path

# Caminho para o banco de dados
DB_PATH = Path(__file__).parent / 'instance' / 'intellexia.db'

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("🔄 Iniciando migração: Adicionar tabela petitions...")
    
    try:
        # Verificar se a tabela já existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='petitions'")
        if cursor.fetchone():
            print("✅ Tabela 'petitions' já existe!")
            return
        
        # Criar tabela petitions
        cursor.execute("""
            CREATE TABLE petitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                generated_by_user_id INTEGER,
                status VARCHAR(20) DEFAULT 'completed',
                error_message TEXT,
                context_summary TEXT,
                FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
            )
        """)
        
        # Criar índices
        cursor.execute("CREATE INDEX idx_petitions_case_id ON petitions(case_id)")
        cursor.execute("CREATE INDEX idx_petitions_version ON petitions(case_id, version)")
        
        conn.commit()
        print("✅ Tabela 'petitions' criada com sucesso!")
        print("✅ Índices criados com sucesso!")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Erro durante a migração: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
