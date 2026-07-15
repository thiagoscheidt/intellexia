"""
Tools: Exportação para Excel (XLSX)
===================================
Usa os MESMOS builders de planilha das telas do sistema:
  - Benefícios   → build_benefits_export_workbook (Painel de Contestações)
  - Contestações → build_contestacoes_export_workbook (Painel FAP)

O que muda em relação às telas é só a entrega: link de download assinado
(itsdangerous, validade de 1 hora), servido pelo próprio servidor MCP em
/export/<token>. Os arquivos ficam em uploads/mcp_exports/{law_firm_id}/
e são limpos automaticamente após 24 horas.
"""
from __future__ import annotations

import os
import re
import secrets
import time
from datetime import datetime
from urllib.parse import urlparse

from itsdangerous import URLSafeTimedSerializer

EXPORT_TTL_SECONDS = 3600          # validade do link (1 hora)
EXPORT_FILE_TTL_SECONDS = 24 * 3600  # arquivos antigos são removidos após 24h
MAX_EXPORT_ROWS = 50000

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_EXPORT_DIR = os.path.join(_PROJECT_ROOT, "uploads", "mcp_exports")


def _serializer():
    from main import app

    return URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="mcp-export")


def _cleanup_old_files() -> None:
    cutoff = time.time() - EXPORT_FILE_TTL_SECONDS
    for root, _dirs, files in os.walk(_EXPORT_DIR):
        for name in files:
            path = os.path.join(root, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass


def _save_workbook(workbook, law_firm_id: int, prefix: str) -> str:
    """Salva o workbook e retorna o caminho relativo (law_firm_id/arquivo)."""
    os.makedirs(os.path.join(_EXPORT_DIR, str(law_firm_id)), exist_ok=True)
    _cleanup_old_files()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{stamp}_{secrets.token_hex(4)}.xlsx"
    rel_path = f"{law_firm_id}/{filename}"
    workbook.save(os.path.join(_EXPORT_DIR, rel_path))
    return rel_path


def build_download_response(token: str):
    """Valida o token assinado e devolve o arquivo (usado pela rota /export)."""
    from itsdangerous import BadSignature, SignatureExpired
    from starlette.responses import FileResponse, JSONResponse

    try:
        payload = _serializer().loads(token, max_age=EXPORT_TTL_SECONDS)
    except SignatureExpired:
        return JSONResponse({"erro": "Link de download expirado. Gere a exportação novamente."}, status_code=410)
    except BadSignature:
        return JSONResponse({"erro": "Link de download inválido."}, status_code=403)

    rel_path = payload.get("f", "")
    # Sanidade: sem path traversal e restrito ao diretório de exports
    if not re.fullmatch(r"\d+/[A-Za-z0-9_.\-]+\.xlsx", rel_path):
        return JSONResponse({"erro": "Link de download inválido."}, status_code=403)
    full_path = os.path.join(_EXPORT_DIR, rel_path)
    if not os.path.isfile(full_path):
        return JSONResponse({"erro": "Arquivo não encontrado (expirado). Gere a exportação novamente."}, status_code=404)

    return FileResponse(
        full_path,
        filename=os.path.basename(full_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _download_result(rel_path: str, mcp_public_url: str, total_linhas: int) -> dict:
    token = _serializer().dumps({"f": rel_path})
    return {
        "arquivo": os.path.basename(rel_path),
        "total_linhas": total_linhas,
        "url_download": f"{mcp_public_url.rstrip('/')}/export/{token}",
        "validade_minutos": EXPORT_TTL_SECONDS // 60,
        "instrucao": "Abra o link no navegador para baixar a planilha.",
    }


# ── Exports (mesmos builders das telas) ───────────────────────────────────────


def export_benefits_excel_handler(law_firm_id: int, mcp_public_url: str, **filters) -> dict:
    """Exporta benefícios com a planilha oficial do Painel de Contestações."""
    from app.blueprints.disputes_center import (
        _base_benefits_query,
        build_benefits_export_workbook,
    )
    from app.models import Benefit, db

    from mcp_server.tools.fap import _filter_benefit_cnpj, _filter_benefit_empresa

    query = _base_benefits_query(law_firm_id)

    if filters.get("cnpj"):
        query = _filter_benefit_cnpj(query, filters["cnpj"])
    if filters.get("empresa"):
        query = _filter_benefit_empresa(query, filters["empresa"], law_firm_id)
    if filters.get("status"):
        query = query.filter(Benefit.status == filters["status"])
    if filters.get("request_type"):
        query = query.filter(Benefit.request_type == filters["request_type"])
    if filters.get("benefit_type"):
        query = query.filter(Benefit.benefit_type == filters["benefit_type"])
    if filters.get("fap_contestation_topic"):
        topic = filters["fap_contestation_topic"]
        query = query.filter(db.or_(
            Benefit.fap_contestation_topics_json.like(f'%"{topic}"%'),
            Benefit.fap_contestation_topic == topic,
        ))
    if filters.get("segurado"):
        query = query.filter(Benefit.insured_name.ilike(f"%{filters['segurado']}%"))
    if filters.get("nit"):
        query = query.filter(Benefit.insured_nit == filters["nit"])
    if filters.get("cpf"):
        query = query.filter(Benefit.insured_cpf == filters["cpf"])
    if filters.get("numero_beneficio"):
        query = query.filter(Benefit.benefit_number == filters["numero_beneficio"])
    if filters.get("ano_vigencia"):
        query = query.filter(Benefit.fap_vigencia_years.like(f"%{filters['ano_vigencia']}%"))

    total = query.count()
    rows = query.order_by(Benefit.created_at.desc(), Benefit.id.desc()).limit(MAX_EXPORT_ROWS).all()
    if not rows:
        return {"erro": "Nenhum benefício encontrado com esses filtros.", "total_linhas": 0}

    workbook = build_benefits_export_workbook(rows)
    rel_path = _save_workbook(workbook, law_firm_id, "beneficios_fap")
    result = _download_result(rel_path, mcp_public_url, len(rows))
    if total > MAX_EXPORT_ROWS:
        result["aviso"] = f"Resultado truncado em {MAX_EXPORT_ROWS} linhas (total: {total})."
    return result


def export_contestacoes_excel_handler(law_firm_id: int, mcp_public_url: str, **filters) -> dict:
    """Exporta contestações com a planilha oficial do Painel FAP."""
    from main import app
    from app.blueprints.fap_panel import build_contestacoes_export_workbook
    from app.models import FapWebContestacao

    query = FapWebContestacao.query.filter_by(law_firm_id=law_firm_id)
    if filters.get("cnpj"):
        query = query.filter(FapWebContestacao.cnpj == filters["cnpj"])
    if filters.get("cnpj_raiz"):
        query = query.filter(FapWebContestacao.cnpj_raiz == filters["cnpj_raiz"])
    if filters.get("ano_vigencia"):
        query = query.filter(FapWebContestacao.ano_vigencia == int(filters["ano_vigencia"]))
    if filters.get("situacao_codigo"):
        query = query.filter(FapWebContestacao.situacao_codigo == filters["situacao_codigo"])
    if filters.get("instancia_codigo"):
        query = query.filter(FapWebContestacao.instancia_codigo == filters["instancia_codigo"])

    total = query.count()
    rows = (
        query.order_by(
            FapWebContestacao.ano_vigencia.desc(),
            FapWebContestacao.cnpj.asc(),
            FapWebContestacao.contestacao_id.asc(),
        )
        .limit(MAX_EXPORT_ROWS)
        .all()
    )
    if not rows:
        return {"erro": "Nenhuma contestação encontrada com esses filtros.", "total_linhas": 0}

    # O builder usa url_for(_external=True) para os links de PDF — fora de uma
    # request, o host público vem do próprio MCP_PUBLIC_URL.
    parsed = urlparse(mcp_public_url)
    with app.test_request_context(base_url=f"{parsed.scheme}://{parsed.netloc}/"):
        workbook = build_contestacoes_export_workbook(law_firm_id, rows, {
            "ano_vigencia": filters.get("ano_vigencia"),
            "cnpj_raiz": filters.get("cnpj_raiz"),
            "cnpj": filters.get("cnpj"),
            "instancia": filters.get("instancia_codigo"),
            "situacao": filters.get("situacao_codigo"),
        })

    rel_path = _save_workbook(workbook, law_firm_id, "contestacoes_fap")
    result = _download_result(rel_path, mcp_public_url, len(rows))
    if total > MAX_EXPORT_ROWS:
        result["aviso"] = f"Resultado truncado em {MAX_EXPORT_ROWS} linhas (total: {total})."
    return result
