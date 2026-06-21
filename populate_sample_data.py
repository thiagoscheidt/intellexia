#!/usr/bin/env python3
"""
Script de seed inicial para Rodriguez & Sousa Advogados Associados.

Popula o banco com configurações de produção:
- Escritório de advocacia
- Usuários do sistema
- Advogados cadastrados
- Status de casos
- Categorias e tags da base de conhecimento
- Motivos de contestação FAP
- Templates de casos
- Teses jurídicas do painel judicial
- Prompts e referências do revisor FAP (IA)

Execute: uv run python populate_sample_data.py
"""

import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def import_models():
    from main import app
    from app.models import (
        db, LawFirm, User, Lawyer,
        CaseStatus, KnowledgeCategory, KnowledgeTag,
        FapReason, CaseTemplate,
    )
    return app, db, LawFirm, User, Lawyer, CaseStatus, KnowledgeCategory, KnowledgeTag, FapReason, CaseTemplate


def ensure_case_statuses(db, CaseStatus):
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
            db.session.add(CaseStatus(
                status_name=status_name,
                status_order=status_order,
                description=description
            ))
            created_count += 1

    if created_count > 0:
        db.session.flush()
        print(f"✓ Criados {created_count} status de caso")
    else:
        print("→ Status de caso já existem")


def create_knowledge_categories(db, KnowledgeCategory, law_firm):
    categories_data = [
        {'name': 'Jurisprudência', 'icon': 'book', 'description': 'Decisões judiciais relevantes, súmulas, precedentes', 'color': '#007bff', 'display_order': 1},
        {'name': 'Legislação', 'icon': 'scale', 'description': 'Leis, decretos, portarias, normas regulamentares', 'color': '#28a745', 'display_order': 2},
        {'name': 'Modelos', 'icon': 'file', 'description': 'Modelos de documentos, petições, contratos', 'color': '#17a2b8', 'display_order': 3},
        {'name': 'Artigos', 'icon': 'newspaper', 'description': 'Artigos jurídicos, estudos, análises doutrinárias', 'color': '#ffc107', 'display_order': 4},
        {'name': 'Manuais', 'icon': 'book-open', 'description': 'Manuais, guias práticos, tutoriais', 'color': '#6f42c1', 'display_order': 5},
        {'name': 'Procedimentos', 'icon': 'wrench', 'description': 'Procedimentos internos, fluxos de trabalho', 'color': '#fd7e14', 'display_order': 6},
        {'name': 'Outros', 'icon': 'box', 'description': 'Outros documentos e arquivos diversos', 'color': '#6c757d', 'display_order': 7},
    ]

    for cat_data in categories_data:
        existing = KnowledgeCategory.query.filter_by(law_firm_id=law_firm.id, name=cat_data['name']).first()
        if not existing:
            db.session.add(KnowledgeCategory(law_firm_id=law_firm.id, **cat_data))
            print(f"✓ Categoria criada: {cat_data['name']}")
        else:
            print(f"→ Categoria já existe: {cat_data['name']}")


def create_knowledge_tags(db, KnowledgeTag, law_firm):
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

    created = 0
    for tag_data in tags_data:
        existing = KnowledgeTag.query.filter_by(law_firm_id=law_firm.id, name=tag_data['name']).first()
        if not existing:
            db.session.add(KnowledgeTag(
                law_firm_id=law_firm.id,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                **tag_data
            ))
            created += 1

    print(f"✓ {created} tags criadas ({len(tags_data) - created} já existiam)")


def create_fap_reasons(db, FapReason, law_firm):
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

    for display_name, description in reasons_data:
        existing = FapReason.query.filter_by(law_firm_id=law_firm.id, display_name=display_name).first()
        if not existing:
            db.session.add(FapReason(
                law_firm_id=law_firm.id,
                display_name=display_name,
                description=description,
                is_active=True
            ))
            print(f"✓ Motivo FAP criado: {display_name}")
        else:
            print(f"→ Motivo FAP já existe: {display_name}")


