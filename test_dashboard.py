#!/usr/bin/env python3
"""
Script para testar o dashboard do sistema Intellexia
"""

import sys
from pathlib import Path

# Adicionar o diretório do projeto ao path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from main import app

def test_dashboard():
    """Testa se o dashboard carrega corretamente"""
    try:
        with app.test_client() as client:
            with app.app_context():
                # Testar se a rota principal redireciona para o dashboard
                response = client.get('/')
                print(f"Status da rota principal: {response.status_code}")
                
                # Testar se a rota do dashboard funciona
                response = client.get('/dashboard')
                print(f"Status do dashboard: {response.status_code}")
                
                if response.status_code == 200:
                    print("✅ Dashboard carregado com sucesso!")
                    return True
                else:
                    print(f"❌ Erro no dashboard: {response.status_code}")
                    print(response.data.decode('utf-8'))
                    return False
                    
    except Exception as e:
        print(f"❌ Erro durante teste: {e}")
        return False

if __name__ == '__main__':
    print("🧪 Testando dashboard...")
    success = test_dashboard()
    sys.exit(0 if success else 1)