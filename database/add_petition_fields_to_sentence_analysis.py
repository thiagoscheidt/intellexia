"""
Script de migração: Adicionar campos de petição inicial na tabela judicial_sentence_analysis
Criado: 04/02/2026
Descrição: Adiciona campos opcionais para armazenar informações da petição inicial
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
    
    print("🔄 Iniciando migração: Adicionar campos de petição inicial")
    print(f"📁 Banco de dados: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Verificar se os campos já existem
        cursor.execute("PRAGMA table_info(judicial_sentence_analysis)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'petition_filename' in columns:
            print("⚠️  Campos de petição inicial já existem. Pulando migração.")
            return True
        
        # Adicionar campos de petição inicial
        print("📝 Adicionando campos de petição inicial...")
        
        cursor.execute("""
            ALTER TABLE judicial_sentence_analysis 
            ADD COLUMN petition_filename VARCHAR(255)
        """)
        
        cursor.execute("""
            ALTER TABLE judicial_sentence_analysis 
            ADD COLUMN petition_file_path VARCHAR(500)
        """)
        
        cursor.execute("""
            ALTER TABLE judicial_sentence_analysis 
            ADD COLUMN petition_file_size INTEGER
        """)
        
        cursor.execute("""
            ALTER TABLE judicial_sentence_analysis 
            ADD COLUMN petition_file_type VARCHAR(50)
        """)
        
        # Commit das mudanças
        conn.commit()
        
        print("✅ Migração concluída com sucesso!")
        print("✅ Campos adicionados:")
        print("   - petition_filename")
        print("   - petition_file_path")
        print("   - petition_file_size")
        print("   - petition_file_type")
        
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Erro durante migração: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()

if __name__ == '__main__':
    print("=" * 60)
    print("MIGRAÇÃO: Campos de Petição Inicial")
    print("=" * 60)
    
    success = migrate()
    
    if success:
        print("\n✅ Migração executada com sucesso!")
    else:
        print("\n❌ Migração falhou!")
    
    print("=" * 60)
