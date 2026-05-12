"""
Subagente de aplicação de treinamento FAP.

Fluxo:
1. Gerar extrato comparativo entre dois documentos.
2. Após confirmação humana, preparar atualizações para manual e casos.
"""

import json
import os
from datetime import datetime
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class ComparisonExtract(BaseModel):
    """Extrato da comparação para validação humana."""

    comparison_summary: str = Field(..., description="Resumo executivo da comparação")
    key_changes: list[str] = Field(default_factory=list, description="Principais alterações detectadas")
    suggested_manual_updates: list[dict[str, str]] = Field(
        default_factory=list,
        description="Sugestões de atualização do manual",
    )
    suggested_case_reference_updates: list[str] = Field(
        default_factory=list,
        description="Sugestões para casos de referência",
    )
    training_ready: bool = Field(default=True, description="Se há insumos para treino")
    recommendation: str = Field(default="", description="Recomendação final ao usuário")


class TrainingApplyPayload(BaseModel):
    """Payload gerado após confirmação para atualizar base."""

    manual_patch_markdown: str = Field(default="", description="Trecho a anexar no manual")
    case_reference_markdown: str = Field(default="", description="Trecho a anexar em casos de referência")
    version_increment: str = Field(default="patch", description="patch/minor/major")
    should_update_manual: bool = Field(default=False)
    should_update_cases: bool = Field(default=False)
    message: str = Field(default="")


class FapTrainingApplySubAgent:
    """Subagente responsável pelo extrato e payload de aplicação do treinamento."""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
    ):
        api_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        self.llm = ChatOpenAI(api_key=api_key, model=model, temperature=temperature)

    async def build_comparison_extract(
        self,
        original_text: str,
        revised_text: str,
        training_identity: str = "",
        training_rules: str = "",
        training_prompt: str = "",
    ) -> ComparisonExtract:
        """Gera extrato estruturado para revisão humana antes de treinar."""

        system_prompt = (
            "Voce e um subagente de comparacao juridica FAP. "
            "Sua funcao e gerar um extrato claro para decisao humana, sem aplicar atualizacoes automaticamente.\n\n"
            f"IDENTIDADE:\n{training_identity or 'Apoiar decisao de treinamento com objetividade.'}\n\n"
            f"REGRAS:\n{training_rules or 'Priorize clareza, rastreabilidade e conservadorismo.'}\n\n"
            f"PROMPT DE TREINAMENTO:\n{training_prompt or 'Sugira apenas atualizacoes com base no texto comparado.'}"
        )

        user_prompt = (
            "Compare os dois textos abaixo e retorne SOMENTE JSON com as chaves:\n"
            "comparison_summary (string),\n"
            "key_changes (array de strings),\n"
            "suggested_manual_updates (array de objetos com section, update, rationale),\n"
            "suggested_case_reference_updates (array de strings),\n"
            "training_ready (boolean),\n"
            "recommendation (string).\n\n"
            f"TEXTO ORIGINAL (recorte):\n{original_text[:12000]}\n\n"
            f"TEXTO REVISADO (recorte):\n{revised_text[:12000]}"
        )

        try:
            response = self.llm.invoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            )
            parsed = self._parse_json(response.content)
            return ComparisonExtract(**parsed)
        except Exception:
            return ComparisonExtract(
                comparison_summary="Nao foi possivel gerar extrato estruturado completo.",
                key_changes=["Falha na geracao automatica do extrato."],
                suggested_manual_updates=[],
                suggested_case_reference_updates=[],
                training_ready=False,
                recommendation="Revisar arquivos manualmente antes de treinar.",
            )

    async def build_apply_payload(
        self,
        extract_data: dict[str, Any],
        training_update_policy: str = "",
        manual_version: str = "1.0.0",
        original_filename: str = "",
        revised_filename: str = "",
    ) -> TrainingApplyPayload:
        """Gera payload para atualizar manual e casos apos confirmacao do usuario."""

        system_prompt = (
            "Voce e um subagente de aplicacao de treinamento FAP. "
            "Gere patches concisos para serem anexados no manual e casos de referencia.\n\n"
            f"POLITICA DE ATUALIZACAO:\n{training_update_policy or 'Atualizar somente com evidencias do extrato.'}\n"
        )

        user_prompt = (
            "Com base no extrato validado pelo usuario, retorne SOMENTE JSON com:\n"
            "manual_patch_markdown (string markdown),\n"
            "case_reference_markdown (string markdown),\n"
            "version_increment (patch/minor/major),\n"
            "should_update_manual (boolean),\n"
            "should_update_cases (boolean),\n"
            "message (string).\n\n"
            f"VERSAO ATUAL DO MANUAL: {manual_version}\n"
            f"ARQUIVO ORIGINAL: {original_filename}\n"
            f"ARQUIVO REVISADO: {revised_filename}\n"
            f"EXTRATO:\n{json.dumps(extract_data, ensure_ascii=False, indent=2)}"
        )

        try:
            response = self.llm.invoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            )
            parsed = self._parse_json(response.content)
            return TrainingApplyPayload(**parsed)
        except Exception:
            now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
            return TrainingApplyPayload(
                manual_patch_markdown=(
                    f"\n\n---\n### Atualizacao de Treinamento ({now_str})\n"
                    "- Nao foi possivel gerar patch automatico detalhado.\n"
                ),
                case_reference_markdown=(
                    f"\n\n---\n### Registro de Treinamento ({now_str})\n"
                    "- Nao foi possivel gerar caso de referencia detalhado.\n"
                ),
                version_increment="patch",
                should_update_manual=False,
                should_update_cases=False,
                message="Falha na geracao automatica do payload de aplicacao.",
            )

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        """Extrai o primeiro objeto JSON valido do texto."""
        if not content:
            return {}

        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}

        snippet = content[start : end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            return {}
