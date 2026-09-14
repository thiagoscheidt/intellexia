"""
Tools: Painel FAP — Empresas, Contestações, Benefícios, Resumo e Sincronização
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from mcp_server.tools.pagination import clamp_limit, clamp_offset, fetch_page, page_envelope


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


def _cnpj_digits_col(col):
    """Expressão SQL: coluna de CNPJ sem pontuação (benefícios guardam formatado)."""
    from app.models import db

    return db.func.replace(db.func.replace(db.func.replace(col, ".", ""), "/", ""), "-", "")


def _filter_benefit_cnpj(query, cnpj: str):
    """Filtra Benefit.employer_cnpj aceitando CNPJ formatado, só dígitos ou raiz (8)."""
    from app.models import Benefit

    digits = "".join(ch for ch in cnpj if ch.isdigit())
    expr = _cnpj_digits_col(Benefit.employer_cnpj)
    if len(digits) <= 8:
        return query.filter(expr.like(f"{digits}%"))
    return query.filter(expr == digits)


def _filter_benefit_empresa(query, empresa: str, law_firm_id: int):
    """Filtra benefícios por nome de empresa: casa o nome do empregador e/ou
    as raízes de CNPJ das empresas FAP cujo nome contém os termos."""
    from app.models import Benefit, FapCompany, db

    tokens = [t for t in empresa.split() if t]
    name_cond = db.and_(*[Benefit.employer_name.ilike(f"%{t}%") for t in tokens]) if tokens else None

    raiz_query = FapCompany.query.filter_by(law_firm_id=law_firm_id)
    for t in tokens:
        raiz_query = raiz_query.filter(FapCompany.nome.ilike(f"%{t}%"))
    raizes = [c.cnpj for c in raiz_query.with_entities(FapCompany.cnpj).limit(20).all() if c.cnpj]

    conds = [c for c in [name_cond] if c is not None]
    if raizes:
        expr = _cnpj_digits_col(Benefit.employer_cnpj)
        conds.append(db.or_(*[expr.like(f"{r}%") for r in raizes]))
    if not conds:
        return query
    return query.filter(db.or_(*conds))


# ── Empresas ──────────────────────────────────────────────────────────────────


def list_fap_companies_handler(
    law_firm_id: int,
    nome: str | None = None,
    cnpj: str | None = None,
    tipo_procuracao: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Retorna empresas FAP do escritório, com filtros e total encontrado."""
    from app.models import FapCompany

    limit = clamp_limit(limit, 100)
    offset = clamp_offset(offset)

    query = FapCompany.query.filter_by(law_firm_id=law_firm_id)

    if nome:
        # Cada palavra do termo precisa aparecer no nome (ordem livre):
        # "banco bradesco" encontra "BRADESCO S.A. - BANCO"
        for token in nome.split():
            query = query.filter(FapCompany.nome.ilike(f"%{token}%"))
    if cnpj:
        digits = "".join(ch for ch in cnpj if ch.isdigit())
        query = query.filter(FapCompany.cnpj.like(f"{digits[:8]}%"))
    if tipo_procuracao:
        query = query.filter(FapCompany.tipo_procuracao_descricao.ilike(f"%{tipo_procuracao}%"))

    total = query.count()
    companies = fetch_page(
        query.order_by(FapCompany.nome, FapCompany.id), limit, offset
    )

    itens = [
        {
            "id": c.id,
            "cnpj": c.cnpj,
            "nome": c.nome,
            "tipo_procuracao_descricao": c.tipo_procuracao_descricao,
            "sincronizada_em": _iso(c.synced_at),
        }
        for c in companies
    ]
    return page_envelope(total, offset, itens)


# ── Contestações ──────────────────────────────────────────────────────────────


def _pdf_url(contestacao, app_public_url: str | None) -> str | None:
    """Link para visualizar o PDF da contestação (rota do Painel de Contestações)."""
    if not app_public_url:
        return None
    cnpj14 = (contestacao.cnpj or "").zfill(14)
    return (
        f"{app_public_url.rstrip('/')}/disputes-center/fap-auto-import/download-contestacao/"
        f"{contestacao.ano_vigencia}/{cnpj14}/{contestacao.contestacao_id}?inline=1"
    )


