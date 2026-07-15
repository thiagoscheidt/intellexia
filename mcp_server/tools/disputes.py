"""
Tools: Painel de Contestações — CATs (Comunicações de Acidente de Trabalho)
"""
from __future__ import annotations


def _iso(value):
    return value.isoformat() if value else None


def list_cats_handler(
    law_firm_id: int,
    vigencia_year: str | None = None,
    cnpj: str | None = None,
    nit: str | None = None,
    cat_number: str | None = None,
    limit: int = 50,
) -> dict:
    """CATs vinculadas às contestações FAP, com filtros."""
    from app.models import FapContestationCat

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
    cats = query.order_by(FapContestationCat.accident_date.desc()).limit(limit).all()

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
    return {"total_encontrado": total, "retornados": len(itens), "itens": itens}
