import os
import time
from typing import Optional, List

from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from app.services.token_usage_service import TokenUsageService
from rich import print

load_dotenv()


# ==================== Modelos Pydantic ====================

class Entities(BaseModel):
    people: List[str] = Field(default_factory=list, description="Pessoas mencionadas")
    organizations: List[str] = Field(default_factory=list, description="Organizações mencionadas")
    locations: List[str] = Field(default_factory=list, description="Localizações mencionadas")


class Party(BaseModel):
    name: str = Field(default="", description="Nome da parte")
    role: str = Field(default="", description="Papel da parte (Autor, Réu, etc)")
    lawyers: List[str] = Field(default_factory=list, description="Lista de advogados")


class Parties(BaseModel):
    active_pole: List[Party] = Field(default_factory=list, description="Polo ativo")
    passive_pole: List[Party] = Field(default_factory=list, description="Polo passivo")


class Decision(BaseModel):
    subject: str = Field(default="", description="Assunto da decisão")
    result: str = Field(default="", description="Resultado (Procedente, Improcedente, Parcialmente Procedente, Não mencionado na sentença)")
    reasoning: str = Field(default="", description="Fundamentação breve da decisão")


class FapBenefitAnalysis(BaseModel):
    benefit_number: str = Field(default="", description="Número do benefício (NB)")
    insured_name: str = Field(default="", description="Nome do segurado")
    accident_type: str = Field(default="", description="Tipo/natureza do acidente")
    result: str = Field(default="", description="Resultado da análise (Aceito, Rejeitado, Não mencionado na sentença)")
    reasoning: str = Field(default="", description="Fundamentação breve da decisão sobre o benefício")


class PetitionRequestCoverage(BaseModel):
    request: str = Field(default="", description="Pedido da petição inicial")
    was_analyzed: bool = Field(default=False, description="Se o pedido foi analisado na sentença")
    decision_result: str = Field(default="", description="Resultado da decisão sobre este pedido")
    comments: str = Field(default="", description="Observações sobre o pedido")


class SentenceInfo(BaseModel):
    process_number: str = Field(default="", description="Número do processo")
    case_value: str = Field(default="", description="Valor da causa")
    subjects: List[str] = Field(default_factory=list, description="Assuntos jurídicos")
    origin_court: str = Field(default="", description="Tribunal de origem com cidade/estado")
    judgment_date: str = Field(default="", description="Data da sentença")
    start_year: str = Field(default="", description="Ano de início do processo")
    nature: str = Field(default="", description="Natureza da ação")
    judicial_power: str = Field(default="", description="Poder judiciário")
    judge: str = Field(default="", description="Nome do juiz/magistrado")
    court_tag: str = Field(default="", description="Tag do tribunal (ex: TJSP, TRF1)")
    parties: Parties = Field(default_factory=Parties, description="Partes envolvidas")
    operative_part: str = Field(default="", description="Dispositivo da sentença")
    overall_result: str = Field(default="", description="Resultado geral (Procedente, Improcedente, Parcialmente Procedente)")
    decisions: List[Decision] = Field(default_factory=list, description="Decisões específicas sobre cada pedido")
    fap_benefits_analysis: List[FapBenefitAnalysis] = Field(default_factory=list, description="Análise individual de benefícios (apenas para processos FAP)")
    legal_grounds: List[str] = Field(default_factory=list, description="Fundamentos legais utilizados")
    jurisprudence_cited: List[str] = Field(default_factory=list, description="Jurisprudências citadas")
    possible_appeals: List[str] = Field(default_factory=list, description="Recursos possíveis")
    petition_requests_coverage: List[PetitionRequestCoverage] = Field(default_factory=list, description="Análise de cobertura dos pedidos da petição inicial")


class SentenceSummary(BaseModel):
    summary: str = Field(description="Resumo geral da sentença")
    summary_short: str = Field(default="", description="Resumo curto (2-4 frases)")
    summary_long: str = Field(default="", description="Resumo longo (2-4 parágrafos)")
    key_points: List[str] = Field(default_factory=list, description="Pontos-chave da sentença")
    entities: Entities = Field(default_factory=Entities, description="Entidades extraídas")
    dates: List[str] = Field(default_factory=list, description="Datas mencionadas")
    language: str = Field(default="pt-BR", description="Idioma do documento")
    notes: str = Field(default="", description="Observações adicionais")
    sentence_info: SentenceInfo = Field(default_factory=SentenceInfo, description="Informações da sentença")

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True)


