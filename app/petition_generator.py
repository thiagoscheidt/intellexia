#!/usr/bin/env python3
"""
Gerador de contexto estruturado para petições jurídicas
Sistema Intellexia - Mapeamento de dados do banco para estrutura JSON
"""

from datetime import datetime
from decimal import Decimal
from app.models import Case, Client, CaseBenefit, Document, CaseCompetence, Lawyer, Court, LawFirm

def generate_fap_petition_context(case_id):
    """
    Gera contexto estruturado para geração de petições de revisão de FAP
    baseado nos dados reais do banco de dados do sistema Intellexia
    
    Args:
        case_id (int): ID do caso no banco de dados
    
    Returns:
        dict: Contexto estruturado para geração da petição
    """
    
    # Buscar dados do caso
    case = Case.query.get(case_id)
    if not case:
        raise ValueError(f"Caso {case_id} não encontrado")
    
    # Buscar dados relacionados
    client = case.client
    court = case.court
    law_firm = case.law_firm
    benefits = case.benefits
    documents = case.documents
    competences = case.competences
    case_lawyers = case.case_lawyers
    
    # Gerar estrutura JSON compatível com geração de petições
    context = {
        "request_metadata": {
            "request_id": f"intellexia-{case.id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "generated_at": datetime.now().isoformat(),
            "case_id": case.id,
            "analysis_version": "1.0",
            "language": "pt-BR",
            "system": "Intellexia Legal Case Management"
        },
        
        "law_firm": {
            "name": law_firm.name if law_firm else None,
            "trade_name": law_firm.trade_name if law_firm else None,
            "cnpj": law_firm.cnpj if law_firm else None,
            "address": {
                "street": law_firm.street if law_firm else None,
                "number": law_firm.number if law_firm else None,
                "district": law_firm.district if law_firm else None,
                "city": law_firm.city if law_firm else None,
                "state": law_firm.state if law_firm else None,
                "zip_code": law_firm.zip_code if law_firm else None
            } if law_firm else None,
            "contact": {
                "phone": law_firm.phone if law_firm else None,
                "email": law_firm.email if law_firm else None,
                "website": law_firm.website if law_firm else None
            } if law_firm else None
        },
        
        "company": {
            "corporate_name": client.name if client else "EMPRESA NÃO IDENTIFICADA",
            "cnpj": client.cnpj if client else None,
            "address": {
                "street": client.street if client else None,
                "number": client.number if client else None,
                "district": client.district if client else None,
                "city": client.city if client else None,
                "state": client.state if client else None,
                "zip_code": client.zip_code if client else None
            } if client else None,
            "has_branches": client.has_branches if client else False,
            "branches_description": client.branches_description if client else None,
            "establishment_cnpj": client.cnpj if client else None  # Simplificado - apenas um estabelecimento
        },
        
        "case_info": {
            "title": case.title,
            "case_type": case.case_type,
            "status": case.status,
            "filing_date": case.filing_date.isoformat() if case.filing_date else None,
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "value_cause": float(case.value_cause) if case.value_cause else None
        },
        
        "fap_context": {
            "calculation_years": list(range(case.fap_start_year, case.fap_end_year + 1)) if case.fap_start_year and case.fap_end_year else [],
            "vigencies": list(range(case.fap_start_year + 1, case.fap_end_year + 2)) if case.fap_start_year and case.fap_end_year else [],
            "start_year": case.fap_start_year,
            "end_year": case.fap_end_year,
            "tax_affected": "GIILRAT",  # Padrão para casos FAP
            "impact": "majoração indevida da alíquota"
        },
        
        "court_info": {
            "section": court.section if court else None,
            "vara_name": court.vara_name if court else None,
            "city": court.city if court else None,
            "state": court.state if court else None
        },
        
        "lawyers": [
            {
                "lawyer_id": cl.lawyer.id,
                "name": cl.lawyer.name,
                "oab_number": cl.lawyer.oab_number,
                "email": cl.lawyer.email,
                "phone": cl.lawyer.phone,
                "role_in_case": cl.role,
                "is_default_for_publications": cl.lawyer.is_default_for_publications
            }
            for cl in case_lawyers if cl.lawyer
        ],
        
        "benefits": [
            {
                "benefit_id": f"ben-{benefit.id}",
                "case_id": case.id,
                "benefit_number": benefit.benefit_number,
                "benefit_type": benefit.benefit_type,
                "benefit_description": _get_benefit_description(benefit.benefit_type),
                "insured_name": benefit.insured_name,
                "insured_nit": benefit.insured_nit,
                "accident_date": benefit.accident_date.isoformat() if benefit.accident_date else None,
                "accident_company_name": benefit.accident_company_name,
                "error_reason": benefit.error_reason,
                "error_description": _get_error_description(benefit.error_reason),
                "notes": benefit.notes,
                "created_at": benefit.created_at.isoformat() if benefit.created_at else None,
                "included_in_fap": True,  # Assumindo que todos os benefícios listados foram incluídos indevidamente
                "establishment_cnpj": client.cnpj if client else None
            }
            for benefit in benefits
        ],
        
        "competences": [
            {
                "competence_id": f"comp-{comp.id}",
                "month": comp.competence_month,
                "year": comp.competence_year,
                "status": comp.status,
                "period": f"{comp.competence_month:02d}/{comp.competence_year}"
            }
            for comp in competences
        ],
        
        "documents": [
            {
                "document_id": doc.id,
                "filename": doc.original_filename,
                "document_type": doc.document_type,
                "description": doc.description,
                "upload_date": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
                "ai_summary": doc.ai_summary,
                "ai_status": doc.ai_status,
                "related_benefit_id": doc.related_benefit_id,
                "use_in_petition": doc.use_in_ai
            }
            for doc in documents
        ],
        
        "legal_facts": {
            "facts_summary": case.facts_summary,
            "thesis_summary": case.thesis_summary,
            "prescription_summary": case.prescription_summary
        },
        
        "legal_basis": {
            "primary_resolution": {
                "code": "CNPS 1.329/2017",
                "effective_from_fap": 2018,
                "summary": "Exclusão de acidentes de trajeto do cálculo do FAP"
            },
            "law_references": [
                {
                    "law": "Lei 8.213/91",
                    "article": "Art. 21, IV, d",
                    "summary": "Caracterização do acidente de trajeto"
                },
                {
                    "law": "Decreto 3.048/99",
                    "article": "Art. 21A",
                    "summary": "Regulamentação do acidente de trajeto"
                }
            ],
            "jurisprudence": [
                {
                    "court": "TRF4",
                    "summary": "Exclusão de benefício decorrente de acidente de trajeto do FAP"
                }
            ]
        },
        
        "analysis": {
            "case_type_analysis": _analyze_case_type(case),
            "benefits_analysis": _analyze_benefits(benefits),
            "fap_error_detected": len(benefits) > 0 and case.case_type in ['fap_trajeto', 'fap_nexo', 'fap_multiplos']
        },
        
        "conclusion": {
            "benefits_to_exclude_from_fap": [benefit.benefit_number for benefit in benefits],
            "reason": _generate_conclusion_reason(case, benefits),
            "recommended_actions": _generate_recommended_actions(case, benefits),
            "total_benefits": len(benefits),
            "estimated_impact": f"Exclusão de {len(benefits)} benefício(s) da base de cálculo do FAP"
        },
        
        "output_preferences": {
            "generate_technical_report": True,
            "generate_legal_summary": True,
            "output_formats": ["HTML", "PDF", "DOCX"],
            "tone": "técnico-jurídico",
            "do_not_invent_information": True,
            "include_jurisprudence": True,
            "include_calculations": True
        }
    }
    
    return context


