"""
Script de migração: Criar tabela judicial_process_cited_benefits
Criado: 18/03/2026
Descrição: Cria a tabela para armazenar benefícios citados no processo
  mas que não fazem parte da ação (polo ativo da demanda).

Uso:
    uv run database/add_judicial_process_cited_benefits_table.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, JudicialProcessCitedBenefit


def migrate():
    with app.app_context():
        try:
            print("🔄 Criando tabela judicial_process_cited_benefits...")

            JudicialProcessCitedBenefit.__table__.create(bind=db.engine, checkfirst=True)

            print("✅ Tabela criada com sucesso!")
            print("")
            print("📊 Estrutura da tabela:")
            print("  - process_id     (FK -> judicial_processes.id)")
            print("  - benefit_number")
            print("  - nit_number")
            print("  - insured_name")
            print("  - benefit_type")
            print("  - fap_vigencia_year")
            print("  - created_at")
            print("  - updated_at")
            print("")
            print("✅ Migração concluída com sucesso!")

        except Exception as e:
            print(f"❌ Erro na migração: {e}")
            raise


if __name__ == "__main__":
    print("=" * 70)
    print("🔧 MIGRAÇÃO: judicial_process_cited_benefits")
    print("=" * 70)
    migrate()
    print("=" * 70)