# ==================== Schemas: Erros Materiais e Omissões ====================

class MaterialError(BaseModel):
    description: str = Field(default="", description="Descrição do erro material identificado")
    location: str = Field(default="", description="Trecho ou parte da sentença onde o erro ocorre")
    correction_suggestion: str = Field(default="", description="Sugestão de correção para o erro")


class Omission(BaseModel):
    benefit_number: str = Field(default="", description="Número do benefício (NB) omitido, se aplicável")
    insured_name: str = Field(default="", description="Nome do segurado omitido, se aplicável")
    description: str = Field(default="", description="Descrição do ponto omitido (pedido, benefício ou questão não analisada)")
    legal_basis: str = Field(default="", description="Fundamento legal que exige análise do ponto omitido")


class JudgmentErrorsAnalysis(BaseModel):
    has_material_errors: bool = Field(default=False, description="Se foram identificados erros materiais na sentença")
    has_omissions: bool = Field(default=False, description="Se foram identificadas omissões na sentença")
    material_errors: List[MaterialError] = Field(default_factory=list, description="Lista de erros materiais identificados")
    omissions: List[Omission] = Field(default_factory=list, description="Lista de omissões identificadas")
    summary: str = Field(default="", description="Resumo geral dos vícios encontrados ou confirmação de que a sentença está completa")
    ed_recommendation: str = Field(
        default="",
        description="Recomendação sobre interpor Embargos de Declaração: 'Recomendado', 'Não recomendado' ou 'Verificar com advogado'",
    )
    ed_arguments: List[str] = Field(default_factory=list, description="Argumentos para os Embargos de Declaração, se recomendado")

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)


# ==================== Classe Principal ====================

_COURT_TAGS = (
    "STF, STJ, TST, TSE, STM, TRF1, TRF2, TRF3, TRF4, TRF5, TRF6, "
    "TJAC, TJAL, TJAM, TJAP, TJBA, TJCE, TJDFT, TJES, TJGO, TJMA, TJMG, TJMS, "
    "TJMT, TJPA, TJPB, TJPE, TJPI, TJPR, TJRJ, TJRN, TJRO, TJRR, TJRS, TJSC, TJSE, TJSP, TJTO"
)

_SYSTEM_PROMPT = (
    "Você é um assistente jurídico especializado em análise de sentenças. "
    "Gere um resumo técnico, objetivo e estruturado."
)