def _get_benefit_description(benefit_type):
    """Retorna descrição do tipo de benefício"""
    descriptions = {
        "B91": "Auxílio por Incapacidade Temporária por Acidente de Trabalho",
        "B94": "Auxílio-Acidente por Acidente de Trabalho",
        "B31": "Aposentadoria por Invalidez",
        "B32": "Aposentadoria por Idade",
        "B92": "Auxílio por Incapacidade Temporária"
    }
    return descriptions.get(benefit_type, f"Benefício {benefit_type}")


def _get_error_description(error_reason):
    """Retorna descrição do motivo do erro"""
    descriptions = {
        "acidente_trajeto": "Acidente de trajeto incluído indevidamente no FAP",
        "sem_nexo_causal": "Ausência de nexo causal entre a atividade laboral e a lesão",
        "classificacao_incorreta": "Classificação incorreta do tipo de acidente",
        "doenca_preexistente": "Doença preexistente não relacionada ao trabalho"
    }
    return descriptions.get(error_reason, error_reason or "Não especificado")


def _analyze_case_type(case):
    """Analisa o tipo de caso para contexto específico"""
    analysis = {
        "type": case.case_type,
        "description": case.facts_summary,
        "legal_framework": case.thesis_summary
    }
    
    if case.case_type == 'fap_trajeto':
        analysis.update({
            "specific_issue": "acidente_de_trajeto",
            "criteria_analysis": [
                "Verificar se ocorreu fora do local de trabalho",
                "Verificar se ocorreu fora do horário de trabalho",
                "Confirmar trajeto residência ↔ trabalho"
            ]
        })
    elif case.case_type == 'fap_nexo':
        analysis.update({
            "specific_issue": "ausencia_nexo_causal",
            "criteria_analysis": [
                "Analisar relação entre atividade e lesão",
                "Verificar exames médicos",
                "Avaliar histórico ocupacional"
            ]
        })
    
    return analysis


