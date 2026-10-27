"""
IntellexIA MCP Server
=====================
Servidor MCP com OAuth 2.1 autenticado contra a base de usuários do IntellexIA.

Expõe ferramentas de:
  - Base de conhecimento (RAG)          [módulo knowledge_base]
  - Painel FAP e contestações           [módulo fap_panel]
  - Painel de processos judiciais       [módulo process_panel]
  - Base de Jurisprudência              [módulo process_panel]
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
from mcp_server.usage_log import UsoMcpMiddleware
from mcp_server.prompt_library import BibliotecaPromptsMiddleware
from mcp_server.tools.knowledge import kb_search_handler, query_knowledge_base_handler, read_kb_file_handler
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
    revelar_nome_segurado_handler,
    consultar_cpf_handler,
)
from mcp_server.tools.fap_calculo import (
    listar_beneficios_calculo_fap_handler,
    resumo_beneficios_calculo_fap_handler,
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
from mcp_server.tools.api_tokens import (
    criar_token_api_handler,
    documentacao_api_handler,
    minha_api_handler,
    revogar_token_api_handler,
)
from mcp_server.tools.prompt_library import (
    biblioteca_prompts_handler,
    salvar_prompt_handler,
    usar_prompt_handler,
)
from mcp_server.tools.numero_processo import search_by_process_number_handler
from mcp_server.tools.jurisprudence import (
    decision_detail_handler,
    export_jurisprudence_excel_handler,
    jurisprudence_filter_values_handler,
    jurisprudence_overview_handler,
    search_jurisprudence_handler,
    similar_decisions_handler,
)
from mcp_server.tools.dou import (
    alert_detail_handler as dou_alert_detail_handler,
    dou_filter_values_handler,
    edition_summary_handler as dou_edition_summary_handler,
    firm_digest_handler as dou_firm_digest_handler,
    get_dou_article_handler,
    latest_editions_handler as dou_latest_editions_handler,
    list_alerts_handler as dou_list_alerts_handler,
    rules_handler as dou_rules_handler,
    search_dou_handler,
    test_term_handler as dou_test_term_handler,
)
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
# Uso por usuário (ferramenta, dia, erros, tempo) para a tela de Atividade de Usuários.
mcp.add_middleware(UsoMcpMiddleware(app))
# Prompts da Biblioteca de cada usuário como comandos prontos (depois do uso, que os conta).
mcp.add_middleware(BibliotecaPromptsMiddleware(app))


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
        como link clicável — e, quando houver, 'url_original' com o documento
        original no Drive, ex.: o PDF protocolado) e 'perguntas_sugeridas'. Para ler uma fonte inteira,
        use ler_arquivo_base_conhecimento com o 'file_id' da fonte.
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
        apresente como link clicável —, mais 'url_original' quando o arquivo é a
        conversão de um original no Drive, ex.: o PDF protocolado). O trecho vem cortado: quando precisar do
        documento inteiro (ex.: um resumo em .md), chame ler_arquivo_base_conhecimento
        com o 'arquivo.id' do resultado.
    """
    claims = require_module("knowledge_base")
    with app.app_context():
        return kb_search_handler(pergunta, claims["law_firm_id"], modo_busca, limite,
                                 app_public_url=APP_PUBLIC_URL)


@mcp.tool()
def ler_arquivo_base_conhecimento(arquivo_id: int, deslocamento: int = 0) -> dict:
    """Lê o conteúdo COMPLETO de um arquivo da base de conhecimento.

    Use depois de pesquisar_base_conhecimento (ou consultar_base_conhecimento),
    quando os trechos não bastarem e o documento inteiro importar — típico de
    resumos e notas em Markdown (.md), que já são curtos e perdem o sentido
    cortados. Markdown e .txt vêm do arquivo original, sem conversão; PDF e DOCX
    vêm remontados dos trechos indexados, com marcas [Página N].

    Documento grande vem em partes de até 40 mil caracteres: se 'tem_mais' for
    true, chame de novo com deslocamento='proximo_deslocamento'. Para achar um
    ponto específico de um documento longo, pesquisar é mais barato que ler tudo.

    Args:
        arquivo_id: O 'arquivo.id' devolvido pela pesquisa.
        deslocamento: Caractere a partir do qual ler (padrão 0 = início).

    Returns:
        Dicionário com 'arquivo' (nome, tipo, categoria…), 'origem_texto'
        ('arquivo_original' ou 'indice_de_busca'), 'texto', 'total_caracteres',
        'tem_mais'/'proximo_deslocamento', 'url_abrir' (apresente como link clicável)
        e, quando houver, 'url_original' (o documento original no Drive — o .md da
        base é a conversão dele; aponte esse link quando o usuário quiser a peça oficial).
    """
    claims = require_module("knowledge_base")
    with app.app_context():
        return read_kb_file_handler(arquivo_id, claims["law_firm_id"], deslocamento,
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
    protocolo: str | None = None,
    limite: int = 100,
    deslocamento: int = 0,
) -> dict:
    """Lista contestações FAP sincronizadas do portal Dataprev, com total encontrado.

    Para "qual o resultado do protocolo X?", filtre por protocolo: uma chamada
    traz a contestação de cada instância com situação e resultado — não pagine
    a lista procurando o número.

    Args:
        protocolo: Protocolo administrativo (NUP), com ou sem pontuação
            (10128.053144/2025-42 ou 10128053144202542), completo ou um trecho.
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
        identificação, instância, situação, resultado do deferimento, data D.O.U.
        e se o PDF já foi baixado).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return list_fap_contestacoes_handler(
            claims["law_firm_id"], cnpj, cnpj_raiz, ano_vigencia,
            situacao_codigo, instancia_codigo, limite, deslocamento,
            app_public_url=APP_PUBLIC_URL, protocolo=protocolo,
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
    grupo: str | None = None,
    protocolo: str | None = None,
    status_1a_instancia: str | None = None,
    status_2a_instancia: str | None = None,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    """Lista benefícios previdenciários vinculados a contestações FAP, com total encontrado.

    Para apenas CONTAR benefícios (ex: "quantos benefícios da empresa X?",
    "quantos B91 da Vale foram indeferidos na 1ª instância?"), prefira
    resumo_fap — responde em uma única chamada, sem listar registros.

    Cada item traz consulta_cpf_receita (quando há CPF e nascimento) é o link da
    situação cadastral do CPF na Receita Federal, já preenchido — a pessoa só
    resolve o captcha, e é lá que se vê o nome do segurado. Ofereça o link a
    quem perguntar pelo nome; você não consegue abrir nem ler essa página.
    segurado_nome vem preenchido quando alguém já revelou o nome na tela
    (botão "Revelar nome", consulta paga por CPF); o MCP não faz essa consulta.

    Combine os filtros numa chamada só em vez de listar tudo e separar depois:
    "B91 da Vale indeferidos na 1ª instância" é grupo="Vale",
    tipo_beneficio="B91", status_1a_instancia="indeferido".

    Args:
        empresa: Nome (ou parte do nome) da empresa/empregador — casa nome do
            empregador e as raízes de CNPJ da empresa FAP correspondente.
        cnpj: CNPJ do empregador (aceita formatado, só dígitos ou raiz de 8).
        status: Status geral do benefício (ex: pending, approved, rejected) — NÃO é
            o resultado por instância; para isso use status_1a_instancia/status_2a_instancia.
        tipo_pedido: exclusao, inclusao ou revisao.
        tipo_beneficio: Ex: B91 (auxílio-acidente), B94 (auxílio-doença acidentário).
        topico_contestacao: Tópico jurídico da contestação (ex: ACIDENTE DE TRAJETO).
        segurado: Nome (ou parte do nome) do segurado. ATENÇÃO: o relatório e o
            portal do FAP não trazem nome — só acha quem teve o nome revelado na
            tela (botão "Revelar nome") ou cadastrado à mão. Se não achar, diga
            que o sistema não tem o nome desse segurado e peça o CPF ou o NIT.
        nit: NIT do segurado (busca exata).
        cpf: CPF do segurado — com ou sem pontuação.
        numero_beneficio: Número do benefício (busca exata).
        ano_vigencia: Ano de vigência FAP em que o benefício aparece (ex: "2023").
        grupo: Grupo empresarial cadastrado (ex: "Vale") — todas as empresas do
            grupo e só elas; nomes em valores_de_filtro_fap.
        protocolo: Protocolo administrativo da contestação (com ou sem pontuação,
            completo ou trecho) — traz os benefícios daquela contestação (CNPJ +
            vigência), com o status de cada um na 1ª e na 2ª instância. É o
            mesmo critério do filtro de protocolo da tela de Benefícios.
        status_1a_instancia: Resultado na 1ª instância administrativa: deferido,
            indeferido, em_analise ou pendente (aceita "indeferidos", "em análise"...).
        status_2a_instancia: Resultado na 2ª instância (recurso), mesmos valores.
            Pendente na 2ª = nenhum resultado nem andamento de recurso registrado
            no sistema; 1ª deferida ou em análise não entra (igual à tela). NÃO
            indica se o prazo de recurso ainda está aberto — não afirme que o
            recurso "ainda é possível" ou "segue cabível".
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
            empresa, limite, deslocamento, protocolo=protocolo, grupo=grupo,
            status_1a_instancia=status_1a_instancia, status_2a_instancia=status_2a_instancia,
        )


