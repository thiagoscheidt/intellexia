"""
IntellexIA MCP Server
=====================
Servidor MCP com OAuth 2.1 autenticado contra a base de usuários do IntellexIA.

Expõe ferramentas de:
  - Base de conhecimento (RAG)          [módulo knowledge_base]
  - Painel FAP e contestações           [módulo fap_panel]
  - Revisor de petições iniciais (stub) [módulo fap_review]

A identidade (user_id, law_firm_id, permissões de módulo) vem do access token
emitido no fluxo OAuth — o usuário autoriza no navegador reusando o login do
sistema em rs-dev.intellexia.com.br.

Uso:
    uv run python mcp_server/server.py

Conexão no Claude Code:
    claude mcp add --transport http intellexia https://rs-dev.intellexia.com.br/mcp
    (depois: /mcp → Authenticate → autorizar no navegador)

Env:
    MCP_PUBLIC_URL  URL pública do MCP (default https://rs-dev.intellexia.com.br/mcp)
    APP_PUBLIC_URL  URL pública do app Flask (default: raiz do domínio do MCP_PUBLIC_URL)
    MCP_HOST/MCP_PORT  bind local do uvicorn (default 127.0.0.1:8001)
"""
from __future__ import annotations

import os
import sys

# Garante que a raiz do projeto está no Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import Response

from main import app  # noqa: E402 — importa o app Flask com DB e configs

from mcp_server.identity import require_module
from mcp_server.oauth_provider import IntellexiaOAuthProvider
from mcp_server.tools.knowledge import query_knowledge_base_handler
from mcp_server.tools.fap import (
    list_fap_companies_handler,
    list_fap_contestacoes_handler,
    list_fap_benefits_handler,
    get_benefit_detail_handler,
)
from mcp_server.tools.petition_reviewer import review_petition_handler

MCP_PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", "https://rs-dev.intellexia.com.br/mcp")

auth_provider = IntellexiaOAuthProvider(
    base_url=MCP_PUBLIC_URL,
    app_public_url=os.environ.get("APP_PUBLIC_URL"),
)

mcp = FastMCP(
    "IntellexIA",
    instructions=(
        "Sistema de automação jurídica especializado em direito trabalhista e previdenciário. "
        "Oferece acesso à base de conhecimento via RAG, painel FAP (Fator Acidentário de Prevenção), "
        "contestações e revisão de petições iniciais. "
        "Todos os recursos são isolados pelo escritório do usuário autenticado e respeitam "
        "suas permissões de módulo."
    ),
    auth=auth_provider,
)


# ──────────────────────────────────────────────────────────────────────────────
# CONSENTIMENTO OAUTH (reusa a sessão de login do Flask)
# ──────────────────────────────────────────────────────────────────────────────


@mcp.custom_route("/consent", methods=["GET"])
async def consent_page(request: Request) -> Response:
    return await auth_provider.consent_page(request)


@mcp.custom_route("/consent", methods=["POST"])
async def consent_submit(request: Request) -> Response:
    return await auth_provider.consent_submit(request)


# ──────────────────────────────────────────────────────────────────────────────
# BASE DE CONHECIMENTO
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def query_knowledge_base(question: str, search_mode: str = "semantic") -> dict:
    """Consulta a base de conhecimento jurídica do escritório usando IA (RAG).

    Busca documentos relevantes no Qdrant (semântico) ou Meilisearch (full-text)
    e gera uma resposta fundamentada via LLM.

    Args:
        question: Pergunta em linguagem natural.
        search_mode: "semantic" (padrão) ou "full_text" (para CPF, CNPJ, número de processo).

    Returns:
        Dicionário com 'answer', 'sources', 'suggested_questions'.
    """
    claims = require_module("knowledge_base")
    with app.app_context():
        return query_knowledge_base_handler(question, claims["law_firm_id"], search_mode)


# ──────────────────────────────────────────────────────────────────────────────
# PAINEL FAP
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def list_fap_companies() -> list[dict]:
    """Lista as empresas FAP cadastradas e sincronizadas do escritório.

    Returns:
        Lista de empresas com id, cnpj, nome e data da última sincronização.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return list_fap_companies_handler(claims["law_firm_id"])


@mcp.tool()
def list_fap_contestacoes(
    cnpj: str | None = None,
    ano_vigencia: int | None = None,
    situacao_codigo: str | None = None,
    instancia_codigo: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Lista contestações FAP sincronizadas do portal Dataprev.

    Permite filtrar por CNPJ, ano de vigência, situação e instância.

    Args:
        cnpj: CNPJ do estabelecimento (14 dígitos, apenas números).
        ano_vigencia: Ano de vigência FAP (ex: 2023).
        situacao_codigo: Código de situação (ex: DEFERIDO, INDEFERIDO).
        instancia_codigo: Código de instância (ex: ADMINISTRATIVO_PRIMEIRA_INSTANCIA).
        limit: Número máximo de registros (padrão 100).

    Returns:
        Lista de contestações com dados de identificação, instância e situação.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return list_fap_contestacoes_handler(
            claims["law_firm_id"], cnpj, ano_vigencia, situacao_codigo, instancia_codigo, limit
        )


@mcp.tool()
def list_fap_benefits(
    cnpj: str | None = None,
    status: str | None = None,
    request_type: str | None = None,
    benefit_type: str | None = None,
    fap_contestation_topic: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Lista benefícios previdenciários vinculados a contestações FAP.

    Args:
        cnpj: CNPJ do empregador (apenas números).
        status: Status do benefício (ex: pending, approved, rejected).
        request_type: Tipo de pedido (exclusao, inclusao, revisao).
        benefit_type: Tipo de benefício (ex: B91, B94).
        fap_contestation_topic: Tema da contestação FAP.
        limit: Número máximo de registros (padrão 50).

    Returns:
        Lista de benefícios com dados do segurado, empregador, período e status de instâncias.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return list_fap_benefits_handler(
            claims["law_firm_id"], cnpj, status, request_type, benefit_type,
            fap_contestation_topic, limit,
        )


@mcp.tool()
def get_benefit_detail(benefit_id: int) -> dict:
    """Retorna detalhes completos de um benefício FAP específico.

    Args:
        benefit_id: ID interno do benefício.

    Returns:
        Dicionário completo com todos os campos do benefício.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return get_benefit_detail_handler(benefit_id, claims["law_firm_id"])


# ──────────────────────────────────────────────────────────────────────────────
# REVISOR DE PETIÇÕES INICIAIS
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def review_initial_petition(petition_text: str, case_type: str = "trabalhista") -> dict:
    """Revisa uma petição inicial jurídica, apontando inconsistências e sugestões de melhoria.

    Módulo em desenvolvimento — retorna análise preliminar baseada em regras gerais.

    Args:
        petition_text: Texto completo da petição inicial.
        case_type: Tipo do caso (trabalhista, previdenciario). Padrão: trabalhista.

    Returns:
        Dicionário com 'status', 'analysis' e 'suggestions'.
    """
    claims = require_module("fap_review")
    with app.app_context():
        return review_petition_handler(petition_text, claims["law_firm_id"], case_type)


if __name__ == "__main__":
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8001"))

    import uvicorn

    uvicorn.run(
        mcp.http_app(path="/"),
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