def _analyze_benefits(benefits):
    """Analisa os benefícios do caso"""
    if not benefits:
        return {"total": 0, "types": [], "analysis": "Nenhum benefício cadastrado"}
    
    types_count = {}
    for benefit in benefits:
        types_count[benefit.benefit_type] = types_count.get(benefit.benefit_type, 0) + 1
    
    return {
        "total": len(benefits),
        "types": types_count,
        "analysis": f"Total de {len(benefits)} benefício(s) identificado(s)",
        "error_patterns": [benefit.error_reason for benefit in benefits if benefit.error_reason]
    }


def _generate_conclusion_reason(case, benefits):
    """Gera o motivo da conclusão baseado no caso e benefícios"""
    if case.case_type == 'fap_trajeto':
        return "Benefícios decorrentes de acidente de trajeto incluídos indevidamente no FAP"
    elif case.case_type == 'fap_nexo':
        return "Benefícios concedidos sem comprovação adequada de nexo causal incluídos no FAP"
    elif case.case_type == 'fap_multiplos':
        return "Múltiplos benefícios incluídos indevidamente na base de cálculo do FAP"
    else:
        return "Benefícios incluídos indevidamente no cálculo do FAP"


def _generate_recommended_actions(case, benefits):
    """Gera ações recomendadas baseadas no caso"""
    actions = [
        "Excluir benefícios da base de cálculo do FAP",
        "Recalcular índice FAP para os períodos afetados",
        "Avaliar restituição de valores pagos a maior"
    ]
    
    if case.case_type == 'fap_trajeto':
        actions.append("Requerer aplicação da Resolução CNPS 1.329/2017")
    
    if len(benefits) > 1:
        actions.append("Analisar impacto cumulativo dos benefícios excluídos")
    
    return actions


# ========================
# FUNÇÕES DE GERAÇÃO DE PETIÇÕES
# ========================

def generate_structured_petition(context):
    """
    Gera petição baseada no contexto estruturado
    
    Args:
        context (dict): Contexto estruturado gerado por generate_fap_petition_context
    
    Returns:
        str: Conteúdo da petição formatada
    """
    case_info = context.get('case_info', {})
    
    # Para casos de acidente de trajeto, gerar apenas o tópico específico
    if case_info.get('case_type') == 'fap_trajeto':
        return generate_accident_trajectory_topic(context)
    
    # Para outros casos, manter a geração completa
    return generate_full_petition(context)


