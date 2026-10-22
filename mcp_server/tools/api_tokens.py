"""
Tools: API do IntellexIA — tokens do próprio usuário e a documentação das rotas.

Para o Claude Code se configurar sozinho: descobrir o endereço, criar o token e
ler as rotas sem sair da conversa. Tudo por ``api_token_service`` (o mesmo da
tela Minha API) e ``public_api_catalogo`` (o mesmo registro que monta a API).
"""
from __future__ import annotations

from fastmcp.exceptions import ToolError


def _usuario(law_firm_id: int, user_id: int):
    from app.models import User, db

    user = db.session.get(User, user_id)
    if not user or user.law_firm_id != law_firm_id:
        raise ToolError("Usuário não encontrado. Reconecte o cliente MCP.")
    return user


def _enderecos(app_public_url: str) -> dict:
    base = app_public_url.rstrip("/")
    return {
        "endereco": base + "/api/v1",
        "openapi": base + "/api/v1/openapi.json",
        "documentacao": base + "/minha-api/documentacao",
    }


def minha_api_handler(law_firm_id: int, user_id: int, app_public_url: str,
                      modulos: list[str] | None = None) -> dict:
    """Endereço da API, documentação e os tokens do usuário (sem o segredo)."""
    from app.services import api_token_service, segurado_nome_service

    user = _usuario(law_firm_id, user_id)
    resultado = {
        **_enderecos(app_public_url),
        "tokens": [api_token_service.serializar(t) for t in api_token_service.listar(user)],
        "como_autenticar": "Header 'Authorization: Bearer <token>'. Token na URL não é aceito.",
    }
    if modulos and "fap_panel" in modulos:
        resultado["consultas_nome_restantes_hoje"] = segurado_nome_service.consultas_restantes_hoje(
            law_firm_id, user_id)
    return resultado


def criar_token_api_handler(law_firm_id: int, user_id: int, nome: str, validade_dias: int | None = 90) -> dict:
    """Cria um token do usuário e devolve o texto (única vez em que ele aparece)."""
    from app.services import api_token_service

    user = _usuario(law_firm_id, user_id)
    try:
        registro, texto = api_token_service.criar(user, nome, validade_dias)
    except ValueError as e:
        raise ToolError(str(e))
    dados = api_token_service.serializar(registro)
    return {
        "token": texto,
        "nome": dados["nome"],
        "final": dados["final"],
        "expira_em": dados["expira_em"],
        "orientacao": (
            "Mostre o token ao usuário UMA vez e diga que ele não aparece de novo. Sugira guardá-lo "
            "numa variável de ambiente (INTELLEXIA_TOKEN) ou num .env fora do git. Não repita o token "
            "depois e não o grave em arquivo versionado nem em página que vá ser publicada."
        ),
    }


def revogar_token_api_handler(law_firm_id: int, user_id: int, token_id: int) -> dict:
    """Revoga um token do próprio usuário (o admin revoga os dos outros pela tela)."""
    from app.models import ApiToken, db
    from app.services import api_token_service

    user = _usuario(law_firm_id, user_id)
    registro = db.session.get(ApiToken, token_id)
    if not registro or registro.user_id != user.id:
        raise ToolError(f"Token {token_id} não encontrado entre os seus tokens (veja minha_api).")
    return api_token_service.serializar(api_token_service.revogar(token_id, user))


def documentacao_api_handler(app_public_url: str, grupo: str | None = None) -> dict:
    """As rotas da API, uma por linha (o OpenAPI completo fica no endereço 'openapi')."""
    from app.services import public_api_catalogo as catalogo

    if grupo and grupo not in catalogo.GRUPOS:
        raise ToolError(f"Grupo '{grupo}' não existe. Use: {', '.join(catalogo.GRUPOS)}.")
    return {
        **_enderecos(app_public_url),
        "grupos": catalogo.GRUPOS,
        "rotas": catalogo.resumo_markdown(grupo),
        "convencoes": (
            "JSON com os mesmos campos das ferramentas MCP. Listas paginam por limite/deslocamento "
            "(tem_mais, proximo_deslocamento). Erros: {\"erro\": \"...\"} com 400, 401, 403, 404 ou 429. "
            "Parâmetros marcados com * são obrigatórios. CORS liberado."
        ),
    }
