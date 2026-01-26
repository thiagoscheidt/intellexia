"""
Script para adicionar a tabela knowledge_chat_history ao banco de dados.
Esta tabela armazena o histórico de perguntas e respostas do chat da base de conhecimento.

Para executar:
    python database/add_knowledge_chat_history_table.py
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path do Python
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db, KnowledgeChatHistory
from main import app

def create_knowledge_chat_history_table():
    """Cria a tabela knowledge_chat_history"""
    with app.app_context():
        print("Criando tabela knowledge_chat_history...")
        
        # Criar a tabela
        db.create_all()
        
        print("✓ Tabela knowledge_chat_history criada com sucesso!")
        print("\nEstrutura da tabela:")
        print("- id: INTEGER PRIMARY KEY")
        print("- user_id: INTEGER (FK para users)")
        print("- law_firm_id: INTEGER (FK para law_firms)")
        print("- question: TEXT (pergunta do usuário)")
        print("- answer: TEXT (resposta da IA)")
        print("- sources: TEXT (fontes utilizadas - JSON)")
        print("- response_time_ms: INTEGER (tempo de resposta)")
        print("- tokens_used: INTEGER (tokens utilizados)")
        print("- user_rating: INTEGER (avaliação do usuário 1-5)")
        print("- user_feedback: TEXT (comentário do usuário)")
        print("- created_at: DATETIME")

if __name__ == '__main__':
    create_knowledge_chat_history_table()
