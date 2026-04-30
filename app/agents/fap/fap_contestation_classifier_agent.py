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

    PRE_FAP_TERMS: tuple[str, ...] = (
        "pre fap",
        "pre-fap",
        "art. 202-a",
        "art 202-a",
        "decreto 6.957",
        "decreto nº 6.957",
        "decreto n 6.957",
        "abril de 2007",
        "1º de abril de 2007",
        "1 de abril de 2007",
        "antes de abril de 2007",
        "anterior a abril de 2007",
        "antes de 2007",
        "did 200",
        "did 19",
    )

    OTHER_COMPANY_TERMS: tuple[str, ...] = (
        "outro cnpj",
        "outro estabelecimento",
        "outra empresa",
        "nao relacionado a este estabelecimento",
        "nao esta relacionado a este estabelecimento",
        "não relacionado a este estabelecimento",
        "não está relacionado a este estabelecimento",
        "nunca foi empregado",
        "apos a rescisao",
        "após a rescisão",
        "did anterior a admissao",
        "did anterior à admissão",
        "cat vinculada",
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

    def _has_pre_fap_evidence(self, normalized_text: str) -> bool:
        if any(term.upper() in normalized_text for term in self.PRE_FAP_TERMS):
            return True

        year_matches = re.findall(r"\b(19\d{2}|20\d{2})\b", normalized_text)
        if year_matches and any(int(year) < 2007 for year in year_matches):
            if "DID" in normalized_text or "ACIDENT" in normalized_text:
                return True

        return False

    def _has_other_company_evidence(self, normalized_text: str) -> bool:
        if any(term.upper() in normalized_text for term in self.OTHER_COMPANY_TERMS):
            return True

        # Cobrir variacoes frasais comuns em justificativas de erro de estabelecimento.
        if re.search(
            r"NAO\s+(?:ESTA\s+)?RELACIONAD[OA]\s+A\s+ESTE\s+ESTABELECIMENTO",
            normalized_text,
        ):
            return True

        # Quando ha mencao de CNPJ diferente em contexto de estabelecimento, tambem e forte indicio.
        if "CNPJ" in normalized_text and "ESTABELECIMENTO" in normalized_text and "NAO" in normalized_text:
            return True

        return False

    def _detect_critical_regex_slugs(self, normalized_text: str) -> list[str]:
        detected: list[str] = []

        has_ntp = bool(re.search(r"\bNTP\b|NEXO TECNICO PREVIDENCIARIO", normalized_text))
        has_pending_signal = bool(
            re.search(
                r"PENDENT[EA]|PENDENTE DE JULGAMENTO|AGUARDANDO JULGAMENTO|EFEITO SUSPENSIVO",
                normalized_text,
            )
        )
        has_contestation = bool(re.search(r"CONTESTACAO|CONTESTAR", normalized_text))
        if has_ntp and (has_pending_signal or has_contestation):
            detected.append("nexo_pendente")

        has_trajeto = bool(re.search(r"ACIDENTE DE TRAJETO", normalized_text))
        has_judicial_signal = bool(
            re.search(r"ACAO JUDICIAL|PROCESSO|AUTOS|SENTENCA|DECISAO JUDICIAL", normalized_text)
        )
        has_sem_cat_signal = bool(re.search(r"SEM CAT|AUSENCIA DE CAT|INEXISTENCIA DE CAT", normalized_text))
        has_cat_number = bool(re.search(r"CAT\s*(?:N|NO|N\s*O|N\s*º|NUMERO)?\s*[\d./-]{4,}", normalized_text))
        if has_trajeto and (has_sem_cat_signal or (has_judicial_signal and not has_cat_number)):
            detected.append("acidente_trajeto_sem_cat")

        has_justica_federal = bool(re.search(r"\bJUSTICA\s+FEDERAL\b", normalized_text))
        has_legal_basis = bool(re.search(r"SUMULA\s*235|ART\.?\s*109", normalized_text))
        has_previdenciario_basis = bool(re.search(r"NATUREZA\s+PREVIDENCIARIA|BENEFICIO\s+PREVIDENCIARIO", normalized_text))
        if has_justica_federal and (has_legal_basis or has_previdenciario_basis):
            detected.append("beneficio_justica_federal")

        return detected

    def _has_justica_federal_evidence(self, normalized_text: str) -> bool:
        has_justica_federal = bool(re.search(r"\bJUSTICA\s+FEDERAL\b", normalized_text))
        has_legal_basis = bool(re.search(r"SUMULA\s*235|ART\.?\s*109", normalized_text))
        has_previdenciario_basis = bool(re.search(r"NATUREZA\s+PREVIDENCIARIA|BENEFICIO\s+PREVIDENCIARIO", normalized_text))
        return has_justica_federal and (has_legal_basis or has_previdenciario_basis)

    def _apply_rule_based_guards(self, text: str, topics_slugs: list[str]) -> list[str]:
        normalized_text = self._normalize_text_for_match(text)
        guarded_topics = topics_slugs.copy()
        critical_slugs = self._detect_critical_regex_slugs(normalized_text)

        other_company_slugs = {
            "erro_estabelecimento",
            "outra_empresa_cat",
            "outra_empresa_nunca_empregado",
            "outra_empresa_pos_rescisao",
            "outra_empresa_did_anterior",
        }

        has_pre_fap = self._has_pre_fap_evidence(normalized_text)
        has_other_company = self._has_other_company_evidence(normalized_text)
        has_justica_federal = self._has_justica_federal_evidence(normalized_text)

        for slug in reversed(critical_slugs):
            guarded_topics = [item for item in guarded_topics if item != slug]
            guarded_topics.insert(0, slug)

        if "acidente_trajeto_sem_cat" in guarded_topics:
            guarded_topics = [slug for slug in guarded_topics if slug != "acidente_trajeto"]

        # Se há CAT numerada explícita no texto, é ACIDENTE DE TRAJETO (com CAT), não sem_cat.
        has_trajeto_text = bool(re.search(r"ACIDENTE DE TRAJETO", normalized_text))
        has_cat_number = bool(re.search(r"CAT\s*(?:N|NO|N\s*O|N\s*º|NUMERO)?\s*[\d./ ]{4,}", normalized_text))
        if has_trajeto_text and has_cat_number:
            guarded_topics = [slug for slug in guarded_topics if slug != "acidente_trajeto_sem_cat"]
            if "acidente_trajeto" not in guarded_topics:
                guarded_topics.insert(0, "acidente_trajeto")

        if not has_justica_federal:
            guarded_topics = [slug for slug in guarded_topics if slug != "beneficio_justica_federal"]

        if has_pre_fap:
            guarded_topics = [slug for slug in guarded_topics if slug != "pre_fap"]
            guarded_topics.insert(0, "pre_fap")

        if has_other_company:
            has_other_company_topic = any(slug in other_company_slugs for slug in guarded_topics)
            if not has_other_company_topic:
                guarded_topics.insert(0, "erro_estabelecimento")
            guarded_topics = [slug for slug in guarded_topics if slug != "discussao_medica"]
        else:
            guarded_topics = [slug for slug in guarded_topics if slug not in other_company_slugs]

        if critical_slugs:
            guarded_topics = [slug for slug in guarded_topics if slug != "discussao_medica"]

        # Remove outros_argumentos e discussao_medica quando há tópico específico
        GENERIC_SLUGS = {"outros_argumentos", "discussao_medica"}
        specific_topics = [s for s in guarded_topics if s not in GENERIC_SLUGS]
        if specific_topics:
            guarded_topics = specific_topics

        deduped: list[str] = []
        for slug in guarded_topics:
            if slug in self.VALID_SLUGS and slug not in deduped:
                deduped.append(slug)
            if len(deduped) >= 3:
                break

        if not deduped:
            deduped = [self._fallback_slug(text)]

        return deduped

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
            "Quando houver cabecalho literal com nome de categoria, trate isso como evidencia forte. "
            "DISCUSSAO MEDICA / OUTROS ARGUMENTOS so pode ser usada quando nenhum outro topico especifico se aplicar. "
            "Prefira sempre topicos juridicos especificos quando houver evidencia textual suficiente. "
            "Evite falso positivo: nunca retorne PRE-FAP, B31 ou NEXO PENDENTE sem evidencia textual explicita. "
            "Quando houver evidencia de evento anterior a abril de 2007/pre-FAP, PRE-FAP deve ser o topico principal. "
            "Nao use categorias de OUTRA EMPRESA ou ERRO DE ESTABELECIMENTO sem indicios textuais explicitos de outro CNPJ/estabelecimento/vinculo empregaticio diverso. "
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
            "- So use outros_argumentos quando NAO houver enquadramento claro em nenhum outro topico especifico\n"
            "- Se houver ao menos um topico especifico aplicavel, NAO inclua discussao_medica nem outros_argumentos\n"
            "- Nao retorne pre_fap, b31_previdenciario ou nexo_pendente sem mencao textual clara e direta\n"
            "- Se o texto mencionar numero de CAT (ex: 'CAT no XXXX', 'CAT 2018...'), use acidente_trajeto, NUNCA acidente_trajeto_sem_cat\n"
            "- acidente_trajeto_sem_cat SOMENTE quando o texto diz explicitamente que NAO ha CAT emitida\n"
            "- Quando houver mencao a evento/DID anterior a abril de 2007, pre_fap deve ser o primeiro slug\n"
            "- Se o texto indicar outro CNPJ, outro estabelecimento, ou ausencia de nexo com este estabelecimento, priorize uma das categorias abaixo:\n"
            "  - outra_empresa_cat\n"
            "  - outra_empresa_nunca_empregado\n"
            "  - outra_empresa_pos_rescisao\n"
            "  - outra_empresa_did_anterior\n"
            "  - erro_estabelecimento\n"
            "- Nao use categorias de outra_empresa_* nem erro_estabelecimento sem expressao textual explicita de outro CNPJ/estabelecimento/empresa\n"
            "- Informe reason apenas quando confidence >= 0.80; caso contrario, reason deve ser string vazia\n"
            "- Se nao houver encaixe:\n"
            "  - Se houver termos medicos -> discussao_medica\n"
            "  - Caso contrario -> outros_argumentos\n\n"
            "Exemplos de sinal forte para OUTRA EMPRESA/ERRO DE ESTABELECIMENTO:\n"
            "- 'nao relacionado a este estabelecimento'\n"
            "- 'acidente vinculado a outro CNPJ'\n"
            "- 'requer exclusao da base de calculo FAP deste estabelecimento por vinculo a outro estabelecimento'\n\n"
            "Exemplos de sinal forte para PRE-FAP:\n"
            "- 'evento acidentario anterior a 1o de abril de 2007'\n"
            "- 'DID 2002'\n"
            "- 'acidente/doenca antes da vigencia do FAP'\n\n"
            "Sinais juridicos fortes por categoria (use para desempate e prioridade):\n"
            "- nexo_pendente: mencao a NTP/nexo tecnico com contestacao pendente de julgamento e pedido de efeito suspensivo\n"
            "- acidente_trajeto: mencao expressa de acidente de trajeto com CAT comprovando o evento\n"
            "- acidente_trajeto_sem_cat: acidente de trajeto comprovado por acao judicial, sem CAT\n"
            "- restabelecimento_b91_60: mencao a restabelecimento em menos de 60 dias (DCB->novo beneficio)\n"
            "- b31_previdenciario: mencao expressa de especie previdenciaria/B31 e exclusao por nao ser acidentario\n"
            "- erro_estabelecimento: beneficio imputado ao estabelecimento/CNPJ errado\n"
            "- pre_fap: evento anterior a abril/2007, art. 202-A, decreto 6.957/2009, irretroatividade\n"
            "- outra_empresa_cat: CAT vincula acidente a outra empresa\n"
            "- outra_empresa_nunca_empregado: ausencia de vinculo empregaticio historico com a empresa\n"
            "- outra_empresa_pos_rescisao: DIB/evento posterior a rescisao contratual\n"
            "- outra_empresa_did_anterior: DID anterior a admissao na empresa\n"
            "- nexo_afastado: pericia/sentenca afasta nexo causal ou concausalidade laboral\n"
            "- beneficio_justica_federal: concessao judicial na Justica Federal indicando natureza previdenciaria\n"
            "- concomitante_b91_aposentadoria: B91 concedido com aposentadoria ativa\n"
            "- concomitante_dois_b91: concessao concomitante de dois auxilios-doenca\n"
            "- concomitante_b94_aposentadoria: B94 acumulado com aposentadoria\n"
            "- b94_duplicado: dois B94 para mesmo fato gerador\n"
            "- b94_sem_custo: DIB=DCB/beneficio sem custo juridico efetivo\n"
            "- discussao_medica: debate clinico/pericial sem enquadramento juridico FAP especifico\n\n"
            "Regra de estruturacao:\n"
            "- Se o texto trouxer mais de um bloco justificativo com fundamentos distintos, retorne multiplos slugs (ate 3), sem inventar.\n"
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

            topics_slugs = self._apply_rule_based_guards(cleaned_text, topics_slugs)

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
