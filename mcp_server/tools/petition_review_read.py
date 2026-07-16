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


# ── Referências: o manual FAP e os casos que o revisor usa como régua ─────────

REFERENCE_TYPES = {
    "manual_fap": "Manual FAP (a régua das revisões)",
    "casos_referencia": "Casos de referência",
    "project_instructions": "Instruções do projeto",
}

# Acima disso, devolver o documento inteiro afogaria o contexto do agente —
# melhor obrigar a filtrar por seção/termo.
MAX_REFERENCE_CHARS = 40_000


def _split_sections(content: str) -> list[dict]:
    """Quebra o markdown por títulos, para permitir ler só uma seção."""
    import re

    sections: list[dict] = []
    current = {"titulo": "(início)", "nivel": 0, "conteudo": []}
    for line in (content or "").splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if current["conteudo"] or sections:
                sections.append(current)
            current = {"titulo": m.group(2).strip(), "nivel": len(m.group(1)), "conteudo": []}
        else:
            current["conteudo"].append(line)
    sections.append(current)
    return [
        {"titulo": s["titulo"], "nivel": s["nivel"], "conteudo": "\n".join(s["conteudo"]).strip()}
        for s in sections
        if s["titulo"] != "(início)" or "\n".join(s["conteudo"]).strip()
    ]


def read_reviewer_manual_handler(
    law_firm_id: int,
    tipo: str = "manual_fap",
    secao: str | None = None,
    termo: str | None = None,
) -> dict:
    """Lê a referência ativa do revisor (manual FAP por padrão).

    É o que permite ao agente explicar um achado citando a seção real do manual —
    os achados trazem 'referencia_manual' e sem isto não há como abrir.
    """
    from app.models import FapReviewReferenceVersion

    if tipo not in REFERENCE_TYPES:
        return {
            "erro": f"Tipo inválido: {tipo}.",
            "tipos_validos": REFERENCE_TYPES,
        }

    ref = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id, reference_type=tipo, is_active=True
    ).first()

    if not ref or not (ref.content or "").strip():
        return {
            "tipo": tipo,
            "tipo_descricao": REFERENCE_TYPES[tipo],
            "configurado": False,
            "aviso": (
                f"O escritório não tem '{REFERENCE_TYPES[tipo]}' cadastrado no módulo "
                "Revisor de Petições. As revisões rodam sem essa régua — avise um "
                "administrador (Revisor → Configurações → Referências)."
            ),
        }

    content = ref.content
    secoes = _split_sections(content)
    base = {
        "tipo": tipo,
        "tipo_descricao": REFERENCE_TYPES[tipo],
        "configurado": True,
        "versao": ref.version_number,
        "atualizado_em": _iso(ref.updated_at or ref.created_at),
        "total_secoes": len(secoes),
    }

    if secao or termo:
        alvo = (secao or termo or "").lower()
        achadas = [
            s for s in secoes
            if alvo in s["titulo"].lower() or (termo and alvo in s["conteudo"].lower())
        ]
        if not achadas:
            return {
                **base,
                "encontrado": False,
                "secoes_disponiveis": [s["titulo"] for s in secoes],
                "aviso": f"Nada encontrado para {secao or termo!r}. Veja as seções disponíveis.",
            }
        return {**base, "encontrado": True, "secoes": achadas}

    if len(content) > MAX_REFERENCE_CHARS:
        return {
            **base,
            "conteudo_completo": False,
            "aviso": (
                f"O documento tem {len(content)} caracteres — grande demais para devolver "
                "inteiro. Peça uma seção ('secao') ou busque por um termo ('termo')."
            ),
            "secoes_disponiveis": [s["titulo"] for s in secoes],
        }

    return {**base, "conteudo_completo": True, "conteudo": content}


