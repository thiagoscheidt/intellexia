"""
Script de migração: Adicionar tabela judicial_appeals
Criado: 26/02/2026
Descrição: Cria a tabela para armazenar recursos judiciais gerados por IA
"""

import sqlite3
import os
from datetime import datetime

# Caminho do banco de dados
DB_PATH = os.path.join('instance', 'intellexia.db')

def migrate():
    """Executa a migração do banco de dados"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Banco de dados não encontrado em: {DB_PATH}")
        return False
    
    print("🔄 Iniciando migração: Adicionar tabela judicial_appeals")
    print(f"📁 Banco de dados: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Verificar se a tabela já existe
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='judicial_appeals'
        """)
        
        if cursor.fetchone():
            print("⚠️  Tabela 'judicial_appeals' já existe. Pulando migração.")
            return True
        
        # Criar tabela judicial_appeals
        print("📝 Criando tabela judicial_appeals...")
        cursor.execute("""
            CREATE TABLE judicial_appeals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                law_firm_id INTEGER NOT NULL,
                sentence_analysis_id INTEGER NOT NULL,
                appeal_type VARCHAR(100) NOT NULL,
                user_notes TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                generated_content TEXT,
                generated_file_path VARCHAR(500),
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (law_firm_id) REFERENCES law_firms (id) ON DELETE CASCADE,
                FOREIGN KEY (sentence_analysis_id) REFERENCES judicial_sentence_analysis (id) ON DELETE CASCADE
            )
        """)
        
        # Criar índices
        print("📝 Criando índices...")
        cursor.execute("""
            CREATE INDEX idx_judicial_appeals_user_id 
            ON judicial_appeals(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_judicial_appeals_law_firm_id 
            ON judicial_appeals(law_firm_id)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_judicial_appeals_sentence_analysis_id 
            ON judicial_appeals(sentence_analysis_id)
        """)
        
        conn.commit()
        print("✅ Tabela judicial_appeals criada com sucesso!")
        print("✅ Índices criados com sucesso!")
        return True
        
    except sqlite3.Error as e:
        conn.rollback()
        print(f"❌ Erro ao executar migração: {e}")
        return False
        
    finally:
        conn.close()


def rollback():
    """Reverte a migração (remove a tabela)"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Banco de dados não encontrado em: {DB_PATH}")
        return False
    
    print("🔄 Revertendo migração: Remover tabela judicial_appeals")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("DROP TABLE IF EXISTS judicial_appeals")
        conn.commit()
        print("✅ Tabela judicial_appeals removida com sucesso!")
        return True
        
    except sqlite3.Error as e:
        conn.rollback()
        print(f"❌ Erro ao reverter migração: {e}")
        return False
        
    finally:
        conn.close()


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback()
    else:
        migrate()
