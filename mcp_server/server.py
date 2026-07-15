"""
IntellexIA MCP Server
=====================
Servidor MCP com OAuth 2.1 autenticado contra a base de usuários do IntellexIA.

Expõe ferramentas de:
  - Base de conhecimento (RAG)          [módulo knowledge_base]
  - Painel FAP e contestações           [módulo fap_panel]
  - Painel de processos judiciais       [módulo process_panel]
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

import base64
import os
import sys
from urllib.parse import urlparse

# Garante que a raiz do projeto está no Python path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

import mcp.types
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import Response

from main import app  # noqa: E402 — importa o app Flask com DB e configs

from mcp_server.identity import require_module
from mcp_server.oauth_provider import IntellexiaOAuthProvider
from mcp_server.tools.knowledge import kb_search_handler, query_knowledge_base_handler
from mcp_server.tools.fap import (
    list_fap_companies_handler,
    list_fap_contestacoes_handler,
    get_contestacao_detail_handler,
    list_fap_benefits_handler,
    get_benefit_detail_handler,
    fap_summary_handler,
    fap_changes_handler,
    list_fap_procuracoes_handler,
    fap_filter_values_handler,
)
from mcp_server.tools.disputes import list_cats_handler
from mcp_server.tools.exports import (
    build_download_response,
    export_benefits_excel_handler,
    export_contestacoes_excel_handler,
)
from mcp_server.tools.process_panel import (
    list_processes_handler,
    get_process_detail_handler,
)
from mcp_server.tools.petition_reviewer import review_petition_handler

MCP_PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", "https://rs-dev.intellexia.com.br/mcp")
_parsed_public = urlparse(MCP_PUBLIC_URL)
APP_PUBLIC_URL = (
    os.environ.get("APP_PUBLIC_URL")
    or f"{_parsed_public.scheme}://{_parsed_public.netloc}"
).rstrip("/")

auth_provider = IntellexiaOAuthProvider(
    base_url=MCP_PUBLIC_URL,
    app_public_url=os.environ.get("APP_PUBLIC_URL"),
)


def _server_icons() -> list[mcp.types.Icon]:
    """Ícone do IntellexIA exibido pelos clientes MCP (conectores do Claude).

    Publica a URL do logo e, como fallback à prova de rede/CORS, o mesmo PNG
    embutido em data URI.
    """
    icons = [
        mcp.types.Icon(
            src=f"{APP_PUBLIC_URL}/static/assets/img/logo.png",
            mimeType="image/png",
            sizes=["128x128"],
        )
    ]
    try:
        with open(os.path.join(_PROJECT_ROOT, "static", "assets", "img", "logo.png"), "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        icons.append(mcp.types.Icon(
            src=f"data:image/png;base64,{encoded}",
            mimeType="image/png",
            sizes=["128x128"],
        ))
    except OSError:
        pass
    return icons


mcp = FastMCP(
    "IntellexIA",
    icons=_server_icons(),
    website_url=APP_PUBLIC_URL,
    instructions=(
        "Sistema de automação jurídica especializado em direito trabalhista e previdenciário "
        "(FAP — Fator Acidentário de Prevenção). Oferece base de conhecimento via RAG, painel "
        "FAP (empresas, contestações, benefícios, procurações, resumo estatístico, alterações "
        "de sincronização) e painel de processos judiciais. Todos os dados são isolados pelo "
        "escritório do usuário autenticado e respeitam suas permissões de módulo. "
        "Datas em formato ISO; CNPJs apenas com números."
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


@mcp.custom_route("/export/{token:path}", methods=["GET"])
async def export_download(request: Request) -> Response:
    """Download de planilhas exportadas (link assinado com validade de 1h)."""
    return build_download_response(request.path_params["token"])


# ──────────────────────────────────────────────────────────────────────────────
# BASE DE CONHECIMENTO
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def consultar_base_conhecimento(pergunta: str) -> dict:
    """Consulta a base de conhecimento jurídica do escritório usando IA (RAG).

    Busca documentos relevantes e gera uma resposta fundamentada com fontes.
    O modo de busca (semântico ou por termos exatos como CPF/CNPJ/nº de processo)
    é escolhido automaticamente a partir da pergunta.

    Args:
        pergunta: Pergunta em linguagem natural.

    Returns:
        Dicionário com 'resposta', 'fontes', 'fontes_detalhe' e 'perguntas_sugeridas'.
    """
    claims = require_module("knowledge_base")
    with app.app_context():
        return query_knowledge_base_handler(
            pergunta, claims["law_firm_id"], user_id=claims.get("user_id")
        )


@mcp.tool()
def pesquisar_base_conhecimento(
    pergunta: str,
    modo_busca: str | None = None,
    limite: int = 20,
) -> dict:
    """Pesquisa na base de conhecimento e retorna os trechos encontrados (sem gerar resposta).

    É a Pesquisa Inteligente do sistema: um roteador LLM decide automaticamente
    entre busca semântica (conceitos) e textual (termos exatos como CPF, CNPJ,
    número de processo), a pergunta é otimizada antes da busca, e os resultados
    voltam ranqueados com fonte, página e relevância. Use quando quiser os
    documentos/trechos em si; para uma resposta elaborada use
    consultar_base_conhecimento.

    Args:
        pergunta: O que pesquisar, em linguagem natural ou termo exato.
        modo_busca: Força "semantic" ou "full_text" (opcional — sem informar,
            o roteador LLM decide).
        limite: Número máximo de trechos retornados (padrão 20).

    Returns:
        Dicionário com 'modo_busca', 'modo_decidido_por', 'pergunta_melhorada',
        'total_resultados' e 'resultados' (trecho, fonte, página, relevância, arquivo).
    """
    claims = require_module("knowledge_base")
    with app.app_context():
        return kb_search_handler(pergunta, claims["law_firm_id"], modo_busca, limite)


# ──────────────────────────────────────────────────────────────────────────────
# PAINEL FAP
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def listar_empresas_fap() -> list[dict]:
    """Lista as empresas FAP cadastradas e sincronizadas do escritório.

    Returns:
        Lista de empresas com id, cnpj, nome, tipo de procuração e data da
        última sincronização com o portal FAP Web.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return list_fap_companies_handler(claims["law_firm_id"])


