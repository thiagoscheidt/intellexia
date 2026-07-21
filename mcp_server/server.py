"""
IntellexIA MCP Server
=====================
Servidor MCP com OAuth 2.1 autenticado contra a base de usuários do IntellexIA.

Expõe ferramentas de:
  - Base de conhecimento (RAG)          [módulo knowledge_base]
  - Painel FAP e contestações           [módulo fap_panel]
  - Painel de processos judiciais       [módulo process_panel]
  - Monitoramento de Processos (DJEN)   [módulo communications]
  - Revisor de petições iniciais (stub) [módulo fap_review]

A identidade (user_id, law_firm_id, permissões de módulo) vem do access token
emitido no fluxo OAuth — o usuário autoriza no navegador reusando o login do
sistema, no domínio desta instalação.

Uso:
    uv run python mcp_server/server.py

Conexão no Claude Code:
    claude mcp add --transport http intellexia https://SEU-DOMINIO/mcp
    (depois: /mcp → Authenticate → autorizar no navegador)

Env (o `.env` do projeto é a fonte — importar `main` já o carrega):
    APP_PUBLIC_URL  Domínio desta instalação. **É só isto que precisa ser definido**:
                    o endereço do MCP sai daqui + "/mcp".
    MCP_PUBLIC_URL  Só quando o MCP vive em outro domínio/subdomínio que o app.
    MCP_HOST/MCP_PORT  bind local do uvicorn (default 127.0.0.1:8001)

Ao contrário das telas, aqui o domínio não pode sair do Host da requisição: o
OAuth fixa issuer e resource no start (ver _resolve_public_urls).
"""
from __future__ import annotations

import base64
import logging
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

from mcp_server.identity import get_identity, require_admin, require_module
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
from mcp_server.tools.disputes import (
    list_cats_handler,
    list_employment_links_handler,
    list_payroll_masses_handler,
    list_turnover_rates_handler,
)
from mcp_server.tools.exports import (
    build_download_response,
    export_benefits_excel_handler,
    export_contestacoes_excel_handler,
)
from mcp_server.tools.process_panel import (
    list_processes_handler,
    get_process_detail_handler,
)
from mcp_server.tools.communications import (
    explain_communication_handler,
    get_communication_detail_handler,
    list_communications_handler,
    monitoring_summary_handler,
    process_communications_handler,
)
from mcp_server.tools.petition_reviewer import (
    compare_petition_versions_handler,
    review_petition_handler,
)
from mcp_server.tools.petition_review_read import (
    get_review_detail_handler,
    lawyer_statistics_handler,
    list_review_petitions_handler,
    petition_review_history_handler,
    read_reviewer_manual_handler,
    reference_versions_handler,
    review_audit_log_handler,
)
from mcp_server.tools.utilities import consultar_cnpj_handler
from mcp_server.tools.insights import (
    prazos_e_alertas_handler,
    comparar_vigencias_handler,
    buscar_por_segurado_handler,
)

def _resolve_public_urls() -> tuple[str, str]:
    """Domínio desta instalação, a partir do `.env` (importar `main` já o carregou).

    Ordem: ``MCP_PUBLIC_URL`` → ``APP_PUBLIC_URL`` + ``/mcp`` → domínio de
    desenvolvimento. Basta ``APP_PUBLIC_URL`` no `.env` para configurar tudo.

    Aqui **não** dá para descobrir o domínio pelo Host da requisição, como as telas
    fazem: o OAuth grava o issuer e o resource dentro dos handlers no start, antes
    de existir requisição — e um issuer que mudasse por requisição quebraria os
    clientes que já cachearam a metadata (o erro "resource does not match").
    """
    app_url = (os.environ.get("APP_PUBLIC_URL") or "").strip().rstrip("/")
    mcp_url = (os.environ.get("MCP_PUBLIC_URL") or "").strip().rstrip("/")

    if not mcp_url and app_url:
        mcp_url = f"{app_url}/mcp"

    if not mcp_url:
        from app.utils.urls import FALLBACK_BASE_URL
        mcp_url = f"{FALLBACK_BASE_URL}/mcp"
        logging.getLogger(__name__).warning(
            "APP_PUBLIC_URL/MCP_PUBLIC_URL ausentes no .env: o MCP vai anunciar %s. "
            "Em produção isto está errado — defina APP_PUBLIC_URL no .env com o "
            "domínio desta instalação e reinicie o serviço.", mcp_url,
        )

    if not app_url:
        parsed = urlparse(mcp_url)
        app_url = f"{parsed.scheme}://{parsed.netloc}"

    return mcp_url, app_url


MCP_PUBLIC_URL, APP_PUBLIC_URL = _resolve_public_urls()

