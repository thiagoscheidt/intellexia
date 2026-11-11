"""
Registro de uso do MCP por usuário — alimenta a tela de Atividade de Usuários.

Um middleware só, em vez de uma linha em cada tool: toda chamada de
ferramenta (``tools/call``) e de comando pronto (``prompts/get``) passa por
aqui. Grava quem, o quê, quando, se deu erro e quanto tempo levou — nunca os
argumentos (CPF, texto de petição, nomes). Ver ``UserMcpCall``. A exceção é o
``usar_prompt``: o argumento ``nome`` é o comando do item da Biblioteca de IA,
e o uso é gravado no nome dele, igual ao comando digitado com "/".

O registro roda depois da chamada, numa thread (o acesso ao banco é síncrono),
e qualquer falha nele só vai para o log: auditoria não derruba ferramenta.
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware

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


def _gravar(app, claims: dict, kind: str, name: str, ok: bool, elapsed_ms: int, erro: str | None):
    from app.services import access_audit_service

    with app.app_context():
        access_audit_service.record_mcp_call(
            int(claims["user_id"]), int(claims["law_firm_id"]), kind, name, ok, elapsed_ms, erro)


# Ferramenta que entrega um item da Biblioteca de IA (ou comando do sistema)
# pelo nome. É o caminho do "Abrir no Claude"; gravada só como ferramenta, a
# tela diria "usar_prompt: 12" sem dizer qual prompt, agente ou skill.
_FERRAMENTA_DE_COMANDO = "usar_prompt"


def _comando_usado(context) -> str | None:
    """Nome do comando pedido ao ``usar_prompt`` — é o nome do item, não dado do usuário."""
    argumentos = getattr(context.message, "arguments", None) or {}
    nome = str(argumentos.get("nome") or "").strip()
    return nome[:100] or None


class UsoMcpMiddleware(Middleware):
    """Conta cada chamada de ferramenta e de comando pronto por usuário e dia."""

    def __init__(self, app):
        self.app = app

    async def _medir(self, context, call_next, kind: str):
        claims = _claims()
        nome = getattr(context.message, "name", None) or "?"
        # Item da biblioteca usado pelo usar_prompt conta como o comando, na
        # mesma linha de quem digitou "/escritorio_agente_x": um uso, uma
        # chamada. Só quando deu certo — aí o nome existe; com erro fica como
        # usar_prompt, para não gravar o texto que o Claude inventou.
        comando = _comando_usado(context) if kind == "tool" and nome == _FERRAMENTA_DE_COMANDO else None
        inicio = time.perf_counter()
        ok, erro = True, None
        try:
            return await call_next(context)
        except Exception as e:
            ok, erro = False, f"{type(e).__name__}: {e}"
            raise
        finally:
            if claims:
                ms = int((time.perf_counter() - inicio) * 1000)
                if ok and comando:
                    kind, nome = "prompt", comando
                try:
                    await asyncio.to_thread(_gravar, self.app, claims, kind, nome, ok, ms, erro)
                except Exception:
                    logger.exception("Falha ao registrar uso do MCP (ignorada)")

    async def on_call_tool(self, context, call_next):
        return await self._medir(context, call_next, "tool")

    async def on_get_prompt(self, context, call_next):
        return await self._medir(context, call_next, "prompt")
