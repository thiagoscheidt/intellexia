"""
Registro de uso do MCP por usuário — alimenta a tela de Atividade de Usuários.

Um middleware só, em vez de uma linha em cada tool: toda chamada de
ferramenta (``tools/call``) e de comando pronto (``prompts/get``) passa por
aqui. Grava quem, o quê, quando, se deu erro e quanto tempo levou — nunca os
argumentos (CPF, texto de petição, nomes). Ver ``UserMcpCall``.

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


class UsoMcpMiddleware(Middleware):
    """Conta cada chamada de ferramenta e de comando pronto por usuário e dia."""

    def __init__(self, app):
        self.app = app

    async def _medir(self, context, call_next, kind: str):
        claims = _claims()
        nome = getattr(context.message, "name", None) or "?"
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
                try:
                    await asyncio.to_thread(_gravar, self.app, claims, kind, nome, ok, ms, erro)
                except Exception:
                    logger.exception("Falha ao registrar uso do MCP (ignorada)")

    async def on_call_tool(self, context, call_next):
        return await self._medir(context, call_next, "tool")

    async def on_get_prompt(self, context, call_next):
        return await self._medir(context, call_next, "prompt")
