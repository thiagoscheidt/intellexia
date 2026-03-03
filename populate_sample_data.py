#!/usr/bin/env python3
"""
Script para popular dados de exemplo no sistema Intellexia
Sistema de gerenciamento de casos jurídicos trabalhistas

Inclui:
- Escritório de advocacia
- Usuários do sistema
- Clientes
- Varas judiciais
- Advogados
- Casos jurídicos
- Benefícios
- Competências
- Atividades
- Comentários
- Categorias de conhecimento
- Tags para documentos
- Motivos de contestação FAP
- Templates de casos

Execute: python populate_sample_data.py
"""

import os
import sys
import traceback
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Adicionar o diretório do projeto ao path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def import_models():
    """Importa modelos apenas quando necessário"""
    from main import app
    from app.models import (
        db, LawFirm, User, Client, Court, Lawyer, Case, CaseLawyer, 
        CaseCompetence, CaseBenefit, Document, CaseActivity, CaseComment,
        CaseStatus,
        KnowledgeCategory, KnowledgeTag, FapReason, CaseTemplate
    )
    return app, db, LawFirm, User, Client, Court, Lawyer, Case, CaseLawyer, CaseCompetence, CaseBenefit, Document, CaseActivity, CaseComment, CaseStatus, KnowledgeCategory, KnowledgeTag, FapReason, CaseTemplate

def ensure_case_statuses(db, CaseStatus):
    """Garante que os status padrão de casos existam no banco"""
    statuses_data = [
        ("Novo caso recebido", 1, "Novo caso foi recebido"),
        ("Em análise jurídica inicial", 2, "Análise jurídica inicial em progresso"),
        ("Aguardando documentos do cliente", 3, "Aguardando documentos do cliente"),
        ("Documentos recebidos", 4, "Documentos do cliente foram recebidos"),
        ("Petição em elaboração", 5, "Petição está sendo elaborada"),
        ("Petição em revisão", 6, "Petição em fase de revisão"),
        ("Petição finalizada", 7, "Petição foi finalizada"),
        ("Aguardando protocolo", 8, "Aguardando protocolo da petição"),
        ("Petição protocolada", 9, "Petição foi protocolada"),
        ("Número do processo recebido", 10, "Número do processo foi recebido"),
        ("Aguardando despacho inicial do juiz", 11, "Aguardando despacho inicial do juiz"),
        ("Em andamento", 12, "Processo em andamento"),
        ("Prazo em aberto", 13, "Prazo em aberto para ação"),
        ("Caso suspenso", 14, "Caso foi suspenso"),
        ("Caso encerrado / arquivado", 15, "Caso foi encerrado ou arquivado"),
    ]

    created_count = 0
    for status_name, status_order, description in statuses_data:
        existing = CaseStatus.query.filter_by(status_name=status_name).first()
        if not existing:
            status = CaseStatus(
                status_name=status_name,
                status_order=status_order,
                description=description
            )
            db.session.add(status)
            created_count += 1

    if created_count > 0:
        db.session.flush()
        print(f"✓ Criados {created_count} status de caso")
    else:
        print("→ Status de caso já existem")

    default_status = CaseStatus.query.order_by(CaseStatus.status_order.asc()).first()
    if not default_status:
        raise ValueError("Nao foi possivel obter status padrão de caso")

    return default_status.id

def create_knowledge_categories(db, KnowledgeCategory, law_firm):
    """Cria categorias de conhecimento padrão"""
    categories_data = [
        {
            'name': 'Jurisprudência',
            'icon': 'book',
            'description': 'Decisões judiciais relevantes, súmulas, precedentes',
            'color': '#007bff',
            'display_order': 1
        },
        {
            'name': 'Legislação',
            'icon': 'scale',
            'description': 'Leis, decretos, portarias, normas regulamentares',
            'color': '#28a745',
            'display_order': 2
        },
        {
            'name': 'Modelos',
            'icon': 'file',
            'description': 'Modelos de documentos, petições, contratos',
            'color': '#17a2b8',
            'display_order': 3
        },
        {
            'name': 'Artigos',
            'icon': 'newspaper',
            'description': 'Artigos jurídicos, estudos, análises doutrinárias',
            'color': '#ffc107',
            'display_order': 4
        },
        {
            'name': 'Manuais',
            'icon': 'book-open',
            'description': 'Manuais, guias práticos, tutoriais',
            'color': '#6f42c1',
            'display_order': 5
        },
        {
            'name': 'Procedimentos',
            'icon': 'wrench',
            'description': 'Procedimentos internos, fluxos de trabalho',
            'color': '#fd7e14',
            'display_order': 6
        },
        {
            'name': 'Outros',
            'icon': 'box',
            'description': 'Outros documentos e arquivos diversos',
            'color': '#6c757d',
            'display_order': 7
        }
    ]
    
    categories = []
    for cat_data in categories_data:
        existing = KnowledgeCategory.query.filter_by(
            law_firm_id=law_firm.id,
            name=cat_data['name']
        ).first()
        
        if not existing:
            category = KnowledgeCategory(
                law_firm_id=law_firm.id,
                **cat_data
            )
            db.session.add(category)
            categories.append(category)
            print(f"[OK] Categoria criada: {cat_data['name']}")
        else:
            categories.append(existing)
            print(f"[JA EXISTE] Categoria ja existe: {cat_data['name']}")
    
    return categories