def generate_accident_trajectory_topic(context):
    """
    Gera apenas o tópico específico de acidente de trajeto
    
    Args:
        context (dict): Contexto estruturado
    
    Returns:
        str: Tópico de acidente de trajeto formatado
    """
    benefits = context.get('benefits', [])
    fap_context = context.get('fap_context', {})
    
    # Cabeçalho do tópico
    topic_content = """3.1. DA EXCLUSÃO DOS ACIDENTES DE TRAJETO

A Resolução CNPS nº 1.329/2017 estabelece expressamente que os benefícios decorrentes de acidentes de trajeto devem ser excluídos do cálculo do FAP, conforme dispõe o art. 21, inciso IV, alínea "d" da Lei 8.213/91.

O acidente de trajeto, por ocorrer fora das dependências da empresa e fora do horário de trabalho, não guarda relação com as condições de segurança do ambiente laboral, não podendo, portanto, ser considerado para majoração das contribuições previdenciárias através do FAP.

"""
    
    # Adicionar informações específicas dos benefícios se disponível
    trajectory_benefits = [b for b in benefits if b.get('benefit_type') in ['B91', 'B94'] and 'trajeto' in str(b.get('error_description', '')).lower()]
    
    if trajectory_benefits:
        topic_content += "3.1.1. DOS BENEFÍCIOS ESPECÍFICOS DE TRAJETO\n\n"
        topic_content += "Os seguintes benefícios foram concedidos em decorrência de acidentes de trajeto e devem ser excluídos do cálculo do FAP:\n\n"
        
        for i, benefit in enumerate(trajectory_benefits, 1):
            topic_content += f"• **Benefício {benefit.get('benefit_number')}** - {benefit.get('insured_name')}\n"
            if benefit.get('accident_date'):
                topic_content += f"  Data do acidente: {benefit.get('accident_date')}\n"
            if benefit.get('error_description'):
                topic_content += f"  Fundamentação: {benefit.get('error_description')}\n"
            topic_content += "\n"
    
    # Adicionar fundamentação legal específica
    topic_content += """3.1.2. DA FUNDAMENTAÇÃO LEGAL

A Lei 8.213/91, em seu artigo 21, inciso IV, alínea "d", define acidente de trajeto como aquele ocorrido no percurso da residência para o local de trabalho ou deste para aquela, qualquer que seja o meio de locomoção, inclusive veículo de propriedade do segurado.

A Resolução CNPS nº 1.329/2017, que regulamenta o cálculo do FAP, estabelece que devem ser excluídos da base de cálculo os benefícios decorrentes de acidentes de trajeto, reconhecendo que tais eventos não estão sob o controle direto do empregador.

O Superior Tribunal de Justiça já consolidou entendimento de que acidentes de trajeto não podem ser imputados ao empregador para fins de responsabilização previdenciária, devendo ser excluídos de qualquer cálculo que majore contribuições empresariais.

"""
    
    # Período FAP se disponível
    if fap_context.get('calculation_years'):
        years = fap_context['calculation_years']
        topic_content += f"3.1.3. DO PERÍODO AFETADO\n\n"
        topic_content += f"A exclusão dos benefícios de trajeto impacta o cálculo do FAP para o período de {min(years)} a {max(years)}, com efeitos na vigência de {min(years)+1} a {max(years)+1}.\n\n"
    
    return topic_content


