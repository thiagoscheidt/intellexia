"""
Tools: Monitoramento de Processos (comunicações processuais por fonte).

Fonte única de regras: app/services/communication_monitor_service.py — os
handlers só adaptam para o envelope do MCP. Teor sempre limpo de HTML
(strip_html_text), pois alguns tribunais publicam HTML completo.
"""
from __future__ import annotations

from mcp_server.tools.pagination import clamp_limit, clamp_offset, fetch_page, page_envelope

PREVIEW_CHARS = 300
TEOR_MAX_CHARS = 20000


def _iso(value):
    return value.isoformat() if value else None


def _clean_teor(texto):
    from app.utils.document_utils import strip_html_text
    return strip_html_text(texto)


def _fonte_label(source):
    from app.models import ProcessCommunication
    return ProcessCommunication.SOURCE_LABELS.get(source, source)


def _parse_iso_date(value, field):
    from datetime import date
    from fastmcp.exceptions import ToolError

    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ToolError(f"Data inválida em '{field}': use o formato YYYY-MM-DD.")


def list_communications_handler(
    law_firm_id: int,
    tribunal: str | None = None,
    tipo: str | None = None,
    fonte: str | None = None,
    advogado_id: int | None = None,
    numero_processo: str | None = None,
    somente_nao_lidas: bool = False,
    data_de: str | None = None,
    data_ate: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Lista comunicações do escritório com os mesmos filtros da tela."""
    from app.services import communication_monitor_service as monitor

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)

    query = monitor.communications_query(
        law_firm_id,
        sigla_tribunal=(tribunal or '').strip() or None,
        tipo_comunicacao=(tipo or '').strip() or None,
        source=(fonte or '').strip() or None,
        lawyer_id=advogado_id,
        numero_processo=(numero_processo or '').strip() or None,
        only_unread=bool(somente_nao_lidas),
        date_from=_parse_iso_date(data_de, 'data_de'),
        date_to=_parse_iso_date(data_ate, 'data_ate'),
    )

    total = query.count()
    comms = fetch_page(query, limit, offset)  # já ordenada por data desc, id desc

    itens = []
    for c in comms:
        teor = _clean_teor(c.texto)
        itens.append({
            "id": c.id,
            "data_disponibilizacao": _iso(c.data_disponibilizacao),
            "tribunal": c.sigla_tribunal,
            "tipo": c.tipo_comunicacao,
            "tipo_documento": c.tipo_documento,
            "fonte": _fonte_label(c.source),
            "numero_processo": c.numero_processo_mascara or c.numero_processo,
            "orgao": c.nome_orgao,
            "classe": c.nome_classe,
            "advogado": c.matched_lawyer.name if c.matched_lawyer else None,
            "lida": c.read_at is not None,
            "tem_explicacao_ia": bool(c.analysis_json),
            "previa_teor": (teor[:PREVIEW_CHARS] + "…") if len(teor) > PREVIEW_CHARS else (teor or None),
        })
    return page_envelope(total, offset, itens)


def get_communication_detail_handler(communication_id: int, law_firm_id: int) -> dict:
    """Detalhe completo de uma comunicação, validando o tenant."""
    from fastmcp.exceptions import ToolError

    from app.models import ProcessCommunication

    comm = ProcessCommunication.query.filter_by(
        id=communication_id, law_firm_id=law_firm_id
    ).first()
    if not comm:
        raise ToolError("Comunicação não encontrada para este escritório.")

    teor = _clean_teor(comm.texto)
    result = {
        "id": comm.id,
        "data_disponibilizacao": _iso(comm.data_disponibilizacao),
        "tribunal": comm.sigla_tribunal,
        "tipo": comm.tipo_comunicacao,
        "tipo_documento": comm.tipo_documento,
        "fonte": _fonte_label(comm.source),
        "meio": comm.meio,
        "numero_processo": comm.numero_processo_mascara or comm.numero_processo,
        "processo_painel_id": comm.judicial_process_id,
        "orgao": comm.nome_orgao,
        "classe": comm.nome_classe,
        "advogado_radar": comm.matched_lawyer.name if comm.matched_lawyer else None,
        "destinatarios": comm.destinatarios_json,
        "advogados_intimados": comm.advogados_json,
        "link_documento_original": comm.link,
        "lida": comm.read_at is not None,
        "lida_em": comm.read_at.isoformat() if comm.read_at else None,
        "teor": teor[:TEOR_MAX_CHARS] or None,
    }
    if comm.analysis_json:
        # Explicação da IA já gerada (cache) — vem de graça no detalhe.
        result["explicacao_ia"] = comm.analysis_json
    return result


def explain_communication_handler(communication_id: int, law_firm_id: int,
                                  user_id: int | None = None) -> dict:
    """Explicação estruturada da comunicação (cache: 1 chamada de IA por comunicação)."""
    from fastmcp.exceptions import ToolError

    from app.services import communication_monitor_service as monitor

    try:
        result = monitor.explain_communication(law_firm_id, communication_id, user_id=user_id)
    except ValueError as exc:
        raise ToolError(str(exc))

    return {
        "comunicacao_id": communication_id,
        "veio_do_cache": result.get("cached", False),
        "gerada_em": result.get("generated_at"),
        "modelo": result.get("model"),
        "explicacao": result.get("data"),
        "aviso": "Apoio à triagem — confira prazos e teor no processo oficial.",
    }


def process_communications_handler(
    law_firm_id: int,
    numero_processo: str,
    buscar_na_fonte: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Linha do tempo de comunicações de um processo (base local e, opcionalmente, DJEN ao vivo)."""
    from fastmcp.exceptions import ToolError

    from app.models import JudicialProcess, ProcessCommunication
    from app.services.comunica_pje_client import ComunicaPjeClient, ComunicaPjeError, only_digits

    numero = (numero_processo or '').strip()
    digits = only_digits(numero)
    if not digits:
        raise ToolError("Informe o número do processo (CNJ, com ou sem máscara).")

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)

    from sqlalchemy import or_
    query = (ProcessCommunication.query
             .filter_by(law_firm_id=law_firm_id)
             .filter(or_(ProcessCommunication.numero_processo == digits,
                         ProcessCommunication.numero_processo_mascara.ilike(f'%{numero}%')))
             .order_by(ProcessCommunication.data_disponibilizacao.asc(),
                       ProcessCommunication.id.asc()))

    total = query.count()
    comms = fetch_page(query, limit, offset)

    itens = []
    for c in comms:
        teor = _clean_teor(c.texto)
        itens.append({
            "id": c.id,
            "data_disponibilizacao": _iso(c.data_disponibilizacao),
            "tribunal": c.sigla_tribunal,
            "tipo": c.tipo_comunicacao,
            "tipo_documento": c.tipo_documento,
            "orgao": c.nome_orgao,
            "fonte": _fonte_label(c.source),
            "lida": c.read_at is not None,
            "tem_explicacao_ia": bool(c.analysis_json),
            "previa_teor": (teor[:PREVIEW_CHARS] + "…") if len(teor) > PREVIEW_CHARS else (teor or None),
        })

    envelope = page_envelope(total, offset, itens)
    envelope["numero_processo"] = numero

    process = (JudicialProcess.query
               .filter_by(law_firm_id=law_firm_id)
               .filter(or_(JudicialProcess.process_number == digits,
                           JudicialProcess.process_number.ilike(f'%{numero}%')))
               .first())
    envelope["processo_painel"] = {
        "id": process.id,
        "titulo": process.title,
        "status": process.status,
        "situacao_descoberta": process.discovery_status,
    } if process else None

    if buscar_na_fonte:
        if len(digits) != 20:
            raise ToolError("Para buscar ao vivo no DJEN, informe o número CNJ completo (20 dígitos).")
        try:
            client = ComunicaPjeClient()
            vivo = []
            for item in client.get_comunicacoes_processo(digits):
                parsed = client.parse_comunicacao(item)
                teor = _clean_teor(parsed.get('texto'))
                vivo.append({
                    "data_disponibilizacao": _iso(parsed.get('data_disponibilizacao')),
                    "tribunal": parsed.get('sigla_tribunal'),
                    "tipo": parsed.get('tipo_comunicacao'),
                    "tipo_documento": parsed.get('tipo_documento'),
                    "orgao": parsed.get('nome_orgao'),
                    "hash": parsed.get('hash'),
                    "link": parsed.get('link'),
                    "previa_teor": (teor[:PREVIEW_CHARS] + "…") if len(teor) > PREVIEW_CHARS else (teor or None),
                })
            envelope["djen_ao_vivo"] = {
                "total": len(vivo),
                "itens": vivo,
                "aviso": "Consulta direta à API pública do DJEN — resultados NÃO foram "
                         "gravados na base; o radar só grava o que pertence às OABs monitoradas.",
            }
        except ComunicaPjeError as exc:
            envelope["djen_ao_vivo"] = {"erro": f"Consulta ao DJEN indisponível agora: {exc}"}

    return envelope


