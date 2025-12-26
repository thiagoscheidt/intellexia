"""
Migração: Adicionar law_firm_id nas tabelas para isolamento multi-tenant
Criado em: 2025-12-26

Este script adiciona a coluna law_firm_id nas tabelas:
- clients
- lawyers
- courts
- cases
"""

from app.models import db, LawFirm, Client, Lawyer, Court, Case
from main import app
from sqlalchemy import text

def migrate():
    with app.app_context():
        print("="*60)
        print("MIGRAÇÃO: Adicionar law_firm_id para isolamento multi-tenant")
        print("="*60)
        
        # Obter o primeiro escritório (ou criar um padrão)
        law_firm = LawFirm.query.first()
        if not law_firm:
            print("\n⚠️  Nenhum escritório encontrado. Criando escritório padrão...")
            law_firm = LawFirm(
                name='Escritório Padrão',
                cnpj='00000000000000',
                is_active=True,
                subscription_plan='trial'
            )
            db.session.add(law_firm)
            db.session.commit()
            print(f"✓ Escritório criado: {law_firm.name} (ID: {law_firm.id})")
        
        default_law_firm_id = law_firm.id
        print(f"\n📌 Usando escritório padrão: {law_firm.name} (ID: {default_law_firm_id})")
        
        try:
            # Verificar e adicionar coluna law_firm_id em clients
            print("\n1. Migrando tabela 'clients'...")
            try:
                db.session.execute(text("SELECT law_firm_id FROM clients LIMIT 1"))
                print("   ✓ Coluna law_firm_id já existe em clients")
            except:
                db.session.rollback()
                print("   → Adicionando coluna law_firm_id...")
                # SQLite: adicionar coluna com valor padrão e NOT NULL em uma linha
                db.session.execute(text(f"ALTER TABLE clients ADD COLUMN law_firm_id INTEGER NOT NULL DEFAULT {default_law_firm_id}"))
                db.session.commit()
                print(f"   ✓ Coluna adicionada com law_firm_id={default_law_firm_id}")
            
            # Verificar e adicionar coluna law_firm_id em lawyers
            print("\n2. Migrando tabela 'lawyers'...")
            try:
                db.session.execute(text("SELECT law_firm_id FROM lawyers LIMIT 1"))
                print("   ✓ Coluna law_firm_id já existe em lawyers")
            except:
                db.session.rollback()
                print("   → Adicionando coluna law_firm_id...")
                db.session.execute(text(f"ALTER TABLE lawyers ADD COLUMN law_firm_id INTEGER NOT NULL DEFAULT {default_law_firm_id}"))
                db.session.commit()
                print(f"   ✓ Coluna adicionada com law_firm_id={default_law_firm_id}")
            
            # Verificar e adicionar coluna law_firm_id em courts
            print("\n3. Migrando tabela 'courts'...")
            try:
                db.session.execute(text("SELECT law_firm_id FROM courts LIMIT 1"))
                print("   ✓ Coluna law_firm_id já existe em courts")
            except:
                db.session.rollback()
                print("   → Adicionando coluna law_firm_id...")
                db.session.execute(text(f"ALTER TABLE courts ADD COLUMN law_firm_id INTEGER NOT NULL DEFAULT {default_law_firm_id}"))
                db.session.commit()
                print(f"   ✓ Coluna adicionada com law_firm_id={default_law_firm_id}")
            
            # Verificar e adicionar coluna law_firm_id em cases
            print("\n4. Migrando tabela 'cases'...")
            try:
                db.session.execute(text("SELECT law_firm_id FROM cases LIMIT 1"))
                print("   ✓ Coluna law_firm_id já existe em cases")
            except:
                db.session.rollback()
                print("   → Adicionando coluna law_firm_id...")
                db.session.execute(text(f"ALTER TABLE cases ADD COLUMN law_firm_id INTEGER NOT NULL DEFAULT {default_law_firm_id}"))
                db.session.commit()
                print(f"   ✓ Coluna adicionada com law_firm_id={default_law_firm_id}")
            
            print("\n" + "="*60)
            print("✅ MIGRAÇÃO CONCLUÍDA COM SUCESSO!")
            print("="*60)
            print("\n📋 Resumo:")
            print(f"   • Escritório padrão: {law_firm.name} (ID: {default_law_firm_id})")
            print(f"   • Clientes migrados: {Client.query.count()}")
            print(f"   • Advogados migrados: {Lawyer.query.count()}")
            print(f"   • Varas migradas: {Court.query.count()}")
            print(f"   • Casos migrados: {Case.query.count()}")
            print("\n⚠️  IMPORTANTE:")
            print("   Todos os registros foram associados ao escritório padrão.")
            print("   Novos registros serão automaticamente associados ao escritório do usuário logado.")
            print("="*60)
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ ERRO na migração: {str(e)}")
            print("Revertendo alterações...")
            raise

if __name__ == '__main__':
    migrate()