def create_case_templates(db, CaseTemplate, law_firm, users):
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
        raise ValueError("Nenhum usuário disponível para criação dos templates")

    for template_name, resumo_curto, categoria in templates_data:
        existing = CaseTemplate.query.filter_by(law_firm_id=law_firm.id, template_name=template_name).first()
        if not existing:
            original_filename = f"{template_name}.docx"
            db.session.add(CaseTemplate(
                user_id=owner_user_id,
                law_firm_id=law_firm.id,
                template_name=template_name,
                resumo_curto=resumo_curto,
                categoria=categoria,
                original_filename=original_filename,
                file_path=f"uploads/templates/{law_firm.id}/{original_filename}",
                file_type='DOCX',
                is_active=True
            ))
            print(f"✓ Template criado: {template_name}")
        else:
            print(f"→ Template já existe: {template_name}")


def create_law_firm(db, LawFirm):
    law_firm_data = {
        'name': 'Rodriguez & Sousa Advogados Associados',
        'trade_name': 'Rodriguez & Sousa',
        'cnpj': '23.456.789/0001-01',
        'street': 'Rua Tenente Silveira',
        'number': '293',
        'complement': '4º andar - Edifício Reflex',
        'district': 'Centro',
        'city': 'Florianópolis',
        'state': 'SC',
        'zip_code': '88010-301',
        'phone': '(48) 3307-4803',
        'email': 'contato@advrodriguez.com.br',
        'website': 'www.advrodriguez.com.br',
        'is_active': True,
        'subscription_plan': 'premium',
        'subscription_expires_at': datetime.now(timezone.utc) + timedelta(days=365),
        'max_users': 50,
        'max_cases': 1000,
    }

    existing = LawFirm.query.filter_by(cnpj=law_firm_data['cnpj']).first()
    if not existing:
        law_firm = LawFirm(**law_firm_data)
        db.session.add(law_firm)
        db.session.flush()
        print(f"✓ Escritório criado: {law_firm_data['name']}")
        return law_firm
    else:
        print(f"→ Escritório já existe: {existing.name}")
        return existing


