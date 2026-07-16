"""
Tools: Painel de Processos Judiciais
"""
from __future__ import annotations

from mcp_server.tools.pagination import clamp_limit, clamp_offset, fetch_page, page_envelope


def _iso(value):
    return value.isoformat() if value else None


def _truncate(text, size=600):
    if not text:
        return None
    text = str(text)
    return text if len(text) <= size else text[:size] + "…"


def _current_phase(process):
    """Fase atual = entrada mais recente do histórico de fases."""
    history = process.phase_history  # já ordenado por occurred_at desc
    if history:
        entry = history[0]
        return {
            "fase": entry.phase.name if entry.phase else None,
            "desde": _iso(entry.occurred_at),
        }
    return None


def list_processes_handler(
    law_firm_id: int,
    status: str | None = None,
    numero_processo: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Lista processos judiciais do escritório, com fase atual."""
    from app.models import JudicialProcess

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)

    query = JudicialProcess.query.filter_by(law_firm_id=law_firm_id)
    if status:
        query = query.filter(JudicialProcess.status == status)
    if numero_processo:
        query = query.filter(JudicialProcess.process_number.like(f"%{numero_processo}%"))

    total = query.count()
    processes = fetch_page(
        query.order_by(JudicialProcess.created_at.desc(), JudicialProcess.id.desc()),
        limit, offset,
    )

    itens = [
        {
            "id": p.id,
            "numero_processo": p.process_number,
            "titulo": p.title,
            "status": p.status,
            "tribunal": p.tribunal_name,
            "juiz": p.judge_name,
            "autor": p.plaintiff_client.name if p.plaintiff_client else None,
            "reu": p.defendant.name if p.defendant else None,
            "valor_causa": float(p.case_value) if p.case_value is not None else None,
            "data_ajuizamento": _iso(p.filing_date),
            "fase_atual": _current_phase(p),
            "qtd_beneficios": len(p.benefits),
        }
        for p in processes
    ]
    return page_envelope(total, offset, itens)


def get_process_detail_handler(process_id: int, law_firm_id: int) -> dict:
    """Detalhes completos de um processo judicial, validando o tenant."""
    from app.models import JudicialProcess

    p = JudicialProcess.query.filter_by(id=process_id, law_firm_id=law_firm_id).first()
    if not p:
        return {"erro": f"Processo {process_id} não encontrado para este escritório."}

    fases = [
        {
            "fase": h.phase.name if h.phase else None,
            "ocorrida_em": _iso(h.occurred_at),
            "observacoes": _truncate(h.notes, 300),
        }
        for h in p.phase_history
    ]

    beneficios = [
        {
            "numero_beneficio": b.benefit_number,
            "segurado_nome": b.insured_name,
            "nit": b.nit_number,
            "tipo_beneficio": b.benefit_type,
            "tipo_pedido": b.request_type,
            "vigencia_fap": b.fap_vigencia_year,
            "teses": [t.name for t in b.legal_theses],
            "status_contestacao_uniao": b.contestation_status_label or b.contestation_status,
            "decisao_primeira_instancia": _truncate(b.first_instance_decision),
            "decisao_segunda_instancia": _truncate(b.second_instance_decision),
        }
        for b in p.benefits
    ]

    notas = [
        {"conteudo": _truncate(n.content, 400), "criada_em": _iso(n.created_at)}
        for n in p.notes[:5]
    ]

    return {
        "id": p.id,
        "numero_processo": p.process_number,
        "titulo": p.title,
        "descricao": _truncate(p.description),
        "status": p.status,
        "classe_processual": p.process_class,
        "assuntos": p.assuntos,
        "tribunal": p.tribunal_name,
        "secao": p.section,
        "unidade_origem": p.origin_unit,
        "juiz": p.judge_name,
        "autor": p.plaintiff_client.name if p.plaintiff_client else None,
        "reu": p.defendant.name if p.defendant else None,
        "valor_causa": float(p.case_value) if p.case_value is not None else None,
        "data_ajuizamento": _iso(p.filing_date),
        "segredo_justica": p.segredo_justica,
        "justica_gratuita": p.justica_gratuita,
        "liminar_tutela": p.liminar_tutela,
        "fase_atual": _current_phase(p),
        "historico_fases": fases,
        "beneficios": beneficios,
        "notas_recentes": notas,
        "ultima_atualizacao": _iso(p.last_update),
        "criado_em": _iso(p.created_at),
    }