def create_knowledge_tags(db, KnowledgeTag, law_firm):
    """Cria tags padrão para documentos"""
    tags_data = [
        {"name": "Trabalhista", "icon": "scale", "description": "Direito do trabalho", "color": "#007bff", "display_order": 1},
        {"name": "Previdenciário", "icon": "building", "description": "Direito previdenciário", "color": "#6c757d", "display_order": 2},
        {"name": "STJ", "icon": "building", "description": "Superior Tribunal de Justiça", "color": "#28a745", "display_order": 3},
        {"name": "STF", "icon": "scale", "description": "Supremo Tribunal Federal", "color": "#dc3545", "display_order": 4},
        {"name": "Súmula", "icon": "list", "description": "Súmulas", "color": "#ffc107", "display_order": 5},
        {"name": "Jurisprudência", "icon": "book", "description": "Decisões judiciais", "color": "#17a2b8", "display_order": 6},
        {"name": "Legislação", "icon": "scroll", "description": "Leis e normas", "color": "#6f42c1", "display_order": 7},
        {"name": "Petição", "icon": "pen", "description": "Peças processuais", "color": "#fd7e14", "display_order": 8},
        {"name": "Recurso", "icon": "file", "description": "Recursos judiciais", "color": "#20c997", "display_order": 9},
        {"name": "Acórdão", "icon": "scale", "description": "Decisões colegiadas", "color": "#e83e8c", "display_order": 10},
        {"name": "Sentença", "icon": "gavel", "description": "Decisões judiciais", "color": "#343a40", "display_order": 11},
        {"name": "Despacho", "icon": "list", "description": "Decisões interlocutórias", "color": "#6c757d", "display_order": 12},
        {"name": "FAP", "icon": "briefcase", "description": "Fator Acidentário de Prevenção", "color": "#007bff", "display_order": 13},
        {"name": "INSS", "icon": "building", "description": "Instituto Nacional do Seguro Social", "color": "#28a745", "display_order": 14},
        {"name": "Acidente", "icon": "exclamation-triangle", "description": "Acidente de trabalho", "color": "#dc3545", "display_order": 15},
        {"name": "Aposentadoria", "icon": "user", "description": "Benefícios de aposentadoria", "color": "#17a2b8", "display_order": 16},
        {"name": "Auxílio-doença", "icon": "heart", "description": "Benefício por incapacidade", "color": "#ffc107", "display_order": 17},
        {"name": "Pensão", "icon": "users", "description": "Pensão por morte", "color": "#6f42c1", "display_order": 18},
    ]
    
    tags = []
    for tag_data in tags_data:
        existing = KnowledgeTag.query.filter_by(
            law_firm_id=law_firm.id,
            name=tag_data['name']
        ).first()
        
        if not existing:
            tag = KnowledgeTag(
                law_firm_id=law_firm.id,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                **tag_data
            )
            db.session.add(tag)
            tags.append(tag)
        else:
            tags.append(existing)
    
    print(f"[OK] {len(tags)} tags criadas/existentes")
    return tags

def create_fap_reasons(db, FapReason, law_firm):
    """Cria motivos padrão de contestação FAP"""
    reasons_data = [
        ("Benefício Revogado Judicialmente", "Benefício concedido por liminar e posteriormente revogado judicialmente"),
        ("Duplicidade de Benefício em Restabelecimento", "B91 concedido duas vezes em menos de 60 dias (restabelecimento indevido)"),
        ("Erro Material na CAT", "CAT com erro material classificando acidente típico em vez de trajeto"),
        ("CAT de Trajeto Extemporânea", "CAT de trajeto enviada fora do prazo (extemporânea)"),
        ("Inclusão Indevida de Acidente de Trajeto no FAP", "Inclusão de acidente de trajeto no cálculo do FAP"),
        ("Acidente Sem Relação com o Trabalho", "Acidente ocorrido sem relação com o trabalho"),
        ("Acidente Vinculado a Outra Empresa", "Acidente ocorrido quando empregado estava vinculado a outra empresa"),
        ("Acidente em Outro Estabelecimento", "Acidente ocorrido em outro estabelecimento (outro CNPJ)"),
        ("Benefício Concomitante com Aposentadoria (B91)", "B91 concedido concomitante com aposentadoria"),
        ("Bloqueio Indevido do FAP por B92", "Bloqueio do FAP causado por B92 indevido"),
        ("Benefício Concomitante B91 com B94", "B91 concedido junto com auxílio-acidente (B94)"),
        ("Duplicidade de Benefício B91", "Dois B91 concedidos ao mesmo tempo"),
        ("Auxílio-acidente com Aposentadoria", "B94 concedido concomitante com aposentadoria"),
        ("Nexo Causal Contestado", "Inexistência de nexo causal entre atividade laboral e doença alegada"),
        ("Benefício Prescrito", "Benefício expulso por ação do tempo ou cumprimento de condições"),
    ]
    
    reasons = []
    for display_name, description in reasons_data:
        existing = FapReason.query.filter_by(
            law_firm_id=law_firm.id,
            display_name=display_name
        ).first()
        
        if not existing:
            reason = FapReason(
                law_firm_id=law_firm.id,
                display_name=display_name,
                description=description,
                is_active=True
            )
            db.session.add(reason)
            reasons.append(reason)
            print(f"✓ Motivo FAP criado: {display_name}")
        else:
            reasons.append(existing)
            print(f"→ Motivo FAP já existe: {display_name}")
    
    return reasons

