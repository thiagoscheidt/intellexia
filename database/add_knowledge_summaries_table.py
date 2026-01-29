"""
Script de migração para criar a tabela knowledge_summaries

Uso:
    python database/add_knowledge_summaries_table.py
"""

import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Importar o app do main.py
from main import app
from app.models import db
from sqlalchemy import text

def create_knowledge_summaries_table():
    """Cria a tabela knowledge_summaries"""
    
    with app.app_context():
        try:
            # Criar tabela
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS knowledge_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                knowledge_base_id INTEGER NOT NULL,
                payload JSON NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(id) ON DELETE CASCADE
            )
            """
            
            db.session.execute(text(create_table_sql))
            
            # Criar índices
            create_indexes_sql = [
                "CREATE INDEX IF NOT EXISTS idx_knowledge_summaries_kb ON knowledge_summaries(knowledge_base_id)",
                "CREATE INDEX IF NOT EXISTS idx_knowledge_summaries_created ON knowledge_summaries(created_at)"
            ]
            
            for sql in create_indexes_sql:
                db.session.execute(text(sql))
            
            db.session.commit()
            print("✅ Tabela knowledge_summaries criada com sucesso!")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro ao criar tabela knowledge_summaries: {e}")
            raise

if __name__ == "__main__":
    create_knowledge_summaries_table()
