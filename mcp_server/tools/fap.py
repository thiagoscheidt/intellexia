"""
Tools: Painel FAP — Empresas, Contestações, Benefícios, Resumo e Sincronização
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta


def _parse_topics(benefit) -> list[str]:
    """Tópicos de contestação do benefício: array atual com fallback no campo legado."""
    if benefit.fap_contestation_topics_json:
        try:
            topics = json.loads(benefit.fap_contestation_topics_json)
            if isinstance(topics, list):
                return [str(t) for t in topics]
        except (ValueError, TypeError):
            pass
    return [benefit.fap_contestation_topic] if benefit.fap_contestation_topic else []


def _iso(value):
    return value.isoformat() if value else None


def _company_name_map(law_firm_id: int) -> dict[str, str]:
    """Mapa cnpj_raiz (8 dígitos) → nome da empresa FAP do escritório."""
    from app.models import FapCompany

    rows = (
        FapCompany.query.filter_by(law_firm_id=law_firm_id)
        .with_entities(FapCompany.cnpj, FapCompany.nome)
        .all()
    )
    return {cnpj: nome for cnpj, nome in rows if cnpj}


def _empresa_por_cnpj(cnpj: str | None, names: dict[str, str]) -> str | None:
    """Resolve o nome da empresa a partir de um CNPJ completo ou raiz (aceita formatado)."""
    if not cnpj:
        return None
    digits = "".join(ch for ch in cnpj if ch.isdigit())
    return names.get(digits) or names.get(digits[:8])


# ── Empresas ──────────────────────────────────────────────────────────────────


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
            "sincronizada_em": _iso(c.synced_at),
        }
        for c in companies
    ]


# ── Contestações ──────────────────────────────────────────────────────────────


def list_fap_contestacoes_handler(
    law_firm_id: int,
    cnpj: str | None = None,
    cnpj_raiz: str | None = None,
    ano_vigencia: int | None = None,
    situacao_codigo: str | None = None,
    instancia_codigo: str | None = None,
    limit: int = 100,
) -> dict:
    """Retorna contestações FAP filtradas, com total encontrado."""
    from app.models import FapWebContestacao

    query = FapWebContestacao.query.filter_by(law_firm_id=law_firm_id)

    if cnpj:
        query = query.filter(FapWebContestacao.cnpj == cnpj)
    if cnpj_raiz:
        query = query.filter(FapWebContestacao.cnpj_raiz == cnpj_raiz)
    if ano_vigencia:
        query = query.filter(FapWebContestacao.ano_vigencia == ano_vigencia)
    if situacao_codigo:
        query = query.filter(FapWebContestacao.situacao_codigo == situacao_codigo)
    if instancia_codigo:
        query = query.filter(FapWebContestacao.instancia_codigo == instancia_codigo)

    total = query.count()
    contestacoes = (
        query.order_by(FapWebContestacao.data_transmissao.desc())
        .limit(limit)
        .all()
    )

    names = _company_name_map(law_firm_id)
    itens = [
        {
            "id": c.id,
            "contestacao_id": c.contestacao_id,
            "empresa_nome": (c.fap_company.nome if c.fap_company else None)
            or _empresa_por_cnpj(c.cnpj_raiz, names),
            "cnpj": c.cnpj,
            "cnpj_raiz": c.cnpj_raiz,
            "ano_vigencia": c.ano_vigencia,
            "instancia_codigo": c.instancia_codigo,
            "instancia_descricao": c.instancia_descricao,
            "situacao_codigo": c.situacao_codigo,
            "situacao_descricao": c.situacao_descricao,
            "protocolo": c.protocolo,
            "data_transmissao": _iso(c.data_transmissao),
            "data_dou": _iso(c.data_dou_date),
            "pdf_baixado": bool(c.file_path),
            "ultima_sincronizacao": _iso(c.last_synced_at),
        }
        for c in contestacoes
    ]
    return {"total_encontrado": total, "retornados": len(itens), "itens": itens}


# ── Benefícios ────────────────────────────────────────────────────────────────


def list_fap_benefits_handler(
    law_firm_id: int,
    cnpj: str | None = None,
    status: str | None = None,
    request_type: str | None = None,
    benefit_type: str | None = None,
    fap_contestation_topic: str | None = None,
    segurado: str | None = None,
    nit: str | None = None,
    cpf: str | None = None,
    numero_beneficio: str | None = None,
    ano_vigencia: str | None = None,
    limit: int = 50,
) -> dict:
    """Retorna benefícios FAP filtrados, com total encontrado."""
    from app.models import Benefit, db

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
        # Campo atual (array JSON) com fallback no legado (string única)
        query = query.filter(db.or_(
            Benefit.fap_contestation_topics_json.like(f'%"{fap_contestation_topic}"%'),
            Benefit.fap_contestation_topic == fap_contestation_topic,
        ))
    if segurado:
        query = query.filter(Benefit.insured_name.ilike(f"%{segurado}%"))
    if nit:
        query = query.filter(Benefit.insured_nit == nit)
    if cpf:
        query = query.filter(Benefit.insured_cpf == cpf)
    if numero_beneficio:
        query = query.filter(Benefit.benefit_number == numero_beneficio)
    if ano_vigencia:
        query = query.filter(Benefit.fap_vigencia_years.like(f"%{ano_vigencia}%"))

    total = query.count()
    benefits = query.order_by(Benefit.created_at.desc()).limit(limit).all()

    names = _company_name_map(law_firm_id)
    itens = [
        {
            "id": b.id,
            "numero_beneficio": b.benefit_number,
            "tipo_beneficio": b.benefit_type,
            "tipo_pedido": b.request_type,
            "status": b.status,
            "segurado_nome": b.insured_name,
            "segurado_nit": b.insured_nit,
            "segurado_cpf": b.insured_cpf,
            "empregador_cnpj": b.employer_cnpj,
            "empregador_nome": b.employer_name or _empresa_por_cnpj(b.employer_cnpj, names),
            "data_inicio_beneficio": _iso(b.benefit_start_date),
            "data_fim_beneficio": _iso(b.benefit_end_date),
            "data_acidente": _iso(b.accident_date),
            "empresa_acidente": b.accident_company_name,
            "numero_cat": b.cat_number,
            "vigencias_fap": b.fap_vigencia_years,
            "topicos_contestacao": _parse_topics(b),
            "status_primeira_instancia": b.first_instance_status,
            "status_segunda_instancia": b.second_instance_status,
            "mensalidade_inicial": float(b.initial_monthly_benefit) if b.initial_monthly_benefit is not None else None,
            "total_pago": float(b.total_paid) if b.total_paid is not None else None,
        }
        for b in benefits
    ]
    return {"total_encontrado": total, "retornados": len(itens), "itens": itens}


def get_benefit_detail_handler(benefit_id: int, law_firm_id: int) -> dict:
    """Retorna detalhes completos de um benefício, validando o tenant."""
    from app.models import Benefit

    benefit = Benefit.query.filter_by(id=benefit_id, law_firm_id=law_firm_id).first()

    if not benefit:
        return {"erro": f"Benefício {benefit_id} não encontrado para este escritório."}

    return {
        "id": benefit.id,
        "numero_beneficio": benefit.benefit_number,
        "tipo_beneficio": benefit.benefit_type,
        "tipo_pedido": benefit.request_type,
        "status": benefit.status,
        # Segurado
        "segurado_nome": benefit.insured_name,
        "segurado_nit": benefit.insured_nit,
        "segurado_cpf": benefit.insured_cpf,
        "segurado_data_nascimento": _iso(benefit.insured_date_of_birth),
        # Empregador
        "empregador_cnpj": benefit.employer_cnpj,
        "empregador_nome": benefit.employer_name,
        # Período
        "data_inicio_beneficio": _iso(benefit.benefit_start_date),
        "data_fim_beneficio": _iso(benefit.benefit_end_date),
        # Financeiro
        "mensalidade_inicial": float(benefit.initial_monthly_benefit) if benefit.initial_monthly_benefit is not None else None,
        "total_pago": float(benefit.total_paid) if benefit.total_paid is not None else None,
        # Acidente
        "data_acidente": _iso(benefit.accident_date),
        "empresa_acidente": benefit.accident_company_name,
        "resumo_acidente": benefit.accident_summary,
        "numero_cat": benefit.cat_number,
        "numero_bo": benefit.bo_number,
        # FAP
        "vigencias_fap": benefit.fap_vigencia_years,
        "topicos_contestacao": _parse_topics(benefit),
        # Instâncias
        "status_primeira_instancia": benefit.first_instance_status,
        "status_primeira_instancia_bruto": benefit.first_instance_status_raw,
        "justificativa_primeira_instancia": benefit.first_instance_justification,
        "parecer_primeira_instancia": benefit.first_instance_opinion,
        "status_segunda_instancia": benefit.second_instance_status,
        "status_segunda_instancia_bruto": benefit.second_instance_status_raw,
        "justificativa_segunda_instancia": benefit.second_instance_justification,
        "parecer_segunda_instancia": benefit.second_instance_opinion,
        # Geral
        "justificativa": benefit.justification,
        "parecer": benefit.opinion,
        "notas": benefit.notes,
        "criado_em": _iso(benefit.created_at),
        "atualizado_em": _iso(benefit.updated_at),
    }


# ── Resumo estatístico ────────────────────────────────────────────────────────


def fap_summary_handler(
    law_firm_id: int,
    ano_vigencia: int | None = None,
    cnpj: str | None = None,
) -> dict:
    """Resumo estatístico do FAP: contestações e benefícios agregados."""
    from app.models import Benefit, FapWebContestacao, db

    # Contestações
    cont_q = FapWebContestacao.query.filter_by(law_firm_id=law_firm_id)
    if ano_vigencia:
        cont_q = cont_q.filter(FapWebContestacao.ano_vigencia == ano_vigencia)
    if cnpj:
        cont_q = cont_q.filter(FapWebContestacao.cnpj == cnpj)

    def _count_by(query, column):
        rows = (
            query.with_entities(column, db.func.count())
            .group_by(column)
            .all()
        )
        return {str(k) if k is not None else "(vazio)": v for k, v in rows}

    names = _company_name_map(law_firm_id)
    por_raiz = _count_by(cont_q, FapWebContestacao.cnpj_raiz)
    por_empresa = {}
    for raiz, qtd in sorted(por_raiz.items(), key=lambda kv: -kv[1]):
        label = _empresa_por_cnpj(raiz, names) or f"CNPJ raiz {raiz}"
        por_empresa[label] = por_empresa.get(label, 0) + qtd

    contestacoes = {
        "total": cont_q.count(),
        "por_ano_vigencia": _count_by(cont_q, FapWebContestacao.ano_vigencia),
        "por_situacao": _count_by(cont_q, FapWebContestacao.situacao_descricao),
        "por_instancia": _count_by(cont_q, FapWebContestacao.instancia_descricao),
        "por_empresa": por_empresa,
    }

    # Benefícios
    ben_q = Benefit.query.filter_by(law_firm_id=law_firm_id)
    if cnpj:
        ben_q = ben_q.filter(Benefit.employer_cnpj == cnpj)
    if ano_vigencia:
        ben_q = ben_q.filter(Benefit.fap_vigencia_years.like(f"%{ano_vigencia}%"))

    por_topico: dict[str, int] = {}
    for b in ben_q.with_entities(Benefit.fap_contestation_topics_json, Benefit.fap_contestation_topic).all():
        topics = []
        if b[0]:
            try:
                parsed = json.loads(b[0])
                topics = parsed if isinstance(parsed, list) else []
            except (ValueError, TypeError):
                topics = []
        if not topics and b[1]:
            topics = [b[1]]
        for t in topics:
            por_topico[str(t)] = por_topico.get(str(t), 0) + 1

    beneficios = {
        "total": ben_q.count(),
        "por_tipo": _count_by(ben_q, Benefit.benefit_type),
        "por_tipo_pedido": _count_by(ben_q, Benefit.request_type),
        "por_status_primeira_instancia": _count_by(ben_q, Benefit.first_instance_status),
        "por_status_segunda_instancia": _count_by(ben_q, Benefit.second_instance_status),
        "por_topico_contestacao": dict(sorted(por_topico.items(), key=lambda kv: -kv[1])),
    }

    return {
        "filtros": {"ano_vigencia": ano_vigencia, "cnpj": cnpj},
        "contestacoes": contestacoes,
        "beneficios": beneficios,
    }


# ── Sincronização: alterações recentes ────────────────────────────────────────


def fap_changes_handler(
    law_firm_id: int,
    cnpj: str | None = None,
    ano_vigencia: int | None = None,
    dias: int = 7,
    limit: int = 100,
) -> dict:
    """Alterações detectadas nas últimas sincronizações com o portal FAP Web."""
    from app.models import FapWebContestacaoChangeHistory

    query = FapWebContestacaoChangeHistory.query.filter_by(law_firm_id=law_firm_id)
    if cnpj:
        query = query.filter(FapWebContestacaoChangeHistory.cnpj == cnpj)
    if ano_vigencia:
        query = query.filter(FapWebContestacaoChangeHistory.ano_vigencia == ano_vigencia)
    if dias:
        since = datetime.now() - timedelta(days=dias)
        query = query.filter(FapWebContestacaoChangeHistory.synced_at >= since)

    total = query.count()
    changes = query.order_by(FapWebContestacaoChangeHistory.synced_at.desc()).limit(limit).all()

    def _json_or_raw(value):
        if not value:
            return None
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value

    names = _company_name_map(law_firm_id)
    itens = [
        {
            "contestacao_id": ch.contestacao_id,
            "empresa_nome": _empresa_por_cnpj(ch.cnpj_raiz or ch.cnpj, names),
            "cnpj": ch.cnpj,
            "ano_vigencia": ch.ano_vigencia,
            "tipo_mudanca": ch.change_type,
            "campos_alterados": _json_or_raw(ch.changed_fields),
            "valores_anteriores": _json_or_raw(ch.old_values),
            "valores_novos": _json_or_raw(ch.new_values),
            "sincronizado_em": _iso(ch.synced_at),
        }
        for ch in changes
    ]
    return {"total_encontrado": total, "retornados": len(itens), "periodo_dias": dias, "itens": itens}


# ── Procurações ───────────────────────────────────────────────────────────────


def list_fap_procuracoes_handler(
    law_firm_id: int,
    cnpj_raiz: str | None = None,
    situacao_codigo: str | None = None,
    limit: int = 100,
) -> dict:
    """Procurações eletrônicas sincronizadas do portal FAP Web."""
    from app.models import FapWebProcuracao

    query = FapWebProcuracao.query.filter_by(law_firm_id=law_firm_id)
    if cnpj_raiz:
        query = query.filter(FapWebProcuracao.cnpj_raiz_outorgante == cnpj_raiz)
    if situacao_codigo:
        query = query.filter(FapWebProcuracao.situacao_codigo == situacao_codigo)

    total = query.count()
    procuracoes = query.order_by(FapWebProcuracao.data_fim.desc()).limit(limit).all()

    itens = [
        {
            "protocolo": p.protocolo,
            "tipo": p.tipo_procuracao_descricao,
            "situacao": p.situacao_descricao,
            "situacao_codigo": p.situacao_codigo,
            "data_inicio": _iso(p.data_inicio),
            "data_fim": _iso(p.data_fim),
            "cnpj_raiz_outorgante": p.cnpj_raiz_outorgante,
            "empresa_outorgante": p.nome_empresa_outorgante,
            "ultima_sincronizacao": _iso(p.last_synced_at),
        }
        for p in procuracoes
    ]
    return {"total_encontrado": total, "retornados": len(itens), "itens": itens}
