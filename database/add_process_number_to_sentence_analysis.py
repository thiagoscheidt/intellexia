"""
Script de migração: Adicionar coluna process_number à tabela judicial_sentence_analysis
Criado: 26/02/2026
Descrição: Adiciona campo opcional para vincular análises de sentença ao painel de processos
"""

import sqlite3
import os

# Caminho do banco de dados
DB_PATH = os.path.join('instance', 'intellexia.db')


def migrate():
    """Executa a migração do banco de dados"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Banco de dados não encontrado em: {DB_PATH}")
        return False
    
    print("🔄 Iniciando migração: Adicionar coluna process_number à judicial_sentence_analysis")
    print(f"📁 Banco de dados: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Verificar se a coluna já existe
        cursor.execute("PRAGMA table_info(judicial_sentence_analysis)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'process_number' in columns:
            print("⚠️  Coluna 'process_number' já existe. Pulando migração.")
            return True
        
        # Adicionar coluna process_number
        print("📝 Adicionando coluna process_number...")
        cursor.execute("""
            ALTER TABLE judicial_sentence_analysis 
            ADD COLUMN process_number VARCHAR(25)
        """)
        
        # Criar índice
        print("📊 Criando índice...")
        cursor.execute("""
            CREATE INDEX idx_judicial_sentence_analysis_process_number 
            ON judicial_sentence_analysis(process_number)
        """)
        
        # Commit das mudanças
        conn.commit()
        
        print("✅ Migração concluída com sucesso!")
        print("✅ Coluna 'process_number' adicionada")
        print("✅ Índice criado")
        
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Erro durante migração: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()


def rollback():
    """Reverte a migração (SQLite não suporta DROP COLUMN nativamente)"""
    print("⚠️  SQLite não suporta DROP COLUMN diretamente.")
    print("⚠️  Para reverter, você precisaria:")
    print("   1. Criar nova tabela sem a coluna")
    print("   2. Copiar dados da tabela antiga")
    print("   3. Deletar tabela antiga")
    print("   4. Renomear nova tabela")
    return False


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback()
    else:
        migrate()
