"""
Script para adicionar a tabela judicial_process_benefits ao banco de dados existente.

Uso:
    python database/add_judicial_process_benefits_table.py
"""

import sys
from pathlib import Path

# Adicionar o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, JudicialProcessBenefit


def add_judicial_process_benefits_table():
    """Adiciona a tabela judicial_process_benefits ao banco"""
    with app.app_context():
        try:
            print("🔄 Criando tabela judicial_process_benefits...")

            JudicialProcessBenefit.__table__.create(bind=db.engine, checkfirst=True)

            print("✅ Tabela judicial_process_benefits criada com sucesso!")
            print("")
            print("📊 Estrutura da tabela:")
            print("  - process_id (FK -> judicial_processes.id)")
            print("  - benefit_number")
            print("  - nit_number")
            print("  - insured_name")
            print("  - benefit_type")
            print("  - fap_vigencia_year")
            print("  - legal_thesis")
            print("  - pfn_technical_note")
            print("  - first_instance_decision")
            print("  - second_instance_decision")
            print("  - third_instance_decision")
            print("")
            print("✅ Migração concluída!")

        except Exception as e:
            print(f"❌ Erro ao criar tabela judicial_process_benefits: {str(e)}")
            raise


if __name__ == '__main__':
    add_judicial_process_benefits_table()