class AgentSentenceSummary:

    def __init__(self, model_name: str = "gpt-5-mini"):
        self.model_name = model_name
        self.model_provider = os.getenv("SENTENCE_SUMMARY_MODEL_PROVIDER", "openai")
        self.chat_model = ChatOpenAI(model=model_name, temperature=0.2)
        self.token_usage_service = TokenUsageService()

    # ------------------------------------------------------------------
    # Helpers de contexto
    # ------------------------------------------------------------------

    def _build_petition_context(self, requests: List[str]) -> str:
        if not requests:
            return ""
        lines = "\n".join(f"{i}. {r}" for i, r in enumerate(requests, 1))
        return (
            "\n\n=== PEDIDOS DA PETIÇÃO INICIAL (use como contexto) ===\n"
            f"Os seguintes pedidos foram formulados na petição inicial:\n{lines}\n\n"
            "IMPORTANTE: No campo 'petition_requests_coverage', analise SE e COMO cada um desses pedidos "
            "foi tratado na sentença. Para cada pedido, indique:\n"
            "- was_analyzed: true se o pedido foi mencionado/analisado na sentença, false caso contrário\n"
            "- decision_result: o resultado da decisão sobre este pedido específico\n"
            "- comments: observações relevantes sobre o pedido\n\n"
        )

    def _build_benefits_context(self, benefits: str | dict | None) -> str:
        if not benefits:
            return ""

        closing = (
            "\nIMPORTANTE: Para CADA benefício listado acima, procure na sentença:\n"
            "- SE encontrar análise/decisão favorável → preencha 'result' com: Aceito\n"
            "- SE encontrar análise/decisão desfavorável → preencha 'result' com: Rejeitado\n"
            "- SE NÃO encontrar menção → preencha 'result' com: Não mencionado na sentença\n"
            "\nNo campo 'fap_benefits_analysis', inclua TODOS os benefícios (tanto mencionados quanto não mencionados).\n"
        )

        if isinstance(benefits, str):
            return (
                "\n\n=== BENEFÍCIOS MENCIONADOS NA PETIÇÃO INICIAL (use como contexto) ===\n"
                f"{benefits}\n{closing}"
            )

        benefits_list = benefits.get("benefits", []) if isinstance(benefits, dict) else []
        if not benefits_list:
            return ""

        lines = ""
        for i, b in enumerate(benefits_list, 1):
            lines += f"\n{i}. Benefício NB {b.get('benefit_number', 'não informado')}:\n"
            lines += f"   - Segurado: {b.get('insured_name', '')}\n"
            lines += f"   - Tipo: {b.get('benefit_type', '')}\n"
            if b.get("accident_date"):
                lines += f"   - Data do acidente: {b.get('accident_date')}\n"
            lines += f"   - Motivo da revisão: {b.get('revision_reason', '')}\n"

        return (
            "\n\n=== BENEFÍCIOS MENCIONADOS NA PETIÇÃO INICIAL (use como contexto) ===\n"
            f"Contexto geral: {benefits.get('general_revision_context', 'Revisão de benefícios')}\n\n"
            f"Os seguintes benefícios foram identificados na petição inicial:{lines}"
            f"{closing}"
            "\nPara cada benefício, extraia:\n"
            "- benefit_number: número do benefício (NB)\n"
            "- insured_name: nome do segurado\n"
            "- accident_type: tipo/natureza do acidente\n"
            "- result: Aceito | Rejeitado | Não mencionado na sentença\n"
            "- reasoning: fundamentação da decisão (ou explicação do porquê não foi mencionado)\n\n"
        )

    def _build_user_prompt(self, text_or_placeholder: str, petition_ctx: str, benefits_ctx: str) -> str:
        return (
            "Resuma a sentença judicial abaixo. Preserve informações jurídicas relevantes. "
            "Regras de tamanho: summary_short com 2-4 frases objetivas; summary_long com 2-4 parágrafos, "
            "mais completo e detalhado que o resumo curto. "
            "Se não houver dado para algum campo, use lista vazia ou string vazia.\n\n"
            f"{petition_ctx}"
            f"{benefits_ctx}"
            "IMPORTANTE: Extraia as seguintes informações estruturadas no campo 'sentence_info':\n"
            "- process_number, case_value, subjects, origin_court, judgment_date, start_year\n"
            "- nature, judicial_power, judge\n"
            f"- court_tag: tag do tribunal (use a CHAVE). Opções: {_COURT_TAGS}\n"
            "- parties: active_pole e passive_pole com nome, papel e advogados\n"
            "- operative_part: dispositivo da sentença (preferencialmente literal)\n"
            "- overall_result: Procedente | Improcedente | Parcialmente Procedente\n"
            "  Regra: TODOS procedentes → Procedente; TODOS improcedentes → Improcedente; mix → Parcialmente Procedente\n"
            "- decisions: array com subject, result e reasoning para cada pedido\n"
            "- fap_benefits_analysis: SE for processo FAP, array com análise por benefício; senão, array vazio\n"
            "- legal_grounds, jurisprudence_cited, possible_appeals\n"
            "- petition_requests_coverage: SE houver pedidos da petição acima, analise cada um\n\n"
            f"SENTENÇA:\n{text_or_placeholder}"
        )

    # ------------------------------------------------------------------
    # Método principal
    # ------------------------------------------------------------------

    def summarizeSentence(
        self,
        text_content: str,
        petition_requests: Optional[List[str]] = None,
        petition_benefits: Optional[str | dict] = None,
        user_id: Optional[int] = None,
        law_firm_id: Optional[int] = None,
    ) -> dict:
        if not text_content:
            raise ValueError("É necessário fornecer text_content")

        petition_ctx = self._build_petition_context(petition_requests or [])
        benefits_ctx = self._build_benefits_context(petition_benefits)

        user_prompt = self._build_user_prompt(text_content, petition_ctx, benefits_ctx)
        messages = [{"role": "user", "content": user_prompt}]

        agent = create_agent(
            model=self.chat_model,
            tools=[],
            system_prompt=_SYSTEM_PROMPT,
            response_format=ToolStrategy(SentenceSummary),
        )

        call_started_at = time.time()
        response_payload = agent.invoke({"messages": messages})
        latency_ms = int((time.time() - call_started_at) * 1000)

        self.token_usage_service.capture_and_store(
            response_payload,
            agent_name="AgentSentenceSummary",
            action_name="summarize_sentence.create_agent",
            print_prefix="[AgentSentenceSummary][summarize_sentence][tokens]",
            model_name=self.model_name,
            model_provider=self.model_provider,
            user_id=user_id,
            law_firm_id=law_firm_id,
            latency_ms=latency_ms,
            status="success",
            metadata_payload={
                "petition_requests_count": len(petition_requests or []),
                "has_petition_benefits": bool(petition_benefits),
            },
        )

        structured_response = response_payload.get("structured_response")
        if not structured_response:
            raise RuntimeError("Resposta estruturada não retornada pelo create_agent")

        return structured_response.to_dict()