def create_case_templates(db, CaseTemplate, law_firm, users):
    """Cria templates de casos FAP padrão"""
    templates_data = [
        ("Acidente Ocorrido em outra Empresa", "Benefício atribuído a empresa diferente da real empregadora do segurado.", "Erro de vínculo empregatício"),
        ("Acidente Ocorrido em outro Estabelecimento", "Acidente imputado ao CNPJ errado (filial diversa).", "Erro de estabelecimento"),
        ("Acidente não Relacionado ao Trabalho", "Evento sem nexo com o trabalho foi classificado como acidentário.", "Erro de nexo causal"),
        ("Acidente de Trajeto", "Acidente de trajeto incluído indevidamente no FAP.", "Acidente de trajeto"),
        ("Acidente de Trajeto - CAT Erro Material", "CAT preenchida incorretamente como típica quando era de trajeto.", "Acidente de trajeto / erro material"),
        ("Acidente de Trajeto - CAT Extemporânea", "CAT registrada fora do prazo e incluída indevidamente no FAP.", "Acidente de trajeto / CAT fora do prazo"),
        ("B91 - Duplicidade de Benefício", "Benefícios concedidos com intervalo inferior a 60 dias deveriam ser restabelecimento.", "Duplicidade de benefício"),
        ("Exclusão dos Bloqueios por B92", "Aposentadoria por invalidez bloqueou bonificação indevidamente.", "Bloqueio indevido do FAP"),
        ("Revogação de Antecipação dos Efeitos da Tutela", "Benefício judicial cancelado permaneceu no FAP.", "Benefício judicial cancelado"),
        ("B91 com Aposentadoria", "B91 concedido junto com aposentadoria.", "Benefício concomitante"),
        ("B91 com Auxílio-acidente", "B91 concedido simultaneamente ao B94.", "Benefício concomitante"),
        ("B91 com Auxílio-doença", "Dois B91 no mesmo período.", "Duplicidade de benefício"),
        ("B92 com Aposentadoria", "B92 concedido simultaneamente com aposentadoria.", "Benefício concomitante"),
        ("B94 com Aposentadoria", "Auxílio-acidente concedido junto com aposentadoria.", "Benefício concomitante"),
        ("B94 com Auxílio-acidente", "Dois auxílios-acidente concedidos.", "Duplicidade de benefício"),
    ]
    
    owner_user_id = users[0].id if users else None
    if owner_user_id is None:
        raise ValueError("Nao foi possivel identificar usuario para criacao dos templates")

    templates = []
    for template_name, resumo_curto, categoria in templates_data:
        existing = CaseTemplate.query.filter_by(
            law_firm_id=law_firm.id,
            template_name=template_name
        ).first()
        
        if not existing:
            original_filename = f"{template_name}.docx"
            file_path = f"uploads/templates/{law_firm.id}/{original_filename}"
            template = CaseTemplate(
                user_id=owner_user_id,
                law_firm_id=law_firm.id,
                template_name=template_name,
                resumo_curto=resumo_curto,
                categoria=categoria,
                original_filename=original_filename,
                file_path=file_path,
                file_type='DOCX',
                is_active=True
            )
            db.session.add(template)
            templates.append(template)
            print(f"✓ Template criado: {template_name}")
        else:
            templates.append(existing)
            print(f"→ Template já existe: {template_name}")
    
    return templates

def create_sample_law_firm(db, LawFirm):
    """Cria escritório de advocacia de exemplo"""
    from datetime import datetime, timedelta, timezone
    
    law_firm_data = {
        'name': 'Silva & Associados Advocacia',
        'trade_name': 'Silva Advocacia',
        'cnpj': '11.222.333/0001-44',
        'street': 'Av. Paulista, 1000',
        'number': '1000',
        'complement': 'Sala 1501',
        'district': 'Bela Vista',
        'city': 'São Paulo',
        'state': 'SP',
        'zip_code': '01310-100',
        'phone': '(11) 3456-7890',
        'email': 'contato@silvaadvocacia.com.br',
        'website': 'www.silvaadvocacia.com.br',
        'is_active': True,
        'subscription_plan': 'premium',
        'subscription_expires_at': datetime.now(timezone.utc) + timedelta(days=365),
        'max_users': 50,
        'max_cases': 1000
    }
    
    # Verificar se já existe
    existing = LawFirm.query.filter_by(cnpj=law_firm_data['cnpj']).first()
    if not existing:
        law_firm = LawFirm(**law_firm_data)
        db.session.add(law_firm)
        db.session.flush()  # Garantir que o ID seja atribuído
        print(f"✓ Escritório criado: {law_firm_data['name']}")
        return law_firm
    else:
        print(f"→ Escritório já existe: {existing.name}")
        return existing

