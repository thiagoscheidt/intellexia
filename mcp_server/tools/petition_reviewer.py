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
