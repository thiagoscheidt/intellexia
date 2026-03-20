"""
Script para adicionar a tabela benefits ao banco de dados existente.

Essa tabela é o registro centralizado de benefícios de todas as fontes
(casos FAP, processos judiciais, etc.), sem relacionamento direto com as
demais tabelas de benefícios já existentes.

Uso:
    python database/add_benefits_table.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, Benefit


def add_benefits_table():
    """Cria a tabela benefits no banco."""
    with app.app_context():
        try:
            print("🔄 Criando tabela benefits...")

            Benefit.__table__.create(bind=db.engine, checkfirst=True)

            print("✅ Tabela benefits criada com sucesso!")
            print("")
            print("📊 Estrutura da tabela:")
            print("  - law_firm_id           (FK -> law_firms.id, NOT NULL)")
            print("  - client_id             (FK -> clients.id, opcional)")
            print("  - benefit_number        (NOT NULL, indexed)")
            print("  - benefit_type          (B91, B94, etc.)")
            print("  - insured_name")
            print("  - insured_nit           (indexed)")
            print("  - insured_cpf           (indexed)")
            print("  - insured_date_of_birth")
            print("  - employer_cnpj         (indexed)")
            print("  - employer_name")
            print("  - benefit_start_date        (DIB)")
            print("  - benefit_end_date          (DCB)")
            print("  - initial_monthly_benefit   (RMI)")
            print("  - total_paid")
            print("  - accident_date")
            print("  - accident_company_name")
            print("  - accident_summary")
            print("  - cat_number")
            print("  - bo_number")
            print("  - fap_vigencia_years    (comma-separated years)")
            print("  - request_type          (exclusao, inclusao, revisao)")
            print("  - justification")
            print("  - status                (pending, in_review, approved, rejected)")
            print("  - opinion")
            print("  - notes")
            print("  - created_at / updated_at")
            print("")
            print("✅ Migração concluída!")

        except Exception as e:
            print(f"❌ Erro ao criar tabela benefits: {str(e)}")
            raise


if __name__ == '__main__':
    add_benefits_table()
