"""
Script para adicionar a coluna file_path na tabela petitions
Execute este script para atualizar o banco de dados existente
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text

def add_file_path_column():
    """Adiciona a coluna file_path na tabela petitions"""
    with app.app_context():
        try:
            # Verificar se a coluna já existe
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('petitions')]
            
            if 'file_path' in columns:
                print("✓ A coluna 'file_path' já existe na tabela 'petitions'")
                return
            
            # Adicionar a coluna
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE petitions ADD COLUMN file_path VARCHAR(500) NULL"
                ))
                conn.commit()
            
            print("✓ Coluna 'file_path' adicionada com sucesso à tabela 'petitions'")
            
        except Exception as e:
            print(f"✗ Erro ao adicionar coluna: {str(e)}")
            raise

if __name__ == '__main__':
    print("Adicionando coluna 'file_path' na tabela 'petitions'...")
    add_file_path_column()
    print("Migração concluída!")
