"""
Migration: Adiciona tabelas para o módulo de Revisão de Petição Inicial FAP
Data: 2026-05-09
"""
import os
import sys
from datetime import datetime
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app, db


def run_migration():
    """Executa a migração"""
    with app.app_context():
        print("[FAP Review] Iniciando criação de tabelas...")
        
        # Executar criação de tabelas
        try:
            db.create_all()
            print("✅ Tabelas criadas com sucesso!")
            print("   - fap_review_prompt_versions")
            print("   - fap_review_reference_versions")
            print("   - fap_review_settings")
            print("   - fap_review_executions")
            print("   - fap_review_audit_logs")
        except Exception as e:
            print(f"❌ Erro ao criar tabelas: {e}")
            raise


if __name__ == '__main__':
    run_migration()
    print("[FAP Review] Migração concluída!")