def generate_full_petition(context):
    """
    Gera petição completa baseada no contexto estruturado
    
    Args:
        context (dict): Contexto estruturado gerado por generate_fap_petition_context
    
    Returns:
        str: Conteúdo da petição completa formatada
    """
    company = context.get('company', {})
    court = context.get('court_info', {})
    case_info = context.get('case_info', {})
    fap_context = context.get('fap_context', {})
    benefits = context.get('benefits', [])
    legal_facts = context.get('legal_facts', {})
    analysis = context.get('analysis', {})
    conclusion = context.get('conclusion', {})
    lawyers = context.get('lawyers', [])
    
    # Cabeçalho
    petition_content = f"""EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) DE DIREITO DA {court.get('vara_name', 'VARA COMPETENTE')}

{company.get('corporate_name', 'EMPRESA AUTORA')}, pessoa jurídica de direito privado, inscrita no CNPJ sob nº {company.get('cnpj', 'XX.XXX.XXX/XXXX-XX')}, com sede em {company.get('address', {}).get('city', 'CIDADE')}/{company.get('address', {}).get('state', 'UF')}, vem, por meio de seu(s) advogado(s) signatário(s), com fundamento na Lei nº 8.213/91 e Resolução CNPS nº 1.329/2017, propor a presente

{get_petition_title(case_info.get('case_type'))}

em face do INSTITUTO NACIONAL DO SEGURO SOCIAL – INSS, autarquia federal, pelos motivos de fato e de direito a seguir expostos:

I – DOS FATOS

{legal_facts.get('facts_summary', 'A empresa autora foi surpreendida com a inclusão indevida de benefícios acidentários no cálculo do Fator Acidentário de Prevenção (FAP), resultando em majoração indevida das contribuições previdenciárias.')}

"""
    
    # Período FAP
    if fap_context.get('calculation_years'):
        years = fap_context['calculation_years']
        petition_content += f"""
A presente ação refere-se ao período de cálculo do FAP dos anos de {min(years)} a {max(years)}, com vigência para os anos de {min(years)+1} a {max(years)+1}.
"""
    
    # Seção dos benefícios
    if benefits:
        petition_content += f"\n\nII – DOS BENEFÍCIOS CONTESTADOS\n\n"
        petition_content += f"Foram indevidamente incluídos no cálculo do FAP da empresa os seguintes benefícios:\n\n"
        
        for i, benefit in enumerate(benefits, 1):
            petition_content += f"{i}. **Benefício nº {benefit.get('benefit_number')}** - {benefit.get('benefit_description')}\n"
            petition_content += f"   • Segurado: {benefit.get('insured_name')}\n"
            
            if benefit.get('insured_nit'):
                petition_content += f"   • NIT: {benefit.get('insured_nit')}\n"
            
            if benefit.get('accident_date'):
                petition_content += f"   • Data do Acidente: {benefit.get('accident_date')}\n"
            
            if benefit.get('error_description'):
                petition_content += f"   • **Motivo da Contestação**: {benefit.get('error_description')}\n"
            
            if benefit.get('notes'):
                petition_content += f"   • Observações: {benefit.get('notes')}\n"
            
            petition_content += "\n"
    
    # Fundamentação jurídica
    petition_content += f"""
III – DO DIREITO

{legal_facts.get('thesis_summary', 'A inclusão indevida dos benefícios acidentários no cálculo do FAP viola os princípios constitucionais da legalidade e da capacidade contributiva.')}

"""
    
    # Adicionar fundamentação específica por tipo de caso
    if case_info.get('case_type') == 'fap_trajeto':
        petition_content += """
3.1. DA EXCLUSÃO DOS ACIDENTES DE TRAJETO

A Resolução CNPS nº 1.329/2017 estabelece expressamente que os benefícios decorrentes de acidentes de trajeto devem ser excluídos do cálculo do FAP, conforme dispõe o art. 21, inciso IV, alínea "d" da Lei 8.213/91.

O acidente de trajeto, por ocorrer fora das dependências da empresa e fora do horário de trabalho, não guarda relação com as condições de segurança do ambiente laboral, não podendo, portanto, ser considerado para majoração das contribuições previdenciárias através do FAP.

"""
    elif case_info.get('case_type') == 'fap_nexo':
        petition_content += """
3.1. DA AUSÊNCIA DE NEXO CAUSAL

Os benefícios contestados foram concedidos sem a devida comprovação do nexo causal entre a atividade laboral desempenhada na empresa e a lesão alegada pelo segurado.

A ausência de nexo causal impede a caracterização do acidente como sendo de responsabilidade da empresa, não podendo, portanto, impactar negativamente no cálculo do FAP.

"""
    
    # Pedidos
    petition_content += f"""
IV – DOS PEDIDOS

Diante do exposto, requer-se a Vossa Excelência:

a) A procedência do pedido para {get_main_request(case_info.get('case_type'))};

b) A determinação ao INSS para exclusão dos benefícios relacionados da base de cálculo do FAP da empresa requerente;

c) O recálculo do FAP para os períodos afetados, com a devida restituição dos valores pagos a maior;

d) A condenação do INSS ao pagamento das custas processuais e honorários advocatícios.

Termos em que, 
Pede deferimento.

{company.get('address', {}).get('city', 'Cidade')}, {context.get('request_metadata', {}).get('generated_at', 'data')}.

"""
    
    # Assinatura dos advogados
    if lawyers:
        for lawyer in lawyers:
            petition_content += f"""
{lawyer.get('name')}
OAB/{lawyer.get('oab_number', 'XX XXXXX')}
"""
    
    return petition_content


