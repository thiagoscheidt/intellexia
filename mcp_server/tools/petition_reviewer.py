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
) -> dict:
    """Revisa o texto de uma petição com o agente revisor oficial do escritório."""
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
    return payload
