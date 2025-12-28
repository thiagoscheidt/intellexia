#!/usr/bin/env python3
"""
Script simplificado para popular dados de exemplo no sistema Intellexia
Versão que inicializa a aplicação diretamente

Execute: python populate_simple.py
"""

import os
import sys
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path

# Configurar path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configurar Flask e SQLAlchemy diretamente
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Criar aplicação Flask
app = Flask(__name__)
app.secret_key = 'dev-key-for-population'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///intellexia.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicializar SQLAlchemy
db = SQLAlchemy(app)

# Importar modelos
from app.models import Client, Court, Lawyer, Case, CaseLawyer, CaseCompetence, CaseBenefit, Document

def populate_data():
    """População principal dos dados"""
    
    # Clientes de exemplo
    clients_data = [
        {
            'name': 'Construtora Silva & Filhos Ltda',
            'cnpj': '12.345.678/0001-90',
            'street': 'Rua das Construções, 123',
            'number': '123',
            'district': 'Centro',
            'city': 'São Paulo',
            'state': 'SP',
            'zip_code': '01234-567',
            'has_branches': True,
            'branches_description': 'Filiais em Santos/SP e Campinas/SP'
        },
        {
            'name': 'Metalúrgica Aço Forte S.A.',
            'cnpj': '98.765.432/0001-10',
            'street': 'Av. Industrial, 500',
            'number': '500',
            'district': 'Distrito Industrial',
            'city': 'Blumenau',
            'state': 'SC',
            'zip_code': '89012-345',
            'has_branches': False,
            'branches_description': None
        }
    ]
    
    # Varas judiciais
    courts_data = [
        {
            'section': 'Seção Judiciária de Santa Catarina',
            'vara_name': '1ª Vara Federal de Blumenau',
            'city': 'Blumenau',
            'state': 'SC'
        },
        {
            'section': 'Seção Judiciária de Santa Catarina',
            'vara_name': '2ª Vara Federal de Joinville',
            'city': 'Joinville',
            'state': 'SC'
        }
    ]
    
    # Advogados
    lawyers_data = [
        {
            'name': 'Dr. João Silva Santos',
            'oab_number': 'SP 123456',
            'email': 'joao.santos@advocacia.com.br',
            'phone': '(11) 98765-4321',
            'is_default_for_publications': True
        },
        {
            'name': 'Dra. Maria Fernanda Costa',
            'oab_number': 'SC 78901',
            'email': 'maria.costa@escritorio.adv.br',
            'phone': '(47) 99123-4567',
            'is_default_for_publications': False
        }
    ]
    
    print("📊 Criando clientes...")
    clients = []
    for data in clients_data:
        existing = Client.query.filter_by(cnpj=data['cnpj']).first()
        if not existing:
            client = Client(**data)
            db.session.add(client)
            clients.append(client)
            print(f"✓ Cliente: {data['name']}")
        else:
            clients.append(existing)
            print(f"→ Cliente já existe: {existing.name}")
    
    print("🏛️ Criando varas judiciais...")
    courts = []
    for data in courts_data:
        existing = Court.query.filter_by(vara_name=data['vara_name']).first()
        if not existing:
            court = Court(**data)
            db.session.add(court)
            courts.append(court)
            print(f"✓ Vara: {data['vara_name']}")
        else:
            courts.append(existing)
            print(f"→ Vara já existe: {existing.vara_name}")
    
    print("⚖️ Criando advogados...")
    lawyers = []
    for data in lawyers_data:
        existing = Lawyer.query.filter_by(oab_number=data['oab_number']).first()
        if not existing:
            lawyer = Lawyer(**data)
            db.session.add(lawyer)
            lawyers.append(lawyer)
            print(f"✓ Advogado: {data['name']}")
        else:
            lawyers.append(existing)
            print(f"→ Advogado já existe: {existing.name}")
    
    # Commit dados básicos
    db.session.commit()
    print("✅ Dados básicos salvos")
    
    # Casos
    cases_data = [
        {
            'title': 'Revisão FAP - Acidente de Trabalho 2019-2021',
            'case_type': 'fap_trajeto',
            'fap_start_year': 2019,
            'fap_end_year': 2021,
            'facts_summary': 'Contestação do FAP em razão de acidente de trajeto.',
            'thesis_summary': 'Art. 21, IV da Lei 8.213/91',
            'prescription_summary': 'Não há prescrição.',
            'value_cause': Decimal('250000.00'),
            'status': 'active',
            'filing_date': date(2023, 3, 15),
            'client_id': clients[0].id if clients else None,
            'court_id': courts[0].id if courts else None
        },
        {
            'title': 'Revisão FAP - Nexo Causal 2020-2022',
            'case_type': 'fap_nexo',
            'fap_start_year': 2020,
            'fap_end_year': 2022,
            'facts_summary': 'Contestação de auxílio-doença acidentário.',
            'thesis_summary': 'Inexistência de nexo causal',
            'prescription_summary': 'Prazo prescricional suspenso',
            'value_cause': Decimal('180000.00'),
            'status': 'active',
            'filing_date': date(2023, 6, 22),
            'client_id': clients[1].id if len(clients) > 1 else clients[0].id,
            'court_id': courts[1].id if len(courts) > 1 else courts[0].id
        }
    ]
    
    print("📋 Criando casos...")
    cases = []
    for data in cases_data:
        existing = Case.query.filter_by(title=data['title']).first()
        if not existing:
            case = Case(**data)
            db.session.add(case)
            cases.append(case)
            print(f"✓ Caso: {data['title']}")
        else:
            cases.append(existing)
            print(f"→ Caso já existe: {existing.title}")
    
    # Commit casos
    db.session.commit()
    print("✅ Casos salvos")
    
    # Relacionamentos caso-advogado
    print("🤝 Criando relações caso-advogado...")
    for i, case in enumerate(cases):
        lawyer = lawyers[i % len(lawyers)] if lawyers else None
        if lawyer:
            existing = CaseLawyer.query.filter_by(case_id=case.id, lawyer_id=lawyer.id).first()
            if not existing:
                case_lawyer = CaseLawyer(
                    case_id=case.id,
                    lawyer_id=lawyer.id,
                    role='responsavel'
                )
                db.session.add(case_lawyer)
                print(f"✓ Relação: {case.title} <-> {lawyer.name}")
    
    # Benefícios
    benefits_data = [
        {
            'case_id': cases[0].id if cases else None,
            'benefit_number': '123456789-01',
            'benefit_type': 'B91',
            'insured_name': 'José da Silva',
            'insured_nit': '12345678901',
            'accident_date': date(2019, 8, 15),
            'accident_company_name': 'Construtora Silva & Filhos Ltda',
            'error_reason': 'acidente_trajeto',
            'notes': 'Acidente no trajeto casa-trabalho'
        }
    ]
    
    print("💰 Criando benefícios...")
    for data in benefits_data:
        if data['case_id']:
            existing = CaseBenefit.query.filter_by(benefit_number=data['benefit_number']).first()
            if not existing:
                benefit = CaseBenefit(**data)
                db.session.add(benefit)
                print(f"✓ Benefício: {data['benefit_number']}")
    
    # Commit final
    db.session.commit()
    print("\n✅ POPULAÇÃO CONCLUÍDA COM SUCESSO!")

def main():
    """Função principal"""
    print("🚀 Populando dados com script simplificado...")
    print("=" * 50)
    
    try:
        with app.app_context():
            # Criar tabelas
            db.create_all()
            print("✓ Tabelas verificadas/criadas")
            
            # Popular dados
            populate_data()
            
    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return False
    
    return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)