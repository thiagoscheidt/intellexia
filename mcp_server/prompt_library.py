"""
Biblioteca de IA como comandos prontos do conector.

Os comandos do sistema ficam no ``server.py`` (``@mcp.prompt``); os da
biblioteca são **por usuário** — cada um vê os seus (``meu_<tipo>_<slug>``) e os do
escritório (``escritorio_<tipo>_<slug>``) — e por isso não podem ser registrados no
start. O middleware acrescenta os itens na lista (``prompts/list``) e responde
esses nomes no ``prompts/get``, sem passar adiante.

Vem **depois** do ``UsoMcpMiddleware`` na cadeia, então o uso de um comando da
biblioteca continua registrado em ``user_mcp_calls`` como qualquer outro.
Falha ao ler a biblioteca não derruba a lista: os comandos do sistema seguem.
"""
from __future__ import annotations

import asyncio
import logging

from fastmcp.exceptions import PromptError
from fastmcp.prompts.base import Prompt, PromptArgument, PromptResult
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware

from app.services import prompt_library_service as svc

logger = logging.getLogger(__name__)


def _claims() -> dict | None:
    try:
        token = get_access_token()
    except Exception:
        return None
    claims = getattr(token, "claims", None) or {}
    if claims.get("user_id") and claims.get("law_firm_id"):
        return claims
    return None


def _usuario(claims: dict):
    from app.models import User, db

    user = db.session.get(User, int(claims["user_id"]))
    if not user or user.law_firm_id != int(claims["law_firm_id"]) or not user.is_active:
        return None
    return user


def _prompts_do_usuario(app, claims: dict) -> list[Prompt]:
    with app.app_context():
        user = _usuario(claims)
        if user is None:
            return []
        saida = []
        for item in svc.visiveis(user).order_by(svc.PromptLibraryItem.id).all():
            descricao = item.titulo + (f" — {item.descricao}" if item.descricao else "")
            if item.visibilidade == "escritorio":
                descricao += " (Biblioteca do escritório)"
            else:
                descricao += " (Minha biblioteca)"
            saida.append(Prompt(
                name=svc.nome_comando(item),
                title=item.titulo,
                description=descricao[:1000],
                arguments=[PromptArgument(name=c, description=c.replace("_", " "), required=False)
                           for c in svc.campos(item.corpo)],
            ))
        return saida


def _renderizar(app, claims: dict, nome: str, argumentos: dict | None) -> PromptResult | None:
    with app.app_context():
        user = _usuario(claims)
        if user is None:
            return None
        item = svc.item_por_comando(user, nome)
        if item is None:
            return None
        texto = svc.texto_para_ia(item, argumentos)
        svc.registrar_uso(item)
        return PromptResult(texto, description=item.titulo)


def _da_biblioteca(nome: str) -> bool:
    return nome.startswith(svc.PREFIXO_MEU) or nome.startswith(svc.PREFIXO_ESCRITORIO)


class BibliotecaPromptsMiddleware(Middleware):
    """Acrescenta e responde os comandos da Biblioteca de IA de cada usuário."""

    def __init__(self, app):
        self.app = app

    async def on_list_prompts(self, context, call_next):
        sistema = list(await call_next(context))
        claims = _claims()
        if not claims:
            return sistema
        try:
            extras = await asyncio.to_thread(_prompts_do_usuario, self.app, claims)
        except Exception:
            logger.exception("Falha ao listar a Biblioteca de IA (ignorada)")
            return sistema
        nomes = {p.name for p in sistema}
        return sistema + [p for p in extras if p.name not in nomes]

    async def on_get_prompt(self, context, call_next):
        nome = getattr(context.message, "name", None) or ""
        claims = _claims()
        if not claims or not _da_biblioteca(nome):
            return await call_next(context)
        resultado = await asyncio.to_thread(
            _renderizar, self.app, claims, nome, getattr(context.message, "arguments", None))
        if resultado is None:
            raise PromptError(f"O comando {nome!r} não está mais na sua biblioteca.")
        return resultado