def create_users(db, User, law_firm):
    users_data = [
        # Admins
        {
            'law_firm_id': law_firm.id,
            'name': 'Alfredo Rodriguez',
            'email': 'alfredo@advrodriguez.com.br',
            'oab_number': 'OAB/SC 53.004',
            'role': 'admin',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Gabriel Batista de Sousa',
            'email': 'gabriel@advrodriguez.com.br',
            'oab_number': 'OAB/SC 46.152',
            'role': 'admin',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Christian da Silveira',
            'email': 'christian@advrodriguez.com.br',
            'oab_number': 'OAB/SC 12.417',
            'role': 'admin',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Aliathan Rudá Martins',
            'email': 'aliathan@advrodriguez.com.br',
            'oab_number': 'OAB/SC 66.093',
            'role': 'admin',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Isrhael dos Santos',
            'email': 'isrhael@advrodriguez.com.br',
            'oab_number': 'OAB/SC 60.421',
            'role': 'admin',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Frederick Vilamil',
            'email': 'frederick@advrodriguez.com.br',
            'role': 'admin',
            'is_active': True,
            'is_verified': True,
        },
        # Advogados
        {
            'law_firm_id': law_firm.id,
            'name': 'Luiza Ludvig de Sousa',
            'email': 'luiza@advrodriguez.com.br',
            'oab_number': 'OAB/SC 51.389',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Ana Gabriela de Oliveira Affonso',
            'email': 'anagabriela@advrodriguez.com.br',
            'oab_number': 'OAB/SP 488.038',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'André Martini de Lemos Portalupi Monteiro',
            'email': 'andre@advrodriguez.com.br',
            'oab_number': 'OAB/SP 300.218',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Edivan V. da Cunha Júnior',
            'email': 'edivan@advrodriguez.com.br',
            'oab_number': 'OAB/SC 72.458',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Felipe Emanuel Biesek',
            'email': 'felipe@advrodriguez.com.br',
            'oab_number': 'OAB/SC 61.875',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Francieli Negri Scheuble',
            'email': 'francieli@advrodriguez.com.br',
            'oab_number': 'OAB/SC 34.296',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Guilherme Henrique Pereira Canuto',
            'email': 'guilherme@advrodriguez.com.br',
            'oab_number': 'OAB/SC 63.967',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Isadora Chaves',
            'email': 'isadora@advrodriguez.com.br',
            'oab_number': 'OAB/SC 55.128',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'João Vítor Fornari Bonassi',
            'email': 'joaovitor@advrodriguez.com.br',
            'oab_number': 'OAB/SC 68.864',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Mariana Carvalho Bellussi',
            'email': 'mariana@advrodriguez.com.br',
            'oab_number': 'OAB/SC 61.821',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Rachel de Macedo',
            'email': 'rachel@advrodriguez.com.br',
            'oab_number': 'OAB/PR 89.519',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Rodrigo Silveira',
            'email': 'rodrigo@advrodriguez.com.br',
            'oab_number': 'OAB/SC 37.869',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Thiago Henrique Elias',
            'email': 'thiago.elias@advrodriguez.com.br',
            'oab_number': 'OAB/SC 60.326',
            'role': 'lawyer',
            'is_active': True,
            'is_verified': True,
        },
        # Administrativo
        {
            'law_firm_id': law_firm.id,
            'name': 'Juliana Alves Maia Ruivo',
            'email': 'juliana@advrodriguez.com.br',
            'role': 'assistant',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Bárbara Magalhães',
            'email': 'barbara@advrodriguez.com.br',
            'role': 'assistant',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Julia Gomes Silva',
            'email': 'julia.gomes@advrodriguez.com.br',
            'role': 'assistant',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Igor Bezerra',
            'email': 'igor@advrodriguez.com.br',
            'role': 'assistant',
            'is_active': True,
            'is_verified': True,
        },
        # Estagiários
        {
            'law_firm_id': law_firm.id,
            'name': 'Bernardo Borges Brascher',
            'email': 'bernardo@advrodriguez.com.br',
            'role': 'user',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Evair da Silva Borges',
            'email': 'evair@advrodriguez.com.br',
            'role': 'user',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Daniel Vieira Cabral Gomes',
            'email': 'daniel@advrodriguez.com.br',
            'role': 'user',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Hanna Carolina Sombrio Monteiro',
            'email': 'hanna.monteiro@advrodriguez.com.br',
            'role': 'user',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Henri Sodré N. de Sousa',
            'email': 'henri@advrodriguez.com.br',
            'role': 'user',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Julia Maria Castanha de Oliveira',
            'email': 'julia@advrodriguez.com.br',
            'role': 'user',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Julia Morenita de Andrade Correa',
            'email': 'julia.morenita@advrodriguez.com.br',
            'role': 'user',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Karoline Silva Correa',
            'email': 'karoline@advrodriguez.com.br',
            'role': 'user',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Kathlin Ricardo Carvalho',
            'email': 'kathlin@advrodriguez.com.br',
            'role': 'user',
            'is_active': True,
            'is_verified': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Maria Eduarda Martins',
            'email': 'maria.martins@advrodriguez.com.br',
            'role': 'user',
            'is_active': True,
            'is_verified': True,
        },
    ]

    users = []
    for data in users_data:
        existing = User.query.filter_by(email=data['email']).first()
        if not existing:
            user = User(**data)
            user.set_password('123456')
            db.session.add(user)
            users.append(user)
            print(f"✓ Usuário criado: {data['name']} ({data['role']})")
        else:
            users.append(existing)
            print(f"→ Usuário já existe: {existing.name}")

    return users


