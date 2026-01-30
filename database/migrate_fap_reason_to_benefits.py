"""
Script de migração: Move campo fap_reason de cases para case_benefits

Migração necessária devido à mudança de modelo:
- Adiciona coluna fap_reason na tabela case_benefits
- Remove coluna fap_reason da tabela cases
- Copia valores de cases.fap_reason para todos os benefícios relacionados

Executar com: python database/migrate_fap_reason_to_benefits.py
"""

import sys
import os

# Adicionar o diretório raiz ao path para importar o módulo app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app
from app.models import db, Case, CaseBenefit
from sqlalchemy import text

def migrate_fap_reason():
    """Migra campo fap_reason de cases para case_benefits"""
    
    with app.app_context():
        print("Iniciando migração de fap_reason...")
        
        # 1. Adicionar coluna fap_reason em case_benefits (se não existir)
        try:
            print("\n1. Adicionando coluna fap_reason em case_benefits...")
            db.session.execute(text("""
                ALTER TABLE case_benefits 
                ADD COLUMN fap_reason VARCHAR(100)
            """))
            db.session.commit()
            print("✓ Coluna fap_reason adicionada em case_benefits")
        except Exception as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                print("→ Coluna fap_reason já existe em case_benefits")
                db.session.rollback()
            else:
                print(f"✗ Erro ao adicionar coluna: {e}")
                db.session.rollback()
                return
        
        # 2. Copiar valores de cases.fap_reason para case_benefits.fap_reason
        try:
            print("\n2. Copiando valores de fap_reason dos casos para os benefícios...")
            
            # Buscar todos os casos com fap_reason preenchido
            cases_with_reason = db.session.execute(text("""
                SELECT id, fap_reason FROM cases WHERE fap_reason IS NOT NULL
            """)).fetchall()
            
            migrated_count = 0
            for case_row in cases_with_reason:
                case_id, fap_reason = case_row
                
                # Atualizar todos os benefícios deste caso
                result = db.session.execute(text("""
                    UPDATE case_benefits 
                    SET fap_reason = :fap_reason 
                    WHERE case_id = :case_id
                """), {"fap_reason": fap_reason, "case_id": case_id})
                
                affected_rows = result.rowcount
                if affected_rows > 0:
                    migrated_count += affected_rows
                    print(f"  → Caso {case_id}: {affected_rows} benefício(s) atualizados com fap_reason='{fap_reason}'")
            
            db.session.commit()
            print(f"✓ {migrated_count} benefícios atualizados com fap_reason")
            
        except Exception as e:
            print(f"✗ Erro ao copiar valores: {e}")
            db.session.rollback()
            return
        
        # 3. Remover coluna fap_reason de cases
        try:
            print("\n3. Removendo coluna fap_reason de cases...")
            db.session.execute(text("""
                ALTER TABLE cases DROP COLUMN fap_reason
            """))
            db.session.commit()
            print("✓ Coluna fap_reason removida de cases")
        except Exception as e:
            if "does not exist" in str(e).lower() or "no such column" in str(e).lower():
                print("→ Coluna fap_reason já foi removida de cases")
                db.session.rollback()
            else:
                print(f"✗ Erro ao remover coluna: {e}")
                db.session.rollback()
                return
        
        print("\n" + "="*60)
        print("Migração concluída com sucesso!")
        print("="*60)
        print("\nResumo:")
        print(f"  • Coluna fap_reason adicionada em case_benefits")
        print(f"  • {migrated_count} benefícios migrados com fap_reason")
        print(f"  • Coluna fap_reason removida de cases")
        print("\nPróximos passos:")
        print("  1. Verifique se os dados foram migrados corretamente")
        print("  2. Atualize formulários para incluir fap_reason em benefícios")
        print("  3. Teste a geração de petições FAP")

if __name__ == '__main__':
    migrate_fap_reason()
