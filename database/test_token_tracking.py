"""
Script para testar o tracking de tokens do KnowledgeQueryAgent.

Para executar:
    uv run database/test_token_tracking.py
"""

import sys
from pathlib import Path

root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from main import app
from app.agents.knowledge_base.knowledge_query_agent import KnowledgeQueryAgent


def test_token_tracking():
    """Testa se o token tracking está funcionando"""
    with app.app_context():
        print("="*60)
        print("TESTE DE TOKEN TRACKING")
        print("="*60)
        
        print("\n1. Inicializando KnowledgeQueryAgent...")
        try:
            agent = KnowledgeQueryAgent()
            print("✓ Agent inicializado")
        except Exception as e:
            print(f"✗ Erro ao inicializar agent: {e}")
            return
        
        print("\n2. Fazendo pergunta de teste...")
        print("Pergunta: 'Olá, como você está?'")
        
        try:
            # Teste SEM user_id/law_firm_id para não depender do banco
            result = agent.ask_with_llm(
                question="Olá, como você está?",
                user_id=None,
                law_firm_id=None,
                history=None,
                chat_session_id=None,
            )
            
            print("\n3. Resposta recebida:")
            print(f"Answer: {result.get('answer', '')[:100]}...")
            print(f"Response time: {result.get('response_time_ms')}ms")
            
            print("\n" + "="*60)
            print("✓ Teste concluído!")
            print("="*60)
            print("\nVerifique acima se os prints do TokenUsageService apareceram.")
            print("Se não apareceram, o capture_and_store não foi chamado.")
            
        except Exception as e:
            print(f"\n✗ Erro ao executar agent: {e}")
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    test_token_tracking()