@mcp.tool()
def listar_contestacoes_fap(
    cnpj: str | None = None,
    cnpj_raiz: str | None = None,
    ano_vigencia: int | None = None,
    situacao_codigo: str | None = None,
    instancia_codigo: str | None = None,
    limite: int = 100,
) -> dict:
    """Lista contestações FAP sincronizadas do portal Dataprev, com total encontrado.

    Args:
        cnpj: CNPJ do estabelecimento (14 dígitos, apenas números).
        cnpj_raiz: Raiz do CNPJ (8 dígitos) para pegar todos os estabelecimentos.
        ano_vigencia: Ano de vigência FAP (ex: 2023).
        situacao_codigo: Código de situação (ex: DEFERIDO, INDEFERIDO).
        instancia_codigo: Código de instância (ex: ADMINISTRATIVO_PRIMEIRA_INSTANCIA).
        limite: Número máximo de registros retornados (padrão 100).

    Returns:
        Dicionário com 'total_encontrado', 'retornados' e 'itens' (cada item com
        identificação, instância, situação, data D.O.U. e se o PDF já foi baixado).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return list_fap_contestacoes_handler(
            claims["law_firm_id"], cnpj, cnpj_raiz, ano_vigencia,
            situacao_codigo, instancia_codigo, limite,
        )


@mcp.tool()
def listar_beneficios_fap(
    cnpj: str | None = None,
    status: str | None = None,
    tipo_pedido: str | None = None,
    tipo_beneficio: str | None = None,
    topico_contestacao: str | None = None,
    segurado: str | None = None,
    nit: str | None = None,
    cpf: str | None = None,
    numero_beneficio: str | None = None,
    ano_vigencia: str | None = None,
    limite: int = 50,
) -> dict:
    """Lista benefícios previdenciários vinculados a contestações FAP, com total encontrado.

    Args:
        cnpj: CNPJ do empregador (apenas números).
        status: Status do benefício (ex: pending, approved, rejected).
        tipo_pedido: exclusao, inclusao ou revisao.
        tipo_beneficio: Ex: B91 (auxílio-acidente), B94 (auxílio-doença acidentário).
        topico_contestacao: Tópico jurídico da contestação (ex: ACIDENTE DE TRAJETO).
        segurado: Nome (ou parte do nome) do segurado.
        nit: NIT do segurado (busca exata).
        cpf: CPF do segurado (busca exata, apenas números).
        numero_beneficio: Número do benefício (busca exata).
        ano_vigencia: Ano de vigência FAP em que o benefício aparece (ex: "2023").
        limite: Número máximo de registros retornados (padrão 50).

    Returns:
        Dicionário com 'total_encontrado', 'retornados' e 'itens' (cada item com
        segurado, empregador, período, tópicos de contestação e status por instância).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return list_fap_benefits_handler(
            claims["law_firm_id"], cnpj, status, tipo_pedido, tipo_beneficio,
            topico_contestacao, segurado, nit, cpf, numero_beneficio, ano_vigencia, limite,
        )