def generate_simple_petition(case, benefits, documents):
    """
    Gera petição simples (fallback quando contexto estruturado não está disponível)
    
    Args:
        case (Case): Objeto do caso
        benefits (list): Lista de benefícios do caso
        documents (list): Lista de documentos do caso
    
    Returns:
        str: Conteúdo da petição básica
    """
    petition_content = f"""EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) DE DIREITO DA {case.court.vara_name if case.court else 'VARA COMPETENTE'}

{case.client.name if case.client else 'EMPRESA AUTORA'}, pessoa jurídica de direito privado, inscrita no CNPJ sob nº {case.client.cnpj if case.client else 'XX.XXX.XXX/XXXX-XX'}, com sede em {case.client.city if case.client else 'CIDADE'}/{case.client.state if case.client else 'UF'}, vem, por meio de seu advogado signatário, propor a presente

AÇÃO DECLARATÓRIA DE INEXISTÊNCIA DE NEXO CAUSAL

em face do INSTITUTO NACIONAL DO SEGURO SOCIAL – INSS.

I – DOS FATOS

{case.facts_summary if case.facts_summary else 'A empresa autora foi surpreendida com a vinculação indevida de benefícios acidentários.'}
"""
    
    if benefits:
        petition_content += "\n\nII – DOS BENEFÍCIOS\n\n"
        for i, benefit in enumerate(benefits, 1):
            petition_content += f"{i}. Benefício nº {benefit.benefit_number} - {benefit.benefit_type}\n"
            petition_content += f"   Segurado: {benefit.insured_name}\n"
    
    petition_content += f"""

III – DO DIREITO

{case.thesis_summary if case.thesis_summary else 'A inclusão indevida de benefícios no cálculo do FAP viola os princípios da legalidade e capacidade contributiva.'}

IV – DOS PEDIDOS

Diante do exposto, requer-se:

a) A procedência do pedido para {get_main_request(case.case_type)};
b) A condenação do INSS ao pagamento das custas e honorários advocatícios.

Termos em que,
Pede deferimento.

{case.client.city if case.client else 'Cidade'}/{case.client.state if case.client else 'UF'}, {datetime.now().strftime('%d de %B de %Y')}.

___________________________________
Advogado(a) OAB/XX XXXXX
"""
    
    return petition_content


def get_petition_title(case_type):
    """
    Retorna o título da petição baseado no tipo de caso
    
    Args:
        case_type (str): Tipo do caso
    
    Returns:
        str: Título da petição
    """
    titles = {
        'fap_trajeto': 'AÇÃO DECLARATÓRIA DE EXCLUSÃO DE ACIDENTE DE TRAJETO DO FAP',
        'fap_nexo': 'AÇÃO DECLARATÓRIA DE INEXISTÊNCIA DE NEXO CAUSAL',
        'fap_multiplos': 'AÇÃO DECLARATÓRIA DE REVISÃO DO FATOR ACIDENTÁRIO DE PREVENÇÃO',
        'auto_infracao': 'AÇÃO ANULATÓRIA DE AUTO DE INFRAÇÃO'
    }
    return titles.get(case_type, 'AÇÃO DECLARATÓRIA')


def get_main_request(case_type):
    """
    Retorna o pedido principal baseado no tipo de caso
    
    Args:
        case_type (str): Tipo do caso
    
    Returns:
        str: Pedido principal da petição
    """
    requests = {
        'fap_trajeto': 'declarar que os benefícios decorrentes de acidentes de trajeto devem ser excluídos do cálculo do FAP',
        'fap_nexo': 'declarar a inexistência de nexo causal entre os benefícios contestados e as atividades da empresa',
        'fap_multiplos': 'revisar o cálculo do FAP com exclusão dos benefícios indevidamente incluídos',
        'auto_infracao': 'anular o auto de infração lavrado indevidamente'
    }
    return requests.get(case_type, 'declarar a improcedência da vinculação dos benefícios à empresa')