auth_provider = IntellexiaOAuthProvider(
    base_url=MCP_PUBLIC_URL,
    app_public_url=APP_PUBLIC_URL,
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
        Dicionário com 'resposta', 'fontes', 'fontes_detalhe' (cada fonte com
        'url_abrir' para o usuário visualizar o documento no navegador — apresente
        como link clicável) e 'perguntas_sugeridas'.
    """
    claims = require_module("knowledge_base")
    with app.app_context():
        return query_knowledge_base_handler(
            pergunta, claims["law_firm_id"], user_id=claims.get("user_id"),
            app_public_url=APP_PUBLIC_URL,
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
        'total_resultados' e 'resultados' (trecho, fonte, página, relevância,
        arquivo e 'url_abrir' para o usuário visualizar o documento no navegador —
        apresente como link clicável).
    """
    claims = require_module("knowledge_base")
    with app.app_context():
        return kb_search_handler(pergunta, claims["law_firm_id"], modo_busca, limite,
                                 app_public_url=APP_PUBLIC_URL)


# ──────────────────────────────────────────────────────────────────────────────
# PAINEL FAP
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def listar_empresas_fap(
    nome: str | None = None,
    cnpj: str | None = None,
    tipo_procuracao: str | None = None,
    limite: int = 100,
    deslocamento: int = 0,
) -> dict:
    """Lista as empresas FAP cadastradas e sincronizadas do escritório.

    Prefira filtrar por nome parcial em vez de listar tudo — a busca aceita
    partes do nome em qualquer ordem (ex: "bradesco" encontra "BANCO BRADESCO S.A.").

    Args:
        nome: Nome ou parte do nome da empresa (palavras em qualquer ordem).
        cnpj: CNPJ ou raiz do CNPJ (aceita formatado; compara pela raiz de 8 dígitos).
        tipo_procuracao: Filtra pelo tipo de procuração (busca parcial).
        limite: Número máximo de registros (padrão 100).
        deslocamento: Pula os N primeiros resultados (paginação). Repasse aqui o
            'proximo_deslocamento' que veio na resposta anterior.

    Returns:
        Dicionário com 'total_encontrado', 'retornados' e 'itens' (id, cnpj — raiz
        de 8 dígitos —, nome, tipo de procuração e última sincronização).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return list_fap_companies_handler(claims["law_firm_id"], nome, cnpj, tipo_procuracao,
                                          limite, deslocamento)


@mcp.tool()
def listar_contestacoes_fap(
    cnpj: str | None = None,
    cnpj_raiz: str | None = None,
    ano_vigencia: int | None = None,
    situacao_codigo: str | None = None,
    instancia_codigo: str | None = None,
    limite: int = 100,
    deslocamento: int = 0,
) -> dict:
    """Lista contestações FAP sincronizadas do portal Dataprev, com total encontrado.

    Args:
        cnpj: CNPJ do estabelecimento (14 dígitos, apenas números).
        cnpj_raiz: Raiz do CNPJ (8 dígitos) para pegar todos os estabelecimentos.
        ano_vigencia: Ano de vigência FAP (ex: 2023).
        situacao_codigo: Código de situação (ex: DEFERIDO, INDEFERIDO).
        instancia_codigo: Código de instância (ex: ADMINISTRATIVO_PRIMEIRA_INSTANCIA).
        limite: Número máximo de registros retornados (padrão 100).
        deslocamento: Pula os N primeiros resultados (paginação). Repasse aqui o
            'proximo_deslocamento' que veio na resposta anterior.

    Returns:
        Dicionário com 'total_encontrado', 'retornados' e 'itens' (cada item com
        identificação, instância, situação, data D.O.U. e se o PDF já foi baixado).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return list_fap_contestacoes_handler(
            claims["law_firm_id"], cnpj, cnpj_raiz, ano_vigencia,
            situacao_codigo, instancia_codigo, limite, deslocamento,
            app_public_url=APP_PUBLIC_URL,
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
    empresa: str | None = None,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    """Lista benefícios previdenciários vinculados a contestações FAP, com total encontrado.

    Para apenas CONTAR benefícios (ex: "quantos benefícios da empresa X?"),
    prefira resumo_fap — responde em uma única chamada, sem listar registros.

    Args:
        empresa: Nome (ou parte do nome) da empresa/empregador — casa nome do
            empregador e as raízes de CNPJ da empresa FAP correspondente.
        cnpj: CNPJ do empregador (aceita formatado, só dígitos ou raiz de 8).
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
        deslocamento: Pula os N primeiros resultados (paginação). Repasse aqui o
            'proximo_deslocamento' que veio na resposta anterior.

    Returns:
        Dicionário com 'total_encontrado', 'retornados' e 'itens' (cada item com
        segurado, empregador, período, tópicos de contestação e status por instância).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return list_fap_benefits_handler(
            claims["law_firm_id"], cnpj, status, tipo_pedido, tipo_beneficio,
            topico_contestacao, segurado, nit, cpf, numero_beneficio, ano_vigencia,
            empresa, limite, deslocamento,
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
def prazos_e_alertas(dias: int = 30) -> dict:
    """Itens do FAP que pedem atenção: contestações transmitidas aguardando
    resultado, decisões recentes (possível janela de recurso) e, se você tiver
    acesso ao Painel de Processos, a distribuição de processos por fase.

    Ideal para "o que preciso olhar hoje/esta semana?".

    Args:
        dias: Janela para considerar uma decisão "recente" (padrão 30).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return prazos_e_alertas_handler(
            claims["law_firm_id"], claims.get("modules") or [], dias
        )


@mcp.tool()
def comparar_vigencias(
    vigencias: list[str],
    empresa: str | None = None,
    cnpj: str | None = None,
) -> dict:
    """Compara resultados de benefícios FAP entre vigências (ex: 2023 vs 2024).

    Mostra, por vigência: total de benefícios, deferidos/indeferidos em 1ª
    instância, total pago em disputa e distribuição por tópico de contestação —
    para ver se a empresa melhorou ou piorou de um ano para o outro.

    Args:
        vigencias: Anos de vigência a comparar, ex: ["2023", "2024"].
        empresa: Nome (ou parte) da empresa (opcional).
        cnpj: CNPJ do empregador (opcional; aceita formatado ou raiz).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return comparar_vigencias_handler(claims["law_firm_id"], vigencias, empresa, cnpj)


@mcp.tool()
def buscar_por_segurado(
    nit: str | None = None,
    cpf: str | None = None,
    nome: str | None = None,
) -> dict:
    """Visão 360º de um segurado: reúne benefícios, CATs e processos judiciais.

    Útil quando chega uma intimação ou consulta sobre uma pessoa específica.
    CATs e processos só entram se você tiver acesso aos respectivos módulos.

    Args:
        nit: NIT do segurado (identificador mais completo para o cruzamento).
        cpf: CPF do segurado (apenas números).
        nome: Nome ou parte do nome do segurado.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return buscar_por_segurado_handler(
            claims["law_firm_id"], claims.get("modules") or [], nit, cpf, nome
        )


@mcp.tool()
def resumo_fap(
    ano_vigencia: int | None = None,
    cnpj: str | None = None,
    empresa: str | None = None,
) -> dict:
    """Resumo estatístico do FAP do escritório: contagens agregadas em uma chamada.

    SEMPRE prefira esta tool para perguntas de contagem/quantidade ("quantos
    benefícios da empresa X?", "quantas contestações deferidas em 2023?") —
    é muito mais rápido do que listar registros. Retorna contestações por ano
    de vigência, situação, instância e empresa; benefícios por tipo, tipo de
    pedido, status de 1ª/2ª instância, tópico e financeiro (total pago).

    Args:
        ano_vigencia: Restringe a um ano de vigência FAP (opcional).
        cnpj: Restringe a um estabelecimento — aceita formatado, só dígitos ou
            raiz de 8 dígitos (opcional).
        empresa: Nome (ou parte do nome) da empresa (opcional) — ex: "bistek".
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return fap_summary_handler(claims["law_firm_id"], ano_vigencia, cnpj, empresa)


try:
    from fastmcp.tools.tool import ToolResult

    from mcp_server.apps.fap_panel import construir_painel, resumo_em_texto
except Exception as exc:  # pragma: no cover - defesa contra dependência 0.x instável
    logging.getLogger(__name__).warning(
        "Painel FAP indisponível (%s) — tool painel_fap não registrada; "
        "resumo_fap segue funcionando.",
        exc,
        exc_info=True,
    )
else:

    @mcp.tool(app=True)
    def painel_fap(
        ano_vigencia: int | None = None,
        cnpj: str | None = None,
        empresa: str | None = None,
    ) -> ToolResult:
        """Painel visual do resumo FAP: cartões e gráficos de barras.

        Use quando o usuário pedir para *ver* o panorama do FAP — um painel,
        gráfico, dashboard ou comparação visual. Para responder uma pergunta
        pontual de contagem em texto, prefira `resumo_fap`.

        Mostra contestações por situação, ano de vigência e empresa; benefícios
        por tópico de contestação e status de 1ª/2ª instância; e cartões com
        totais, valor pago e cobertura de CAT.

        Args:
            ano_vigencia: Restringe a um ano de vigência FAP (opcional).
            cnpj: Restringe a um estabelecimento — aceita formatado, só dígitos
                ou raiz de 8 dígitos (opcional).
            empresa: Nome (ou parte do nome) da empresa (opcional).
        """
        claims = require_module("fap_panel")
        with app.app_context():
            dados = fap_summary_handler(
                claims["law_firm_id"], ano_vigencia, cnpj, empresa
            )
        # fap_summary_handler não devolve `empresa` em `filtros` (só
        # ano_vigencia/cnpj) — sem isto, um painel filtrado por empresa
        # aparece rotulado "sem filtros", como se fosse o escritório inteiro.
        dados["filtros"]["empresa"] = empresa
        return ToolResult(
            content=resumo_em_texto(dados),
            structured_content=construir_painel(dados),
        )


@mcp.tool()
def alteracoes_recentes_fap(
    cnpj: str | None = None,
    ano_vigencia: int | None = None,
    dias: int = 7,
    limite: int = 100,
    deslocamento: int = 0,
) -> dict:
    """Alterações detectadas nas sincronizações com o portal FAP Web.

    Mostra o que mudou nas contestações (campos, valores anteriores e novos) —
    útil para "o que mudou desde ontem/na última semana?".

    Args:
        cnpj: Filtra por estabelecimento (opcional).
        ano_vigencia: Filtra por ano de vigência (opcional).
        dias: Janela de tempo em dias (padrão 7; use 0 para todo o histórico).
        limite: Número máximo de registros (padrão 100).
        deslocamento: Pula os N primeiros resultados (paginação). Repasse aqui o
            'proximo_deslocamento' que veio na resposta anterior.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return fap_changes_handler(claims["law_firm_id"], cnpj, ano_vigencia, dias, limite,
                                  deslocamento)


@mcp.tool()
def listar_procuracoes_fap(
    cnpj_raiz: str | None = None,
    situacao_codigo: str | None = None,
    limite: int = 100,
    deslocamento: int = 0,
) -> dict:
    """Lista procurações eletrônicas sincronizadas do portal FAP Web.

    Args:
        cnpj_raiz: Raiz do CNPJ da empresa outorgante (8 dígitos, opcional).
        situacao_codigo: Código de situação da procuração (opcional).
        limite: Número máximo de registros (padrão 100).
        deslocamento: Pula os N primeiros resultados (paginação). Repasse aqui o
            'proximo_deslocamento' que veio na resposta anterior.

    Returns:
        Dicionário com 'total_encontrado', 'retornados' e 'itens' (protocolo, tipo,
        situação, vigência e empresa outorgante).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return list_fap_procuracoes_handler(claims["law_firm_id"], cnpj_raiz, situacao_codigo,
                                            limite, deslocamento)


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
        return get_contestacao_detail_handler(contestacao_id, claims["law_firm_id"],
                                              app_public_url=APP_PUBLIC_URL)


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
    deslocamento: int = 0,
) -> dict:
    """Lista CATs (Comunicações de Acidente de Trabalho) das contestações FAP.

    Args:
        vigencia: Ano de vigência FAP (ex: "2023").
        cnpj: CNPJ do empregador (apenas números).
        nit: NIT do segurado.
        numero_cat: Número da CAT (busca exata).
        limite: Número máximo de registros (padrão 50).
        deslocamento: Pula os N primeiros resultados (paginação). Repasse aqui o
            'proximo_deslocamento' que veio na resposta anterior.

    Returns:
        Dicionário com 'total_encontrado', 'retornados' e 'itens' (dados da CAT,
        segurado, datas e status/justificativas por instância).
    """
    claims = require_module("disputes_center")
    with app.app_context():
        return list_cats_handler(claims["law_firm_id"], vigencia, cnpj, nit, numero_cat,
                                 limite, deslocamento)


@mcp.tool()
def listar_massas_salariais_fap(
    vigencia: str | None = None,
    cnpj: str | None = None,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    """Lista massas salariais (folha de pagamento) contestadas no FAP, por competência.

    Inclui remuneração total, valores pleiteados e status/justificativas por instância.

    Args:
        vigencia: Ano de vigência FAP (ex: "2023").
        cnpj: CNPJ do empregador (apenas números).
        limite: Número máximo de registros (padrão 50).
        deslocamento: Pula os N primeiros resultados (paginação). Repasse aqui o
            'proximo_deslocamento' que veio na resposta anterior.
    """
    claims = require_module("disputes_center")
    with app.app_context():
        return list_payroll_masses_handler(claims["law_firm_id"], vigencia, cnpj, limite,
                                           deslocamento)


@mcp.tool()
def listar_vinculos_fap(
    vigencia: str | None = None,
    cnpj: str | None = None,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    """Lista vínculos empregatícios contestados no FAP, por competência.

    Inclui quantidade de vínculos, quantidades pleiteadas e status por instância.

    Args:
        vigencia: Ano de vigência FAP (ex: "2023").
        cnpj: CNPJ do empregador (apenas números).
        limite: Número máximo de registros (padrão 50).
        deslocamento: Pula os N primeiros resultados (paginação). Repasse aqui o
            'proximo_deslocamento' que veio na resposta anterior.
    """
    claims = require_module("disputes_center")
    with app.app_context():
        return list_employment_links_handler(claims["law_firm_id"], vigencia, cnpj, limite,
                                             deslocamento)


@mcp.tool()
def listar_rotatividade_fap(
    vigencia: str | None = None,
    cnpj: str | None = None,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    """Lista taxas de rotatividade contestadas no FAP, por ano.

    Inclui taxa, admissões, rescisões, vínculos iniciais, valores pleiteados e
    status por instância.

    Args:
        vigencia: Ano de vigência FAP (ex: "2023").
        cnpj: CNPJ do empregador (apenas números).
        limite: Número máximo de registros (padrão 50).
        deslocamento: Pula os N primeiros resultados (paginação). Repasse aqui o
            'proximo_deslocamento' que veio na resposta anterior.
    """
    claims = require_module("disputes_center")
    with app.app_context():
        return list_turnover_rates_handler(claims["law_firm_id"], vigencia, cnpj, limite,
                                           deslocamento)


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
    empresa: str | None = None,
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
            numero_beneficio=numero_beneficio, ano_vigencia=ano_vigencia, empresa=empresa,
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
    deslocamento: int = 0,
) -> dict:
    """Lista processos judiciais do escritório, com fase atual de cada um.

    Args:
        status: ativo, suspenso, encerrado ou aguardando (opcional).
        numero_processo: Número CNJ (busca parcial, opcional).
        limite: Número máximo de registros (padrão 50).
        deslocamento: Pula os N primeiros resultados (paginação). Repasse aqui o
            'proximo_deslocamento' que veio na resposta anterior.

    Returns:
        Dicionário com 'total_encontrado', 'retornados' e 'itens' (número, título,
        tribunal, juiz, partes, valor da causa, fase atual e qtd. de benefícios).
    """
    claims = require_module("process_panel")
    with app.app_context():
        return list_processes_handler(claims["law_firm_id"], status, numero_processo, limite,
                                      deslocamento)


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
# MONITORAMENTO DE PROCESSOS (comunicações do DJEN)
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def listar_comunicacoes(
    tribunal: str | None = None,
    tipo: str | None = None,
    fonte: str | None = None,
    advogado_id: int | None = None,
    numero_processo: str | None = None,
    somente_nao_lidas: bool = False,
    data_de: str | None = None,
    data_ate: str | None = None,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    """Lista comunicações processuais do Monitoramento de Processos (radar DJEN).

    Cada item traz data, tribunal, tipo, fonte, processo, órgão, advogado do
    escritório, se está lida, se já tem explicação da IA e uma prévia do teor.

    Args:
        tribunal: Sigla do tribunal (ex.: TRF4, TRT3) — opcional.
        tipo: Tipo de comunicação (ex.: Intimação) — opcional.
        fonte: Fonte da informação (hoje: comunica_pje) — opcional.
        advogado_id: Restringe às comunicações capturadas pela OAB desse advogado.
        numero_processo: Número CNJ (aceita máscara ou só dígitos) — opcional.
        somente_nao_lidas: True para ver apenas o que aguarda leitura.
        data_de: Data inicial de disponibilização (YYYY-MM-DD) — opcional.
        data_ate: Data final de disponibilização (YYYY-MM-DD) — opcional.
        limite: Número máximo de registros (padrão 50).
        deslocamento: Pula os N primeiros (paginação) — repasse o
            'proximo_deslocamento' da resposta anterior.

    Returns:
        Envelope paginado com 'total_encontrado', 'tem_mais' e 'itens'.
    """
    claims = require_module("communications")
    with app.app_context():
        return list_communications_handler(
            claims["law_firm_id"], tribunal, tipo, fonte, advogado_id,
            numero_processo, somente_nao_lidas, data_de, data_ate,
            limite, deslocamento,
        )


@mcp.tool()
def detalhar_comunicacao(comunicacao_id: int) -> dict:
    """Detalhe completo de uma comunicação processual, com o inteiro teor.

    Inclui teor limpo (sem HTML), destinatários e polos, advogados intimados,
    link do documento original no PJe e — quando já gerada — a explicação da IA
    em 'explicacao_ia' (sem custo adicional). Consultar aqui NÃO marca como lida.

    Args:
        comunicacao_id: ID interno da comunicação (obtido em listar_comunicacoes).
    """
    claims = require_module("communications")
    with app.app_context():
        return get_communication_detail_handler(comunicacao_id, claims["law_firm_id"])


@mcp.tool()
def explicar_comunicacao(comunicacao_id: int) -> dict:
    """Explica uma comunicação em linguagem clara: prazo, ação exigida e urgência.

    Retorna resumo, ação requerida (exige_acao / acao_facultativa / apenas_ciencia),
    prazo com data-limite estimada, datas-chave, papel do escritório no processo,
    urgência e glossário de termos. A explicação é gerada por IA **uma única vez**
    por comunicação e fica em cache — chamadas repetidas são instantâneas e sem
    custo. É apoio à triagem: prazos devem ser conferidos no processo oficial.

    Args:
        comunicacao_id: ID interno da comunicação (obtido em listar_comunicacoes).
    """
    claims = require_module("communications")
    with app.app_context():
        return explain_communication_handler(
            comunicacao_id, claims["law_firm_id"], user_id=claims.get("user_id")
        )


@mcp.tool()
def comunicacoes_do_processo(
    numero_processo: str,
    buscar_na_fonte: bool = False,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    """Linha do tempo de comunicações de um processo, pelo número CNJ.

    Busca na base do escritório (ordem cronológica) e informa se o processo está
    no Painel de Processos. Com buscar_na_fonte=True, consulta também a API
    pública do DJEN ao vivo — útil para processos fora do radar; esses resultados
    não são gravados na base.

    Args:
        numero_processo: Número CNJ, com ou sem máscara (busca local aceita
            parcial; a busca ao vivo exige os 20 dígitos completos).
        buscar_na_fonte: True para consultar também o DJEN ao vivo (mais lento;
            sujeito ao rate limit da API pública).
        limite: Número máximo de registros da base local (padrão 50).
        deslocamento: Paginação da base local — repasse o 'proximo_deslocamento'.
    """
    claims = require_module("communications")
    with app.app_context():
        return process_communications_handler(
            claims["law_firm_id"], numero_processo, buscar_na_fonte,
            limite, deslocamento,
        )


@mcp.tool()
def resumo_monitoramento(dias: int = 7) -> dict:
    """Visão executiva do Monitoramento de Processos numa chamada só.

    Total de comunicações, quantas aguardam leitura, distribuição do período por
    tribunal/tipo/fonte, advogados monitorados e os que estão fora do radar
    (OAB/UF incompleta). Use antes de listar: para contagens, esta tool responde
    sem paginar.

    Args:
        dias: Janela do recorte por período (padrão 7, máx. 365).
    """
    claims = require_module("communications")
    with app.app_context():
        return monitoring_summary_handler(claims["law_firm_id"], dias)


# ──────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def consultar_cnpj(cnpj: str) -> dict:
    """Consulta dados cadastrais públicos de um CNPJ (Receita Federal via OpenCNPJ).

    Retorna razão social, situação cadastral, endereço, CNAE, sócios e se o
    estabelecimento é matriz ou filial. Cada filial tem CNPJ próprio (mesma
    raiz de 8 dígitos, sufixo diferente) — consulte o CNPJ completo da filial.

    Args:
        cnpj: CNPJ completo de 14 dígitos (aceita formatado ou só números).
    """
    get_identity()  # dados públicos — exige apenas usuário autenticado
    with app.app_context():
        return consultar_cnpj_handler(cnpj)


# ──────────────────────────────────────────────────────────────────────────────
# REVISOR DE PETIÇÕES INICIAIS
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def revisar_peticao_inicial(
    texto_peticao: str,
    tipo_caso: str = "trabalhista",
    identificador_documento: str | None = None,
    titulo: str = "",
) -> dict:
    """Revisa uma petição FAP com o agente revisor oficial do escritório.

    Usa os mesmos prompts, manual FAP e casos de referência configurados no
    módulo Revisor de Petições. Retorna achados (findings) com severidade,
    documentos faltantes, teses identificadas e resumo executivo. A revisão pode
    levar ~1 minuto em petições longas.

    Informando 'identificador_documento', a revisão é **registrada no módulo**
    como uma revisão da petição (histórico, custo e status do fluxo) — igual à
    feita pela tela. Sem ele, a revisão é descartada depois da resposta.

    Args:
        texto_peticao: Texto completo da petição (mínimo ~200 caracteres).
        tipo_caso: trabalhista ou previdenciario (padrão: trabalhista).
        identificador_documento: Identificador da petição no escritório (ex.: "FAP-2024-013").
            Se a petição já existir com esse identificador, entra como nova revisão dela.
        titulo: Título da petição, usado só quando ela é criada agora.

    Returns:
        Achados e resumo da revisão. 'registrado_no_sistema' indica se ficou salva;
        quando true, traz 'peticao_id', 'revisao_id' e 'numero_revisao'.
    """
    claims = require_module("fap_review")
    with app.app_context():
        return review_petition_handler(
            texto_peticao, claims["law_firm_id"], tipo_caso, user_id=claims.get("user_id"),
            identificador_documento=identificador_documento, titulo=titulo,
        )


@mcp.tool()
def listar_peticoes_revisao(
    status: str | None = None,
    identificador: str | None = None,
    titulo: str | None = None,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    """Lista as petições do módulo Revisor com o estágio de cada uma.

    Responde "o que está aguardando ajuste?", "o que já está pronto para protocolo?".

    Args:
        status: Filtra pelo estágio: new (nova), in_review (em revisão),
            awaiting_adjustments (aguardando ajustes), ready_for_filing (aprovada
            pelo revisor), filed (processo iniciado), archived (arquivada).
        identificador: Identificador do documento no escritório (busca parcial).
        titulo: Título ou parte do título (palavras em qualquer ordem).
        limite: Número máximo de registros (padrão 50).
        deslocamento: Pula os N primeiros resultados (paginação). Repasse aqui o
            'proximo_deslocamento' que veio na resposta anterior.

    Returns:
        Dicionário com 'total_encontrado', 'retornados', 'tem_mais' e 'itens'
        (peticao_id, identificador, título, status, nº de revisões, última revisão).
    """
    claims = require_module("fap_review")
    with app.app_context():
        return list_review_petitions_handler(
            claims["law_firm_id"], status, identificador, titulo, limite, deslocamento
        )


@mcp.tool()
def detalhar_revisao(revisao_id: int) -> dict:
    """Achados completos de uma revisão já feita (pela tela ou pelo Claude).

    Use isto em vez de revisar de novo: a revisão já existe, custa ~1 minuto de IA
    para refazer e o resultado ficaria fora do histórico. Pegue o 'revisao_id' em
    listar_peticoes_revisao ('ultima_revisao_id') ou em historico_revisoes_peticao.

    Args:
        revisao_id: Id da revisão (execução) no módulo Revisor.

    Returns:
        Achados com gravidade, localização, correção sugerida e referência do manual;
        documentos faltantes, teses identificadas, resumo executivo e custo.
    """
    claims = require_module("fap_review")
    with app.app_context():
        return get_review_detail_handler(claims["law_firm_id"], revisao_id)


@mcp.tool()
def historico_revisoes_peticao(
    peticao_id: int | None = None,
    identificador: str | None = None,
) -> dict:
    """Evolução das revisões de uma petição: o que foi resolvido e o que reincidiu.

    Útil para "a segunda versão corrigiu o que o revisor apontou?".

    Args:
        peticao_id: Id da petição no módulo Revisor.
        identificador: Alternativa ao id — identificador do documento no escritório.

    Returns:
        Lista das revisões em ordem, cada uma com total de achados por gravidade e,
        em relação à revisão anterior: 'novos', 'reincidentes' e
        'resolvidos_desde_a_anterior'.
    """
    claims = require_module("fap_review")
    with app.app_context():
        return petition_review_history_handler(claims["law_firm_id"], peticao_id, identificador)


@mcp.tool()
def comparar_versoes_peticao(
    texto_original: str,
    texto_revisado: str,
    identificador_documento: str | None = None,
    titulo: str = "",
) -> dict:
    """Revisa duas versões de uma petição em conjunto (original × revisada).

    Use quando existirem duas versões e a pergunta for "a v2 corrigiu o que o
    revisor apontou?": o agente oficial analisa as mudanças, em vez de comparar
    os textos por conta própria. Para uma versão só, use revisar_peticao_inicial.
    Leva ~1 minuto.

    Args:
        texto_original: Texto completo da versão anterior (mínimo ~200 caracteres).
        texto_revisado: Texto completo da versão nova (mínimo ~200 caracteres).
        identificador_documento: Identificador da petição no escritório. Informando,
            a comparação é registrada como uma revisão da petição (histórico e custo).
        titulo: Título da petição, usado só quando ela é criada agora.

    Returns:
        Achados, mudanças entre as versões e resumo executivo. 'registrado_no_sistema'
        indica se ficou salva.
    """
    claims = require_module("fap_review")
    with app.app_context():
        return compare_petition_versions_handler(
            texto_original, texto_revisado, claims["law_firm_id"],
            user_id=claims.get("user_id"),
            identificador_documento=identificador_documento, titulo=titulo,
        )


@mcp.tool()
def ler_manual_revisor(
    tipo: str = "manual_fap",
    secao: str | None = None,
    termo: str | None = None,
) -> dict:
    """Lê a régua que o revisor usa: o manual FAP do escritório e seus anexos.

    Use para explicar um achado citando o texto real: os achados trazem
    'referencia_manual' (ex.: "2.1") e é aqui que se abre essa seção. Prefira
    filtrar por 'secao' ou 'termo' — manuais longos não cabem inteiros na resposta.

    Args:
        tipo: manual_fap (padrão), casos_referencia ou project_instructions.
        secao: Título (ou parte) da seção desejada.
        termo: Busca por um termo no título ou no corpo das seções.

    Returns:
        Conteúdo pedido e a versão ativa. Se o escritório não tiver a referência
        cadastrada, retorna 'configurado: false' com o aviso — nesse caso as
        revisões estão rodando sem essa régua.
    """
    claims = require_module("fap_review")
    with app.app_context():
        return read_reviewer_manual_handler(claims["law_firm_id"], tipo, secao, termo)


@mcp.tool()
def versoes_manual_revisor(tipo: str | None = None) -> dict:
    """Histórico de versões do manual e das referências do revisor.

    O treinamento do módulo pode reescrever o manual e ativar uma versão nova —
    isto mostra o que existe, qual está ativa, quem criou e quando.

    Args:
        tipo: Filtra por manual_fap, casos_referencia ou project_instructions.
    """
    claims = require_module("fap_review")
    with app.app_context():
        return reference_versions_handler(claims["law_firm_id"], tipo)


@mcp.tool()
def auditoria_revisor(
    peticao_id: int | None = None,
    acao: str | None = None,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    """Trilha de auditoria do módulo Revisor: quem fez o quê e quando.

    Args:
        peticao_id: Restringe aos eventos de uma petição.
        acao: Filtra pelo tipo de ação (busca parcial), ex.: "status", "revision".
        limite: Número máximo de registros (padrão 50).
        deslocamento: Pula os N primeiros resultados (paginação). Repasse aqui o
            'proximo_deslocamento' que veio na resposta anterior.
    """
    claims = require_module("fap_review")
    with app.app_context():
        return review_audit_log_handler(claims["law_firm_id"], peticao_id, acao,
                                        limite, deslocamento)


@mcp.tool()
def estatisticas_revisor() -> dict:
    """Score, retrabalho e reincidência por advogado — os mesmos números da tela.

    **Restrito a administradores**, como a tela correspondente no sistema: são
    dados de desempenho individual.

    Returns:
        Panorama do escritório e, por advogado, score, revisões, achados por
        gravidade, taxa de retrabalho e de reincidência.
    """
    claims = require_admin("fap_review")
    with app.app_context():
        return lawyer_statistics_handler(claims["law_firm_id"])


# ──────────────────────────────────────────────────────────────────────────────
# PROMPTS (comandos prontos que aparecem no cliente MCP)
# ──────────────────────────────────────────────────────────────────────────────


@mcp.prompt(name="relatorio_semanal_fap", description="Relatório semanal do FAP: resumo geral + o que mudou na semana")
def relatorio_semanal_fap() -> str:
    return (
        "Monte um relatório semanal do FAP do escritório em português, seguindo estes passos:\n"
        "1. Chame resumo_fap (sem filtros) para o panorama geral: contestações por vigência, "
        "situação e instância; benefícios por tipo, status e tópico.\n"
        "2. Chame alteracoes_recentes_fap com dias=7 para o que mudou na última semana.\n"
        "3. Estruture o relatório com: **Panorama geral** (números-chave e destaques), "
        "**Mudanças da semana** (o que mudou, por empresa, com antes/depois relevante) e "
        "**Pontos de atenção** (situações que merecem ação, ex.: indeferimentos novos, "
        "contestações transmitidas aguardando resultado).\n"
        "Seja objetivo: números primeiro, interpretação depois. Formate em Markdown."
    )


@mcp.prompt(name="analise_empresa", description="Análise completa de uma empresa no FAP: benefícios, contestações e financeiro")
def analise_empresa(nome_empresa: str) -> str:
    return (
        f"Faça uma análise completa da empresa \"{nome_empresa}\" no FAP, em português:\n"
        "1. Chame resumo_fap com empresa=\"" + nome_empresa + "\" para os agregados "
        "(benefícios por tipo/status/tópico, financeiro, contestações).\n"
        "2. Chame listar_beneficios_fap com empresa e limite=20 para exemplos concretos.\n"
        "3. Se houver contestações, chame listar_contestacoes_fap para as situações e PDFs.\n"
        "4. Estruture: **Visão geral** (quem é, volumes), **Benefícios em contestação** "
        "(distribuição por tipo e tópico, casos relevantes), **Resultados** (deferidos vs. "
        "indeferidos por instância), **Impacto financeiro** (total pago em disputa) e "
        "**Recomendações** (onde concentrar esforço).\n"
        "Use tabelas Markdown para os números e cite benefícios específicos como exemplos."
    )


@mcp.prompt(name="agenda_do_dia", description="O que precisa de atenção hoje: prazos, decisões recentes e processos")
def agenda_do_dia() -> str:
    return (
        "Monte a agenda de atenção do escritório em português:\n"
        "1. Chame prazos_e_alertas (dias=15) para contestações aguardando resultado, "
        "decisões recentes e processos por fase.\n"
        "2. Organize por prioridade: **Ação urgente** (decisões recentes que podem ter "
        "prazo de recurso), **Acompanhar** (contestações transmitidas aguardando D.O.U., "
        "as mais antigas primeiro) e **Panorama** (processos por fase).\n"
        "Seja direto e acionável: diga o que fazer, não só o que existe."
    )


@mcp.prompt(name="minuta_recurso", description="Esqueleto de recurso para um benefício indeferido em 1ª instância")
def minuta_recurso(numero_beneficio: str) -> str:
    return (
        f"Prepare o esqueleto de um recurso administrativo para o benefício "
        f"{numero_beneficio}, em português:\n"
        "1. Chame listar_beneficios_fap com numero_beneficio=\"" + numero_beneficio + "\" e "
        "depois detalhar_beneficio para obter o parecer da 1ª instância, os tópicos de "
        "contestação e os dados do segurado/empregador.\n"
        "2. Chame pesquisar_base_conhecimento com os tópicos de contestação e o número do "
        "benefício para reunir fundamentos e precedentes já usados pelo escritório (cite as "
        "fontes com o link para abrir).\n"
        "3. Monte a minuta com: **Síntese dos fatos**, **Do indeferimento em 1ª instância** "
        "(resumo do parecer da Receita), **Das razões do recurso** (rebatendo cada ponto, "
        "amparado nos tópicos e fundamentos encontrados), **Dos pedidos** e **Documentos a "
        "anexar**.\n"
        "IMPORTANTE: é um rascunho de apoio — sinalize claramente onde o advogado deve "
        "revisar, complementar ou confirmar informação. Não invente fundamentos que não "
        "vieram das fontes."
    )


@mcp.prompt(name="resumir_decisao", description="Resume uma decisão/parecer FAP: resultado, fundamentação e efeito no FAP")
def resumir_decisao(texto_decisao: str) -> str:
    return (
        "Analise o texto da decisão/parecer FAP abaixo e resuma em português, de forma "
        "objetiva, extraindo:\n"
        "- **Resultado** (deferido / indeferido / parcial) e a instância;\n"
        "- **Benefício(s) e empresa** mencionados;\n"
        "- **Fundamentação** da decisão (por que decidiram assim), em 2–4 pontos;\n"
        "- **Efeito no FAP** (implica recálculo? exclui/mantém a ocorrência?);\n"
        "- **Próximos passos** sugeridos (cabe recurso? qual prazo/instância?).\n"
        "Se algum item não estiver claro no texto, diga explicitamente que não consta.\n\n"
        "--- TEXTO DA DECISÃO ---\n" + texto_decisao
    )


@mcp.prompt(name="email_cliente", description="Redige um e-mail ao cliente explicando o resultado do FAP em linguagem simples")
def email_cliente(nome_empresa: str, vigencia: str) -> str:
    return (
        f"Redija um e-mail para o cliente \"{nome_empresa}\" explicando o resultado do FAP "
        f"da vigência {vigencia}, em português claro e sem juridiquês:\n"
        "1. Chame resumo_fap com empresa=\"" + nome_empresa + "\" e ano_vigencia=" + vigencia + " "
        "para os números reais.\n"
        "2. Escreva um e-mail profissional e acolhedor com: saudação, um parágrafo com o "
        "resultado geral (quantos benefícios contestados, quantos deferidos/indeferidos, "
        "impacto), o que isso significa na prática para a empresa, os próximos passos do "
        "escritório e uma despedida cordial.\n"
        "Evite termos técnicos (ou explique-os em uma frase). Use os números que vieram do "
        "sistema, não invente. Deixe [espaços] para o remetente personalizar antes de enviar."
    )


@mcp.prompt(name="analise_risco_empresa", description="Onde concentrar esforço: tópicos com mais chance de deferimento para uma empresa")
def analise_risco_empresa(nome_empresa: str) -> str:
    return (
        f"Faça uma análise estratégica de risco/oportunidade da empresa \"{nome_empresa}\" "
        "no FAP, em português:\n"
        "1. Chame resumo_fap com empresa para a distribuição por tópico e status.\n"
        "2. Se houver mais de uma vigência, chame comparar_vigencias para ver a evolução "
        "dos resultados.\n"
        "3. Cruze os dados: para cada tópico de contestação, estime a **taxa de êxito** "
        "(deferidos / total decididos) com base no histórico do escritório.\n"
        "4. Entregue: **Tópicos mais promissores** (maior taxa de deferimento — priorizar), "
        "**Tópicos de baixo retorno** (muito indeferimento — repensar a tese), **Evolução** "
        "(melhorou ou piorou entre vigências) e **Recomendação** (onde concentrar esforço no "
        "próximo ciclo).\n"
        "Baseie tudo nos números reais retornados; deixe claro quando a amostra for pequena "
        "demais para conclusão firme."
    )


@mcp.prompt(name="corrigir_peticao", description="Pega uma revisão já feita e devolve os trechos reescritos, achado a achado")
def corrigir_peticao(identificador_documento: str) -> str:
    return (
        f"Ajude a corrigir a petição \"{identificador_documento}\" a partir da revisão que o "
        "escritório já fez — não refaça a revisão:\n"
        f"1. Chame historico_revisoes_peticao com identificador=\"{identificador_documento}\" "
        "para achar a revisão mais recente (e ver o que já reincidiu).\n"
        "2. Chame detalhar_revisao com o 'revisao_id' dela para ler os achados.\n"
        "3. Para cada achado, na ordem CRÍTICO → MODERADO → FORMAL, apresente: o **problema** "
        "(descrição e localização na petição), o **texto sugerido** pronto para colar e a "
        "**referência do manual** que sustenta a correção.\n"
        "4. Liste à parte os **documentos faltantes**, porque não se resolvem reescrevendo texto.\n"
        "Regras: reescreva apenas o que o achado aponta, preservando o estilo da peça; não "
        "invente fatos, número de benefício, data ou tese que não estejam na revisão; onde "
        "faltar informação, deixe [colchetes] indicando o que o advogado precisa completar."
    )


@mcp.prompt(name="pronto_para_protocolo", description="Checklist objetivo: a petição pode ser protocolada?")
def pronto_para_protocolo(identificador_documento: str) -> str:
    return (
        f"Avalie se a petição \"{identificador_documento}\" pode ser protocolada:\n"
        f"1. Chame historico_revisoes_peticao com identificador=\"{identificador_documento}\".\n"
        "2. Chame detalhar_revisao na revisão mais recente.\n"
        "3. Responda começando por um veredito claro — **PODE PROTOCOLAR** ou "
        "**NÃO PODE AINDA** — e só depois a justificativa.\n"
        "Critérios: qualquer achado CRÍTICO em aberto ou documento obrigatório faltante "
        "impede o protocolo; achados FORMAIS não impedem, mas liste-os como ressalva.\n"
        "Mostre também: quantas revisões a peça já teve, se algum achado **reincidiu** entre "
        "elas (sinal de que a correção não pegou) e qual o status atual no fluxo.\n"
        "Se a revisão mais recente não estiver concluída, diga isso em vez de opinar."
    )


@mcp.prompt(name="devolutiva_ao_advogado", description="Transforma os achados da revisão em uma devolutiva construtiva")
def devolutiva_ao_advogado(identificador_documento: str) -> str:
    return (
        f"Escreva a devolutiva para quem redigiu a petição \"{identificador_documento}\":\n"
        f"1. Chame historico_revisoes_peticao com identificador=\"{identificador_documento}\" e "
        "detalhar_revisao na revisão mais recente.\n"
        "2. Redija uma mensagem em português, profissional e construtiva, com: um parágrafo de "
        "abertura com o balanço geral, **o que precisa ser ajustado** (agrupado por gravidade, "
        "explicando o porquê e citando a seção do manual), **documentos a anexar** e um "
        "fechamento com os próximos passos.\n"
        "Tom: colega ajudando colega — aponte o que está errado com clareza, sem rispidez, e "
        "reconheça o que está correto quando houver. Se algum achado **reincidiu** de uma "
        "revisão anterior, diga isso explicitamente, pois é o ponto que mais gera retrabalho.\n"
        "Não invente achado que não esteja na revisão nem atribua culpa a pessoas."
    )


@mcp.prompt(name="ficha_empresa", description="Ficha cadastral de uma empresa a partir do CNPJ (dados públicos da Receita)")
def ficha_empresa(cnpj: str) -> str:
    return (
        f"Monte a ficha cadastral da empresa de CNPJ {cnpj}:\n"
        f"1. Chame consultar_cnpj com cnpj=\"{cnpj}\".\n"
        "2. Apresente, em português e bem organizado: **razão social** e nome fantasia, "
        "**situação cadastral**, início de atividade, porte, natureza jurídica, "
        "**endereço completo**, e-mail, e um resumo do **quadro societário** (quantos "
        "sócios e quem são os administradores).\n"
        "Regras de leitura, que valem mais que a formatação:\n"
        "- Se `tipo_estabelecimento` for **Filial**, diga isso logo no início e avise que o "
        "quadro societário é o da matriz — não apresente os dados como se fossem da empresa "
        "inteira. Cada filial tem CNPJ próprio.\n"
        "- Se `qsa` vier vazio, escreva **\"não há sócios registrados\"** de forma explícita "
        "(é o normal em MEI e empresa individual). Não omita em silêncio, que se confunde com "
        "falha de consulta.\n"
        "- Se a resposta trouxer a chave `erro`, relate a falha com clareza (e o "
        "`status_code`, se houver) e **não invente** nenhum dado.\n"
        "Use apenas o que a tool devolveu; campo ausente é campo não informado, não é zero."
    )


@mcp.prompt(name="socios_empresa", description="Quadro societário de uma empresa a partir do CNPJ (dados públicos da Receita)")
def socios_empresa(cnpj: str) -> str:
    return (
        f"Liste o quadro societário da empresa de CNPJ {cnpj}:\n"
        f"1. Chame consultar_cnpj com cnpj=\"{cnpj}\".\n"
        "2. Identifique a empresa em uma linha (razão social e situação cadastral) e, em "
        "seguida, apresente **apenas os sócios** em tabela: nome, CPF/CNPJ, qualificação e "
        "identificador. Informe o total de sócios.\n"
        "Regras de leitura, que valem mais que a formatação:\n"
        "- Se `qsa` vier vazio, responda que **não há sócios registrados** para este CNPJ — "
        "é o esperado em MEI e empresa individual — e não tente deduzir sócios de outro campo.\n"
        "- Se `tipo_estabelecimento` for **Filial**, avise que o quadro societário é o da "
        "matriz, não da filial consultada.\n"
        "- Se a resposta trouxer a chave `erro`, relate a falha com clareza (e o "
        "`status_code`, se houver) e **não invente** sócios.\n"
        "Não faça juízo sobre as pessoas listadas nem cruze com outras bases: são dados "
        "cadastrais públicos, apresentados como estão."
    )


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
