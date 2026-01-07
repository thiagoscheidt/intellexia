"""
Script para adicionar a coluna fap_reason na tabela cases
Execute este script para atualizar o banco de dados existente
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db
from sqlalchemy import text

def add_fap_reason_column():
    """Adiciona a coluna fap_reason na tabela cases"""
    with app.app_context():
        try:
            # Verificar se a coluna já existe
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('cases')]
            
            if 'fap_reason' in columns:
                print("✓ A coluna 'fap_reason' já existe na tabela 'cases'")
                return
            
            # Adicionar a coluna
            with db.engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE cases ADD COLUMN fap_reason VARCHAR(100) NULL"
                ))
                conn.commit()
            
            print("✓ Coluna 'fap_reason' adicionada com sucesso à tabela 'cases'")
            
        except Exception as e:
            print(f"✗ Erro ao adicionar coluna: {str(e)}")
            raise

if __name__ == '__main__':
    print("Adicionando coluna 'fap_reason' na tabela 'cases'...")
    add_fap_reason_column()
    print("Migração concluída!")
