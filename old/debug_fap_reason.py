#!/usr/bin/env python3
"""
Script de debug para verificar o problema com fap_reason_id
"""

from main import app, db
from app.models import FapReason, Case, LawFirm

def test_fap_reason_choices():
    """Testa se as choices estão sendo criadas corretamente"""
    
    with app.app_context():
        print("\n" + "="*60)
        print("🧪 DEBUG: FAP_REASON_ID CHOICES")
        print("="*60)
        
        # 1. Verificar se existem casos e law_firms
        law_firms = LawFirm.query.all()
        print(f"\n✓ Law Firms: {len(law_firms)}")
        
        if not law_firms:
            print("  ⚠️  Nenhuma law firm encontrada!")
            return
        
        law_firm = law_firms[0]
        print(f"  - Primeira law firm: ID {law_firm.id}")
        
        # 2. Verificar se existem fap_reasons
        fap_reasons = FapReason.query.filter_by(
            law_firm_id=law_firm.id,
            is_active=True
        ).order_by(FapReason.display_name).all()
        
        print(f"\n✓ FapReasons para law_firm {law_firm.id}: {len(fap_reasons)}")
        for reason in fap_reasons:
            print(f"  - ID {reason.id} (type={type(reason.id).__name__}): {reason.display_name}")
        
        # 3. Simular as choices que seriam criadas
        print("\n✓ Choices que seriam criadas:")
        choices = [('', 'Nenhum motivo selecionado')] + [(str(r.id), r.display_name) for r in fap_reasons]
        for choice_value, choice_label in choices[:5]:
            print(f"  - value={repr(choice_value)} (type={type(choice_value).__name__}), label={choice_label}")
        
        # 4. Testar o coerce
        print("\n✓ Testando coerce com int_or_none_coerce:")
        from app.form import int_or_none_coerce
        
        test_values = ['', '1', 1, '5', None]
        for val in test_values:
            result = int_or_none_coerce(val)
            print(f"  - input={repr(val)} → output={repr(result)} (type={type(result).__name__})")
        
        # 5. Verificar case
        cases = Case.query.filter_by(law_firm_id=law_firm.id).all()
        print(f"\n✓ Cases para law_firm {law_firm.id}: {len(cases)}")
        
        if cases:
            case = cases[0]
            print(f"  - Primeiro case: ID {case.id}, fap_start_year={case.fap_start_year}, fap_end_year={case.fap_end_year}")
        
        print("\n" + "="*60)
        print("✅ DEBUG CONCLUÍDO")
        print("="*60 + "\n")

if __name__ == '__main__':
    test_fap_reason_choices()
