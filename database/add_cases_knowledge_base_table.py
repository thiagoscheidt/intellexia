"""
Script para adicionar a tabela cases_knowledge_base ao banco de dados.
Esta tabela armazena arquivos da base de conhecimento geral de casos (não específica de um caso).

Para executar:
    python database/add_cases_knowledge_base_table.py
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path do Python
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db, CasesKnowledgeBase
from main import app

def create_cases_knowledge_base_table():
    """Cria a tabela cases_knowledge_base"""
    with app.app_context():
        print("Criando tabela cases_knowledge_base...")
        
        # Criar a tabela
        db.create_all()
        
        print("✓ Tabela cases_knowledge_base criada com sucesso!")
        print("\nEstrutura da tabela:")
        print("- id: INTEGER PRIMARY KEY")
        print("- user_id: INTEGER (FK para users)")
        print("- law_firm_id: INTEGER (FK para law_firms)")
        print("- original_filename: VARCHAR(255)")
        print("- file_path: VARCHAR(500)")
        print("- file_size: INTEGER (bytes)")
        print("- file_type: VARCHAR(50)")
        print("- description: TEXT")
        print("- category: VARCHAR(100)")
        print("- tags: VARCHAR(500)")
        print("- is_active: BOOLEAN")
        print("- uploaded_at: DATETIME")
        print("- updated_at: DATETIME")
        print("\nEsta é uma base de conhecimento GERAL para casos,")
        print("não específica de um caso individual.")

if __name__ == '__main__':
    create_cases_knowledge_base_table()
