"""
Tools: Revisor de Petições FAP
==============================
Usa o FapPetitionReviewerAgent real (mesmo agente do módulo Revisor de
Petições), com os prompts e referências ativos do escritório — manual FAP,
casos de referência e instruções de projeto versionados por law_firm.
"""
from __future__ import annotations

import asyncio
import os


def _build_agent(law_firm_id: int):
    """Agente revisor com os prompts, referências e configuração do escritório."""
    from app.agents.fap_review.reviewer_agent import FapPetitionReviewerAgent
    from app.models import FapReviewPromptVersion, FapReviewReferenceVersion, FapReviewSetting

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY não configurada no servidor.")

    def _active_reference(ref_type: str) -> str:
        row = FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id, reference_type=ref_type, is_active=True
        ).first()
        return row.content if row else ""

    def _active_prompt(prompt_type: str) -> str:
        row = FapReviewPromptVersion.query.filter_by(
            law_firm_id=law_firm_id, prompt_type=prompt_type, is_active=True
        ).first()
        return row.content if row else ""

    setting = FapReviewSetting.query.filter_by(law_firm_id=law_firm_id).first()
    model = setting.reviewer_model if setting else "gpt-4o-mini"
    temperature = setting.reviewer_temperature if setting else 0.0

    agent = FapPetitionReviewerAgent(
        openai_api_key=openai_api_key,
        model=model,
        temperature=temperature,
    )
    agent.load_reference_documents(
        manual_md=_active_reference("manual_fap"),
        cases_md=_active_reference("casos_referencia"),
        project_instructions_md=_active_reference("project_instructions"),
    )
    prompts = {
        "reviewer_identity": _active_prompt("revisor_identity"),
        "reviewer_rules": _active_prompt("revisor_rules"),
        "reviewer_output_format": _active_prompt("revisor_output_format"),
    }
    return agent, prompts, model


def compare_petition_versions_handler(
    texto_original: str,
    texto_revisado: str,
    law_firm_id: int,
    user_id: int | None = None,
    identificador_documento: str | None = None,
    titulo: str = "",
) -> dict:
    """Revisão comparativa (versão original × revisada) com o agente do escritório.

    A tela já faz isso; o MCP só sabia revisar versão única. Responde "a v2
    corrigiu o que o revisor apontou?" com o próprio agente, em vez de o
    assistente comparar os textos por conta.
    """
    texto_original = (texto_original or "").strip()
    texto_revisado = (texto_revisado or "").strip()
    if len(texto_original) < 200 or len(texto_revisado) < 200:
        return {
            "erro": "Envie o texto completo das duas versões (mínimo ~200 caracteres cada)."
        }

    try:
        agent, prompts, model = _build_agent(law_firm_id)
    except RuntimeError as e:
        return {"erro": str(e)}

    result = asyncio.run(agent.review_petition_comparative(
        original_petition_file_path="",
        revised_petition_file_path="",
        original_petition_text=texto_original,
        revised_petition_text=texto_revisado,
        user_id=user_id,
        law_firm_id=law_firm_id,
        **prompts,
    ))

    payload = result.model_dump(mode="json")
    payload["modelo_utilizado"] = model
    payload["tipo_analise"] = "comparativa"

    identificador = (identificador_documento or "").strip()
    if not identificador:
        payload["registrado_no_sistema"] = False
        payload["aviso_registro"] = (
            "Comparação não registrada no módulo Revisor: informe "
            "'identificador_documento' para que ela entre no histórico da petição."
        )
        return payload

    from app.services.fap_review_service import record_text_review

    try:
        registro = record_text_review(
            law_firm_id=law_firm_id,
            user_id=user_id,
            identifier=identificador,
            petition_text=texto_revisado,
            result_payload=payload,
            title=titulo,
            comparative=True,
        )
    except ValueError as e:
        payload["registrado_no_sistema"] = False
        payload["aviso_registro"] = f"Comparação não registrada: {e}"
        return payload

    payload["registrado_no_sistema"] = True
    payload.update(registro)
    return payload


def review_petition_handler(
    petition_text: str,
    law_firm_id: int,
    case_type: str = "trabalhista",
    user_id: int | None = None,
    identificador_documento: str | None = None,
    titulo: str = "",
) -> dict:
    """Revisa o texto de uma petição com o agente revisor oficial do escritório.

    Com ``identificador_documento``, a revisão é **registrada no módulo** (entra no
    histórico da petição, no custo e no status do fluxo), igual à feita pela tela.
    Sem ele, a revisão é efêmera — e a resposta diz isso, para o agente não dar a
    entender que ficou salva.
    """
    from app.agents.fap_review.reviewer_agent import FapPetitionReviewerAgent
    from app.models import FapReviewPromptVersion, FapReviewReferenceVersion, FapReviewSetting

    petition_text = (petition_text or "").strip()
    if len(petition_text) < 200:
        return {
            "erro": "Texto da petição muito curto para revisão (mínimo ~200 caracteres). "
                    "Envie o texto completo da petição."
        }

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        return {"erro": "OPENAI_API_KEY não configurada no servidor."}

    def _active_reference(ref_type: str) -> str:
        row = FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id, reference_type=ref_type, is_active=True
        ).first()
        return row.content if row else ""

    def _active_prompt(prompt_type: str) -> str:
        row = FapReviewPromptVersion.query.filter_by(
            law_firm_id=law_firm_id, prompt_type=prompt_type, is_active=True
        ).first()
        return row.content if row else ""

    setting = FapReviewSetting.query.filter_by(law_firm_id=law_firm_id).first()
    model = setting.reviewer_model if setting else "gpt-4o-mini"
    temperature = setting.reviewer_temperature if setting else 0.0

    agent = FapPetitionReviewerAgent(
        openai_api_key=openai_api_key,
        model=model,
        temperature=temperature,
    )
    agent.load_reference_documents(
        manual_md=_active_reference("manual_fap"),
        cases_md=_active_reference("casos_referencia"),
        project_instructions_md=_active_reference("project_instructions"),
    )

    result = asyncio.run(agent.review_petition_single_version(
        petition_file_path="",
        petition_text=petition_text,
        reviewer_identity=_active_prompt("revisor_identity"),
        reviewer_rules=_active_prompt("revisor_rules"),
        reviewer_output_format=_active_prompt("revisor_output_format"),
        user_id=user_id,
        law_firm_id=law_firm_id,
    ))

    payload = result.model_dump(mode="json")
    payload["modelo_utilizado"] = model
    payload["tipo_caso"] = case_type

    identificador = (identificador_documento or "").strip()
    if not identificador:
        payload["registrado_no_sistema"] = False
        payload["aviso_registro"] = (
            "Revisão não registrada no módulo Revisor: informe 'identificador_documento' "
            "para que ela entre no histórico da petição, no custo e no status do fluxo."
        )
        return payload

    from app.services.fap_review_service import record_text_review

    try:
        registro = record_text_review(
            law_firm_id=law_firm_id,
            user_id=user_id,
            identifier=identificador,
            petition_text=petition_text,
            result_payload=payload,
            title=titulo,
        )
    except ValueError as e:
        # A revisão foi feita; só o registro falhou — devolve o resultado assim mesmo.
        payload["registrado_no_sistema"] = False
        payload["aviso_registro"] = f"Revisão não registrada: {e}"
        return payload

    payload["registrado_no_sistema"] = True
    payload.update(registro)
    return payload
