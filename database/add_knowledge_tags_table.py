"""
Script para adicionar a tabela knowledge_tags ao banco de dados
"""

import sys
from pathlib import Path

# Adicionar o diretório pai ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Importar o app do main.py
from main import app
from app.models import db
from sqlalchemy import text

def add_knowledge_tags_table():
    with app.app_context():
        try:
            # Criar tabela knowledge_tags
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS knowledge_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                law_firm_id INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL,
                icon VARCHAR(50),
                description TEXT,
                color VARCHAR(20) DEFAULT '#007bff',
                display_order INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (law_firm_id) REFERENCES law_firms(id) ON DELETE CASCADE
            )
            """
            
            db.session.execute(text(create_table_sql))
            
            # Criar índices
            create_indexes_sql = [
                "CREATE INDEX IF NOT EXISTS idx_knowledge_tags_law_firm ON knowledge_tags(law_firm_id)",
                "CREATE INDEX IF NOT EXISTS idx_knowledge_tags_active ON knowledge_tags(is_active)",
                "CREATE INDEX IF NOT EXISTS idx_knowledge_tags_order ON knowledge_tags(display_order)"
            ]
            
            for sql in create_indexes_sql:
                db.session.execute(text(sql))
            
            db.session.commit()
            print("✅ Tabela knowledge_tags criada com sucesso!")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro ao criar tabela knowledge_tags: {e}")
            raise

if __name__ == "__main__":
    add_knowledge_tags_table()