@mcp.tool()
def detalhar_beneficio(beneficio_id: int) -> dict:
    """Retorna todos os dados de um benefício FAP específico.

    Inclui dados do segurado, empregador, acidente (CAT/BO), valores pagos,
    tópicos de contestação e justificativas/pareceres por instância.

    Args:
        beneficio_id: ID interno do benefício (obtido em listar_beneficios_fap).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return get_benefit_detail_handler(beneficio_id, claims["law_firm_id"])


@mcp.tool()
def resumo_fap(ano_vigencia: int | None = None, cnpj: str | None = None) -> dict:
    """Resumo estatístico do FAP do escritório: contagens agregadas.

    Contestações por ano de vigência, situação e instância; benefícios por tipo,
    tipo de pedido, status de primeira/segunda instância e tópico de contestação.
    Ideal para perguntas gerenciais ("quantas deferidas em 2023?") sem listar tudo.

    Args:
        ano_vigencia: Restringe a um ano de vigência FAP (opcional).
        cnpj: Restringe a um estabelecimento (opcional, apenas números).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return fap_summary_handler(claims["law_firm_id"], ano_vigencia, cnpj)


@mcp.tool()
def alteracoes_recentes_fap(
    cnpj: str | None = None,
    ano_vigencia: int | None = None,
    dias: int = 7,
    limite: int = 100,
) -> dict:
    """Alterações detectadas nas sincronizações com o portal FAP Web.

    Mostra o que mudou nas contestações (campos, valores anteriores e novos) —
    útil para "o que mudou desde ontem/na última semana?".

    Args:
        cnpj: Filtra por estabelecimento (opcional).
        ano_vigencia: Filtra por ano de vigência (opcional).
        dias: Janela de tempo em dias (padrão 7; use 0 para todo o histórico).
        limite: Número máximo de registros (padrão 100).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return fap_changes_handler(claims["law_firm_id"], cnpj, ano_vigencia, dias, limite)


@mcp.tool()
def listar_procuracoes_fap(
    cnpj_raiz: str | None = None,
    situacao_codigo: str | None = None,
    limite: int = 100,
) -> dict:
    """Lista procurações eletrônicas sincronizadas do portal FAP Web.

    Args:
        cnpj_raiz: Raiz do CNPJ da empresa outorgante (8 dígitos, opcional).
        situacao_codigo: Código de situação da procuração (opcional).
        limite: Número máximo de registros (padrão 100).

    Returns:
        Dicionário com 'total_encontrado', 'retornados' e 'itens' (protocolo, tipo,
        situação, vigência e empresa outorgante).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return list_fap_procuracoes_handler(claims["law_firm_id"], cnpj_raiz, situacao_codigo, limite)


@mcp.tool()
def detalhar_contestacao(contestacao_id: int) -> dict:
    """Detalhe completo de uma contestação FAP.

    Inclui todos os dados da contestação, os benefícios vinculados à mesma
    vigência/CNPJ (com contagem por status de 1ª instância) e as alterações
    recentes detectadas na sincronização.

    Args:
        contestacao_id: ID interno da contestação (campo 'id' de listar_contestacoes_fap).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return get_contestacao_detail_handler(contestacao_id, claims["law_firm_id"])


@mcp.tool()
def valores_de_filtro_fap() -> dict:
    """Valores válidos (em uso no escritório) para os filtros das tools FAP.

    Retorna situações e instâncias de contestação (código → descrição), anos de
    vigência, tipos de benefício/pedido, status e tópicos de contestação em uso,
    além do catálogo de motivos FAP. Consulte antes de filtrar para usar códigos
    exatos em vez de adivinhar.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return fap_filter_values_handler(claims["law_firm_id"])


@mcp.tool()
def listar_cats_fap(
    vigencia: str | None = None,
    cnpj: str | None = None,
    nit: str | None = None,
    numero_cat: str | None = None,
    limite: int = 50,
) -> dict:
    """Lista CATs (Comunicações de Acidente de Trabalho) das contestações FAP.

    Args:
        vigencia: Ano de vigência FAP (ex: "2023").
        cnpj: CNPJ do empregador (apenas números).
        nit: NIT do segurado.
        numero_cat: Número da CAT (busca exata).
        limite: Número máximo de registros (padrão 50).

    Returns:
        Dicionário com 'total_encontrado', 'retornados' e 'itens' (dados da CAT,
        segurado, datas e status/justificativas por instância).
    """
    claims = require_module("disputes_center")
    with app.app_context():
        return list_cats_handler(claims["law_firm_id"], vigencia, cnpj, nit, numero_cat, limite)


