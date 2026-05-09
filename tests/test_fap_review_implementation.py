#!/usr/bin/env python
"""
Script de teste para o módulo FAP Review
Testa a invocação dos agentes e o fluxo completo de revisão
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Setup
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))
os.environ.setdefault('ENVIRONMENT', 'development')

from main import app, db
from app.models import (
    User, LawFirm,
    FapReviewExecution, FapReviewSetting,
    FapReviewPromptVersion, FapReviewReferenceVersion
)


def test_database_setup():
    """Testa se o banco de dados foi criado corretamente"""
    print("\n" + "="*80)
    print("🔍 TESTE 1: Verificar Banco de Dados")
    print("="*80)
    
    with app.app_context():
        try:
            # Verificar tabelas
            execution_count = FapReviewExecution.query.count()
            setting_count = FapReviewSetting.query.count()
            prompt_count = FapReviewPromptVersion.query.count()
            reference_count = FapReviewReferenceVersion.query.count()
            
            print(f"✅ Tabela FapReviewExecution: {execution_count} registros")
            print(f"✅ Tabela FapReviewSetting: {setting_count} registros")
            print(f"✅ Tabela FapReviewPromptVersion: {prompt_count} registros")
            print(f"✅ Tabela FapReviewReferenceVersion: {reference_count} registros")
            
            return True
        except Exception as e:
            print(f"❌ Erro: {e}")
            return False


def test_agent_imports():
    """Testa se os agentes podem ser importados"""
    print("\n" + "="*80)
    print("🔍 TESTE 2: Verificar Importação dos Agentes")
    print("="*80)
    
    try:
        from app.agents.fap_review import FapPetitionReviewerAgent, FapTrainingEvolutionAgent
        print("✅ FapPetitionReviewerAgent importado com sucesso")
        print("✅ FapTrainingEvolutionAgent importado com sucesso")
        
        # Verificar métodos
        reviewer = FapPetitionReviewerAgent(openai_api_key="test-key")
        assert hasattr(reviewer, 'review_petition_single_version'), "Método single_version não encontrado"
        assert hasattr(reviewer, 'review_petition_comparative'), "Método comparative não encontrado"
        assert hasattr(reviewer, 'load_reference_documents'), "Método load_reference_documents não encontrado"
        
        print("✅ Métodos do revisor verificados")
        
        trainer = FapTrainingEvolutionAgent(openai_api_key="test-key")
        assert hasattr(trainer, 'process_reviewer_findings'), "Método process_reviewer_findings não encontrado"
        
        print("✅ Métodos do treinador verificados")
        
        return True
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False


def test_settings_creation():
    """Testa criação de configurações padrão"""
    print("\n" + "="*80)
    print("🔍 TESTE 3: Verificar Criação de Configurações")
    print("="*80)
    
    with app.app_context():
        try:
            # Obter primeira law firm
            law_firm = LawFirm.query.first()
            if not law_firm:
                print("⚠️  Nenhum escritório encontrado no banco de dados")
                return False
            
            # Verificar/criar setting
            setting = FapReviewSetting.query.filter_by(law_firm_id=law_firm.id).first()
            if not setting:
                setting = FapReviewSetting(
                    law_firm_id=law_firm.id,
                    reviewer_model='gpt-4o-mini',
                    reviewer_temperature=0.7
                )
                db.session.add(setting)
                db.session.commit()
                print(f"✅ Configuração criada para {law_firm.name}")
            else:
                print(f"✅ Configuração encontrada para {law_firm.name}")
            
            print(f"   - Modelo Revisor: {setting.reviewer_model}")
            print(f"   - Temperatura: {setting.reviewer_temperature}")
            print(f"   - Revisor Ativado: {setting.reviewer_enabled}")
            
            return True
        except Exception as e:
            print(f"❌ Erro: {e}")
            return False


def test_document_extraction():
    """Testa extração de texto de documentos"""
    print("\n" + "="*80)
    print("🔍 TESTE 4: Verificar Extração de Documentos")
    print("="*80)
    
    from app.blueprints.fap_review import _extract_text_from_document
    
    # Criar arquivo de teste
    test_file = Path('test_document.txt')
    test_content = """
    PETIÇÃO INICIAL DE AÇÃO REVISIONAL FAP
    
    Autor: João Silva
    Réu: INSS
    Assunto: Revisão de Fator Acidentário de Prevenção
    
    PRESENÇA: Conforme assinado pela Procuradoria Federal Especializada (PFE)
    
    FATOS: Durante o período de maio de 2020 a outubro de 2021, a empresa
    exerceu atividades que geram exposição a riscos de acidente de trabalho,
    em desconformidade com as normas de segurança regulamentares.
    """
    
    try:
        # Escrever arquivo
        test_file.write_text(test_content)
        print(f"✅ Arquivo de teste criado: {test_file}")
        
        # Extrair texto
        extracted = _extract_text_from_document(str(test_file))
        
        if extracted and len(extracted) > 0:
            print(f"✅ Texto extraído com sucesso: {len(extracted)} caracteres")
            print(f"   Primeiros 100 caracteres: {extracted[:100]}...")
        else:
            print("❌ Nenhum texto foi extraído")
            return False
        
        # Cleanup
        test_file.unlink()
        print("✅ Arquivo de teste removido")
        
        return True
    except Exception as e:
        print(f"❌ Erro: {e}")
        if test_file.exists():
            test_file.unlink()
        return False


def test_blueprint_routes():
    """Testa se as rotas do blueprint estão registradas"""
    print("\n" + "="*80)
    print("🔍 TESTE 5: Verificar Rotas do Blueprint")
    print("="*80)
    
    try:
        routes = []
        for rule in app.url_map.iter_rules():
            if 'fap_review' in rule.endpoint:
                routes.append((rule.rule, rule.methods - {'HEAD', 'OPTIONS'}))
        
        if routes:
            print(f"✅ {len(routes)} rotas encontradas:")
            for path, methods in sorted(routes):
                print(f"   {path}: {', '.join(sorted(methods))}")
            return True
        else:
            print("❌ Nenhuma rota encontrada para 'fap_review'")
            return False
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False


def run_all_tests():
    """Executa todos os testes"""
    print("\n")
    print("████████████████████████████████████████████████████████████████████████████████")
    print("  TESTES DO MÓDULO FAP REVIEW")
    print("████████████████████████████████████████████████████████████████████████████████")
    
    results = []
    
    # Executar testes
    results.append(("Database Setup", test_database_setup()))
    results.append(("Agent Imports", test_agent_imports()))
    results.append(("Settings Creation", test_settings_creation()))
    results.append(("Document Extraction", test_document_extraction()))
    results.append(("Blueprint Routes", test_blueprint_routes()))
    
    # Resumo
    print("\n" + "="*80)
    print("📊 RESUMO DOS TESTES")
    print("="*80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSOU" if result else "❌ FALHOU"
        print(f"{status} | {test_name}")
    
    print(f"\nTotal: {passed}/{total} testes passaram")
    
    if passed == total:
        print("\n🎉 TODOS OS TESTES PASSARAM!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} teste(s) falharam")
        return 1


if __name__ == '__main__':
    exit_code = run_all_tests()
    sys.exit(exit_code)
