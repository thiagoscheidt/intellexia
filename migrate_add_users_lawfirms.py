"""
Migração: Adicionar tabelas law_firms e users
Criado em: 2025-12-26
"""

from app.models import db, LawFirm, User
from main import app

def migrate():
    with app.app_context():
        print("Criando tabelas law_firms e users...")
        
        # Criar as tabelas
        db.create_all()
        
        # Criar um escritório de advocacia padrão para testes
        law_firm = LawFirm.query.filter_by(cnpj='00000000000191').first()
        if not law_firm:
            law_firm = LawFirm(
                name='Escritório de Advocacia Demo',
                trade_name='Demo Advocacia',
                cnpj='00000000000191',
                street='Rua Principal',
                number='123',
                district='Centro',
                city='São Paulo',
                state='SP',
                zip_code='01000-000',
                phone='(11) 99999-9999',
                email='contato@demo.com.br',
                is_active=True,
                subscription_plan='premium',
                max_users=10,
                max_cases=100
            )
            db.session.add(law_firm)
            db.session.commit()
            print(f"✓ Escritório criado: {law_firm.name}")
        else:
            print(f"✓ Escritório já existe: {law_firm.name}")
        
        # Criar usuário administrador padrão
        admin_user = User.query.filter_by(email='admin@demo.com.br').first()
        if not admin_user:
            admin_user = User(
                law_firm_id=law_firm.id,
                name='Administrador',
                email='admin@demo.com.br',
                role='admin',
                oab_number='SP123456',
                phone='(11) 98888-8888',
                is_active=True,
                is_verified=True
            )
            admin_user.set_password('admin123')  # Senha padrão
            db.session.add(admin_user)
            db.session.commit()
            print(f"✓ Usuário admin criado: {admin_user.email}")
            print(f"  Senha padrão: admin123")
        else:
            print(f"✓ Usuário admin já existe: {admin_user.email}")
        
        # Criar usuário regular para testes
        regular_user = User.query.filter_by(email='usuario@demo.com.br').first()
        if not regular_user:
            regular_user = User(
                law_firm_id=law_firm.id,
                name='Usuário Teste',
                email='usuario@demo.com.br',
                role='lawyer',
                oab_number='SP654321',
                phone='(11) 97777-7777',
                is_active=True,
                is_verified=True
            )
            regular_user.set_password('usuario123')  # Senha padrão
            db.session.add(regular_user)
            db.session.commit()
            print(f"✓ Usuário regular criado: {regular_user.email}")
            print(f"  Senha padrão: usuario123")
        else:
            print(f"✓ Usuário regular já existe: {regular_user.email}")
        
        print("\n" + "="*50)
        print("Migração concluída com sucesso!")
        print("="*50)
        print("\nCredenciais de teste:")
        print("-" * 50)
        print("Admin:")
        print("  Email: admin@demo.com.br")
        print("  Senha: admin123")
        print("\nUsuário:")
        print("  Email: usuario@demo.com.br")
        print("  Senha: usuario123")
        print("-" * 50)

if __name__ == '__main__':
    migrate()