# ==================== Agente: Erros Materiais e Omissões ====================

_ERRORS_SYSTEM_PROMPT = (
    "Você é um assistente jurídico especializado em análise crítica de sentenças judiciais. "
    "Sua tarefa é identificar erros materiais (erros de cálculo, de fato, ou de referência) e omissões "
    "(pedidos, benefícios ou questões não analisadas) que possam fundamentar Embargos de Declaração. "
    "Seja preciso e objetivo. Só aponte vícios concretos, não suposições genéricas."
)


class AgentSentenceErrorsAnalysis:

    def __init__(self, model_name: str = "gpt-5-mini"):
        self.model_name = model_name
        self.model_provider = os.getenv("SENTENCE_SUMMARY_MODEL_PROVIDER", "openai")
        self.chat_model = ChatOpenAI(model=model_name, temperature=0.1)
        self.token_usage_service = TokenUsageService()

    def _build_benefits_context(self, benefits: str | dict | None) -> str:
        if not benefits:
            return ""

        if isinstance(benefits, str):
            return (
                "\n\n=== BENEFÍCIOS DO PROCESSO (use para verificar omissões) ===\n"
                f"{benefits}\n"
            )

        benefits_list = benefits.get("benefits", []) if isinstance(benefits, dict) else []
        if not benefits_list:
            return ""

        rows = ["| NB | Segurado | Tipo | Motivo/Tese |", "|---|---|---|---|"]
        for b in benefits_list:
            if not isinstance(b, dict):
                continue
            rows.append(
                f"| {b.get('benefit_number', '-')} "
                f"| {b.get('insured_name', '-')} "
                f"| {b.get('benefit_type', '-')} "
                f"| {b.get('revision_reason', '-')} |"
            )

        return (
            "\n\n=== BENEFÍCIOS DO PROCESSO (use para verificar omissões) ===\n"
            + "\n".join(rows)
            + "\n"
        )

    def analyze(
        self,
        text_content: str,
        benefits: str | dict | None = None,
        user_id: int | None = None,
        law_firm_id: int | None = None,
    ) -> dict:
        if not text_content:
            raise ValueError("É necessário fornecer text_content")

        benefits_ctx = self._build_benefits_context(benefits)

        user_prompt = (
            "Analise a sentença judicial abaixo em busca de:\n"
            "1. **Erros materiais**: erros de cálculo, de fato, de referência a partes/benefícios/datas erradas.\n"
            "2. **Omissões**: pedidos, benefícios ou questões suscitadas pelas partes que não foram analisados.\n\n"
            "Para cada omissão de benefício, informe o número do benefício (NB) e o nome do segurado se identificável.\n"
            "Ao final, indique se é recomendável interpor Embargos de Declaração e liste os argumentos.\n"
            f"{benefits_ctx}\n"
            f"SENTENÇA:\n{text_content}"
        )

        agent = create_agent(
            model=self.chat_model,
            tools=[],
            system_prompt=_ERRORS_SYSTEM_PROMPT,
            response_format=ToolStrategy(JudgmentErrorsAnalysis),
        )

        call_started_at = time.time()
        response_payload = agent.invoke({"messages": [{"role": "user", "content": user_prompt}]})
        latency_ms = int((time.time() - call_started_at) * 1000)

        self.token_usage_service.capture_and_store(
            response_payload,
            agent_name="AgentSentenceErrorsAnalysis",
            action_name="analyze_errors.create_agent",
            print_prefix="[AgentSentenceErrorsAnalysis][analyze_errors][tokens]",
            model_name=self.model_name,
            model_provider=self.model_provider,
            user_id=user_id,
            law_firm_id=law_firm_id,
            latency_ms=latency_ms,
            status="success",
            metadata_payload={"has_benefits": bool(benefits)},
        )

        structured_response = response_payload.get("structured_response")
        if not structured_response:
            raise RuntimeError("Resposta estruturada não retornada pelo create_agent")

        return structured_response.to_dict()
