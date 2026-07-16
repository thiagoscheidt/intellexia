"""
Tools: Revisor de Petições FAP — leitura do módulo.

Deixam o Claude **ler** as revisões que já existem no sistema (feitas pela tela ou
por ele mesmo), em vez de só criar novas. É o que permite "o que a revisão da
petição X apontou? me ajuda a corrigir" sem gastar outra rodada de IA.

Os rótulos e a leitura do resultado vêm de ``app/services/fap_review_service.py`` —
a mesma fonte da tela.
"""
from __future__ import annotations

from mcp_server.tools.pagination import (
    clamp_limit,
    clamp_offset,
    fetch_page,
    page_envelope,
)


def _iso(value):
    return value.isoformat() if value else None


def _status_label(status: str) -> str:
    from app.services.fap_review_service import PETITION_WORKFLOW_STATUSES
    return PETITION_WORKFLOW_STATUSES.get(status, status or '')


def _finding_dict(f: dict) -> dict:
    """Achado no vocabulário das tools (o result_json usa chaves em inglês)."""
    return {
        "categoria": f.get("category"),
        "gravidade": f.get("severity"),
        "descricao": f.get("description"),
        "localizacao": f.get("location"),
        "correcao_sugerida": f.get("correction"),
        "referencia_manual": f.get("manual_reference"),
        "padrao_novo": f.get("is_new_pattern", False),
    }


def _severity_counts(findings: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for f in findings:
        key = (f.get("severity") or "SEM GRAVIDADE").upper()
        counts[key] = counts.get(key, 0) + 1
    return counts


def list_review_petitions_handler(
    law_firm_id: int,
    status: str | None = None,
    identificador: str | None = None,
    titulo: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Petições do Revisor com status do fluxo, nº de revisões e última revisão."""
    from app.models import FapReviewPetition

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)

    query = FapReviewPetition.query.filter_by(law_firm_id=law_firm_id)
    if status:
        query = query.filter(FapReviewPetition.workflow_status == status)
    if identificador:
        query = query.filter(
            FapReviewPetition.office_document_identifier.ilike(f"%{identificador}%")
        )
    if titulo:
        for token in titulo.split():
            query = query.filter(FapReviewPetition.title.ilike(f"%{token}%"))

    total = query.count()
    rows = fetch_page(
        query.order_by(FapReviewPetition.updated_at.desc(), FapReviewPetition.id.desc()),
        limit, offset,
    )

    itens = [
        {
            "peticao_id": p.id,
            "identificador": p.office_document_identifier,
            "titulo": p.title,
            "status": p.workflow_status,
            "status_descricao": _status_label(p.workflow_status),
            "revisoes": p.revision_count or 0,
            "ultima_revisao_em": _iso(p.last_reviewed_at),
            "ultima_revisao_id": p.latest_revision_id,
            "criada_em": _iso(p.created_at),
        }
        for p in rows
    ]
    return page_envelope(total, offset, itens)


def get_review_detail_handler(law_firm_id: int, revisao_id: int) -> dict:
    """Achados completos de uma revisão já feita, validando o escritório."""
    from app.models import FapReviewExecution
    from app.services.fap_review_service import load_execution_result_payload

    execution = FapReviewExecution.query.filter_by(
        id=revisao_id, law_firm_id=law_firm_id
    ).first()
    if not execution:
        return {"erro": f"Revisão {revisao_id} não encontrada para este escritório."}

    payload = load_execution_result_payload(execution)
    findings = payload.get("findings") or []
    petition = execution.petition

    if execution.status != "completed":
        return {
            "revisao_id": execution.id,
            "status": execution.status,
            "erro_execucao": execution.error_message,
            "aviso": "A revisão ainda não foi concluída — não há achados para mostrar.",
        }

    resumo = payload.get("executive_summary") or {}
    return {
        "revisao_id": execution.id,
        "peticao_id": execution.petition_id,
        "identificador": execution.law_firm_document_identifier,
        "titulo_peticao": petition.title if petition else None,
        "status_peticao": petition.workflow_status if petition else None,
        "status_peticao_descricao": _status_label(petition.workflow_status) if petition else None,
        "numero_revisao": execution.revision_number,
        "tipo_analise": payload.get("analysis_type"),
        "revisao_focada": payload.get("focused_review", False),
        "documento": execution.main_document_filename,
        "concluida_em": _iso(execution.completed_at),
        "total_achados": len(findings),
        "achados_por_gravidade": _severity_counts(findings),
        "achados": [_finding_dict(f) for f in findings],
        "documentos_faltantes": [
            {
                "tipo_documento": d.get("document_type"),
                "tese": d.get("thesis"),
                "referencia_manual": d.get("manual_reference"),
            }
            for d in (payload.get("missing_documents") or [])
        ],
        "teses": [
            {
                "tese": t.get("thesis"),
                "numero_beneficio": t.get("benefit_number"),
                "enquadramento": t.get("classification"),
            }
            for t in (payload.get("theses") or [])
        ],
        "mudancas_comparativas": payload.get("comparative_changes") or [],
        "resumo_executivo": resumo,
        "tokens_usados": execution.tokens_used,
        "custo_usd": float(execution.cost_usd) if execution.cost_usd is not None else None,
    }


def petition_review_history_handler(
    law_firm_id: int,
    peticao_id: int | None = None,
    identificador: str | None = None,
) -> dict:
    """Evolução das revisões de uma petição: o que saiu e o que reincidiu.

    Aceita o id da petição ou o identificador do escritório.
    """
    from app.models import FapReviewExecution, FapReviewPetition
    from app.services.fap_review_service import load_execution_result_payload

    query = FapReviewPetition.query.filter_by(law_firm_id=law_firm_id)
    if peticao_id:
        petition = query.filter_by(id=peticao_id).first()
    elif identificador:
        petition = query.filter_by(office_document_identifier=identificador.strip()).first()
    else:
        return {"erro": "Informe 'peticao_id' ou 'identificador' da petição."}

    if not petition:
        return {"erro": "Petição não encontrada para este escritório."}

    executions = (
        FapReviewExecution.query
        .filter_by(law_firm_id=law_firm_id, petition_id=petition.id, execution_type='revision')
        .order_by(FapReviewExecution.revision_number.asc(), FapReviewExecution.id.asc())
        .all()
    )

    revisoes = []
    anteriores: set[str] = set()
    for e in executions:
        payload = load_execution_result_payload(e)
        findings = payload.get("findings") or []
        # Descrição normalizada identifica o mesmo achado entre revisões.
        atuais = {
            " ".join(str(f.get("description") or "").lower().split())
            for f in findings if f.get("description")
        }
        revisoes.append({
            "revisao_id": e.id,
            "numero_revisao": e.revision_number,
            "status": e.status,
            "concluida_em": _iso(e.completed_at),
            "total_achados": len(findings),
            "achados_por_gravidade": _severity_counts(findings),
            "reincidentes": sorted(atuais & anteriores) if anteriores else [],
            "resolvidos_desde_a_anterior": sorted(anteriores - atuais) if anteriores else [],
            "novos": sorted(atuais - anteriores) if anteriores else sorted(atuais),
        })
        anteriores = atuais

    return {
        "peticao_id": petition.id,
        "identificador": petition.office_document_identifier,
        "titulo": petition.title,
        "status": petition.workflow_status,
        "status_descricao": _status_label(petition.workflow_status),
        "total_revisoes": len(revisoes),
        "revisoes": revisoes,
    }