@mcp.tool()
def revelar_nome_segurado(cpf: str) -> dict:
    """Revela o NOME de UM segurado pelo CPF — consulta PAGA a um serviço externo.

    O FAP não informa nome; esta é a mesma consulta do botão "Revelar nome" das
    telas de Benefícios, e o nome fica salvo para o escritório (telas e MCP).

    USE SOMENTE quando o usuário pedir EXPLICITAMENTE o nome de uma pessoa
    específica ("qual o nome do segurado do CPF X?", "revele o nome deste
    segurado"). NUNCA chame por iniciativa própria, para enriquecer listagens,
    em lote, em sequência para vários CPFs, nem para "completar" uma tabela —
    se pedirem nomes de muitos segurados, explique que cada nome é uma consulta
    paga e peça que escolham quais. Antes, confira em segurado_nome dos
    benefícios se o nome já não foi revelado (aí não precisa chamar).

    Há limite diário de consultas por usuário (consultas_restantes_hoje na
    resposta); nome já salvo não conta. Se vier 'aviso' de nascimento
    divergente, repasse ao usuário: o nome pode ser de outra pessoa.

    Args:
        cpf: CPF do segurado (com ou sem pontuação). Precisa estar na base do
            escritório (benefício da Central ou do cálculo FAP).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return revelar_nome_segurado_handler(claims["law_firm_id"], claims.get("user_id"), cpf)


@mcp.tool()
def consultar_cpf(cpf: str) -> dict:
    """Consulta COMPLETA de um CPF no serviço externo — PAGA — e devolve tudo o que ele traz.

    Diferente de revelar_nome_segurado: vale para qualquer CPF válido (mesmo
    fora da base do escritório) e a resposta vem inteira em "dados", como o
    fornecedor manda (ex.: NOME, NASC, SEXO, NOME_MAE). Nada fica salvo.

    USE SOMENTE quando o usuário pedir explicitamente os dados de UM CPF
    ("consulte o CPF X", "quem é o titular deste CPF?"). NUNCA por iniciativa
    própria, em lote, em sequência para vários CPFs nem para completar tabela —
    cada chamada é uma consulta paga. Só para saber o NOME de um segurado da
    base, prefira revelar_nome_segurado (o nome fica salvo e não paga de novo).
    Os dados são pessoais (inclusive nome da mãe): mostre ao usuário, sem
    repetir em outros textos ou documentos que ele não pediu.

    Entra no mesmo limite diário do revelar nome (consultas_restantes_hoje na
    resposta).

    Args:
        cpf: CPF com ou sem pontuação (11 dígitos, dígito verificador válido).
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return consultar_cpf_handler(claims["law_firm_id"], claims.get("user_id"), cpf)