def reference_versions_handler(law_firm_id: int, tipo: str | None = None) -> dict:
    """Histórico de versões das referências do revisor.

    O treinamento pode reescrever o manual e ativar uma versão nova; este é o
    caminho para auditar o que mudou, quando e por quem.
    """
    from app.models import FapReviewReferenceVersion, User

    query = FapReviewReferenceVersion.query.filter_by(law_firm_id=law_firm_id)
    if tipo:
        if tipo not in REFERENCE_TYPES:
            return {"erro": f"Tipo inválido: {tipo}.", "tipos_validos": REFERENCE_TYPES}
        query = query.filter_by(reference_type=tipo)

    rows = query.order_by(
        FapReviewReferenceVersion.reference_type,
        FapReviewReferenceVersion.version_number.desc(),
    ).all()

    if not rows:
        return {
            "total": 0,
            "versoes": [],
            "aviso": "O escritório não tem referências cadastradas no módulo Revisor.",
        }

    autores = {
        u.id: u.name
        for u in User.query.filter(
            User.id.in_([r.created_by_id for r in rows if r.created_by_id])
        ).all()
    } if any(r.created_by_id for r in rows) else {}

    return {
        "total": len(rows),
        "versoes": [
            {
                "tipo": r.reference_type,
                "tipo_descricao": REFERENCE_TYPES.get(r.reference_type, r.reference_type),
                "versao": r.version_number,
                "ativa": r.is_active,
                "tamanho_caracteres": len(r.content or ""),
                "criada_por": autores.get(r.created_by_id),
                "criada_em": _iso(r.created_at),
            }
            for r in rows
        ],
    }


# ── Auditoria ────────────────────────────────────────────────────────────────


def review_audit_log_handler(
    law_firm_id: int,
    peticao_id: int | None = None,
    acao: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Trilha de auditoria do módulo Revisor: quem fez o quê e quando."""
    from app.models import FapReviewAuditLog, User

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)

    query = FapReviewAuditLog.query.filter_by(law_firm_id=law_firm_id)
    if peticao_id:
        query = query.filter(
            FapReviewAuditLog.entity_type == 'petition',
            FapReviewAuditLog.entity_id == peticao_id,
        )
    if acao:
        query = query.filter(FapReviewAuditLog.action.ilike(f"%{acao}%"))

    total = query.count()
    rows = fetch_page(
        query.order_by(FapReviewAuditLog.created_at.desc(), FapReviewAuditLog.id.desc()),
        limit, offset,
    )

    autores = {
        u.id: u.name
        for u in User.query.filter(User.id.in_([r.user_id for r in rows if r.user_id])).all()
    } if rows else {}

    itens = [
        {
            "id": r.id,
            "acao": r.action,
            "entidade": r.entity_type,
            "entidade_id": r.entity_id,
            "descricao": r.change_description,
            "valor_anterior": r.old_value or None,
            "valor_novo": r.new_value or None,
            "usuario": autores.get(r.user_id),
            "quando": _iso(r.created_at),
        }
        for r in rows
    ]
    return page_envelope(total, offset, itens)


# ── Estatísticas por advogado (admin) ────────────────────────────────────────


def lawyer_statistics_handler(law_firm_id: int) -> dict:
    """Score, retrabalho e reincidência por advogado — os mesmos números da tela."""
    from app.services.fap_review_service import build_lawyer_statistics

    stats = build_lawyer_statistics(law_firm_id)
    overview = stats.get("overview") or {}
    lawyers = stats.get("lawyers") or []

    if not lawyers:
        return {
            "panorama": overview,
            "advogados": [],
            "aviso": "Ainda não há revisões concluídas para calcular estatísticas.",
        }

    return {
        "panorama": {
            "advogados": overview.get("total_lawyers"),
            "revisoes": overview.get("total_revisions"),
            "achados": overview.get("total_findings"),
            "achados_reincidentes": overview.get("repeated_findings"),
            "taxa_reincidencia": overview.get("recurrence_rate"),
        },
        "advogados": [
            {
                "usuario_id": l.get("user_id"),
                "nome": l.get("name"),
                "papel": l.get("role"),
                "score": l.get("score"),
                "revisoes": l.get("total_revisions"),
                "peticoes": l.get("petitions_count"),
                "achados": l.get("total_findings"),
                "achados_criticos": l.get("critical_findings"),
                "achados_moderados": l.get("moderate_findings"),
                "achados_formais": l.get("formal_findings"),
                "media_achados_por_revisao": l.get("avg_findings_per_revision"),
                "peticoes_com_retrabalho": l.get("rework_petitions"),
                "taxa_retrabalho": l.get("rework_ratio"),
                "achados_reincidentes": l.get("repeated_findings"),
                "taxa_reincidencia": l.get("recurrence_rate"),
                "categorias_mais_frequentes": l.get("top_categories"),
            }
            for l in lawyers
        ],
        "nota": (
            "Score é heurístico (100 menos penalidades por média de achados, retrabalho e "
            "reincidência) — serve para orientar melhoria, não para ranquear pessoas."
        ),
    }