@mcp.tool()
def exportar_beneficios_excel(
    cnpj: str | None = None,
    status: str | None = None,
    tipo_pedido: str | None = None,
    tipo_beneficio: str | None = None,
    topico_contestacao: str | None = None,
    segurado: str | None = None,
    nit: str | None = None,
    cpf: str | None = None,
    numero_beneficio: str | None = None,
    ano_vigencia: str | None = None,
) -> dict:
    """Exporta benefícios FAP para uma planilha Excel (XLSX) e retorna o link de download.

    Use quando o usuário pedir muitos registros ou uma planilha — em vez de listar
    tudo no chat. Aceita os mesmos filtros de listar_beneficios_fap, sem limite de
    registros (até 50.000 linhas). O link expira em 1 hora.

    Args:
        cnpj: CNPJ do empregador (apenas números).
        status: Status do benefício.
        tipo_pedido: exclusao, inclusao ou revisao.
        tipo_beneficio: Ex: B91, B94.
        topico_contestacao: Tópico jurídico da contestação.
        segurado: Nome (ou parte do nome) do segurado.
        nit: NIT do segurado.
        cpf: CPF do segurado.
        numero_beneficio: Número do benefício.
        ano_vigencia: Ano de vigência FAP (ex: "2023").

    Returns:
        Dicionário com 'arquivo', 'total_linhas', 'url_download' e 'validade_minutos'.
        Apresente o url_download ao usuário como link clicável.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return export_benefits_excel_handler(
            claims["law_firm_id"], MCP_PUBLIC_URL,
            cnpj=cnpj, status=status, request_type=tipo_pedido, benefit_type=tipo_beneficio,
            fap_contestation_topic=topico_contestacao, segurado=segurado, nit=nit, cpf=cpf,
            numero_beneficio=numero_beneficio, ano_vigencia=ano_vigencia,
        )


@mcp.tool()
def exportar_contestacoes_excel(
    cnpj: str | None = None,
    cnpj_raiz: str | None = None,
    ano_vigencia: int | None = None,
    situacao_codigo: str | None = None,
    instancia_codigo: str | None = None,
) -> dict:
    """Exporta contestações FAP para uma planilha Excel (XLSX) e retorna o link de download.

    Use quando o usuário pedir muitos registros ou uma planilha. Aceita os mesmos
    filtros de listar_contestacoes_fap, sem limite de registros (até 50.000 linhas).
    O link expira em 1 hora.

    Args:
        cnpj: CNPJ do estabelecimento (apenas números).
        cnpj_raiz: Raiz do CNPJ (8 dígitos).
        ano_vigencia: Ano de vigência FAP.
        situacao_codigo: Código de situação (consulte valores_de_filtro_fap).
        instancia_codigo: Código de instância (consulte valores_de_filtro_fap).

    Returns:
        Dicionário com 'arquivo', 'total_linhas', 'url_download' e 'validade_minutos'.
        Apresente o url_download ao usuário como link clicável.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return export_contestacoes_excel_handler(
            claims["law_firm_id"], MCP_PUBLIC_URL,
            cnpj=cnpj, cnpj_raiz=cnpj_raiz, ano_vigencia=ano_vigencia,
            situacao_codigo=situacao_codigo, instancia_codigo=instancia_codigo,
        )


# ──────────────────────────────────────────────────────────────────────────────
# PAINEL DE PROCESSOS JUDICIAIS
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def listar_processos(
    status: str | None = None,
    numero_processo: str | None = None,
    limite: int = 50,
) -> dict:
    """Lista processos judiciais do escritório, com fase atual de cada um.

    Args:
        status: ativo, suspenso, encerrado ou aguardando (opcional).
        numero_processo: Número CNJ (busca parcial, opcional).
        limite: Número máximo de registros (padrão 50).

    Returns:
        Dicionário com 'total_encontrado', 'retornados' e 'itens' (número, título,
        tribunal, juiz, partes, valor da causa, fase atual e qtd. de benefícios).
    """
    claims = require_module("process_panel")
    with app.app_context():
        return list_processes_handler(claims["law_firm_id"], status, numero_processo, limite)


@mcp.tool()
def detalhar_processo(processo_id: int) -> dict:
    """Retorna os detalhes completos de um processo judicial.

    Inclui dados do processo (classe, assuntos, tribunal, juiz, partes, valor),
    histórico de fases, benefícios vinculados com teses e decisões por instância,
    e notas internas recentes.

    Args:
        processo_id: ID interno do processo (obtido em listar_processos).
    """
    claims = require_module("process_panel")
    with app.app_context():
        return get_process_detail_handler(processo_id, claims["law_firm_id"])


# ──────────────────────────────────────────────────────────────────────────────
# REVISOR DE PETIÇÕES INICIAIS
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def revisar_peticao_inicial(texto_peticao: str, tipo_caso: str = "trabalhista") -> dict:
    """Revisa uma petição inicial jurídica, apontando inconsistências e sugestões.

    Módulo em desenvolvimento — retorna análise preliminar baseada em regras gerais.

    Args:
        texto_peticao: Texto completo da petição inicial.
        tipo_caso: trabalhista ou previdenciario (padrão: trabalhista).
    """
    claims = require_module("fap_review")
    with app.app_context():
        return review_petition_handler(texto_peticao, claims["law_firm_id"], tipo_caso)


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