def create_sample_users(db, User, law_firm):
    """Cria usuários de exemplo"""
    users_data = [
        {
            'law_firm_id': law_firm.id,
            'name': 'João Silva Santos',
            'email': 'joao@silvaadvocacia.com.br',
            'oab_number': 'SP 123456',
            'phone': '(11) 98765-4321',
            'role': 'admin',
            'is_active': True,
            'is_verified': True
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Maria Fernanda Costa',
            'email': 'maria@silvaadvocacia.com.br',
            'oab_number': 'SC 78901',
            'phone': '(47) 99123-4567',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Ana Beatriz Assistente',
            'email': 'ana@silvaadvocacia.com.br',
            'phone': '(11) 94567-8901',
            'role': 'assistant',
            'is_active': True,
            'is_verified': True
        }
    ]
    
    users = []
    for data in users_data:
        # Debug: verificar se law_firm_id está correto
        print(f"   Criando usuário: {data['name']} com law_firm_id: {data['law_firm_id']}")
        
        # Verificar se já existe
        existing = User.query.filter_by(email=data['email']).first()
        if not existing:
            user = User(**data)
            # Definir senha padrão para todos os usuários
            user.set_password('123456')
            db.session.add(user)
            users.append(user)
            print(f"✓ Usuário criado: {data['name']} ({data['role']})")
        else:
            users.append(existing)
            print(f"→ Usuário já existe: {existing.name}")
    
    return users
def create_sample_clients(db, Client, law_firm):
    """Cria empresas clientes de exemplo"""
    clients_data = [
        {
            'law_firm_id': law_firm.id,
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
            'law_firm_id': law_firm.id,
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
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Transportadora Rodoviária Express Ltda',
            'cnpj': '45.123.789/0001-55',
            'street': 'Rodovia BR-101, Km 150',
            'number': 'S/N',
            'district': 'Zona Rural',
            'city': 'Joinville',
            'state': 'SC',
            'zip_code': '89567-890',
            'has_branches': True,
            'branches_description': 'Filiais em Curitiba/PR, Florianópolis/SC e Porto Alegre/RS'
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Indústria Têxtil Fios de Ouro S.A.',
            'cnpj': '78.901.234/0001-33',
            'street': 'Rua dos Tecelões, 789',
            'number': '789',
            'district': 'Vila Operária',
            'city': 'Itajaí',
            'state': 'SC',
            'zip_code': '88300-123',
            'has_branches': False,
            'branches_description': None
        }
    ]
    
    clients = []
    for data in clients_data:
        # Verificar se já existe
        existing = Client.query.filter_by(cnpj=data['cnpj']).first()
        if not existing:
            client = Client(**data)
            db.session.add(client)
            clients.append(client)
            print(f"✓ Cliente criado: {data['name']}")
        else:
            clients.append(existing)
            print(f"→ Cliente já existe: {existing.name}")
    
    return clients

def create_sample_courts(db, Court, law_firm):
    """Cria varas judiciais de exemplo"""
    courts_data = [
        {
            'law_firm_id': law_firm.id,
            'section': 'Seção Judiciária de Santa Catarina',
            'vara_name': '1ª Vara Federal de Blumenau',
            'city': 'Blumenau',
            'state': 'SC'
        },
        {
            'law_firm_id': law_firm.id,
            'section': 'Seção Judiciária de Santa Catarina',
            'vara_name': '2ª Vara Federal de Joinville',
            'city': 'Joinville',
            'state': 'SC'
        },
        {
            'law_firm_id': law_firm.id,
            'section': 'Seção Judiciária de Santa Catarina',
            'vara_name': '1ª Vara Federal de Itajaí',
            'city': 'Itajaí',
            'state': 'SC'
        },
        {
            'law_firm_id': law_firm.id,
            'section': 'Seção Judiciária de São Paulo',
            'vara_name': '3ª Vara Federal de São Paulo',
            'city': 'São Paulo',
            'state': 'SP'
        },
        {
            'law_firm_id': law_firm.id,
            'section': 'Seção Judiciária do Paraná',
            'vara_name': '1ª Vara Federal de Curitiba',
            'city': 'Curitiba',
            'state': 'PR'
        }
    ]
    
    courts = []
    for data in courts_data:
        # Verificar se já existe
        existing = Court.query.filter_by(vara_name=data['vara_name']).first()
        if not existing:
            court = Court(**data)
            db.session.add(court)
            courts.append(court)
            print(f"✓ Vara criada: {data['vara_name']}")
        else:
            courts.append(existing)
            print(f"→ Vara já existe: {existing.vara_name}")
    
    return courts

def create_sample_lawyers(db, Lawyer, law_firm):
    """Cria advogados de exemplo"""
    lawyers_data = [
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. João Silva Santos',
            'oab_number': 'SP 123456',
            'email': 'joao.santos@advocacia.com.br',
            'phone': '(11) 98765-4321',
            'is_default_for_publications': True
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dra. Maria Fernanda Costa',
            'oab_number': 'SC 78901',
            'email': 'maria.costa@escritorio.adv.br',
            'phone': '(47) 99123-4567',
            'is_default_for_publications': False
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. Carlos Eduardo Oliveira',
            'oab_number': 'SC 45123',
            'email': 'carlos.oliveira@direito.com',
            'phone': '(47) 98888-7777',
            'is_default_for_publications': False
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dra. Ana Paula Rodrigues',
            'oab_number': 'SP 67890',
            'email': 'ana.rodrigues@advocaciasp.com.br',
            'phone': '(11) 97777-8888',
            'is_default_for_publications': False
        }
    ]
    
    lawyers = []
    for data in lawyers_data:
        # Verificar se já existe
        existing = Lawyer.query.filter_by(oab_number=data['oab_number']).first()
        if not existing:
            lawyer = Lawyer(**data)
            db.session.add(lawyer)
            lawyers.append(lawyer)
            print(f"✓ Advogado criado: {data['name']} - OAB: {data['oab_number']}")
        else:
            lawyers.append(existing)
            print(f"→ Advogado já existe: {existing.name}")
    
    return lawyers

