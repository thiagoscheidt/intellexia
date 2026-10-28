"""
Tools: Revisor de Petições FAP — revisão feita no Claude
========================================================
O Claude do usuário revisa a petição na própria conversa, com o arquivo que já
está anexado, seguindo as mesmas instruções que o agente revisor do escritório
recebe. O IntellexIA não recebe a petição: entrega as instruções, confere o
JSON do resultado e, se o usuário quiser, grava a revisão no histórico com o
selo "Feita no Claude".

Substitui a revisão no servidor do RPI-37 (arquivo por link de envio, `curl`
ou Drive). Regras em ``app/services/fap_review_claude_service.py``.
"""
from __future__ import annotations

_SEM_USUARIO = {"erro": "Não foi possível identificar o usuário desta conexão. Conecte o IntellexIA de novo."}


def review_instructions_handler(
    law_firm_id: int,
    modo: str,
    identificador_documento: str | None = None,
    peticao_id: int | None = None,
    parte: int = 1,
) -> dict:
    """Uma parte das instruções do Revisor para o Claude revisar na conversa."""
    from app.services import fap_review_claude_service as claude_svc

    return claude_svc.instrucoes(
        law_firm_id, modo, identificador=identificador_documento, peticao_id=peticao_id, parte=parte,
    )


def confer_review_handler(
    law_firm_id: int,
    user_id: int | None,
    resultado_json,
    modo: str = "revisao",
    identificador_documento: str | None = None,
    peticao_id: int | None = None,
) -> dict:
    """Confere o JSON do Claude (parse + saneador) e guarda o rascunho."""
    from app.services import fap_review_claude_service as claude_svc

    if not user_id:
        return dict(_SEM_USUARIO)
    return claude_svc.conferir(
        law_firm_id, user_id, resultado_json, modo,
        identificador=identificador_documento, peticao_id=peticao_id,
    )


def save_review_handler(
    law_firm_id: int,
    user_id: int | None,
    rascunho_id: int,
    identificador_documento: str | None = None,
    peticao_id: int | None = None,
    titulo: str = "",
    nome_arquivo: str = "",
    modelo: str = "",
) -> dict:
    """Grava o rascunho conferido no histórico da petição ("Feita no Claude")."""
    from app.services import fap_review_claude_service as claude_svc

    if not user_id:
        return dict(_SEM_USUARIO)
    return claude_svc.gravar(
        law_firm_id, user_id, rascunho_id,
        identificador=identificador_documento, peticao_id=peticao_id,
        titulo=titulo, nome_arquivo=nome_arquivo, modelo=modelo,
    )