def list_fap_contestacoes_handler(
    law_firm_id: int,
    cnpj: str | None = None,
    cnpj_raiz: str | None = None,
    ano_vigencia: int | None = None,
    situacao_codigo: str | None = None,
    instancia_codigo: str | None = None,
    limit: int = 100,
    offset: int = 0,
    app_public_url: str | None = None,
) -> dict:
    """Retorna contestações FAP filtradas, com total encontrado."""
    from app.models import FapWebContestacao

    limit = clamp_limit(limit, 100)
    offset = clamp_offset(offset)

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
    contestacoes = fetch_page(
        # data_transmissao é nula/repetida em muitos registros: o id desempata.
        query.order_by(FapWebContestacao.data_transmissao.desc(), FapWebContestacao.id.desc()),
        limit, offset,
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
            "url_abrir_pdf": _pdf_url(c, app_public_url),
            "ultima_sincronizacao": _iso(c.last_synced_at),
        }
        for c in contestacoes
    ]
    return page_envelope(total, offset, itens)


def get_contestacao_detail_handler(contestacao_id: int, law_firm_id: int,
                                   app_public_url: str | None = None) -> dict:
    """Detalhe completo de uma contestação: dados, mudanças e benefícios da vigência."""
    from app.models import Benefit, FapVigenciaCnpj, FapWebContestacao, FapWebContestacaoChangeHistory, db

    c = FapWebContestacao.query.filter_by(id=contestacao_id, law_firm_id=law_firm_id).first()
    if not c:
        return {"erro": f"Contestação {contestacao_id} não encontrada para este escritório."}

    names = _company_name_map(law_firm_id)

    # Benefícios da mesma vigência/CNPJ (vínculo oficial + fallback textual)
    vigencia_ids = [
        v.id for v in FapVigenciaCnpj.query.filter_by(
            law_firm_id=law_firm_id, employer_cnpj=c.cnpj, vigencia_year=str(c.ano_vigencia)
        ).all()
    ]
    ben_q = Benefit.query.filter_by(law_firm_id=law_firm_id)
    if vigencia_ids:
        ben_q = ben_q.filter(Benefit.fap_vigencia_cnpj_id.in_(vigencia_ids))
    else:
        ben_q = ben_q.filter(
            db.func.replace(db.func.replace(db.func.replace(
                Benefit.employer_cnpj, ".", ""), "/", ""), "-", "") == c.cnpj,
            Benefit.fap_vigencia_years.like(f"%{c.ano_vigencia}%"),
        )
    beneficios = ben_q.order_by(Benefit.created_at.desc()).limit(50).all()

    por_status_1a: dict[str, int] = {}
    for b in beneficios:
        key = b.first_instance_status or "(sem status)"
        por_status_1a[key] = por_status_1a.get(key, 0) + 1

    alteracoes = (
        FapWebContestacaoChangeHistory.query.filter_by(contestacao_db_id=c.id)
        .order_by(FapWebContestacaoChangeHistory.synced_at.desc())
        .limit(10)
        .all()
    )

    return {
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
        "url_abrir_pdf": _pdf_url(c, app_public_url),
        "ultima_sincronizacao": _iso(c.last_synced_at),
        "beneficios_vinculados": {
            "total": ben_q.count(),
            "por_status_primeira_instancia": por_status_1a,
            "itens": [
                {
                    "id": b.id,
                    "numero_beneficio": b.benefit_number,
                    "tipo_beneficio": b.benefit_type,
                    "segurado_nome": b.insured_name,
                    "topicos_contestacao": _parse_topics(b),
                    "status_primeira_instancia": b.first_instance_status,
                    "status_segunda_instancia": b.second_instance_status,
                    "total_pago": float(b.total_paid) if b.total_paid is not None else None,
                }
                for b in beneficios
            ],
        },
        "alteracoes_recentes": [
            {
                "tipo_mudanca": a.change_type,
                "campos_alterados": a.changed_fields,
                "sincronizado_em": _iso(a.synced_at),
            }
            for a in alteracoes
        ],
    }


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
    empresa: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Retorna benefícios FAP filtrados, com total encontrado."""
    from app.models import Benefit, db

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)

    query = Benefit.query.filter_by(law_firm_id=law_firm_id)

    if cnpj:
        query = _filter_benefit_cnpj(query, cnpj)
    if empresa:
        query = _filter_benefit_empresa(query, empresa, law_firm_id)
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
    benefits = fetch_page(
        # Centenas de benefícios compartilham o mesmo created_at (carga em lote):
        # sem o id, o banco não garante ordem entre eles e a paginação pularia linhas.
        query.order_by(Benefit.created_at.desc(), Benefit.id.desc()),
        limit, offset,
    )

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
    return page_envelope(total, offset, itens)


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
        # Decisões de julgamento extraídas de relatórios (quando houver)
        "decisoes_julgamento": _benefit_decisions(benefit.id),
        "criado_em": _iso(benefit.created_at),
        "atualizado_em": _iso(benefit.updated_at),
    }


def _benefit_decisions(benefit_id: int) -> list[dict]:
    from app.models import BenefitContestationDecision

    decisions = (
        BenefitContestationDecision.query.filter_by(benefit_id=benefit_id)
        .order_by(BenefitContestationDecision.instancia, BenefitContestationDecision.sequence)
        .all()
    )
    return [
        {
            "instancia": d.instancia,
            "sequencia": d.sequence,
            "status": d.status,
            "justificativa": d.justification,
            "parecer": d.opinion,
        }
        for d in decisions
    ]


# ── Resumo estatístico ────────────────────────────────────────────────────────


def fap_summary_handler(
    law_firm_id: int,
    ano_vigencia: int | None = None,
    cnpj: str | None = None,
    empresa: str | None = None,
) -> dict:
    """Resumo estatístico do FAP: contestações e benefícios agregados."""
    from app.models import Benefit, FapCompany, FapWebContestacao, db

    empresa_raizes: list[str] = []
    if empresa:
        raiz_query = FapCompany.query.filter_by(law_firm_id=law_firm_id)
        for t in empresa.split():
            raiz_query = raiz_query.filter(FapCompany.nome.ilike(f"%{t}%"))
        empresa_raizes = [c.cnpj for c in raiz_query.with_entities(FapCompany.cnpj).limit(20).all() if c.cnpj]

    # Contestações
    cont_q = FapWebContestacao.query.filter_by(law_firm_id=law_firm_id)
    if ano_vigencia:
        cont_q = cont_q.filter(FapWebContestacao.ano_vigencia == ano_vigencia)
    if cnpj:
        digits = "".join(ch for ch in cnpj if ch.isdigit())
        if len(digits) <= 8:
            cont_q = cont_q.filter(FapWebContestacao.cnpj_raiz == digits)
        else:
            cont_q = cont_q.filter(FapWebContestacao.cnpj == digits)
    if empresa:
        cont_q = cont_q.filter(FapWebContestacao.cnpj_raiz.in_(empresa_raizes or ["__nenhuma__"]))

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
        ben_q = _filter_benefit_cnpj(ben_q, cnpj)
    if empresa:
        ben_q = _filter_benefit_empresa(ben_q, empresa, law_firm_id)
    if ano_vigencia:
        ben_q = ben_q.filter(Benefit.fap_vigencia_years.like(f"%{ano_vigencia}%"))

    por_topico: dict[str, int] = {}
    com_topico_contestacao = 0
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
        if topics:
            com_topico_contestacao += 1
        for t in topics:
            por_topico[str(t)] = por_topico.get(str(t), 0) + 1

    total_pago_soma = ben_q.with_entities(db.func.sum(Benefit.total_paid)).scalar()
    com_valor = ben_q.filter(Benefit.total_paid.isnot(None)).count()
    com_cat = ben_q.filter(Benefit.cat_number.isnot(None), Benefit.cat_number != "").count()
    total_beneficios = ben_q.count()

    beneficios = {
        "total": total_beneficios,
        "por_tipo": _count_by(ben_q, Benefit.benefit_type),
        "por_tipo_pedido": _count_by(ben_q, Benefit.request_type),
        "por_status_primeira_instancia": _count_by(ben_q, Benefit.first_instance_status),
        "por_status_segunda_instancia": _count_by(ben_q, Benefit.second_instance_status),
        "por_topico_contestacao": dict(sorted(por_topico.items(), key=lambda kv: -kv[1])),
        "com_topico_contestacao": com_topico_contestacao,
        "financeiro": {
            "total_pago_soma": float(total_pago_soma) if total_pago_soma is not None else 0.0,
            "beneficios_com_valor_informado": com_valor,
        },
        "com_cat": com_cat,
        "sem_cat": total_beneficios - com_cat,
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
    offset: int = 0,
) -> dict:
    """Alterações detectadas nas últimas sincronizações com o portal FAP Web."""
    from app.models import FapWebContestacaoChangeHistory

    limit = clamp_limit(limit, 100)
    offset = clamp_offset(offset)

    query = FapWebContestacaoChangeHistory.query.filter_by(law_firm_id=law_firm_id)
    if cnpj:
        query = query.filter(FapWebContestacaoChangeHistory.cnpj == cnpj)
    if ano_vigencia:
        query = query.filter(FapWebContestacaoChangeHistory.ano_vigencia == ano_vigencia)
    if dias:
        since = datetime.now() - timedelta(days=dias)
        query = query.filter(FapWebContestacaoChangeHistory.synced_at >= since)

    total = query.count()
    changes = fetch_page(
        # Uma sincronização grava dezenas de mudanças no mesmo synced_at.
        query.order_by(FapWebContestacaoChangeHistory.synced_at.desc(),
                       FapWebContestacaoChangeHistory.id.desc()),
        limit, offset,
    )

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
    return {**page_envelope(total, offset, itens), "periodo_dias": dias}


# ── Procurações ───────────────────────────────────────────────────────────────


def list_fap_procuracoes_handler(
    law_firm_id: int,
    cnpj_raiz: str | None = None,
    situacao_codigo: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Procurações eletrônicas sincronizadas do portal FAP Web."""
    from app.models import FapWebProcuracao

    limit = clamp_limit(limit, 100)
    offset = clamp_offset(offset)

    query = FapWebProcuracao.query.filter_by(law_firm_id=law_firm_id)
    if cnpj_raiz:
        query = query.filter(FapWebProcuracao.cnpj_raiz_outorgante == cnpj_raiz)
    if situacao_codigo:
        query = query.filter(FapWebProcuracao.situacao_codigo == situacao_codigo)

    total = query.count()
    procuracoes = fetch_page(
        query.order_by(FapWebProcuracao.data_fim.desc(), FapWebProcuracao.id.desc()),
        limit, offset,
    )

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
    return page_envelope(total, offset, itens)