def create_sample_cases(db, Case, law_firm, clients, courts, lawyers, default_case_status_id):
    """Cria casos jurídicos de exemplo"""
    cases_data = [
        {
            'law_firm_id': law_firm.id,
            'title': 'Revisão FAP - Acidente de Trabalho 2019-2021',
            'case_type': 'fap',
            'fap_start_year': 2019,
            'fap_end_year': 2021,
            'facts_summary': 'Contestação do FAP em razão de acidente de trajeto classificado incorretamente como acidente típico.',
            'thesis_summary': 'Art. 21, IV da Lei 8.213/91 - Acidente de trajeto não deve impactar no cálculo do FAP',
            'prescription_summary': 'Não há prescrição. Pedido administrativo protocolado em 2022.',
            'value_cause': Decimal('250000.00'),
            'status': 'active',
            'filing_date': date(2023, 3, 15)
        },
        {
            'law_firm_id': law_firm.id,
            'title': 'Revisão FAP - Nexo Causal Contestado 2020-2022',
            'case_type': 'fap',
            'fap_start_year': 2020,
            'fap_end_year': 2022,
            'facts_summary': 'Contestação de auxílio-doença acidentário concedido indevidamente sem nexo causal comprovado.',
            'thesis_summary': 'Inexistência de nexo causal entre atividade laboral e doença alegada pelo segurado',
            'prescription_summary': 'Prazo prescricional suspenso durante análise administrativa',
            'value_cause': Decimal('180000.00'),
            'status': 'active',
            'filing_date': date(2023, 6, 22)
        },
        {
            'law_firm_id': law_firm.id,
            'title': 'Anulação de Auto de Infração - NR12',
            'case_type': 'outros',
            'fap_start_year': None,
            'fap_end_year': None,
            'facts_summary': 'Auto de infração lavrado por descumprimento da NR12 sem fundamentação técnica adequada.',
            'thesis_summary': 'Vício de fundamentação e ausência de nexo entre irregularidade apontada e norma violada',
            'prescription_summary': 'Prazo para defesa respeitado dentro do prazo legal',
            'value_cause': Decimal('75000.00'),
            'status': 'draft',
            'filing_date': None
        },
        {
            'law_firm_id': law_firm.id,
            'title': 'Revisão FAP - Múltiplos Benefícios 2018-2020',
            'case_type': 'fap',
            'fap_start_year': 2018,
            'fap_end_year': 2020,
            'facts_summary': 'Contestação de múltiplos benefícios acidentários concedidos incorretamente impactando FAP.',
            'thesis_summary': 'Aplicação dos critérios do Decreto 6.042/2007 e análise individual de cada benefício',
            'prescription_summary': 'Parcialmente prescrito para período anterior a 2018',
            'value_cause': Decimal('420000.00'),
            'status': 'active',
            'filing_date': date(2023, 1, 10)
        }
    ]
    
    cases = []
    for i, data in enumerate(cases_data):
        # Atribuir cliente e vara
        data['client_id'] = clients[i % len(clients)].id
        data['court_id'] = courts[i % len(courts)].id
        data['case_status_id'] = default_case_status_id
        
        # Verificar se já existe
        existing = Case.query.filter_by(title=data['title']).first()
        if not existing:
            case = Case(**data)
            db.session.add(case)
            cases.append(case)
            print(f"✓ Caso criado: {data['title']}")
        else:
            cases.append(existing)
            print(f"→ Caso já existe: {existing.title}")
    
    return cases

def create_case_lawyers_relations(db, CaseLawyer, cases, lawyers):
    """Cria relacionamentos entre casos e advogados"""
    relations = []
    
    for i, case in enumerate(cases):
        # Verificar se já existe relação
        existing = CaseLawyer.query.filter_by(case_id=case.id).first()
        if not existing:
            # Advogado responsável
            responsible_lawyer = lawyers[i % len(lawyers)]
            case_lawyer = CaseLawyer(
                case_id=case.id,
                lawyer_id=responsible_lawyer.id,
                role='responsavel'
            )
            db.session.add(case_lawyer)
            relations.append(case_lawyer)
            
            # Alguns casos com advogado adicional para publicações
            if i % 2 == 0 and len(lawyers) > 1:
                pub_lawyer = lawyers[(i + 1) % len(lawyers)]
                if pub_lawyer.id != responsible_lawyer.id:
                    case_lawyer_pub = CaseLawyer(
                        case_id=case.id,
                        lawyer_id=pub_lawyer.id,
                        role='publicacoes'
                    )
                    db.session.add(case_lawyer_pub)
                    relations.append(case_lawyer_pub)
            
            print(f"✓ Relação caso-advogado criada para: {case.title}")
        else:
            print(f"→ Relação já existe para: {case.title}")
    
    return relations

