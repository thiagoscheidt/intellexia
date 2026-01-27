"""
Script de migração para adicionar a coluna lawsuit_number na tabela knowledge_base

Uso:
    python database/add_lawsuit_number_column.py
"""

import sys
import os
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Importar o app do main.py
from main import app
from app.models import db

def add_lawsuit_number_column():
    """Adiciona a coluna lawsuit_number à tabela knowledge_base"""
    
    with app.app_context():
        try:
            # Verifica se a coluna já existe
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('knowledge_base')]
            
            if 'lawsuit_number' in columns:
                print("⚠️  A coluna 'lawsuit_number' já existe na tabela 'knowledge_base'.")
                return
            
            # Adiciona a coluna
            print("🔄 Adicionando coluna 'lawsuit_number' à tabela 'knowledge_base'...")
            
            with db.engine.connect() as conn:
                conn.execute(db.text(
                    "ALTER TABLE knowledge_base ADD COLUMN lawsuit_number VARCHAR(100)"
                ))
                conn.commit()
            
            print("✅ Coluna 'lawsuit_number' adicionada com sucesso!")
            print("📋 A coluna permite armazenar números de processos judiciais (até 100 caracteres)")
            
        except Exception as e:
            print(f"❌ Erro ao adicionar coluna: {e}")
            raise

if __name__ == '__main__':
    print("=" * 70)
    print("🔧 MIGRAÇÃO: Adicionar coluna lawsuit_number")
    print("=" * 70)
    add_lawsuit_number_column()
    print("=" * 70)
    print("✅ Migração concluída!")
    print("=" * 70)
