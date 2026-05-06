"""
Script de teste: Verificar se o agente FAP está persistindo histórico de execução.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.agents.fap.fap_contestation_classifier_agent import FAPContestationClassifierAgent
from app.models import AgentExecutionHistory
from app.services.agent_execution_history_service import AgentExecutionHistoryService


def test_fap_execution_history():
    """Testa a persistência do histórico de execução do agente FAP."""
    
    with app.app_context():
        print("\n" + "="*70)
        print("🧪 Teste: Persistência de Histórico de Execução do Agente FAP")
        print("="*70 + "\n")

        # Criar agente
        agent = FAPContestationClassifierAgent()

        # Texto de teste
        test_text = """
        A contestação refere-se a um benefício que foi concedido na Justiça Federal.
        Conforme a Súmula 235 do STF, benefícios acidentários devem ser processados 
        na Justiça Estadual, não Federal. A concessão em Justiça Federal indica 
        natureza previdenciária.
        """

        print(f"📝 Texto de teste:\n{test_text}\n")

        # Executar classificação
        print("⏳ Executando classificação...")
        result = agent.classify(
            test_text,
            law_firm_id=None,
        )

        print(f"✓ Classificação concluída: {result}\n")

        # Recuperar execuções mais recentes
        print("📊 Recuperando históricos de execução recentes...")
        executions = AgentExecutionHistoryService.get_recent_executions(
            agent_type="fap_classifier",
            limit=5
        )

        if executions:
            print(f"\n✓ Encontrados {len(executions)} históricos!\n")
            
            for execution in executions:
                print(f"ID: {execution.id}")
                print(f"  Agente: {execution.agent_name}")
                print(f"  Ação: {execution.action_name}")
                print(f"  Status: {execution.status}")
                print(f"  Modelo: {execution.model_name}")
                print(f"  Data: {execution.created_at}")
                print(f"  System Prompt: {execution.system_prompt[:100]}..." if execution.system_prompt else "  System Prompt: None")
                print(f"  User Prompt: {execution.user_prompt[:100]}..." if execution.user_prompt else "  User Prompt: None")
                print(f"  Modelo Response: {execution.model_response[:100]}..." if execution.model_response else "  Modelo Response: None")
                print(f"  Result Data: {execution.result_data}")
                print()
        else:
            print("❌ Nenhum histórico encontrado!\n")

        print("="*70)
        print("✅ Teste concluído!")
        print("="*70 + "\n")


if __name__ == "__main__":
    test_fap_execution_history()
