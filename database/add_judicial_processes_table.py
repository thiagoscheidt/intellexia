"""
Script de migração: Adicionar tabela judicial_processes
Criado: 26/02/2026
Descrição: Cria a tabela para armazenar processos judiciais centralizados no painel de processos
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
    
    print("🔄 Iniciando migração: Adicionar tabela judicial_processes")
    print(f"📁 Banco de dados: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Verificar se a tabela já existe
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='judicial_processes'
        """)
        
        if cursor.fetchone():
            print("⚠️  Tabela 'judicial_processes' já existe. Pulando migração.")
            return True
        
        # Criar tabela judicial_processes
        print("📝 Criando tabela judicial_processes...")
        cursor.execute("""
            CREATE TABLE judicial_processes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                law_firm_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                case_id INTEGER,
                
                -- Identificação do processo (CNJ format: NNNNNNN-DD.AAAA.J.TR.OOOO)
                process_number VARCHAR(25) NOT NULL UNIQUE,
                
                -- Informações do processo
                title VARCHAR(255),
                description TEXT,
                
                -- Status
                status VARCHAR(50) DEFAULT 'ativo',
                
                -- Dados do processo (preenchidos por DataJud ou manualmente)
                judge_name VARCHAR(255),
                tribunal VARCHAR(255),
                section VARCHAR(100),
                origin_unit VARCHAR(255),
                case_value NUMERIC(15, 2),
                filing_date DATE,
                last_update DATETIME,
                
                -- Notas internas
                internal_notes TEXT,
                
                -- Auditoria
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                
                FOREIGN KEY (law_firm_id) REFERENCES law_firms (id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (case_id) REFERENCES cases (id) ON DELETE SET NULL
            )
        """)
        
        # Criar índices
        print("📊 Criando índices...")
        cursor.execute("""
            CREATE INDEX idx_judicial_processes_law_firm 
            ON judicial_processes(law_firm_id)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_judicial_processes_user 
            ON judicial_processes(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_judicial_processes_case 
            ON judicial_processes(case_id)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_judicial_processes_process_number 
            ON judicial_processes(process_number)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_judicial_processes_status 
            ON judicial_processes(status)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_judicial_processes_created 
            ON judicial_processes(created_at)
        """)
        
        # Commit das mudanças
        conn.commit()
        
        print("✅ Migração concluída com sucesso!")
        print("✅ Tabela 'judicial_processes' criada")
        print("✅ Índices criados")
        
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Erro durante migração: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()


def rollback():
    """Reverte a migração (remove a tabela)"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Banco de dados não encontrado em: {DB_PATH}")
        return False
    
    print("🔄 Revertendo migração: Remover tabela judicial_processes")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("DROP TABLE IF EXISTS judicial_processes")
        conn.commit()
        print("✅ Tabela judicial_processes removida com sucesso!")
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
