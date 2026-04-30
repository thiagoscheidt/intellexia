from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.agents.config import DEFAULT_MODEL_MINI
from app.services.token_usage_service import TokenUsageService


logger = logging.getLogger(__name__)


class FAPContestationClassifierAgent:
    """Classifica justificativas de contestação FAP em um tópico jurídico padronizado."""

    ALLOWED_TOPICS: tuple[str, ...] = (
        "NEXO TÉCNICO PREVIDENCIÁRIO PENDENTE DE JULGAMENTO",
        "ACIDENTE DE TRAJETO",
        "ACIDENTE DE TRAJETO SEM CAT – AÇÃO JUDICIAL",
        "RESTABELECIMENTO DE BENEFÍCIO – B91 60 DIAS",
        "AUXÍLIO-DOENÇA PREVIDENCIÁRIO – B31",
        "ERRO DE ESTABELECIMENTO",
        "PRÉ-FAP",
        "OUTRA EMPRESA – CAT VINCULADA",
        "OUTRA EMPRESA – NUNCA FOI EMPREGADO",
        "OUTRA EMPRESA – APÓS A RESCISÃO CONTRATUAL",
        "OUTRA EMPRESA – DID ANTERIOR À ADMISSÃO NA EMPRESA",
        "NEXO AFASTADO",
        "BENEFÍCIO CONCEDIDO NA JUSTIÇA FEDERAL",
        "CONCOMITANTE – AUXÍLIO-DOENÇA (B91) COM APOSENTADORIA",
        "CONCESSÃO CONCOMITANTE DE DOIS AUXÍLIO-DOENÇA",
        "CONCESSÃO - AUXÍLIO-ACIDENTE (B94) COM APOSENTADORIA",
        "AUXÍLIO-ACIDENTE (B94) DUPLICADO",
        "AUXÍLIO-DOENÇA (B94) SEM CUSTO",
        "DISCUSSÃO MÉDICA / OUTROS ARGUMENTOS",
        "OUTROS ARGUMENTOS",
    )

    SLUG_TO_TOPIC: dict[str, str] = {
        "nexo_pendente": "NEXO TÉCNICO PREVIDENCIÁRIO PENDENTE DE JULGAMENTO",
        "acidente_trajeto": "ACIDENTE DE TRAJETO",
        "acidente_trajeto_sem_cat": "ACIDENTE DE TRAJETO SEM CAT – AÇÃO JUDICIAL",
        "restabelecimento_b91_60": "RESTABELECIMENTO DE BENEFÍCIO – B91 60 DIAS",
        "b31_previdenciario": "AUXÍLIO-DOENÇA PREVIDENCIÁRIO – B31",
        "erro_estabelecimento": "ERRO DE ESTABELECIMENTO",
        "pre_fap": "PRÉ-FAP",
        "outra_empresa_cat": "OUTRA EMPRESA – CAT VINCULADA",
        "outra_empresa_nunca_empregado": "OUTRA EMPRESA – NUNCA FOI EMPREGADO",
        "outra_empresa_pos_rescisao": "OUTRA EMPRESA – APÓS A RESCISÃO CONTRATUAL",
        "outra_empresa_did_anterior": "OUTRA EMPRESA – DID ANTERIOR À ADMISSÃO NA EMPRESA",
        "nexo_afastado": "NEXO AFASTADO",
        "beneficio_justica_federal": "BENEFÍCIO CONCEDIDO NA JUSTIÇA FEDERAL",
        "concomitante_b91_aposentadoria": "CONCOMITANTE – AUXÍLIO-DOENÇA (B91) COM APOSENTADORIA",
        "concomitante_dois_b91": "CONCESSÃO CONCOMITANTE DE DOIS AUXÍLIO-DOENÇA",
        "concomitante_b94_aposentadoria": "CONCESSÃO - AUXÍLIO-ACIDENTE (B94) COM APOSENTADORIA",
        "b94_duplicado": "AUXÍLIO-ACIDENTE (B94) DUPLICADO",
        "b94_sem_custo": "AUXÍLIO-DOENÇA (B94) SEM CUSTO",
        "discussao_medica": "DISCUSSÃO MÉDICA / OUTROS ARGUMENTOS",
        "outros_argumentos": "OUTROS ARGUMENTOS",
    }
    VALID_SLUGS: set[str] = set(SLUG_TO_TOPIC.keys())

    MEDICAL_TERMS: tuple[str, ...] = (
        "laudo",
        "pericia",
        "diagnostico",
        "cid",
        "atestado",
        "prognostico",
        "parecer medico",
        "prontuario",
        "incapacidade",
    )

    def __init__(self, model_name: str | None = None, temperature: float = 0.1):
        self.model_name = model_name or os.environ.get("FAP_CLASSIFIER_MODEL") or DEFAULT_MODEL_MINI
        self.temperature = temperature
        self.llm = ChatOpenAI(model=self.model_name, temperature=self.temperature)
        self.token_usage_service = TokenUsageService()

    @classmethod
    def _normalize_topic(cls, value: str | None) -> str:
        if not value:
            return ""

        normalized = str(value).strip().upper()
        replacements = {
            "TÉ": "TE",
            "É": "E",
            "Ê": "E",
            "Ã": "A",
            "Á": "A",
            "Â": "A",
            "À": "A",
            "Í": "I",
            "Ó": "O",
            "Ô": "O",
            "Õ": "O",
            "Ú": "U",
            "Ç": "C",
            "–": "-",
            "—": "-",
            "‑": "-",
        }

        for old, new in replacements.items():
            normalized = normalized.replace(old, new)

        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @classmethod
    def _build_topic_lookup(cls) -> dict[str, str]:
        return {cls._normalize_topic(topic): topic for topic in cls.ALLOWED_TOPICS}

    @classmethod
    def _get_canonical_topic(cls, topic: str | None) -> str | None:
        normalized = cls._normalize_topic(topic)
        if not normalized:
            return None

        topic_lookup = cls._build_topic_lookup()
        return topic_lookup.get(normalized)

    @classmethod
    def _normalize_text_for_match(cls, value: str) -> str:
        normalized = cls._normalize_topic(value)
        normalized = normalized.replace("-", " ")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @staticmethod
    def _strip_markdown_json_fence(raw_content: str) -> str:
        content = (raw_content or "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?", "", content, flags=re.IGNORECASE).strip()
            if content.endswith("```"):
                content = content[:-3].strip()
        return content

    def _safe_parse_json(self, raw_content: str) -> dict[str, Any] | None:
        if not raw_content:
            return None

        content = self._strip_markdown_json_fence(raw_content)

        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
            return None
        except Exception:
            # Fallback para respostas com texto adicional fora do JSON.
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if not match:
                return None

            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None

    def _fallback_topic(self, text: str) -> str:
        normalized_text = self._normalize_text_for_match(text)
        if any(term.upper() in normalized_text for term in self.MEDICAL_TERMS):
            return "DISCUSSÃO MÉDICA / OUTROS ARGUMENTOS"
        return "OUTROS ARGUMENTOS"

    def _fallback_slug(self, text: str) -> str:
        normalized_text = self._normalize_text_for_match(text)
        if any(term.upper() in normalized_text for term in self.MEDICAL_TERMS):
            return "discussao_medica"
        return "outros_argumentos"

    @staticmethod
    def _extract_last_message_content(response_payload: dict[str, Any] | None) -> str:
        if not isinstance(response_payload, dict):
            return ""

        messages = response_payload.get("messages")
        if not isinstance(messages, list) or not messages:
            return ""

        last_message = messages[-1]

        if hasattr(last_message, "content"):
            return str(last_message.content or "").strip()

        if isinstance(last_message, dict):
            return str(last_message.get("content", "") or "").strip()

        return str(last_message or "").strip()

    def classify(self, text: str, *, law_firm_id: int | None = None) -> dict[str, Any]:
        """
        Classifica um texto de justificativa FAP em tópico padronizado.

        Returns:
            Dict no formato:
            {
              "topic": "TOPICO PRINCIPAL",
              "topics": ["TOPICO 1", "TOPICO 2", ...]
            }
        """
        cleaned_text = (text or "").strip()
        if not cleaned_text:
            return {
                "topic": "OUTROS ARGUMENTOS",
                "topics": ["OUTROS ARGUMENTOS"],
            }

        system_prompt = (
            "Voce e um especialista juridico em FAP. "
            "Classifique o texto em ATE 3 topicos e retorne JSON valido. "
            "Ordene por relevancia, com o principal na primeira posicao. "
            "DISCUSSAO MEDICA / OUTROS ARGUMENTOS so pode ser usada quando nenhum outro topico especifico se aplicar. "
            "Prefira sempre topicos juridicos especificos quando houver evidencia textual suficiente. "
            "Evite falso positivo: nunca retorne PRE-FAP, B31 ou NEXO PENDENTE sem evidencia textual explicita. "
            "Quando houver indicio de acidente vinculado a outro CNPJ/estabelecimento, priorize categorias de OUTRA EMPRESA e/ou ERRO DE ESTABELECIMENTO. "
            "Priorize interpretacao juridica. "
            "Nunca invente categorias."
        )

        user_prompt = (
            "Classifique o texto e retorne uma lista de SLUGS (de 1 a 3).\n\n"
            "Topicos:\n"
            "NEXO TECNICO PREVIDENCIARIO PENDENTE DE JULGAMENTO -> nexo_pendente\n"
            "ACIDENTE DE TRAJETO -> acidente_trajeto\n"
            "ACIDENTE DE TRAJETO SEM CAT - ACAO JUDICIAL -> acidente_trajeto_sem_cat\n"
            "RESTABELECIMENTO DE BENEFICIO - B91 60 DIAS -> restabelecimento_b91_60\n"
            "AUXILIO-DOENCA PREVIDENCIARIO - B31 -> b31_previdenciario\n"
            "ERRO DE ESTABELECIMENTO -> erro_estabelecimento\n"
            "PRE-FAP -> pre_fap\n"
            "OUTRA EMPRESA - CAT VINCULADA -> outra_empresa_cat\n"
            "OUTRA EMPRESA - NUNCA FOI EMPREGADO -> outra_empresa_nunca_empregado\n"
            "OUTRA EMPRESA - APOS A RESCISAO -> outra_empresa_pos_rescisao\n"
            "OUTRA EMPRESA - DID ANTERIOR -> outra_empresa_did_anterior\n"
            "NEXO AFASTADO -> nexo_afastado\n"
            "BENEFICIO NA JUSTICA FEDERAL -> beneficio_justica_federal\n"
            "B91 COM APOSENTADORIA -> concomitante_b91_aposentadoria\n"
            "DOIS B91 -> concomitante_dois_b91\n"
            "B94 COM APOSENTADORIA -> concomitante_b94_aposentadoria\n"
            "B94 DUPLICADO -> b94_duplicado\n"
            "B94 SEM CUSTO -> b94_sem_custo\n"
            "DISCUSSAO MEDICA -> discussao_medica\n"
            "OUTROS -> outros_argumentos\n\n"
            "Regras:\n"
            "- Retorne de 1 a 3 slugs validos, sem duplicidade\n"
            "- O primeiro slug deve ser o tema principal\n"
            "- So use discussao_medica quando NAO houver enquadramento claro em nenhum outro topico especifico\n"
            "- Se houver ao menos um topico especifico aplicavel, NAO inclua discussao_medica\n"
            "- Nao retorne pre_fap, b31_previdenciario ou nexo_pendente sem mencao textual clara e direta\n"
            "- Se o texto indicar outro CNPJ, outro estabelecimento, ou ausencia de nexo com este estabelecimento, priorize uma das categorias abaixo:\n"
            "  - outra_empresa_cat\n"
            "  - outra_empresa_nunca_empregado\n"
            "  - outra_empresa_pos_rescisao\n"
            "  - outra_empresa_did_anterior\n"
            "  - erro_estabelecimento\n"
            "- Informe reason apenas quando confidence >= 0.80; caso contrario, reason deve ser string vazia\n"
            "- Se nao houver encaixe:\n"
            "  - Se houver termos medicos -> discussao_medica\n"
            "  - Caso contrario -> outros_argumentos\n\n"
            "Exemplos de sinal forte para OUTRA EMPRESA/ERRO DE ESTABELECIMENTO:\n"
            "- 'nao relacionado a este estabelecimento'\n"
            "- 'acidente vinculado a outro CNPJ'\n"
            "- 'requer exclusao da base de calculo FAP deste estabelecimento por vinculo a outro estabelecimento'\n\n"
            "Formato:\n"
            '{"topics":["slug1","slug2"],"confidence":0.0,"reason":"explicacao curta ou vazio"}\n\n'
            f"Texto:\n{cleaned_text}"
        )

        try:
            agent = create_agent(model=self.llm, system_prompt=system_prompt)

            call_started_at = time.time()
            response_payload = agent.invoke(
                {"messages": [{"role": "user", "content": user_prompt}]}
            )
            latency_ms = int((time.time() - call_started_at) * 1000)

            self.token_usage_service.capture_and_store(
                response_payload,
                agent_name="FAPContestationClassifierAgent",
                action_name="classify",
                print_prefix="[FAPContestationClassifierAgent][tokens]",
                model_name=self.model_name,
                model_provider="openai",
                user_id=None,
                law_firm_id=law_firm_id,
                chat_session_id=None,
                latency_ms=latency_ms,
                status="success",
                metadata_payload={
                    "input_chars": len(cleaned_text),
                    "temperature": self.temperature,
                },
            )

            raw_content = self._extract_last_message_content(response_payload)
            parsed = self._safe_parse_json(raw_content)

            if not parsed:
                return {
                    "topic": "OUTROS ARGUMENTOS",
                    "topics": ["OUTROS ARGUMENTOS"],
                }

            raw_topics = parsed.get("topics")
            topics_slugs: list[str] = []

            if isinstance(raw_topics, list):
                for item in raw_topics:
                    slug = str(item or "").strip().lower()
                    if slug in self.VALID_SLUGS and slug not in topics_slugs:
                        topics_slugs.append(slug)
                    if len(topics_slugs) >= 3:
                        break

            # Compatibilidade com formato antigo: {"topic":"slug"}
            if not topics_slugs:
                topic_slug = str(parsed.get("topic") or "").strip().lower()
                if topic_slug in self.VALID_SLUGS:
                    topics_slugs = [topic_slug]

            if not topics_slugs:
                fallback_slug = self._fallback_slug(cleaned_text)
                return {
                    "topic": self.SLUG_TO_TOPIC[fallback_slug],
                    "topics": [self.SLUG_TO_TOPIC[fallback_slug]],
                }

            topics = [self.SLUG_TO_TOPIC[slug] for slug in topics_slugs]

            return {
                "topic": topics[0],
                "topics": topics,
            }

        except Exception as exc:
            logger.exception("Erro ao classificar justificativa FAP: %s", exc)
            return {
                "topic": "OUTROS ARGUMENTOS",
                "topics": ["OUTROS ARGUMENTOS"],
            }
