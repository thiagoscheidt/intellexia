"""
Tools: Painel de Contestações — CATs (Comunicações de Acidente de Trabalho)
"""
from __future__ import annotations

from mcp_server.tools.pagination import clamp_limit, clamp_offset, fetch_page, page_envelope


def _iso(value):
    return value.isoformat() if value else None


def list_cats_handler(
    law_firm_id: int,
    vigencia_year: str | None = None,
    cnpj: str | None = None,
    nit: str | None = None,
    cat_number: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """CATs vinculadas às contestações FAP, com filtros."""
    from app.models import FapContestationCat

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)

    query = FapContestationCat.query.filter_by(law_firm_id=law_firm_id)
    if vigencia_year:
        query = query.filter(FapContestationCat.vigencia_year == str(vigencia_year))
    if cnpj:
        query = query.filter(FapContestationCat.employer_cnpj == cnpj)
    if nit:
        query = query.filter(FapContestationCat.insured_nit == nit)
    if cat_number:
        query = query.filter(FapContestationCat.cat_number == cat_number)

    total = query.count()
    cats = fetch_page(
        # accident_date repete (e é nula em parte dos registros): o id desempata.
        query.order_by(FapContestationCat.accident_date.desc(), FapContestationCat.id.desc()),
        limit, offset,
    )

    itens = [
        {
            "id": c.id,
            "numero_cat": c.cat_number,
            "vigencia": c.vigencia_year,
            "empregador_cnpj": c.employer_cnpj,
            "empregador_nome": c.employer_name,
            "segurado_nit": c.insured_nit,
            "data_acidente": _iso(c.accident_date),
            "data_registro_cat": _iso(c.cat_registration_date),
            "data_obito": _iso(c.insured_death_date),
            "status": c.status,
            "status_primeira_instancia": c.first_instance_status,
            "justificativa_primeira_instancia": c.first_instance_justification,
            "status_segunda_instancia": c.second_instance_status,
            "justificativa": c.justification,
            "parecer": c.opinion,
        }
        for c in cats
    ]
    return page_envelope(total, offset, itens)


def _instance_fields(row) -> dict:
    """Campos comuns de status/justificativa por instância das abas de contestação."""
    return {
        "status": row.status,
        "status_primeira_instancia": row.first_instance_status,
        "justificativa_primeira_instancia": row.first_instance_justification,
        "parecer_primeira_instancia": row.first_instance_opinion,
        "status_segunda_instancia": row.second_instance_status,
        "justificativa_segunda_instancia": row.second_instance_justification,
        "parecer_segunda_instancia": row.second_instance_opinion,
    }


def list_payroll_masses_handler(
    law_firm_id: int,
    vigencia_year: str | None = None,
    cnpj: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Massas salariais (folha de pagamento) contestadas, por competência."""
    from app.models import FapContestationPayrollMass as M

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)

    query = M.query.filter_by(law_firm_id=law_firm_id)
    if vigencia_year:
        query = query.filter(M.vigencia_year == str(vigencia_year))
    if cnpj:
        query = query.filter(M.employer_cnpj == cnpj)

    total = query.count()
    rows = fetch_page(
        query.order_by(M.vigencia_year.desc(), M.competence, M.id),
        limit, offset,
    )
    itens = [
        {
            "id": r.id,
            "vigencia": r.vigencia_year,
            "empregador_cnpj": r.employer_cnpj,
            "empregador_nome": r.employer_name,
            "competencia": r.competence,
            "remuneracao_total": float(r.total_remuneration) if r.total_remuneration is not None else None,
            "valor_pleiteado_primeira_instancia": float(r.first_instance_requested_value) if r.first_instance_requested_value is not None else None,
            "valor_pleiteado_segunda_instancia": float(r.second_instance_requested_value) if r.second_instance_requested_value is not None else None,
            **_instance_fields(r),
        }
        for r in rows
    ]
    return page_envelope(total, offset, itens)


def list_employment_links_handler(
    law_firm_id: int,
    vigencia_year: str | None = None,
    cnpj: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Vínculos empregatícios contestados, por competência."""
    from app.models import FapContestationEmploymentLink as M

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)

    query = M.query.filter_by(law_firm_id=law_firm_id)
    if vigencia_year:
        query = query.filter(M.vigencia_year == str(vigencia_year))
    if cnpj:
        query = query.filter(M.employer_cnpj == cnpj)

    total = query.count()
    rows = fetch_page(
        query.order_by(M.vigencia_year.desc(), M.competence, M.id),
        limit, offset,
    )
    itens = [
        {
            "id": r.id,
            "vigencia": r.vigencia_year,
            "empregador_cnpj": r.employer_cnpj,
            "empregador_nome": r.employer_name,
            "competencia": r.competence,
            "quantidade": r.quantity,
            "quantidade_pleiteada_primeira_instancia": r.first_instance_requested_quantity,
            "quantidade_pleiteada_segunda_instancia": r.second_instance_requested_quantity,
            **_instance_fields(r),
        }
        for r in rows
    ]
    return page_envelope(total, offset, itens)


def list_turnover_rates_handler(
    law_firm_id: int,
    vigencia_year: str | None = None,
    cnpj: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Taxas de rotatividade contestadas, por ano."""
    from app.models import FapContestationTurnoverRate as M

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)

    query = M.query.filter_by(law_firm_id=law_firm_id)
    if vigencia_year:
        query = query.filter(M.vigencia_year == str(vigencia_year))
    if cnpj:
        query = query.filter(M.employer_cnpj == cnpj)

    total = query.count()
    rows = fetch_page(
        query.order_by(M.vigencia_year.desc(), M.year, M.id),
        limit, offset,
    )
    itens = [
        {
            "id": r.id,
            "vigencia": r.vigencia_year,
            "empregador_cnpj": r.employer_cnpj,
            "empregador_nome": r.employer_name,
            "ano": r.year,
            "taxa_rotatividade": float(r.turnover_rate) if r.turnover_rate is not None else None,
            "admissoes": r.admissions,
            "rescisoes": r.dismissals,
            "vinculos_iniciais": r.initial_links_count,
            **_instance_fields(r),
        }
        for r in rows
    ]
    return page_envelope(total, offset, itens)
