"""
Script de migração para criar a tabela knowledge_categories

Uso:
    python database/add_knowledge_categories_table.py
"""

import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Importar o app do main.py
from main import app
from app.models import db

def create_knowledge_categories_table():
    """Cria a tabela knowledge_categories"""
    
    with app.app_context():
        try:
            # Verifica se a tabela já existe
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            if 'knowledge_categories' in tables:
                print("⚠️  A tabela 'knowledge_categories' já existe.")
                return
            
            # Cria a tabela
            print("🔄 Criando tabela 'knowledge_categories'...")
            
            with db.engine.connect() as conn:
                conn.execute(db.text("""
                    CREATE TABLE knowledge_categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        law_firm_id INTEGER NOT NULL,
                        name VARCHAR(100) NOT NULL,
                        icon VARCHAR(50),
                        description TEXT,
                        color VARCHAR(20),
                        display_order INTEGER DEFAULT 0,
                        is_active BOOLEAN DEFAULT 1,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (law_firm_id) REFERENCES law_firms(id)
                    )
                """))
                
                # Criar índice
                conn.execute(db.text(
                    "CREATE INDEX ix_knowledge_categories_law_firm_id ON knowledge_categories(law_firm_id)"
                ))
                
                conn.commit()
            
            print("✅ Tabela 'knowledge_categories' criada com sucesso!")
            
        except Exception as e:
            print(f"❌ Erro ao criar tabela: {e}")
            raise

if __name__ == '__main__':
    print("=" * 70)
    print("🔧 MIGRAÇÃO: Criar tabela knowledge_categories")
    print("=" * 70)
    create_knowledge_categories_table()
    print("=" * 70)
    print("✅ Migração concluída!")
    print("=" * 70)
