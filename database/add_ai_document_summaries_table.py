"""
Script para adicionar a tabela ai_document_summaries ao banco de dados existente
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, AiDocumentSummary

def add_ai_document_summaries_table():
    """Adiciona a tabela ai_document_summaries ao banco"""
    with app.app_context():
        print("🔄 Criando tabela ai_document_summaries...")
        
        # Criar apenas a tabela nova (se não existir)
        db.create_all()
        
        print("✅ Tabela ai_document_summaries criada com sucesso!")
        print("")
        print("📊 Estrutura da tabela:")
        print("  - id (Integer, Primary Key)")
        print("  - user_id (Integer, Foreign Key)")
        print("  - law_firm_id (Integer, Foreign Key)")
        print("  - original_filename (String)")
        print("  - file_path (String)")
        print("  - file_size (Integer)")
        print("  - file_type (String)")
        print("  - status (String): pending, processing, completed, error")
        print("  - summary_text (Text)")
        print("  - error_message (Text)")
        print("  - processed_at (DateTime)")
        print("  - uploaded_at (DateTime)")
        print("  - updated_at (DateTime)")
        print("")
        print("✅ Migração concluída!")

if __name__ == '__main__':
    add_ai_document_summaries_table()
