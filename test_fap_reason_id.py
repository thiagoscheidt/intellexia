#!/usr/bin/env python3
"""
Script de teste para verificar se fap_reason_id está sendo salvo corretamente
"""

from main import app, db
from app.models import Case, CaseBenefit, FapReason, LawFirm

def test_fap_reason_id():
    """Testa se fap_reason_id está sendo salvo corretamente"""
    
    with app.app_context():
        print("\n" + "="*60)
        print("🧪 TESTE: FAP_REASON_ID")
        print("="*60)
        
        # 1. Verificar se existem fap_reasons
        print("\n✓ Verificando FapReasons...")
        fap_reasons = FapReason.query.all()
        print(f"  - Total de FapReasons: {len(fap_reasons)}")
        
        if fap_reasons:
            for reason in fap_reasons[:3]:
                print(f"    - ID {reason.id}: {reason.display_name}")
        else:
            print("  ⚠️  Nenhum FapReason encontrado. Criando um...")
            
            # Pegar a primeira law firm
            law_firm = LawFirm.query.first()
            if law_firm:
                reason = FapReason(
                    law_firm_id=law_firm.id,
                    display_name="Teste Motivo FAP",
                    description="Motivo de teste para validação"
                )
                db.session.add(reason)
                db.session.commit()
                print(f"  ✓ FapReason criado com ID {reason.id}")
        
        # 2. Verificar case_benefits com fap_reason_id
        print("\n✓ Verificando CaseBenefits com fap_reason_id...")
        benefits = CaseBenefit.query.all()
        print(f"  - Total de benefícios: {len(benefits)}")
        
        # Mostrar alguns benefícios com fap_reason_id
        benefits_with_fap = [b for b in benefits if b.fap_reason_id]
        print(f"  - Benefícios com fap_reason_id: {len(benefits_with_fap)}")
        
        if benefits_with_fap:
            for benefit in benefits_with_fap[:3]:
                print(f"    - ID {benefit.id}: fap_reason_id={benefit.fap_reason_id}")
                if benefit.fap_reason_obj:
                    print(f"      Motivo: {benefit.fap_reason_obj.display_name}")
        
        # 3. Verificar se a coluna fap_reason_id existe
        print("\n✓ Verificando estrutura do banco de dados...")
        import sqlite3
        conn = sqlite3.connect('instance/intellexia.db')
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(case_benefits)")
        columns = cursor.fetchall()
        
        column_names = [col[1] for col in columns]
        print(f"  - Colunas da tabela case_benefits: {len(column_names)}")
        
        if 'fap_reason_id' in column_names:
            print("  ✓ Coluna 'fap_reason_id' existe!")
        else:
            print("  ✗ Coluna 'fap_reason_id' NÃO existe!")
            print(f"    Colunas disponíveis: {column_names}")
        
        conn.close()
        
        print("\n" + "="*60)
        print("✅ TESTE CONCLUÍDO")
        print("="*60 + "\n")

if __name__ == '__main__':
    test_fap_reason_id()