def create_sample_benefits(db, CaseBenefit, cases):
    """Cria benefícios de exemplo relacionados aos casos"""
    benefits_data = [
        # Caso 1 - Revisão FAP Trajeto
        [
            {
                'benefit_number': '123456789-01',
                'benefit_type': 'B91',
                'insured_name': 'José da Silva',
                'insured_nit': '12345678901',
                'numero_cat': 'CAT-2019-001234',
                'numero_bo': 'BO-SC-2019-5678',
                'data_inicio_beneficio': date(2019, 8, 20),
                'data_fim_beneficio': date(2019, 11, 15),
                'accident_date': date(2019, 8, 15),
                'accident_company_name': 'Construtora Silva & Filhos Ltda',
                'notes': 'Acidente ocorreu no trajeto casa-trabalho, classificado incorretamente como típico'
            },
            {
                'benefit_number': '987654321-02',
                'benefit_type': 'B94',
                'insured_name': 'Maria Santos',
                'insured_nit': '98765432101',
                'numero_cat': 'CAT-2020-002345',
                'numero_bo': None,
                'data_inicio_beneficio': date(2020, 2, 15),
                'data_fim_beneficio': None,
                'accident_date': date(2020, 2, 10),
                'accident_company_name': 'Construtora Silva & Filhos Ltda',
                'notes': 'Queda de bicicleta no trajeto trabalho-casa'
            }
        ],
        # Caso 2 - Revisão FAP Nexo
        [
            {
                'benefit_number': '555666777-03',
                'benefit_type': 'B31',
                'insured_name': 'Carlos Oliveira',
                'insured_nit': '55566677701',
                'numero_cat': None,
                'numero_bo': None,
                'data_inicio_beneficio': date(2020, 11, 10),
                'data_fim_beneficio': date(2021, 5, 20),
                'accident_date': date(2020, 11, 5),
                'accident_company_name': 'Metalúrgica Aço Forte S.A.',
                'notes': 'Doença preexistente não relacionada ao trabalho'
            }
        ],
        # Caso 3 - Auto de Infração (sem benefícios)
        [],
        # Caso 4 - Múltiplos Benefícios
        [
            {
                'benefit_number': '111222333-04',
                'benefit_type': 'B91',
                'insured_name': 'Ana Costa',
                'insured_nit': '11122233301',
                'numero_cat': 'CAT-2018-003456',
                'numero_bo': 'BO-SC-2018-9012',
                'data_inicio_beneficio': date(2018, 5, 25),
                'data_fim_beneficio': date(2018, 8, 10),
                'accident_date': date(2018, 5, 20),
                'accident_company_name': 'Indústria Têxtil Fios de Ouro S.A.',
                'notes': 'Benefício concedido sem comprovação adequada'
            },
            {
                'benefit_number': '444555666-05',
                'benefit_type': 'B94',
                'insured_name': 'Pedro Alves',
                'insured_nit': '44455566601',
                'numero_cat': 'CAT-2019-004567',
                'numero_bo': None,
                'data_inicio_beneficio': date(2019, 9, 18),
                'data_fim_beneficio': None,
                'accident_date': date(2019, 9, 12),
                'accident_company_name': 'Indústria Têxtil Fios de Ouro S.A.',
                'notes': 'Lesão não relacionada à atividade profissional'
            },
            {
                'benefit_number': '777888999-06',
                'benefit_type': 'B31',
                'insured_name': 'Lucia Ferreira',
                'insured_nit': '77788899901',
                'numero_cat': 'CAT-2020-005678',
                'numero_bo': 'BO-SC-2020-3456',
                'data_inicio_beneficio': date(2020, 1, 15),
                'data_fim_beneficio': date(2020, 7, 30),
                'accident_date': date(2020, 1, 8),
                'accident_company_name': 'Indústria Têxtil Fios de Ouro S.A.',
                'notes': 'Acidente no trajeto, classificado como típico'
            }
        ]
    ]
    
    all_benefits = []
    for case_index, case_benefits in enumerate(benefits_data):
        if case_index < len(cases):
            case = cases[case_index]
            for benefit_data in case_benefits:
                benefit_data['case_id'] = case.id
                
                # Verificar se já existe
                existing = CaseBenefit.query.filter_by(
                    benefit_number=benefit_data['benefit_number']
                ).first()
                
                if not existing:
                    benefit = CaseBenefit(**benefit_data)
                    db.session.add(benefit)
                    all_benefits.append(benefit)
                    print(f"✓ Benefício criado: {benefit_data['benefit_number']} - {benefit_data['insured_name']}")
                else:
                    all_benefits.append(existing)
                    print(f"→ Benefício já existe: {existing.benefit_number}")
    
    return all_benefits

def create_sample_competences(db, CaseCompetence, cases):
    """Cria competências de exemplo para os casos"""
    competences = []
    
    for case in cases:
        if case.fap_start_year and case.fap_end_year:
            # Criar competências mensais para o período do FAP
            for year in range(case.fap_start_year, case.fap_end_year + 1):
                for month in range(1, 13):
                    # Verificar se já existe
                    existing = CaseCompetence.query.filter_by(
                        case_id=case.id,
                        competence_month=month,
                        competence_year=year
                    ).first()
                    
                    if not existing:
                        # Determinar status (algumas competências prescritas para exemplo)
                        status = 'prescribed' if year < case.fap_start_year + 1 and month <= 6 else 'valid'
                        
                        competence = CaseCompetence(
                            case_id=case.id,
                            competence_month=month,
                            competence_year=year,
                            status=status
                        )
                        db.session.add(competence)
                        competences.append(competence)
    
    if competences:
        print(f"✓ Criadas {len(competences)} competências para os casos FAP")
    
    return competences

