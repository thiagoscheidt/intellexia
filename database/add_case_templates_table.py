"""
Script de migração para criar a tabela case_templates
Armazena templates de documentos para geração de casos (petições FAP)
"""

import sys
from pathlib import Path

# Adiciona o diretório raiz ao path para permitir imports do app
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db, CaseTemplate
from main import app


def create_case_templates_table():
    """Cria a tabela case_templates no banco de dados"""
    
    with app.app_context():
        print("=" * 80)
        print("CRIAÇÃO DA TABELA: case_templates")
        print("=" * 80)
        print("\n📋 Descrição:")
        print("   Tabela para armazenar templates de documentos para geração de casos FAP")
        print("   Permite upload e gerenciamento de templates como:")
        print("   - Petições iniciais")
        print("   - Templates de acidente de trajeto")
        print("   - Templates de benefícios concomitantes")
        print("   - E outros 35+ tipos de templates")
        
        print("\n📊 Campos principais:")
        print("   - template_name: Nome do template")
        print("   - resumo_curto: Descrição breve do template")
        print("   - categoria: Categoria do caso (ex: 'Erro de nexo causal')")
        print("   - file_path: Caminho do arquivo .docx")
        print("   - is_active: Se o template está disponível para uso")
        print("   - status: Status (available, draft, archived)")
        print("   - usage_count: Contador de uso")
        print("   - last_used_at: Última utilização")
        
        print("\n🔧 Criando tabela...")
        
        try:
            # Cria apenas a tabela CaseTemplate
            db.create_all()
            
            print("✅ Tabela 'case_templates' criada com sucesso!")
            print("\n" + "=" * 80)
            print("PRÓXIMOS PASSOS:")
            print("=" * 80)
            print("1. Criar rotas para upload de templates")
            print("2. Criar interface para gerenciar templates")
            print("3. Integrar com o agente de classificação de casos")
            print("4. Implementar sistema de seleção de templates")
            print("\n" + "=" * 80)
            
        except Exception as e:
            print(f"❌ Erro ao criar tabela: {e}")
            raise


if __name__ == "__main__":
    create_case_templates_table()
