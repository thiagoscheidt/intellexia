"""
Tools: Revisor de Petições FAP — revisão feita no Claude
========================================================
O Claude do usuário revisa a petição na própria conversa, com o arquivo que já
está anexado, seguindo as mesmas instruções que o agente revisor do escritório
recebe. O IntellexIA não recebe a petição: entrega as instruções, confere o
JSON do resultado e, se o usuário quiser, grava a revisão no histórico com o
selo "Feita no Claude". `mudar_status_peticao` muda o status da petição com
as regras da tela, quando o usuário pede.

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
    planilha_beneficios=None,
) -> dict:
    """Confere o JSON do Claude (parse + saneador) e guarda o rascunho."""
    from app.services import fap_review_claude_service as claude_svc

    if not user_id:
        return dict(_SEM_USUARIO)
    return claude_svc.conferir(
        law_firm_id, user_id, resultado_json, modo,
        identificador=identificador_documento, peticao_id=peticao_id,
        planilha_beneficios=planilha_beneficios,
    )


def spreadsheet_script_handler() -> dict:
    """Script da checagem da planilha de benefícios, para o Claude rodar no ambiente dele."""
    from app.services import fap_review_claude_service as claude_svc

    return claude_svc.script_planilha()


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


# ── Status da petição ────────────────────────────────────────────────


def _status_pedido(texto: str) -> str | None:
    """Código do status a partir do código ou do nome em português ("Aguardando aprovação")."""
    import unicodedata

    from app.services.fap_review_service import PETITION_WORKFLOW_STATUSES

    def chave(valor) -> str:
        sem_acento = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode()
        return " ".join(sem_acento.lower().replace("_", " ").split())

    pedido = chave(texto)
    for codigo, rotulo in PETITION_WORKFLOW_STATUSES.items():
        if pedido in (chave(codigo), chave(rotulo)):
            return codigo
    return None


def change_status_handler(
    law_firm_id: int,
    user_id: int | None,
    novo_status: str,
    peticao_id: int | None = None,
    identificador: str | None = None,
) -> dict:
    """Muda o status da petição com as mesmas regras da tela (change_petition_status).

    O papel do usuário é relido do banco a cada chamada: o token do MCP guarda
    um retrato das permissões de quando foi autorizado, e um admin rebaixado
    continuaria aprovando.
    """
    from app.models import FapReviewPetition, User
    from app.services import fap_review_service as svc
    from app.utils.permissions import has_module_permission

    user = User.query.get(user_id) if user_id else None
    if (not user or not user.is_active or user.law_firm_id != law_firm_id
            or not user.law_firm or not user.law_firm.is_active
            or not has_module_permission("fap_review", user.role, user.module_permissions)):
        return {"erro": "Seu usuário não tem acesso ao Revisor de Petições neste escritório."}

    codigo = _status_pedido(novo_status)
    if not codigo:
        validos = ", ".join(f"{rotulo} ({c})" for c, rotulo in svc.PETITION_WORKFLOW_STATUSES.items())
        return {"erro": f'Status "{novo_status}" não existe. Use um destes: {validos}.'}

    query = FapReviewPetition.query.filter_by(law_firm_id=law_firm_id)
    if peticao_id:
        petition = query.filter_by(id=peticao_id).first()
    elif (identificador or "").strip():
        petition = query.filter_by(office_document_identifier=identificador.strip()).first()
    else:
        return {"erro": "Informe a petição: 'peticao_id' ou o Id Wrike em 'identificador'."}
    if not petition:
        return {"erro": "Petição não encontrada neste escritório."}

    rotulo = svc.PETITION_WORKFLOW_STATUSES
    try:
        anterior = svc.change_petition_status(petition, codigo, user_id=user.id, user_role=user.role,
                                              via="via Claude")
    except svc.StatusChangeRefused as e:
        return {"erro": str(e), "peticao_id": petition.id, "status_atual": petition.workflow_status,
                "status_atual_descricao": rotulo.get(petition.workflow_status, petition.workflow_status)}

    resposta = {
        "peticao_id": petition.id,
        "identificador": petition.office_document_identifier,
        "titulo": petition.title,
        "status_anterior": anterior,
        "status_anterior_descricao": rotulo.get(anterior, anterior),
        "status": codigo,
        "status_descricao": rotulo[codigo],
    }
    if anterior == codigo:
        resposta["sem_mudanca"] = True
        resposta["mensagem_para_usuario"] = f'A petição "{petition.title}" já está em "{rotulo[codigo]}".'
    else:
        resposta["mensagem_para_usuario"] = (
            f'A petição "{petition.title}" passou de "{rotulo.get(anterior, anterior)}" para "{rotulo[codigo]}".')
    return resposta