def create_sample_activities(db, CaseActivity, cases, users):
    """Cria atividades de exemplo para os casos"""
    from datetime import datetime, timedelta, timezone
    
    activities = []
    activity_types = [
        {'type': 'caso_criado', 'title': 'Caso criado no sistema', 'icon': 'bi-file-text'},
        {'type': 'documento_adicionado', 'title': 'Documento adicionado', 'icon': 'bi-file-earmark'},
        {'type': 'beneficio_adicionado', 'title': 'Benefício adicionado', 'icon': 'bi-plus-circle'},
        {'type': 'advogado_atribuido', 'title': 'Advogado atribuído', 'icon': 'bi-person-plus'},
        {'type': 'status_alterado', 'title': 'Status alterado', 'icon': 'bi-arrow-repeat'},
    ]
    
    descriptions = {
        'caso_criado': 'Novo caso registrado no sistema',
        'documento_adicionado': 'Novo documento anexado ao processo',
        'beneficio_adicionado': 'Novo benefício de segurado adicionado',
        'advogado_atribuido': 'Advogado responsável pelo caso definido',
        'status_alterado': 'Status do caso foi atualizado'
    }
    
    # Para cada caso, criar 2-3 atividades
    for case_index, case in enumerate(cases):
        user = users[case_index % len(users)]
        
        # Atividade 1: Caso criado
        activity1_exists = CaseActivity.query.filter_by(
            case_id=case.id,
            activity_type='caso_criado'
        ).first()
        
        if not activity1_exists:
            activity1 = CaseActivity(
                case_id=case.id,
                user_id=user.id,
                activity_type='caso_criado',
                title='Caso criado no sistema',
                description='Novo caso registrado no sistema',
                created_at=datetime.now(timezone.utc) - timedelta(days=5)
            )
            db.session.add(activity1)
            activities.append(activity1)
        
        # Atividade 2: Benefício adicionado
        activity2_exists = CaseActivity.query.filter_by(
            case_id=case.id,
            activity_type='beneficio_adicionado'
        ).first()
        
        if not activity2_exists:
            activity2 = CaseActivity(
                case_id=case.id,
                user_id=user.id,
                activity_type='beneficio_adicionado',
                title='Benefício adicionado',
                description='Novo benefício de segurado adicionado ao caso',
                created_at=datetime.now(timezone.utc) - timedelta(days=3)
            )
            db.session.add(activity2)
            activities.append(activity2)
        
        # Atividade 3: Advogado atribuído
        activity3_exists = CaseActivity.query.filter_by(
            case_id=case.id,
            activity_type='advogado_atribuido'
        ).first()
        
        if not activity3_exists:
            activity3 = CaseActivity(
                case_id=case.id,
                user_id=user.id,
                activity_type='advogado_atribuido',
                title='Advogado atribuído',
                description=f'Advogado {user.name} foi atribuído ao caso',
                created_at=datetime.now(timezone.utc) - timedelta(days=2)
            )
            db.session.add(activity3)
            activities.append(activity3)
    
    if activities:
        print(f"✓ Criadas {len(activities)} atividades de exemplo")
    
    return activities

def create_sample_comments(db, CaseComment, cases, users):
    """Cria comentários de exemplo para os casos"""
    from datetime import datetime, timedelta, timezone
    
    comments = []
    
    comment_data = [
        {
            'title': 'Análise técnica do FAP',
            'content': 'Analisando a documentação do FAP, identifiquei inconsistências no período de 2019-2021. Será necessário requerer cálculo administrativo junto à INSS.'
        },
        {
            'title': 'Documentação faltante',
            'content': 'Solicitar ao cliente a lista completa de beneficiários inclusos no FAP para cotejamento com os dados do CNIS.'
        },
        {
            'title': 'Estratégia processual',
            'content': 'Recomendo primeiro tentar resolução administrativa via protocolo de contestação antes de ingressar ação judicial.'
        },
        {
            'title': 'Prazos críticos',
            'content': 'Atenção: prazo de prescrição termina em 6 meses. Protocolo administrativo deve ser feito até essa data.'
        },
        {
            'title': 'Parecer jurídico',
            'content': 'Com base na jurisprudência pacífica, acidente de trajeto não deve impactar o FAP. Temos tese forte para o caso.'
        }
    ]
    
    # Para cada caso, criar 1-2 comentários
    for case_index, case in enumerate(cases):
        # Pegar usuário aleatório (preferivelmente advogado)
        user = users[case_index % len(users)]
        
        # Comentário 1
        comment1_data = comment_data[case_index % len(comment_data)]
        comment1_exists = CaseComment.query.filter_by(
            case_id=case.id,
            title=comment1_data['title']
        ).first()
        
        if not comment1_exists:
            comment1 = CaseComment(
                case_id=case.id,
                user_id=user.id,
                comment_type='internal',
                title=comment1_data['title'],
                content=comment1_data['content'],
                is_pinned=case_index % 3 == 0,  # Algumas fixadas
                created_at=datetime.now(timezone.utc) - timedelta(days=2)
            )
            db.session.add(comment1)
            comments.append(comment1)
            db.session.flush()
            
            # Comentário 2: resposta ao comentário 1 (50% dos casos)
            if case_index % 2 == 0 and len(users) > 1:
                reply_user = users[(case_index + 1) % len(users)]
                reply_content = 'Concorrer com a análise. Vou preparar o protocolo administrativo para não perder o prazo.'
                
                comment2 = CaseComment(
                    case_id=case.id,
                    user_id=reply_user.id,
                    comment_type='internal',
                    content=reply_content,
                    parent_comment_id=comment1.id,
                    created_at=datetime.now(timezone.utc) - timedelta(hours=6)
                )
                db.session.add(comment2)
                comments.append(comment2)
    
    if comments:
        print(f"✓ Criados {len(comments)} comentários de exemplo")
    
    return comments