def create_lawyers(db, Lawyer, law_firm):
    lawyers_data = [
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. Alfredo Rodriguez',
            'oab_number': 'OAB/SC 53.004',
            'email': 'alfredo@advrodriguez.com.br',
            'is_default_for_publications': True,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. Gabriel Batista de Sousa',
            'oab_number': 'OAB/SC 46.152',
            'email': 'gabriel@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dra. Luiza Ludvig de Sousa',
            'oab_number': 'OAB/SC 51.389',
            'email': 'luiza@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. Christian da Silveira',
            'oab_number': 'OAB/SC 12.417',
            'email': 'christian@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. Aliathan Rudá Martins',
            'oab_number': 'OAB/SC 66.093',
            'email': 'aliathan@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. Isrhael dos Santos',
            'oab_number': 'OAB/SC 60.421',
            'email': 'isrhael@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dra. Ana Gabriela de Oliveira Affonso',
            'oab_number': 'OAB/SP 488.038',
            'email': 'anagabriela@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. André Martini de Lemos Portalupi Monteiro',
            'oab_number': 'OAB/SP 300.218',
            'email': 'andre@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. Edivan V. da Cunha Júnior',
            'oab_number': 'OAB/SC 72.458',
            'email': 'edivan@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. Felipe Emanuel Biesek',
            'oab_number': 'OAB/SC 61.875',
            'email': 'felipe@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dra. Francieli Negri Scheuble',
            'oab_number': 'OAB/SC 34.296',
            'email': 'francieli@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. Guilherme Henrique Pereira Canuto',
            'oab_number': 'OAB/SC 63.967',
            'email': 'guilherme@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dra. Isadora Chaves',
            'oab_number': 'OAB/SC 55.128',
            'email': 'isadora@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. João Vítor Fornari Bonassi',
            'oab_number': 'OAB/SC 68.864',
            'email': 'joaovitor@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dra. Mariana Carvalho Bellussi',
            'oab_number': 'OAB/SC 61.821',
            'email': 'mariana@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dra. Rachel de Macedo',
            'oab_number': 'OAB/PR 89.519',
            'email': 'rachel@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. Rodrigo Silveira',
            'oab_number': 'OAB/SC 37.869',
            'email': 'rodrigo@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
        {
            'law_firm_id': law_firm.id,
            'name': 'Dr. Thiago Henrique Elias',
            'oab_number': 'OAB/SC 60.326',
            'email': 'thiago.elias@advrodriguez.com.br',
            'is_default_for_publications': False,
        },
    ]

    for data in lawyers_data:
        existing = Lawyer.query.filter_by(oab_number=data['oab_number']).first()
        if not existing:
            db.session.add(Lawyer(**data))
            print(f"✓ Advogado criado: {data['name']} - OAB: {data['oab_number']}")
        else:
            print(f"→ Advogado já existe: {existing.name}")


def main():
    print("Iniciando seed de producao — Rodriguez & Sousa Advogados Associados")
    print("=" * 60)

    (
        app, db, LawFirm, User, Lawyer, CaseStatus,
        KnowledgeCategory, KnowledgeTag, FapReason, CaseTemplate
    ) = import_models()

    try:
        with app.app_context():
            db.create_all()
            print("[OK] Tabelas verificadas")

            print("\n[ESCRITORIO] Criando escritorio...")
            law_firm = create_law_firm(db, LawFirm)

            print("\n[USUARIOS] Criando usuarios...")
            users = create_users(db, User, law_firm)

            db.session.commit()
            print("[OK] Escritório e usuários salvos")

            print("\n[ADVOGADOS] Criando advogados...")
            create_lawyers(db, Lawyer, law_firm)

            print("\n[STATUS] Criando status de casos...")
            ensure_case_statuses(db, CaseStatus)

            print("\n[CONHECIMENTO] Criando categorias...")
            create_knowledge_categories(db, KnowledgeCategory, law_firm)

            print("\n[TAGS] Criando tags...")
            create_knowledge_tags(db, KnowledgeTag, law_firm)

            print("\n[FAP] Criando motivos de contestacao FAP...")
            create_fap_reasons(db, FapReason, law_firm)

            print("\n[TEMPLATES] Criando templates de casos...")
            create_case_templates(db, CaseTemplate, law_firm, users)

            db.session.commit()
            print("[OK] Configuracoes base salvas")

        # Seeds que gerenciam seu próprio contexto
        print("\n[TESES] Populando teses juridicas padrao...")
        from database.populate_default_legal_theses import populate_default_legal_theses
        populate_default_legal_theses()

        print("\n[FAP REVIEW] Populando prompts e referencias do revisor FAP...")
        from database.seed_fap_review_data import seed_initial_data
        seed_initial_data()

        print("\n" + "=" * 60)
        print("[SUCESSO] Seed de producao concluido com exito!")
        print("=" * 60)

    except Exception as e:
        print(f"\n[ERRO] {e}")
        try:
            from main import app
            from app.models import db
            with app.app_context():
                db.session.rollback()
        except Exception:
            pass
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n[ERRO FATAL] {e}")
        traceback.print_exc()
        sys.exit(1)