@mcp.tool()
def detalhar_beneficio(beneficio_id: int) -> dict:
    """Retorna todos os dados de um benefício FAP específico.

    Inclui dados do segurado, empregador, acidente (CAT/BO), valores pagos,
    tópicos de contestação e justificativas/pareceres por instância.
    consulta_cpf_receita abre a situação cadastral do CPF na Receita já
    preenchida (falta o captcha) — é onde se vê o nome do segurado.

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
    Com CPF ou NIT, traz também 'beneficios_calculo_fap': os benefícios e CATs do
    cálculo FAP (base da Consulta do portal), que existem mesmo sem contestação.

    Cada benefício traz consulta_cpf_receita (quando há CPF e nascimento) é o link da
    situação cadastral do CPF na Receita Federal, já preenchido — a pessoa só
    resolve o captcha, e é lá que se vê o nome do segurado. Ofereça o link a
    quem perguntar pelo nome; você não consegue abrir nem ler essa página.
    segurado_nome vem preenchido quando alguém já revelou o nome na tela
    (botão "Revelar nome", consulta paga por CPF); o MCP não faz essa consulta.

    Args:
        nit: NIT do segurado (identificador mais completo para o cruzamento).
        cpf: CPF do segurado, com ou sem pontuação. Só com o CPF, CATs e
            processos vêm pelos NITs dos benefícios desse CPF.
        nome: Nome ou parte do nome do segurado. Relatório e portal do FAP não
            trazem nome: só acha quem teve o nome revelado na tela (botão "Revelar
            nome") ou cadastrado à mão. Se não achar, avise e peça o CPF ou o NIT.
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
    grupo: str | None = None,
    tipo_beneficio: str | None = None,
    status_1a_instancia: str | None = None,
    status_2a_instancia: str | None = None,
) -> dict:
    """Resumo estatístico do FAP do escritório: contagens agregadas em uma chamada.

    SEMPRE prefira esta tool para perguntas de contagem/quantidade ("quantos
    benefícios da empresa X?", "quantas contestações deferidas em 2023?") —
    é muito mais rápido do que listar registros. Retorna contestações por ano
    de vigência, situação, instância e empresa; benefícios por tipo, tipo de
    pedido, status de 1ª/2ª instância, tópico, financeiro (total pago) e o
    ranking de estabelecimentos (beneficios.por_estabelecimento: os 20 CNPJs
    com mais benefícios, com nome e matriz/filial) — é a resposta para "quais
    filiais têm mais benefícios?", sem listar benefício por benefício.

    Tipo × resultado por instância vem cruzado em
    beneficios.por_tipo_x_status_primeira_instancia e
    ..._segunda_instancia ({"B91": {"indeferido": 120, ...}}): "quantos B91 da
    Vale foram indeferidos na 1ª instância?" é resumo_fap(grupo="Vale") e ler
    a célula, sem listar nada. Para restringir todo o bloco de benefícios, use
    tipo_beneficio e status_1a_instancia/status_2a_instancia.

    Com filtro por empresa ou grupo, 'empresas_na_conta' diz quais empresas
    (CNPJ raiz) entraram no número. Se vier 'aviso_empresas', o nome casou com
    mais de uma empresa: mostre isso ao usuário antes de apresentar o total.

    Args:
        ano_vigencia: Restringe a um ano de vigência FAP (opcional).
        cnpj: Restringe a um estabelecimento — aceita formatado, só dígitos ou
            raiz de 8 dígitos (opcional).
        empresa: Nome (ou parte do nome) da empresa (opcional) — ex: "bistek".
            Casa por pedaço de nome: "vale" também pega "Cooperativa Vale do
            Itajaí". Para um grupo econômico, prefira `grupo`.
        grupo: Grupo empresarial cadastrado no sistema (ex: "Vale") — todas as
            empresas do grupo e só elas. Nomes em valores_de_filtro_fap.
        tipo_beneficio: Restringe os benefícios a um tipo (ex: B91) (opcional).
        status_1a_instancia: deferido, indeferido, em_analise ou pendente —
            restringe os benefícios ao resultado na 1ª instância (opcional).
        status_2a_instancia: Mesmos valores, para a 2ª instância (opcional).
            Pendente na 2ª = nenhum resultado nem andamento de recurso registrado;
            não diz se o prazo de recurso ainda está aberto, então não afirme que
            o recurso ainda é possível. Em por_tipo_x_status_segunda_instancia,
            "nao_se_aplica" é quem foi deferido ou está em análise na 1ª.
            Esses três filtros não mudam os números de contestações.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return fap_summary_handler(
            claims["law_firm_id"], ano_vigencia, cnpj, empresa, grupo=grupo,
            tipo_beneficio=tipo_beneficio, status_1a_instancia=status_1a_instancia,
            status_2a_instancia=status_2a_instancia,
        )


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
def listar_beneficios_calculo_fap(
    vigencia: int | None = None,
    empresa: str | None = None,
    grupo: str | None = None,
    cnpj: str | None = None,
    cpf: str | None = None,
    nit: str | None = None,
    numero: str | None = None,
    tipo: str | None = None,
    situacao: str | None = None,
    contestado: bool | None = None,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    """Lista os benefícios (B91/B92/B93/B94) e CATs que entraram no CÁLCULO do FAP.

    É a base da Consulta do FAP no portal, sincronizada por vigência: traz tudo
    que o portal usou no cálculo, tenha o escritório contestado ou não. Para
    benefícios JÁ contestados (status por instância, justificativas) use
    listar_beneficios_fap. Para apenas contar, use resumo_beneficios_calculo_fap.

    Cada item traz consulta_cpf_receita (quando há CPF e nascimento) é o link da
    situação cadastral do CPF na Receita Federal, já preenchido — a pessoa só
    resolve o captcha, e é lá que se vê o nome do segurado. Ofereça o link a
    quem perguntar pelo nome; você não consegue abrir nem ler essa página.
    segurado_nome vem preenchido quando alguém já revelou o nome na tela
    (botão "Revelar nome", consulta paga por CPF); o MCP não faz essa consulta.

    Args:
        vigencia: Ano da vigência FAP (ex: 2023).
        empresa: Nome (ou parte) da empresa FAP.
        grupo: Grupo empresarial cadastrado (nomes em valores_de_filtro_fap).
        cnpj: CNPJ do estabelecimento (14 dígitos) ou raiz de 8, com ou sem pontuação.
        cpf: CPF do segurado — vem inteiro, com ou sem pontuação.
        nit: NIT do segurado.
        numero: Número do benefício (NB) ou da CAT.
        tipo: B91, B92, B93, B94 ou CAT.
        situacao: "conta" (entra no cálculo) ou "excluido" (o portal tirou do
            cálculo no recálculo — foi excluído, por exemplo, por contestação
            deferida).
        contestado: true/false. É por VIGÊNCIA: "contestado" = o mesmo número
            existe na Central na mesma vigência; o mesmo NB contestado em outra
            vigência conta como não contestado aqui.
        limite: Máximo de registros por página (padrão 50).
        deslocamento: Pula os N primeiros (paginação); repasse o 'proximo_deslocamento'.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return listar_beneficios_calculo_fap_handler(
            claims["law_firm_id"], vigencia, empresa, grupo, cnpj, cpf, nit, numero,
            tipo, situacao, contestado, limite, deslocamento,
        )


@mcp.tool()
def resumo_beneficios_calculo_fap(
    vigencia: int | None = None,
    empresa: str | None = None,
    grupo: str | None = None,
    cnpj: str | None = None,
    tipo: str | None = None,
) -> dict:
    """Contagens dos benefícios e CATs do cálculo FAP, em uma chamada.

    Devolve total, total por tipo, quantos foram excluídos do cálculo, quantos
    não foram contestados e o cruzamento tipo × situação (conta/excluido) ×
    contestado/nao_contestado. "Contestado" é por vigência (mesmo número e mesma
    vigência na Central). Use para "quantos B91 excluídos da Vale em 2023 não
    contestamos?" antes de listar.

    Args:
        vigencia: Ano da vigência FAP (ex: 2023).
        empresa: Nome (ou parte) da empresa FAP.
        grupo: Grupo empresarial cadastrado.
        cnpj: CNPJ do estabelecimento ou raiz, com ou sem pontuação.
        tipo: B91, B92, B93, B94 ou CAT.
    """
    claims = require_module("fap_panel")
    with app.app_context():
        return resumo_beneficios_calculo_fap_handler(
            claims["law_firm_id"], vigencia, empresa, grupo, cnpj, tipo)


@mcp.tool()
def valores_de_filtro_fap() -> dict:
    """Valores válidos (em uso no escritório) para os filtros das tools FAP.

    Retorna os grupos empresariais cadastrados (filtro `grupo`), situações e
    instâncias de contestação (código → descrição), anos de vigência, tipos de
    benefício/pedido, status e tópicos de contestação em uso, além do catálogo
    de motivos FAP. Consulte antes de filtrar para usar códigos
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
# BUSCA POR NÚMERO DE PROCESSO (todas as bases)
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def buscar_por_numero_processo(
    numero: str,
    bases: list[str] | None = None,
    limite: int = 20,
    deslocamento: int = 0,
) -> dict:
    """Acha tudo o que o escritório tem de um processo, pelo número — em todas as bases.

    Busca exata e sem IA: compara só os dígitos, então o número vale com ou sem
    pontuação ("5001181-56.2023.4.03.6100" ou "50011815620234036100"). Com os 20
    dígitos procura o número exato; com menos (mínimo 7), procura quem CONTÉM
    esses dígitos — serve para número incompleto ("5001181" ou "5001181-56.2023").
    Prefira esta tool a pesquisar_base_conhecimento quando a pergunta traz um
    número de processo: aquela busca por texto e significado.

    Args:
        numero: Número do processo, completo ou parcial (mínimo 7 dígitos).
        bases: Quais bases consultar (padrão: todas as que o usuário pode ver):
            'base_conhecimento' (petições e documentos), 'jurisprudencia'
            (decisões), 'pecas_modelo' e 'processos' (Painel de Processos).
        limite: Máximo de itens POR BASE (padrão 20).
        deslocamento: Paginação dentro de uma base — repasse o
            'proximo_deslocamento' junto com bases=[a base].

    Returns:
        'digitos' buscados, 'comparacao' (igual ou contém), 'total_encontrado' e
        'bases' — um grupo por base com 'total_encontrado', 'itens' (cada um com
        id, número, o que é e 'url'/'url_abrir' — apresente como link clicável —,
        mais 'url_original' quando houver o original no Drive) e 'proximo_passo'
        (qual tool lê o item inteiro). 'sem_permissao' lista bases que o usuário
        não pode ver.
    """
    claims = get_identity()
    with app.app_context():
        return search_by_process_number_handler(
            claims["law_firm_id"], claims.get("modules") or [], numero, bases=bases,
            limite=limite, deslocamento=deslocamento, app_public_url=APP_PUBLIC_URL)


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
        numero_processo: Número CNJ com ou sem pontuação, completo ou parcial
            (mínimo 7 dígitos) — opcional.
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
# BASE DE JURISPRUDÊNCIA (decisões FAP do escritório)
# ──────────────────────────────────────────────────────────────────────────────
#
# Cada decisão tem N teses em dois campos: a ORIGINAL (como veio escrita) e a do
# CATÁLOGO (padronizada pelo escritório). Resultado é sempre na visão da empresa.


@mcp.tool()
def pesquisar_jurisprudencia(
    termo: str | None = None,
    modo: str = "campos",
    teses_catalogo: list[str] | None = None,
    teses_originais: list[str] | None = None,
    resultados: list[str] | None = None,
    tribunais: list[str] | None = None,
    instancias: list[str] | None = None,
    uf: str | None = None,
    vigencia: int | None = None,
    julgada_de: str | None = None,
    julgada_ate: str | None = None,
    ordem: str = "recentes",
    limite: int = 20,
    deslocamento: int = 0,
) -> dict:
    """Pesquisa a base de jurisprudência do escritório (sentenças, acórdãos e embargos FAP).

    Sem termo, lista a base inteira (paginada) com os filtros dados. Com termo:
    todas as palavras precisam aparecer, com sinônimos (trajeto acha percurso e
    in itinere); aspas juntam uma expressão; número de processo vale com ou sem
    pontuação. Cada item traz a citação pronta para a peça, o trecho onde o termo
    aparece («assim») e o link da decisão.

    Args:
        termo: Palavras, expressão entre aspas ou número de processo (opcional).
        modo: "campos" (padrão: resumo, motivo, ementa, teses, fundamentos) ou
            "inteiro_teor" (texto completo das decisões com PDF indexado; aí só
            valem os filtros de tribunal, resultado e instância).
        teses_catalogo: Teses padronizadas do escritório (nomes de valores_de_filtro_jurisprudencia).
        teses_originais: Teses como vieram escritas na decisão (acento/caixa não importam).
        resultados: favoravel, parcial e/ou desfavoravel — sempre para a EMPRESA.
        tribunais: Siglas, ex.: ["TRF4", "TRF3", "STJ"].
        instancias: sentenca, acordao, embargos e/ou outra.
        uf: UF de origem (ex.: "SC").
        vigencia: Ano de vigência FAP coberto pela decisão (ex.: 2019 casa "2017 a 2021").
        julgada_de: Data mínima de julgamento, YYYY-MM-DD.
        julgada_ate: Data máxima de julgamento, YYYY-MM-DD.
        ordem: recentes (padrão), instancia (acórdão/tribunal superior primeiro) ou favoraveis.
        limite: Itens por página (padrão 20, máximo 200).
        deslocamento: Paginação — repita o 'proximo_deslocamento' da resposta anterior.

    Returns:
        Envelope paginado com 'itens', 'total_encontrado', 'processos_distintos' e
        'como_tem_decidido' (favorável/parcial/desfavorável do recorte todo).
    """
    claims = require_module("process_panel")
    with app.app_context():
        return search_jurisprudence_handler(
            claims["law_firm_id"], APP_PUBLIC_URL, modo=modo, limite=limite, deslocamento=deslocamento,
            termo=termo, teses_catalogo=teses_catalogo, teses_originais=teses_originais,
            resultados=resultados, tribunais=tribunais, instancias=instancias, uf=uf,
            vigencia=vigencia, julgada_de=julgada_de, julgada_ate=julgada_ate, ordem=ordem,
        )


@mcp.tool()
def detalhar_decisao(decisao_id: int) -> dict:
    """Tudo de uma decisão da base de jurisprudência.

    Motivo do resultado, resumo do caso, ementa (e se é transcrição ou resumo —
    resumo não pode ser citado entre aspas), fundamentos do julgador, argumentos
    da empresa acolhidos e rejeitados, precedentes citados (marcando os que também
    estão na base), teses originais e do catálogo, citação pronta e as outras
    decisões do mesmo processo (sentença → acórdão → embargos).

    Args:
        decisao_id: ID da decisão (vem de pesquisar_jurisprudencia).
    """
    claims = require_module("process_panel")
    with app.app_context():
        return decision_detail_handler(decisao_id, claims["law_firm_id"], APP_PUBLIC_URL)


@mcp.tool()
def panorama_jurisprudencia(
    termo: str | None = None,
    teses_catalogo: list[str] | None = None,
    teses_originais: list[str] | None = None,
    tribunais: list[str] | None = None,
    instancias: list[str] | None = None,
    uf: str | None = None,
    vigencia: int | None = None,
    julgada_de: str | None = None,
    julgada_ate: str | None = None,
) -> dict:
    """Como os tribunais têm decidido num recorte da base — uma chamada, sem paginar.

    Use para perguntas do tipo "qual a chance da tese X no TRF4?": devolve a
    distribuição de resultados (visão da empresa), a mesma distribuição por
    tribunal e por instância, os processos que VIRARAM no acórdão (sentença
    perdida, acórdão melhor — os precedentes mais fortes) e as decisões
    favoráveis mais recentes com citação pronta.

    Args: os mesmos filtros de pesquisar_jurisprudencia (sem resultado, que é o que se mede).
    """
    claims = require_module("process_panel")
    with app.app_context():
        return jurisprudence_overview_handler(
            claims["law_firm_id"], APP_PUBLIC_URL,
            termo=termo, teses_catalogo=teses_catalogo, teses_originais=teses_originais,
            tribunais=tribunais, instancias=instancias, uf=uf, vigencia=vigencia,
            julgada_de=julgada_de, julgada_ate=julgada_ate,
        )


@mcp.tool()
def valores_de_filtro_jurisprudencia() -> dict:
    """Valores que existem na base de jurisprudência, com contagem de decisões.

    Consulte antes de filtrar para usar os nomes exatos: teses do catálogo, teses
    originais (como vieram nas decisões), tribunais, instâncias, resultados, UFs,
    anos de vigência FAP e o período de julgamento coberto pela base.
    """
    claims = require_module("process_panel")
    with app.app_context():
        return jurisprudence_filter_values_handler(claims["law_firm_id"])


@mcp.tool()
def decisoes_parecidas(decisao_id: int, limite: int = 6) -> dict:
    """Decisões da base com conteúdo mais parecido com o de uma decisão.

    Compara por semelhança de conteúdo (índice próprio da base de jurisprudência),
    não por palavra nem por tese — acha a decisão que discute o mesmo ponto com
    outras palavras ou outra tese registrada.

    Args:
        decisao_id: ID da decisão de referência.
        limite: Quantas devolver (padrão 6, máximo 20).
    """
    claims = require_module("process_panel")
    with app.app_context():
        return similar_decisions_handler(decisao_id, claims["law_firm_id"], APP_PUBLIC_URL, limite)


@mcp.tool()
def exportar_jurisprudencia_excel(
    termo: str | None = None,
    teses_catalogo: list[str] | None = None,
    teses_originais: list[str] | None = None,
    resultados: list[str] | None = None,
    tribunais: list[str] | None = None,
    instancias: list[str] | None = None,
    uf: str | None = None,
    vigencia: int | None = None,
    julgada_de: str | None = None,
    julgada_ate: str | None = None,
    ordem: str = "recentes",
) -> dict:
    """Exporta decisões da base de jurisprudência para Excel (XLSX) e retorna o link de download.

    Use quando o usuário pedir a lista inteira ou uma planilha, em vez de paginar
    no chat. Mesmos filtros de pesquisar_jurisprudencia (modo "campos"); uma linha
    por decisão com teses, resultado, fundamentos, argumentos, precedentes,
    ementa, citação e link. Até 50.000 linhas; o link expira em 1 hora.

    Returns:
        'arquivo', 'total_linhas', 'url_download' e 'validade_minutos'.
        Apresente o url_download ao usuário como link clicável.
    """
    claims = require_module("process_panel")
    with app.app_context():
        return export_jurisprudence_excel_handler(
            claims["law_firm_id"], MCP_PUBLIC_URL, APP_PUBLIC_URL,
            termo=termo, teses_catalogo=teses_catalogo, teses_originais=teses_originais,
            resultados=resultados, tribunais=tribunais, instancias=instancias, uf=uf,
            vigencia=vigencia, julgada_de=julgada_de, julgada_ate=julgada_ate, ordem=ordem,
        )


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
        numero_processo: Número CNJ com ou sem pontuação, completo ou parcial
            (mínimo 7 dígitos) — opcional.
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
        numero_processo: Número CNJ com ou sem pontuação (busca local aceita
            parcial, mínimo 7 dígitos; a busca ao vivo exige os 20 dígitos).
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
# DIÁRIO OFICIAL DA UNIÃO (acervo do INLABS + alertas do escritório)
# ──────────────────────────────────────────────────────────────────────────────
#
# O acervo é público (sem law_firm_id); alertas e regras são do escritório.
# Permissão: módulo "dou", a mesma da tela.


@mcp.tool()
def pesquisar_dou(
    termo: str | None = None,
    secao: str | None = None,
    orgao: str | None = None,
    tipo: str | None = None,
    data_de: str | None = None,
    data_ate: str | None = None,
    ordem: str | None = None,
    limite: int = 20,
    deslocamento: int = 0,
) -> dict:
    """Pesquisa no Diário Oficial da União capturado pelo sistema (busca de texto).

    O termo pode ser texto livre, um CNPJ ou um número de processo — CNPJ e
    processo são reconhecidos sozinhos, com ou sem pontuação, e buscados como
    número exato. Sem termo, lista o recorte dos filtros, do mais recente para o
    mais antigo.

    ASPAS: para expressão ou sigla, passe o termo entre aspas duplas
    ('"fator acidentário de prevenção"', '"FAP"'). Sem aspas o índice procura
    as palavras soltas e com tolerância a erro de digitação: a mesma expressão
    dá 748 matérias sem aspas e 7 com aspas, e "FAP" sem aspas traz FAPESP,
    FAPEMIG etc.

    A resposta traz, além das matérias, o total real e a distribuição por
    seção, órgão e tipo de ato (por_secao/por_orgao/por_tipo): para perguntas
    de quantidade use esses totais, não conte as páginas. Cada matéria vem com
    trecho («» marca o achado), url (no sistema), url_pagina_pdf (folha do PDF
    assinado) e url_oficial (portal da Imprensa Nacional).

    Se o resultado for vazio, confira em ultimas_edicoes_dou se o período já foi
    capturado antes de afirmar que nada foi publicado.

    Args:
        termo: Texto livre, CNPJ ou número de processo (opcional se houver filtro).
        secao: 1, 2 ou 3; "seção 1 extra" para a edição extra. Várias com ";".
        orgao: Órgão (raiz da hierarquia), ex.: "Ministério da Previdência Social".
            Aceita sem acento; nomes em valores_de_filtro_dou. Vários com ";".
        tipo: Tipo de ato, ex.: "Portaria", "Despacho", "Edital". Vários com ";".
        data_de: Publicado a partir de (YYYY-MM-DD).
        data_ate: Publicado até (YYYY-MM-DD).
        ordem: "relevancia" (padrão com termo) ou "data" (mais recentes primeiro).
        limite: Matérias por página (padrão 20).
        deslocamento: Paginação — repasse o 'proximo_deslocamento'. A busca
            alcança os primeiros 1.000 resultados.
    """
    require_module("dou")
    with app.app_context():
        return search_dou_handler(termo, secao, orgao, tipo, data_de, data_ate, ordem,
                                  limite, deslocamento, app_public_url=APP_PUBLIC_URL)


@mcp.tool()
def ler_materia_dou(materia_id: int, max_caracteres: int = 20000) -> dict:
    """Inteiro teor de uma matéria do Diário Oficial.

    Traz identificação, órgão, seção, página, ementa, o texto completo (cortado
    em max_caracteres, com aviso), os CNPJs e números de processo citados e os
    links: no sistema, na folha do PDF assinado (url_pagina_pdf — o documento
    oficial para citar) e no portal da Imprensa Nacional. Se a matéria gerou
    alerta para o escritório, 'alerta_do_escritorio' diz quais clientes ela
    cita e o resultado FAP de cada um.

    Args:
        materia_id: ID da matéria (vem de pesquisar_dou, sumario_edicao_dou ou dos alertas).
        max_caracteres: Tamanho máximo do texto devolvido (padrão 20.000, até 60.000).
    """
    claims = require_module("dou")
    with app.app_context():
        return get_dou_article_handler(materia_id, claims["law_firm_id"], APP_PUBLIC_URL,
                                       max_caracteres)


@mcp.tool()
def valores_de_filtro_dou() -> dict:
    """Seções, órgãos e tipos de ato que existem no acervo do Diário Oficial.

    Consulte antes de filtrar por órgão ou tipo, para usar o nome certo. Traz
    também o período coberto pelo acervo e o total de matérias.
    """
    require_module("dou")
    with app.app_context():
        return dou_filter_values_handler()


@mcp.tool()
def ultimas_edicoes_dou(quantas: int = 5) -> dict:
    """As últimas edições do Diário Oficial capturadas e a situação da captura.

    Responde "até que dia o DOU está no sistema?", "saiu edição extra?". Por
    data: matérias de cada seção (e das extras), se o PDF assinado está
    disponível, seções não publicadas e as que falharam na captura. Se vier
    'aviso', a captura está parada ou com falha — o acervo pode estar
    incompleto, e isso tem de ser dito ao usuário.

    Args:
        quantas: Quantas datas trazer (padrão 5, até 30).
    """
    require_module("dou")
    with app.app_context():
        return dou_latest_editions_handler(quantas, APP_PUBLIC_URL)


@mcp.tool()
def sumario_edicao_dou(
    data: str | None = None,
    secao: str | None = None,
    orgao: str | None = None,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    """Sumário da edição do Diário Oficial de um dia, como o do portal da Imprensa Nacional.

    Sem órgão: por seção, os órgãos na ordem das páginas (primeira página e
    quantas matérias cada um publicou) e os tipos de ato mais frequentes.
    Com órgão: as matérias daquele órgão no dia (identificação, tipo, página,
    ementa), paginadas.

    Args:
        data: Dia (YYYY-MM-DD); sem data, a edição mais recente do acervo.
        secao: 1, 2 ou 3 ("seção 1 extra" para a extra); sem seção, todas.
        orgao: Órgão (raiz), ex.: "Ministério da Previdência Social".
        limite: Matérias por página quando há órgão (padrão 50).
        deslocamento: Paginação — repasse o 'proximo_deslocamento'.
    """
    require_module("dou")
    with app.app_context():
        return dou_edition_summary_handler(data, secao, orgao, limite, deslocamento,
                                           APP_PUBLIC_URL)


@mcp.tool()
def resumo_dou_escritorio(edicoes: int = 3) -> dict:
    """O que o Diário Oficial trouxe para o escritório nas últimas edições.

    É o conteúdo do e-mail diário do DOU: clientes da carteira citados
    (agrupados por empresa, com quantos estabelecimentos), os resultados de
    recurso FAP (quantos clientes tiveram recurso julgado, quantos com
    deferimento) e as matérias que casaram com as regras de "O que vigiar".
    Deferimento é ganho de causa; indeferimento abre prazo para recorrer.

    Args:
        edicoes: Quantas edições publicadas considerar (padrão 3, até 10).
    """
    claims = require_module("dou")
    with app.app_context():
        return dou_firm_digest_handler(claims["law_firm_id"], edicoes, APP_PUBLIC_URL)


@mcp.tool()
def alertas_dou(
    status: str | None = None,
    cliente: str | None = None,
    resultado_fap: str | None = None,
    origem: str | None = None,
    secao: str | None = None,
    regra: str | None = None,
    data_de: str | None = None,
    data_ate: str | None = None,
    limite: int = 30,
    deslocamento: int = 0,
) -> dict:
    """Alertas do Diário Oficial do escritório: clientes citados e palavras-chave.

    A mesma lista da tela Alertas do Diário Oficial. Cada alerta é uma matéria,
    com os clientes citados, o resultado de recurso FAP de cada um (quando é
    edital de julgamento) e as regras de "O que vigiar" que casaram. Dentro de
    cada dia, quem traz decisão vem primeiro. Para as linhas do edital (processo,
    CNPJ, instância, resultado), use detalhar_alerta_dou.

    Args:
        status: "nao_lidos", "lidos" ou "todos" (padrão: todos).
        cliente: Nome (ou parte) ou CNPJ/raiz do cliente.
        resultado_fap: "com" (houve decisão), "deferimento" (onde ganhamos),
            "indeferimento" (prazo correndo) ou a decisão exata.
        origem: "cliente" (CNPJ da carteira) ou "regra" (palavra-chave).
        secao: 1, 2 ou 3 (uma por vez).
        regra: Nome da regra de "O que vigiar".
        data_de: Publicado a partir de (YYYY-MM-DD).
        data_ate: Publicado até (YYYY-MM-DD).
        limite: Alertas por página (padrão 30).
        deslocamento: Paginação — repasse o 'proximo_deslocamento'.
    """
    claims = require_module("dou")
    with app.app_context():
        return dou_list_alerts_handler(
            claims["law_firm_id"], status, cliente, resultado_fap, origem, secao, regra,
            data_de, data_ate, limite, deslocamento, APP_PUBLIC_URL)


@mcp.tool()
def detalhar_alerta_dou(alerta_id: int, max_linhas: int = 200) -> dict:
    """Um alerta do Diário Oficial por inteiro: estabelecimentos e linhas do edital.

    Traz cada estabelecimento do cliente citado (CNPJ, se é o cadastrado ou
    outro do grupo, resultado FAP) e as linhas do edital que o citam, em texto
    ("processo | ano | CNPJ | instância | resultado"), com o cabeçalho da
    tabela quando existe. É o "ver trecho" da tela.

    Args:
        alerta_id: ID do alerta (vem de alertas_dou ou de ler_materia_dou).
        max_linhas: Máximo de linhas e estabelecimentos (padrão 200, até 400).
    """
    claims = require_module("dou")
    with app.app_context():
        return dou_alert_detail_handler(claims["law_firm_id"], alerta_id, APP_PUBLIC_URL,
                                        max_linhas)


@mcp.tool()
def regras_dou() -> dict:
    """As regras de "O que vigiar" do escritório no Diário Oficial.

    Por regra: termo, modo (frase exata ou todas as palavras), seções, órgão,
    se está ativa, quem criou, quantos alertas gerou e quando casou pela última
    vez — "essa regra não pega nada há 40 dias" aparece aqui.
    """
    claims = require_module("dou")
    with app.app_context():
        return dou_rules_handler(claims["law_firm_id"], APP_PUBLIC_URL)


@mcp.tool()
def testar_termo_dou(
    termo: str | None = None,
    modo: str | None = None,
    secao: str | None = None,
    orgao: str | None = None,
) -> dict:
    """Quantos alertas um termo geraria no Diário Oficial — antes de criar a regra.

    Roda o mesmo teste da tela "O que vigiar" nas últimas edições: alertas no
    período, média por edição, avaliação do volume (ok, alto, ruidoso) e
    exemplos com o trecho. Não cria regra: para isso, a tela (link em
    'como_criar'). Termo comum ("licitação") gera centenas por dia — o teste
    existe para mostrar isso antes.

    Args:
        termo: Palavra ou expressão a vigiar (opcional se houver órgão).
        modo: "frase" (a sequência exata, padrão) ou "palavras" (todas, em qualquer ordem).
        secao: 1, 2 ou 3 para restringir (vários com ";").
        orgao: Órgão (raiz) para restringir.
    """
    require_module("dou")
    with app.app_context():
        return dou_test_term_handler(termo, modo, secao, orgao, APP_PUBLIC_URL)


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
def minha_api() -> dict:
    """Endereço da API do IntellexIA, link da documentação e os tokens de API do usuário.

    A API entrega os mesmos dados destas ferramentas em JSON, para o usuário
    montar telas, planilhas e scripts (ex.: no Claude Code). Os tokens vêm sem
    o segredo (só o final), com situação, validade e último uso.
    """
    claims = require_module("api")
    with app.app_context():
        return minha_api_handler(claims["law_firm_id"], claims.get("user_id"), APP_PUBLIC_URL,
                                 claims.get("modules") or [])


@mcp.tool()
def criar_token_api(nome: str, validade_dias: int | None = 90) -> dict:
    """Cria um token pessoal da API do IntellexIA para o usuário.

    Use SOMENTE quando o usuário pedir um token (ex.: para configurar o Claude
    Code ou um script). Mostre o token UMA vez, avisando que ele não aparece de
    novo, e sugira guardá-lo numa variável de ambiente (INTELLEXIA_TOKEN) ou num
    .env fora do git. NUNCA repita o token depois, nunca o grave em arquivo
    versionado nem em página que vá ser publicada. Se o usuário já tem token
    ativo (veja minha_api), pergunte antes se quer outro.

    Args:
        nome: Para o usuário reconhecer onde o token é usado (ex.: "Claude Code do notebook").
        validade_dias: 30, 90 (padrão) ou 180; null = sem validade.
    """
    claims = require_module("api")
    with app.app_context():
        return criar_token_api_handler(claims["law_firm_id"], claims.get("user_id"), nome, validade_dias)


@mcp.tool()
def revogar_token_api(token_id: int) -> dict:
    """Revoga um token de API do próprio usuário: ele para de funcionar na hora.

    Args:
        token_id: id do token (em minha_api). Tokens de outros usuários só o
            administrador revoga, pela tela Minha API.
    """
    claims = require_module("api")
    with app.app_context():
        return revogar_token_api_handler(claims["law_firm_id"], claims.get("user_id"), token_id)


@mcp.tool()
def documentacao_api(grupo: str | None = None) -> dict:
    """Rotas da API do IntellexIA (uma por linha, com parâmetros e os campos que
    cada uma devolve) e o endereço do OpenAPI, que traz o schema completo.

    Use para montar integrações com a API (telas, scripts, planilhas): os
    nomes de parâmetro e os números são os mesmos destas ferramentas. Na API as
    listas vão até 1000 por página e a resposta não traz a "dica" (paginação só
    por tem_mais/proximo_deslocamento). Autenticação: header
    "Authorization: Bearer <token>".

    Args:
        grupo: Restringe a um grupo: conta, fap, segurados, base-conhecimento,
            jurisprudencia ou processos.
    """
    require_module("api")
    with app.app_context():
        return documentacao_api_handler(APP_PUBLIC_URL, grupo)


# ──────────────────────────────────────────────────────────────────────────────
# BIBLIOTECA DE PROMPTS
# ──────────────────────────────────────────────────────────────────────────────


@mcp.tool()
def biblioteca_prompts(busca: str | None = None, incluir_sistema: bool = False) -> dict:
    """Prompts, agentes e skills da Biblioteca de IA do usuário: os dele e os do escritório.

    Use quando o usuário pedir "aquele prompt de...", "o que tem na biblioteca",
    ou antes de montar do zero algo que o escritório já pode ter pronto. Os
    recomendados pelo escritório vêm primeiro. Para usar um item, chame
    usar_prompt com o "nome" devolvido aqui.

    Args:
        busca: Palavras para filtrar por título, texto ou área (ex.: "sentença").
        incluir_sistema: True para incluir os comandos prontos do IntellexIA.
    """
    claims = get_identity()
    with app.app_context():
        return biblioteca_prompts_handler(claims["law_firm_id"], claims.get("user_id"), busca, incluir_sistema)


@mcp.tool()
def usar_prompt(nome: str, campos: dict[str, str] | None = None) -> dict:
    """Entrega o texto pronto de um item da Biblioteca de IA, com os campos preenchidos.

    Depois de chamar, SIGA o "texto" devolvido como se o usuário o tivesse
    escrito (é o roteiro que ele guardou). Campo que faltar vem indicado no
    próprio texto: pergunte ao usuário antes de seguir.

    Args:
        nome: O "nome" do item em biblioteca_prompts (ex.: "escritorio_prompt_resumo_sentenca").
        campos: Valores dos campos do item, ex.: {"empresa": "Vale", "vigencia": "2025"}.
    """
    claims = get_identity()
    with app.app_context():
        return usar_prompt_handler(claims["law_firm_id"], claims.get("user_id"), nome, campos)


@mcp.tool()
def salvar_prompt(
    titulo: str,
    texto: str,
    quando_usar: str | None = None,
    tipo: str = "prompt",
    area: str = "geral",
    compartilhar: bool = False,
    usa_intellexia: bool = False,
    comando: str | None = None,
) -> dict:
    """Guarda um prompt na Biblioteca de IA do usuário.

    Use SOMENTE quando o usuário pedir para salvar ("guarda esse prompt", "salva
    isso na minha biblioteca"). Escreva o texto como instrução reutilizável, sem
    dados do caso da conversa (nada de CPF, CNPJ, nome de segurado ou de
    cliente): o que varia de uma vez para outra vira campo entre chaves duplas,
    como {{empresa}} ou {{vigencia}}. Mostre o texto ao usuário antes de salvar.
    Por padrão fica só para ele; compartilhar=True só se ele pedir.

    Args:
        titulo: Nome curto para achar depois (ex.: "Resumo de sentença FAP").
        texto: O prompt, com {{campos}} no que muda a cada uso.
        quando_usar: Uma frase dizendo para que serve.
        tipo: prompt, agente (roteiro que usa as ferramentas do IntellexIA) ou skill.
        area: fap, jurisprudencia, processos, comunicacao, base_conhecimento, dou ou geral.
        compartilhar: True para todo o escritório ver; False (padrão) = só o usuário.
        usa_intellexia: True quando o texto manda consultar dados pelo conector.
        comando: Nome curto do comando no Claude (ex.: "resumo_sentenca"), se o
            usuário escolher um; sem ele, sai do título. Vira meu_<tipo>_<comando>
            ou escritorio_<tipo>_<comando> (ex.: escritorio_agente_resumo_sentenca).
    """
    claims = get_identity()
    with app.app_context():
        return salvar_prompt_handler(claims["law_firm_id"], claims.get("user_id"), APP_PUBLIC_URL, titulo, texto,
                                     quando_usar, tipo, area, compartilhar, usa_intellexia, comando)


@mcp.tool()
def revisar_peticao_inicial(
    identificador_documento: str,
    titulo: str = "",
    texto_peticao: str | None = None,
    link_drive: str | None = None,
) -> dict:
    """Pede uma revisão nova de uma petição FAP ao agente revisor oficial do escritório.

    A revisão entra no módulo Revisor de Petições como se o usuário a tivesse
    enviado pela tela: mesmos prompts, manual FAP, casos de referência e pontos
    de atenção da revisão anterior; fica no histórico da petição, com custo e
    status do fluxo.

    ANTES de chamar, pergunte ao usuário o Id Wrike da petição (só números) e
    confira em listar_peticoes_revisao(identificador=...) se ela já existe. Se
    existir, diga qual é (título e nº de revisões) — a revisão entra como a
    próxima dela; se não, a petição é criada com o 'titulo' informado.

    COMO MANDAR A PETIÇÃO — escolha uma entrada, nunca duas:
    - Arquivo anexado na conversa, ou petição longa: NÃO copie o texto. Chame
      sem 'texto_peticao' e sem 'link_drive': a resposta traz 'link_envio' e o
      'comando_curl'. Siga o 'proximo_passo' — ele diz como escolher o anexo em
      /mnt/user-data/attachments/ (se houver mais de um PDF/DOCX/TXT, pergunte
      ao usuário qual é) e o que fazer se o curl não funcionar (repassar o link
      para a pessoa soltar o arquivo na página).
    - Arquivo no Google Drive: passe o link em 'link_drive'. Ele precisa estar
      compartilhado com intellexia-drive@intellexia-503416.iam.gserviceaccount.com
      ou aberto a qualquer pessoa com o link.
    - Petição curta colada na conversa (até ~20 mil caracteres): 'texto_peticao'.

    A revisão leva alguns minutos e roda em segundo plano: a resposta volta na
    hora com status "processando", o 'link' da revisão e a 'mensagem_para_usuario'.
    Repasse essa mensagem (com o link) e encerre: não espere nem chame de novo.
    Quando o usuário pedir o resultado, use detalhar_revisao(revisao_id).

    Args:
        identificador_documento: Id Wrike da petição (ex.: "4387120543"). Obrigatório.
        titulo: Título da petição, usado só quando ela é criada agora.
        texto_peticao: Texto da petição — só para petição curta colada na conversa.
        link_drive: Link do arquivo no Google Drive (PDF, DOCX ou Google Docs).

    Returns:
        Com texto ou Drive: status "processando", 'revisao_id', 'numero_revisao',
        'peticao_id', 'link' e 'mensagem_para_usuario'. Sem os dois: status
        "aguardando_arquivo", 'link_envio', 'expira_em', 'comando_curl' e
        'proximo_passo'. Se a petição já tiver uma revisão rodando, devolve essa
        ('ja_em_andamento': true) sem abrir outra.
    """
    claims = require_module("fap_review")
    with app.app_context():
        return review_petition_handler(
            texto_peticao, claims["law_firm_id"], user_id=claims.get("user_id"),
            identificador_documento=identificador_documento, titulo=titulo,
            link_drive=link_drive,
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

    Use isto em vez de revisar de novo: a revisão já existe, custa minutos de IA
    para refazer e o resultado ficaria fora do histórico. Pegue o 'revisao_id' em
    listar_peticoes_revisao ('ultima_revisao_id'), em historico_revisoes_peticao
    ou na resposta de revisar_peticao_inicial. Se ainda estiver "processando",
    diga ao usuário há quanto tempo e que ele recebe e-mail ao terminar.

    Para "como está a revisão N da petição X?" (a pergunta que a página de envio
    manda copiar): chame historico_revisoes_peticao(identificador=X) e use o
    'revisao_id' da revisão N.

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
    identificador_documento: str,
    titulo: str = "",
) -> dict:
    """Pede uma revisão das duas versões de uma petição em conjunto (original × revisada).

    Use quando existirem duas versões e a pergunta for "a v2 corrigiu o que o
    revisor apontou?": o agente oficial analisa as mudanças, em vez de comparar
    os textos por conta própria. Para uma versão só, use revisar_peticao_inicial.

    Como em revisar_peticao_inicial: pergunte antes o Id Wrike ao usuário; a
    comparação entra no histórico da petição, roda em segundo plano (alguns
    minutos) e a resposta volta na hora com status "processando". O resultado sai
    por detalhar_revisao(revisao_id) e o usuário recebe e-mail ao terminar.

    Args:
        texto_original: Texto completo da versão anterior (mínimo ~200 caracteres).
        texto_revisado: Texto completo da versão nova (mínimo ~200 caracteres).
        identificador_documento: Id Wrike da petição (só números). Obrigatório.
        titulo: Título da petição, usado só quando ela é criada agora.

    Returns:
        status "processando", 'revisao_id', 'numero_revisao', 'peticao_id' e 'link'.
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


@mcp.prompt(name="dou_do_dia", description="O Diário Oficial de hoje para o escritório: clientes citados, recursos FAP julgados e o que casou com as regras")
def dou_do_dia() -> str:
    return (
        "Monte o resumo do Diário Oficial da União para o escritório, em português:\n"
        "1. Chame ultimas_edicoes_dou (quantas=1). Se vier 'aviso', comece dizendo que a "
        "captura está atrasada ou com falha e até que data o acervo vai.\n"
        "2. Chame resumo_dou_escritorio (edicoes=1).\n"
        "3. **Recursos FAP julgados**: por cliente, quantos estabelecimentos tiveram "
        "deferimento (ganho de causa) e quantos indeferimento (prazo para recorrer). "
        "Para cada cliente com indeferimento, chame detalhar_alerta_dou no alerta "
        "correspondente (alertas_dou com cliente e resultado_fap='indeferimento') e "
        "liste processo e CNPJ.\n"
        "4. **Clientes citados** sem decisão de recurso: o que é cada matéria, com link.\n"
        "5. **O que vigiar**: as matérias que casaram com as regras, uma linha cada.\n"
        "6. **Seção 1 de interesse**: chame sumario_edicao_dou (secao=1) e destaque os "
        "atos de órgãos ligados a previdência e trabalho (ex.: Ministério da Previdência "
        "Social, Ministério do Trabalho e Emprego), se houver.\n"
        "Cite sempre o link da folha do PDF assinado (url_pagina_pdf) ou url_oficial. "
        "Seja direto: primeiro o que exige ação."
    )


@mcp.prompt(name="radar_regulatorio_fap", description="O que mudou nas regras do FAP, NTEP e RAT no Diário Oficial no período")
def radar_regulatorio_fap(dias: str = "30") -> str:
    return (
        f"Monte o radar regulatório de FAP dos últimos {dias} dias no Diário Oficial da União, "
        "em português:\n"
        "1. Chame ultimas_edicoes_dou para saber até que data o acervo vai; o período é "
        f"os {dias} dias anteriores a essa data.\n"
        "2. Chame pesquisar_dou (ordem='data', data_de no início do período) para cada termo, "
        "SEMPRE com o termo entre aspas duplas dentro do valor (frase exata — sem aspas as "
        "palavras vêm soltas e FAP casa FAPESP): '\"Fator Acidentário de Prevenção\"', "
        "'\"FAP\"', '\"Nexo Técnico Epidemiológico\"', '\"NTEP\"', "
        "'\"Riscos Ambientais do Trabalho\"', '\"Conselho de Recursos da Previdência Social\"' "
        "e '\"acidente de trabalho\"'. Use por_orgao e por_tipo para ver o volume.\n"
        "3. Descarte o que não é regra nem pauta (editais de licitação, extratos de contrato, "
        "fundações de amparo à pesquisa como FAPESP ou FAPEMIG).\n"
        "4. Para os atos relevantes (portarias, resoluções, instruções normativas, pautas de "
        "julgamento do CRPS), chame ler_materia_dou e resuma o que muda e para quem.\n"
        "5. Entregue: **Normas** (o que mudou, vigência, impacto para as empresas clientes), "
        "**Pautas e julgamentos** (datas e órgão) e **Para acompanhar**. Cada item com a data, "
        "a identificação do ato e o link da folha do PDF assinado (url_pagina_pdf) ou url_oficial.\n"
        "Se não houver nada relevante, diga isso claramente — é uma resposta útil."
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