def main():
    """Função principal para executar a população de dados"""
    print("Iniciando populacao de dados de exemplo...")
    print("=" * 50)
    
    # Importar modelos no contexto correto
    app, db, LawFirm, User, Client, Court, Lawyer, Case, CaseLawyer, CaseCompetence, CaseBenefit, Document, CaseActivity, CaseComment, CaseStatus, KnowledgeCategory, KnowledgeTag, FapReason, CaseTemplate = import_models()
    
    # Garantir que o app seja configurado corretamente
    app.config.update({
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'SQLALCHEMY_DATABASE_URI': app.config.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///intellexia.db')
    })
    
    try:
        with app.app_context():
            # Verificar se as tabelas existem
            db.create_all()
            print("[OK] Tabelas verificadas/criadas")
            
            # Criar escritório de advocacia
            print("\n[ESCRITORIO] Criando escritorio de advocacia...")
            law_firm = create_sample_law_firm(db, LawFirm)
            
            # Criar usuários do sistema
            print("\n[USUARIOS] Criando usuarios...")
            users = create_sample_users(db, User, law_firm)
            
            # Commit dos dados básicos
            db.session.commit()
            print("[OK] Escritorio e usuarios salvos")
            
            # Criar bases de conhecimento padrão
            print("\n[CONHECIMENTO] Criando categorias de conhecimento...")
            categories = create_knowledge_categories(db, KnowledgeCategory, law_firm)
            
            print("\n[TAGS] Criando tags padrao...")
            tags = create_knowledge_tags(db, KnowledgeTag, law_firm)
            
            # Commit dos dados de conhecimento
            db.session.commit()
            print("[OK] Base de conhecimento configurada")
            
            # Criar dados de exemplo para casos
            print("\n[CLIENTES] Criando clientes...")
            clients = create_sample_clients(db, Client, law_firm)
            
            print("\n[VARAS] Criando varas judiciais...")
            courts = create_sample_courts(db, Court, law_firm)
            
            print("\n[ADVOGADOS] Criando advogados...")
            lawyers = create_sample_lawyers(db, Lawyer, law_firm)
            
            print("\n[FAP] Criando motivos de contestacao FAP...")
            fap_reasons = create_fap_reasons(db, FapReason, law_firm)
            
            print("\n[TEMPLATES] Criando templates de casos...")
            templates = create_case_templates(db, CaseTemplate, law_firm, users)

            print("\n[STATUS] Garantindo status de casos...")
            default_case_status_id = ensure_case_statuses(db, CaseStatus)
            
            # Commit dos dados básicos
            db.session.commit()
            print("[OK] Dados de setup salvos")
            
            print("\n[CASOS] Criando casos...")
            cases = create_sample_cases(db, Case, law_firm, clients, courts, lawyers, default_case_status_id)
            
            print("\n[RELACOES] Criando relacoes caso-advogado...")
            case_lawyers = create_case_lawyers_relations(db, CaseLawyer, cases, lawyers)
            
            print("\n[BENEFICIOS] Criando beneficios...")
            benefits = create_sample_benefits(db, CaseBenefit, cases)
            
            print("\n[COMPETENCIAS] Criando competencias...")
            competences = create_sample_competences(db, CaseCompetence, cases)
            
            print("\n[ATIVIDADES] Criando atividades de exemplo...")
            activities = create_sample_activities(db, CaseActivity, cases, users)
            
            print("\n[COMENTARIOS] Criando comentarios e discussoes...")
            comments = create_sample_comments(db, CaseComment, cases, users)
            
            # Commit final
            db.session.commit()
            
            print("\n" + "=" * 50)
            print("[SUCESSO] POPULACAO DE DADOS CONCLUIDA COM EXITO!")
            print(f"[RESUMO] Dados criados:")
            print(f"   - 1 escritorio de advocacia")
            print(f"   - {len(users)} usuarios")
            print(f"   - {len(categories)} categorias de conhecimento")
            print(f"   - {len(tags)} tags de documentos")
            print(f"   - {len(fap_reasons)} motivos de contestacao FAP")
            print(f"   - {len(templates)} templates de casos")
            print(f"   - {len(clients)} clientes")
            print(f"   - {len(courts)} varas judiciais")
            print(f"   - {len(lawyers)} advogados")
            print(f"   - {len(cases)} casos")
            print(f"   - {len(case_lawyers)} relacoes caso-advogado")
            print(f"   - {len(benefits)} beneficios")
            print(f"   - {len(competences)} competencias")
            print(f"   - {len(activities)} atividades")
            print(f"   - {len(comments)} comentarios")
            print("=" * 50)
            
    except Exception as e:
        print(f"[ERRO] Erro durante a populacao de dados: {e}")
        try:
            with app.app_context():
                db.session.rollback()
        except Exception as rollback_error:
            print(f"[ERRO] Erro no rollback: {rollback_error}")
        raise

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n[ERRO FATAL] {e}")
        print("\n[DETALHES] Detalhes do erro:")
        traceback.print_exc()
        sys.exit(1)