def monitoring_summary_handler(law_firm_id: int, dias: int = 7) -> dict:
    """Visão executiva do radar: totais, não lidas e distribuição do período."""
    from datetime import date, timedelta

    from sqlalchemy import func

    from app.models import db, ProcessCommunication
    from app.services import communication_monitor_service as monitor

    dias = max(1, min(int(dias or 7), 365))
    since = date.today() - timedelta(days=dias)

    base = ProcessCommunication.query.filter_by(law_firm_id=law_firm_id)
    period = base.filter(ProcessCommunication.data_disponibilizacao >= since)

    def _group(column, query):
        rows = (query.with_entities(column, func.count(ProcessCommunication.id))
                .group_by(column)
                .order_by(func.count(ProcessCommunication.id).desc())
                .all())
        return {str(k if k is not None else '—'): v for k, v in rows}

    ready, skipped = monitor.monitored_lawyers(law_firm_id)

    return {
        "periodo_dias": dias,
        "total_geral": base.count(),
        "nao_lidas": monitor.unread_count(law_firm_id),
        "no_periodo": {
            "total": period.count(),
            "por_tribunal": _group(ProcessCommunication.sigla_tribunal, period),
            "por_tipo": _group(ProcessCommunication.tipo_comunicacao, period),
            "por_fonte": {
                _fonte_label(k): v
                for k, v in _group(ProcessCommunication.source, period).items()
            },
        },
        "advogados_monitorados": len(ready),
        "advogados_fora_do_radar": [l.name for l in skipped],
        "tribunais_do_historico": monitor.firm_tribunal_siglas(law_firm_id),
    }
