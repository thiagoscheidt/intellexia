"""
Tools: Painel FAP — Empresas, Contestações e Benefícios
"""
from __future__ import annotations


def list_fap_companies_handler(law_firm_id: int) -> list[dict]:
    """Retorna empresas FAP do escritório."""
    from app.models import FapCompany

    companies = (
        FapCompany.query.filter_by(law_firm_id=law_firm_id)
        .order_by(FapCompany.nome)
        .all()
    )
    return [
        {
            "id": c.id,
            "cnpj": c.cnpj,
            "nome": c.nome,
            "tipo_procuracao_descricao": c.tipo_procuracao_descricao,
            "synced_at": c.synced_at.isoformat() if c.synced_at else None,
        }
        for c in companies
    ]


def list_fap_contestacoes_handler(
    law_firm_id: int,
    cnpj: str | None = None,
    ano_vigencia: int | None = None,
    situacao_codigo: str | None = None,
    instancia_codigo: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Retorna contestações FAP filtradas."""
    from app.models import FapWebContestacao

    query = FapWebContestacao.query.filter_by(law_firm_id=law_firm_id)

    if cnpj:
        query = query.filter(FapWebContestacao.cnpj == cnpj)
    if ano_vigencia:
        query = query.filter(FapWebContestacao.ano_vigencia == ano_vigencia)
    if situacao_codigo:
        query = query.filter(FapWebContestacao.situacao_codigo == situacao_codigo)
    if instancia_codigo:
        query = query.filter(FapWebContestacao.instancia_codigo == instancia_codigo)

    contestacoes = (
        query.order_by(FapWebContestacao.data_transmissao.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": c.id,
            "contestacao_id": c.contestacao_id,
            "cnpj": c.cnpj,
            "cnpj_raiz": c.cnpj_raiz,
            "ano_vigencia": c.ano_vigencia,
            "instancia_codigo": c.instancia_codigo,
            "instancia_descricao": c.instancia_descricao,
            "situacao_codigo": c.situacao_codigo,
            "situacao_descricao": c.situacao_descricao,
            "protocolo": c.protocolo,
            "data_transmissao": c.data_transmissao.isoformat() if c.data_transmissao else None,
            "last_synced_at": c.last_synced_at.isoformat() if c.last_synced_at else None,
        }
        for c in contestacoes
    ]


def list_fap_benefits_handler(
    law_firm_id: int,
    cnpj: str | None = None,
    status: str | None = None,
    request_type: str | None = None,
    benefit_type: str | None = None,
    fap_contestation_topic: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Retorna benefícios FAP filtrados."""
    from app.models import Benefit

    query = Benefit.query.filter_by(law_firm_id=law_firm_id)

    if cnpj:
        query = query.filter(Benefit.employer_cnpj == cnpj)
    if status:
        query = query.filter(Benefit.status == status)
    if request_type:
        query = query.filter(Benefit.request_type == request_type)
    if benefit_type:
        query = query.filter(Benefit.benefit_type == benefit_type)
    if fap_contestation_topic:
        query = query.filter(Benefit.fap_contestation_topic == fap_contestation_topic)

    benefits = (
        query.order_by(Benefit.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": b.id,
            "benefit_number": b.benefit_number,
            "benefit_type": b.benefit_type,
            "request_type": b.request_type,
            "status": b.status,
            "insured_name": b.insured_name,
            "insured_nit": b.insured_nit,
            "insured_cpf": b.insured_cpf,
            "employer_cnpj": b.employer_cnpj,
            "employer_name": b.employer_name,
            "benefit_start_date": b.benefit_start_date.isoformat() if b.benefit_start_date else None,
            "benefit_end_date": b.benefit_end_date.isoformat() if b.benefit_end_date else None,
            "accident_date": b.accident_date.isoformat() if b.accident_date else None,
            "fap_vigencia_years": b.fap_vigencia_years,
            "fap_contestation_topic": b.fap_contestation_topic,
            "first_instance_status": b.first_instance_status,
            "second_instance_status": b.second_instance_status,
            "total_paid": float(b.total_paid) if b.total_paid is not None else None,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in benefits
    ]


def get_benefit_detail_handler(benefit_id: int, law_firm_id: int) -> dict:
    """Retorna detalhes completos de um benefício, validando o tenant."""
    from app.models import Benefit

    benefit = Benefit.query.filter_by(id=benefit_id, law_firm_id=law_firm_id).first()

    if not benefit:
        return {"error": f"Benefício {benefit_id} não encontrado para este escritório."}

    return {
        "id": benefit.id,
        "benefit_number": benefit.benefit_number,
        "benefit_type": benefit.benefit_type,
        "request_type": benefit.request_type,
        "status": benefit.status,
        # Segurado
        "insured_name": benefit.insured_name,
        "insured_nit": benefit.insured_nit,
        "insured_cpf": benefit.insured_cpf,
        "insured_date_of_birth": benefit.insured_date_of_birth.isoformat() if benefit.insured_date_of_birth else None,
        # Empregador
        "employer_cnpj": benefit.employer_cnpj,
        "employer_name": benefit.employer_name,
        # Período
        "benefit_start_date": benefit.benefit_start_date.isoformat() if benefit.benefit_start_date else None,
        "benefit_end_date": benefit.benefit_end_date.isoformat() if benefit.benefit_end_date else None,
        # Financeiro
        "initial_monthly_benefit": float(benefit.initial_monthly_benefit) if benefit.initial_monthly_benefit is not None else None,
        "total_paid": float(benefit.total_paid) if benefit.total_paid is not None else None,
        # Acidente
        "accident_date": benefit.accident_date.isoformat() if benefit.accident_date else None,
        "accident_company_name": benefit.accident_company_name,
        "accident_summary": benefit.accident_summary,
        "cat_number": benefit.cat_number,
        "bo_number": benefit.bo_number,
        # FAP
        "fap_vigencia_years": benefit.fap_vigencia_years,
        "fap_contestation_topic": benefit.fap_contestation_topic,
        "fap_contestation_topics_json": benefit.fap_contestation_topics_json,
        # Instâncias
        "first_instance_status": benefit.first_instance_status,
        "first_instance_status_raw": benefit.first_instance_status_raw,
        "first_instance_justification": benefit.first_instance_justification,
        "first_instance_opinion": benefit.first_instance_opinion,
        "second_instance_status": benefit.second_instance_status,
        "second_instance_status_raw": benefit.second_instance_status_raw,
        "second_instance_justification": benefit.second_instance_justification,
        "second_instance_opinion": benefit.second_instance_opinion,
        # Geral
        "justification": benefit.justification,
        "opinion": benefit.opinion,
        "notes": benefit.notes,
        "created_at": benefit.created_at.isoformat() if benefit.created_at else None,
        "updated_at": benefit.updated_at.isoformat() if benefit.updated_at else None,
    }
