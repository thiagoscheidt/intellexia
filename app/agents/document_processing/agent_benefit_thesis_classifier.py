import os
import re
import logging
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from markitdown import MarkItDown
from pydantic import BaseModel, Field
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


load_dotenv()


class BenefitThesisClassificationItem(BaseModel):
    benefit_number: str = Field(default="", description="Numero do beneficio (NB)")
    legal_thesis_id: Optional[int] = Field(default=None, description="ID da tese juridica escolhida")
    legal_thesis_name: str = Field(default="", description="Nome da tese juridica escolhida")


class BenefitThesisClassificationResult(BaseModel):
    classifications: list[BenefitThesisClassificationItem] = Field(
        default_factory=list,
        description="Classificacao de tese por beneficio",
    )


class AgentBenefitThesisClassifier:
    """Classifica beneficios em teses juridicas usando paginas finais (pedidos) do documento."""

    def __init__(
        self,
        model_name: str = "gpt-5-mini",
        model_provider: str | None = None,
        final_pages_count: int = 6,
        max_context_chars: int = 24000,
    ):
        self.model_name = model_name
        self.model_provider = model_provider or os.getenv("BENEFIT_CLASSIFIER_MODEL_PROVIDER", "openai")
        self.final_pages_count = final_pages_count
        self.max_context_chars = max_context_chars
        self.chat_model = ChatOpenAI(model=self.model_name, temperature=0)

    @staticmethod
    def _clean_text(value: str) -> str:
        value = (value or "").replace("\u00a0", " ").strip()
        return re.sub(r"\s+", " ", value)

    @staticmethod
    def _normalize_digits(value: str | None) -> str:
        return re.sub(r"\D", "", str(value or ""))

    def _build_classifier_agent(self):
        return create_agent(
            model=self.chat_model,
            tools=[],
            system_prompt=(
                "Voce e um classificador juridico de beneficios previdenciarios. "
                "Para cada beneficio, escolha apenas uma tese entre as teses cadastradas, "
                "priorizando correspondencia com as secoes de pedidos do documento."
            ),
            response_format=ToolStrategy(BenefitThesisClassificationResult),
        )

    def _load_legal_theses_from_db(self, law_firm_id: int | None = None) -> list[dict[str, Any]]:
        if law_firm_id is None:
            logger.warning("law_firm_id nao informado para carregar teses juridicas")
            return []

        try:
            from app.models import JudicialLegalThesis

            items = (
                JudicialLegalThesis.query
                .filter_by(law_firm_id=law_firm_id, is_active=True)
                .order_by(JudicialLegalThesis.name.asc())
                .all()
            )
            result = [
                {
                    "id": item.id,
                    "key": str(item.key or "").strip(),
                    "name": str(item.name or "").strip(),
                }
                for item in items
                if str(item.name or "").strip()
            ]
            logger.info(f"Carregadas {len(result)} teses juridicas para law_firm_id={law_firm_id}")
            return result
        except Exception as e:
            logger.error(f"Erro ao carregar teses juridicas: {e}", exc_info=True)
            return []

    def _extract_text_for_final_search(
        self,
        file_path: str | Path,
        text_content: str | None = None,
    ) -> str:
        """Extrai e retorna os últimos 40% do texto do documento."""
        extracted_text = ""

        if text_content:
            extracted_text = text_content if isinstance(text_content, str) else str(text_content)
        else:
            file_path = str(file_path)
            if not file_path.lower().endswith(".pdf"):
                logger.warning(f"Arquivo nao eh PDF: {file_path}")
                return ""

            try:
                md = MarkItDown()
                print("Iniciando conversao da peticao para extracao de pedidos...")
                result = md.convert(file_path)
                extracted_text = result.text_content or ""
            except Exception as e:
                logger.error(f"Erro ao ler PDF para extrair trecho final: {e}", exc_info=True)
                return ""

        if not extracted_text.strip():
            raise ValueError("Nao foi possivel extrair texto do documento")

        print(f"Texto extraido: {len(extracted_text)} caracteres")

        start_idx = int(len(extracted_text) * 0.6)
        text_for_search = extracted_text[start_idx:]
        print(f"Focando nos ultimos 40% do documento: {len(text_for_search)} caracteres")
        return text_for_search

    def classify_benefits(
        self,
        file_path: str | Path,
        benefits: list[dict[str, Any]] | None,
        law_firm_id: int | None,
    ) -> dict[str, Any]:
        if not benefits:
            return {"classifications": []}

        normalized_benefits = []
        for item in benefits:
            if not isinstance(item, dict):
                continue
            benefit_number = self._normalize_digits(item.get("benefit_number"))
            if not benefit_number:
                continue
            normalized_benefits.append({
                "benefit_number": benefit_number,
                "benefit_type": str(item.get("benefit_type", "") or "").strip(),
                "insured_name": str(item.get("insured_name", "") or "").strip(),
            })

        if not normalized_benefits:
            return {"classifications": []}

        legal_theses = self._load_legal_theses_from_db(law_firm_id=law_firm_id)
        if not legal_theses:
            return {"classifications": []}

        theses_prompt = "\n".join(
            f"- id: {t['id']} | key: {t['key']} | nome: {t['name']}"
            for t in legal_theses
        )

        benefits_prompt = "\n".join(
            f"- beneficio: {b['benefit_number']} | tipo: {b['benefit_type']} | segurado: {b['insured_name']}"
            for b in normalized_benefits
        )

        final_context = self._extract_text_for_final_search(file_path=file_path)
        final_context_prompt = final_context or "(trecho final do documento nao encontrado)"
        user_prompt = (
            "Classifique cada beneficio em UMA tese juridica cadastrada.\n\n"
            "REGRAS:\n"
            "- Use apenas as teses cadastradas fornecidas.\n"
            "- Se nao houver confianca, retorne legal_thesis_id nulo e legal_thesis_name vazio.\n"
            "- Sempre retorne um item de classificacao para cada beneficio de entrada.\n\n"
            "BENEFICIOS:\n"
            f"{benefits_prompt}\n\n"
            "TESES CADASTRADAS:\n"
            f"{theses_prompt}\n\n"
            "TRECHO FINAL DO DOCUMENTO (ultimos 40%):\n"
            f"{final_context_prompt}"
        )

        try:
            logger.info(f"Invocando agente classificador para {len(normalized_benefits)} beneficios")
            agent = self._build_classifier_agent()
            response = agent.invoke({"messages": [{"role": "user", "content": user_prompt}]})
            logger.debug(f"Resposta do agente: {response}")
            structured_response = response.get("structured_response")
            if not structured_response:
                logger.warning("Resposta estruturada nao retornada no classificador")
                raise RuntimeError("Resposta estruturada nao retornada no classificador")

            payload = structured_response.model_dump()
            classifications = payload.get("classifications", []) if isinstance(payload, dict) else []
            logger.info(f"Recebidas {len(classifications)} classificacoes do agente")

            by_benefit: dict[str, dict[str, Any]] = {}
            for cls_item in classifications:
                if not isinstance(cls_item, dict):
                    continue
                bn = self._normalize_digits(cls_item.get("benefit_number"))
                if bn:
                    cls_item["benefit_number"] = bn
                    by_benefit[bn] = cls_item

            completed: list[dict[str, Any]] = []
            for item in normalized_benefits:
                bn = item["benefit_number"]
                existing = by_benefit.get(bn)
                if existing:
                    completed.append(existing)
                else:
                    completed.append(
                        {
                            "benefit_number": bn,
                            "legal_thesis_id": None,
                            "legal_thesis_name": "",
                        }
                    )

            logger.info(f"Classificacao completada com {len(completed)} items")
            return {"classifications": completed}
        except Exception as e:
            logger.error(f"Erro durante classificacao: {e}", exc_info=True)
            fallback = [
                {
                    "benefit_number": item["benefit_number"],
                    "legal_thesis_id": None,
                    "legal_thesis_name": "",
                }
                for item in normalized_benefits
            ]
            logger.warning(f"Retornando fallback com {len(fallback)} items")
            return {"classifications": fallback}
