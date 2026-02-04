"""
Script de migração: Adicionar tabela judicial_sentence_analysis
Criado: 04/02/2026
Descrição: Cria a tabela para armazenar análises de sentenças judiciais por IA
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
    
    print("🔄 Iniciando migração: Adicionar tabela judicial_sentence_analysis")
    print(f"📁 Banco de dados: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Verificar se a tabela já existe
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='judicial_sentence_analysis'
        """)
        
        if cursor.fetchone():
            print("⚠️  Tabela 'judicial_sentence_analysis' já existe. Pulando migração.")
            return True
        
        # Criar tabela judicial_sentence_analysis
        print("📝 Criando tabela judicial_sentence_analysis...")
        cursor.execute("""
            CREATE TABLE judicial_sentence_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                law_firm_id INTEGER NOT NULL,
                original_filename VARCHAR(255) NOT NULL,
                file_path VARCHAR(500) NOT NULL,
                file_size INTEGER,
                file_type VARCHAR(50),
                status VARCHAR(20) DEFAULT 'pending',
                analysis_result TEXT,
                error_message TEXT,
                processed_at DATETIME,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (law_firm_id) REFERENCES law_firms (id)
            )
        """)
        
        # Criar índices
        print("📊 Criando índices...")
        cursor.execute("""
            CREATE INDEX idx_judicial_sentence_user 
            ON judicial_sentence_analysis(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_judicial_sentence_law_firm 
            ON judicial_sentence_analysis(law_firm_id)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_judicial_sentence_status 
            ON judicial_sentence_analysis(status)
        """)
        
        # Commit das mudanças
        conn.commit()
        
        print("✅ Migração concluída com sucesso!")
        print("✅ Tabela 'judicial_sentence_analysis' criada")
        print("✅ Índices criados")
        
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Erro durante migração: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()

if __name__ == '__main__':
    print("=" * 60)
    print("MIGRAÇÃO: Tabela judicial_sentence_analysis")
    print("=" * 60)
    
    success = migrate()
    
    if success:
        print("\n✅ Migração executada com sucesso!")
    else:
        print("\n❌ Migração falhou!")
    
    print("=" * 60)
