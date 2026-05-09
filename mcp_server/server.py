"""
IntellexIA MCP Server
=====================
Servidor MCP que expõe ferramentas de:
  - Base de conhecimento (RAG)
  - Painel FAP e contestações
  - Revisor de petições iniciais (futuro)

Uso:
    uv run python mcp_server/server.py

Configuração no cliente MCP (ex: Claude Desktop):
    {
      "mcpServers": {
        "intellexia": {
          "command": "uv",
          "args": ["run", "python", "mcp_server/server.py"],
          "cwd": "<caminho_para_o_projeto>"
        }
      }
    }
"""
from __future__ import annotations

import os
import sys

# Garante que a raiz do projeto está no Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp import FastMCP

from main import app  # noqa: E402 — importa o app Flask com DB e configs

# ── Autenticação (requerida quando MCP_TRANSPORT=streamable-http) ──────────────
_MCP_API_KEY = os.environ.get("MCP_API_KEY", "")

def _auth_provider(api_key: str) -> bool:
    """Valida o Bearer token enviado pelo cliente MCP."""
    if not _MCP_API_KEY:
        return True  # sem chave configurada: só permite em desenvolvimento local
    return api_key == _MCP_API_KEY

from mcp_server.tools.knowledge import (
    query_knowledge_base_handler,
)
from mcp_server.tools.fap import (
    list_fap_companies_handler,
    list_fap_contestacoes_handler,
    list_fap_benefits_handler,
    get_benefit_detail_handler,
)
from mcp_server.tools.petition_reviewer import review_petition_handler

mcp = FastMCP(
    "IntellexIA",
    instructions=(
        "Sistema de automação jurídica especializado em direito trabalhista e previdenciário. "
        "Oferece acesso à base de conhecimento via RAG, painel FAP (Fator Acidentário de Prevenção), "
        "contestações e revisão de petições iniciais. "
        "Todos os recursos são isolados por escritório (law_firm_id)."
    ),
)


# ──────────────────────────────────────────────────────────────────────────────
# BASE DE CONHECIMENTO
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def query_knowledge_base(
    question: str,
    law_firm_id: int,
    search_mode: str = "semantic",
) -> dict:
    """Consulta a base de conhecimento jurídica do escritório usando IA (RAG).

    Busca documentos relevantes no Qdrant (semântico) ou Meilisearch (full-text)
    e gera uma resposta fundamentada via LLM.

    Args:
        question: Pergunta em linguagem natural.
        law_firm_id: ID do escritório de advocacia.
        search_mode: "semantic" (padrão) ou "full_text" (para CPF, CNPJ, número de processo).

    Returns:
        Dicionário com 'answer', 'sources', 'suggested_questions'.
    """
    with app.app_context():
        return query_knowledge_base_handler(question, law_firm_id, search_mode)


# ──────────────────────────────────────────────────────────────────────────────
# PAINEL FAP
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def list_fap_companies(law_firm_id: int) -> list[dict]:
    """Lista as empresas FAP cadastradas e sincronizadas do escritório.

    Args:
        law_firm_id: ID do escritório de advocacia.

    Returns:
        Lista de empresas com id, cnpj, nome e data da última sincronização.
    """
    with app.app_context():
        return list_fap_companies_handler(law_firm_id)


@mcp.tool()
def list_fap_contestacoes(
    law_firm_id: int,
    cnpj: str | None = None,
    ano_vigencia: int | None = None,
    situacao_codigo: str | None = None,
    instancia_codigo: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Lista contestações FAP sincronizadas do portal Dataprev.

    Permite filtrar por CNPJ, ano de vigência, situação e instância.

    Args:
        law_firm_id: ID do escritório de advocacia.
        cnpj: CNPJ do estabelecimento (14 dígitos, apenas números).
        ano_vigencia: Ano de vigência FAP (ex: 2023).
        situacao_codigo: Código de situação (ex: DEFERIDO, INDEFERIDO).
        instancia_codigo: Código de instância (ex: ADMINISTRATIVO_PRIMEIRA_INSTANCIA).
        limit: Número máximo de registros (padrão 100).

    Returns:
        Lista de contestações com dados de identificação, instância e situação.
    """
    with app.app_context():
        return list_fap_contestacoes_handler(
            law_firm_id, cnpj, ano_vigencia, situacao_codigo, instancia_codigo, limit
        )


@mcp.tool()
def list_fap_benefits(
    law_firm_id: int,
    cnpj: str | None = None,
    status: str | None = None,
    request_type: str | None = None,
    benefit_type: str | None = None,
    fap_contestation_topic: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Lista benefícios previdenciários vinculados a contestações FAP.

    Args:
        law_firm_id: ID do escritório de advocacia.
        cnpj: CNPJ do empregador (apenas números).
        status: Status do benefício (ex: pending, approved, rejected).
        request_type: Tipo de pedido (exclusao, inclusao, revisao).
        benefit_type: Tipo de benefício (ex: B91, B94).
        fap_contestation_topic: Tema da contestação FAP.
        limit: Número máximo de registros (padrão 50).

    Returns:
        Lista de benefícios com dados do segurado, empregador, período e status de instâncias.
    """
    with app.app_context():
        return list_fap_benefits_handler(
            law_firm_id, cnpj, status, request_type, benefit_type, fap_contestation_topic, limit
        )


@mcp.tool()
def get_benefit_detail(benefit_id: int, law_firm_id: int) -> dict:
    """Retorna detalhes completos de um benefício FAP específico.

    Args:
        benefit_id: ID interno do benefício.
        law_firm_id: ID do escritório de advocacia (validação de tenant).

    Returns:
        Dicionário completo com todos os campos do benefício.
    """
    with app.app_context():
        return get_benefit_detail_handler(benefit_id, law_firm_id)


# ──────────────────────────────────────────────────────────────────────────────
# REVISOR DE PETIÇÕES INICIAIS
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def review_initial_petition(
    petition_text: str,
    law_firm_id: int,
    case_type: str = "trabalhista",
) -> dict:
    """Revisa uma petição inicial jurídica, apontando inconsistências e sugestões de melhoria.

    Módulo em desenvolvimento — retorna análise preliminar baseada em regras gerais.

    Args:
        petition_text: Texto completo da petição inicial.
        law_firm_id: ID do escritório de advocacia.
        case_type: Tipo do caso (trabalhista, previdenciario). Padrão: trabalhista.

    Returns:
        Dicionário com 'status', 'analysis' e 'suggestions'.
    """
    with app.app_context():
        return review_petition_handler(petition_text, law_firm_id, case_type)


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")  # streamable-http | stdio
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8001"))

    if transport == "streamable-http":
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run(transport="stdio")