# ── Valores válidos de filtro ─────────────────────────────────────────────────


def fap_filter_values_handler(law_firm_id: int) -> dict:
    """Valores em uso no escritório para os filtros das tools FAP."""
    from app.models import Benefit, FapReason, FapWebContestacao, FapWebProcuracao, db

    def _distinct_pairs(model, code_col, desc_col):
        rows = (
            model.query.filter_by(law_firm_id=law_firm_id)
            .with_entities(code_col, desc_col)
            .distinct()
            .all()
        )
        return {code: desc for code, desc in rows if code}

    def _distinct(model, col):
        rows = (
            model.query.filter_by(law_firm_id=law_firm_id)
            .with_entities(col)
            .distinct()
            .all()
        )
        return sorted(str(r[0]) for r in rows if r[0] is not None)

    topicos: set[str] = set()
    for row in (
        Benefit.query.filter_by(law_firm_id=law_firm_id)
        .with_entities(Benefit.fap_contestation_topics_json, Benefit.fap_contestation_topic)
        .all()
    ):
        if row[0]:
            try:
                parsed = json.loads(row[0])
                if isinstance(parsed, list):
                    topicos.update(str(t) for t in parsed)
            except (ValueError, TypeError):
                pass
        if row[1]:
            topicos.add(row[1])

    motivos = [
        r.display_name
        for r in FapReason.query.filter_by(law_firm_id=law_firm_id, is_active=True)
        .order_by(FapReason.display_name)
        .all()
    ]

    return {
        "contestacoes": {
            "situacoes": _distinct_pairs(FapWebContestacao, FapWebContestacao.situacao_codigo, FapWebContestacao.situacao_descricao),
            "instancias": _distinct_pairs(FapWebContestacao, FapWebContestacao.instancia_codigo, FapWebContestacao.instancia_descricao),
            "anos_vigencia": _distinct(FapWebContestacao, FapWebContestacao.ano_vigencia),
        },
        "beneficios": {
            "tipos_beneficio": _distinct(Benefit, Benefit.benefit_type),
            "tipos_pedido": _distinct(Benefit, Benefit.request_type),
            "status": _distinct(Benefit, Benefit.status),
            "status_primeira_instancia": _distinct(Benefit, Benefit.first_instance_status),
            "status_segunda_instancia": _distinct(Benefit, Benefit.second_instance_status),
            "topicos_contestacao": sorted(topicos),
        },
        "procuracoes": {
            "situacoes": _distinct_pairs(FapWebProcuracao, FapWebProcuracao.situacao_codigo, FapWebProcuracao.situacao_descricao),
        },
        "motivos_fap_catalogo": motivos,
    }
