"""
Identidade do usuário autenticado nas tools MCP.

As claims (user_id, law_firm_id, modules...) são gravadas no access token
durante o consentimento e recuperadas aqui via contexto de auth do FastMCP.
"""
from __future__ import annotations

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token

from app.utils.permissions import MODULE_PERMISSIONS


def get_identity() -> dict:
    """Retorna as claims do usuário autenticado ou levanta erro claro."""
    token = get_access_token()
    claims = getattr(token, "claims", None) or {}
    if not claims.get("user_id") or not claims.get("law_firm_id"):
        raise ToolError("Não autenticado. Reconecte o cliente MCP para autorizar o acesso.")
    return claims


def require_module(module_key: str) -> dict:
    """Garante que o usuário tem o módulo liberado; retorna as claims."""
    claims = get_identity()
    modules = claims.get("modules") or []
    if module_key not in modules:
        label = MODULE_PERMISSIONS.get(module_key, module_key)
        raise ToolError(
            f"Acesso negado: seu usuário não tem permissão para o módulo '{label}'. "
            "Solicite acesso a um administrador do escritório."
        )
    return claims


def require_admin(module_key: str) -> dict:
    """Módulo liberado **e** papel de administrador.

    Espelha o ``require_admin_user`` das telas: há dados que a tela só mostra a
    admin (ex.: desempenho individual de advogado), e o MCP não pode ser uma porta
    lateral para eles. O papel vem das claims do token, renovadas a cada hora — um
    usuário rebaixado perde o acesso na próxima renovação, como nos módulos.
    """
    claims = require_module(module_key)
    if str(claims.get("role") or "").strip().lower() != "admin":
        raise ToolError(
            "Acesso negado: esta informação é restrita a administradores do escritório "
            "(mesma regra da tela no sistema)."
        )
    return claims
