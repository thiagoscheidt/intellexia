"""
Agente de IA para geração de documentos jurídicos vinculados a processos judiciais.

Cada tipo de documento tem seu próprio método, schema Pydantic e prompt especializado.

As funções recebem `selections`: lista de dicts no formato:
    {
        'benefit': JudicialProcessBenefit,
        'thesis': JudicialLegalThesis | None,
        'contestation': JudicialProcessBenefitThesisContestation | None,
    }
Isso permite argumentação específica por par (benefício, tese).
"""

from pathlib import Path
from typing import Optional
import re
import time
import logging
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from app.agents.core.file_agent import FileAgent
from app.services.token_usage_service import TokenUsageService
from app.services.agent_execution_history_service import AgentExecutionHistoryService

load_dotenv()
from app.agents.config import DEFAULT_MODEL_LEGAL_DRAFTING

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
logger = logging.getLogger(__name__)


def _load_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8")


_IMPUGNACAO_SYSTEM_PROMPT = _load_prompt("system_prompt_impugnacao_v2.md")

_IMPUGNACAO_INTERNAL_GUARDRAILS = """
=== REFORÇO INTERNO DE EXECUÇÃO (RUNTIME) ===

1) Numeração arábica e hierárquica é obrigatória na peça final.
- Seções principais no Modo A: 1., 2., 3., 4., 5.
- Subseções: 1.1, 1.2, 4.1, 4.2, etc.
- No bloco de mérito, nunca use 1., 2., 3. como nível principal; use 4.1, 4.2, 4.3...

2) Campos macro do schema não podem aparecer como bloco solto sem título.
- `general_legal_grounds` e `jurisprudence` são campos de consolidação interna.
- No texto final da peça, integre esse conteúdo aos blocos já existentes (introdução, insuficiência técnica e mérito).
- Se houver seção separada, ela deve ter título explícito e numeração hierárquica coerente.

3) Prioridade para jurisprudência regional quando disponível no catálogo.
- Se o foro do processo indicar região específica (ex.: JFSP/TRF3), priorize ao menos uma citação inline do tribunal regional correspondente.
- Jurisprudência de outras regiões deve ser complementar quando houver precedente regional validado.
""".strip()


# ── Impugnação à Contestação da União ─────────────────────────────────────

class ImpugnacaoBenefitThesisSection(BaseModel):
    benefit_number: str = Field(description="Número do benefício (NB)")
    insured_name: str = Field(description="Nome do segurado")
    thesis_name: str = Field(description="Nome da tese jurídica contestada, ou 'Geral' se não houver tese específica")
    argument: str = Field(
        description=(
            "Argumentação jurídica para este par benefício+tese, seguindo a estrutura: "
            "identificação do pedido + tabela do benefício + síntese do fundamento da União "
            "+ refutação técnica (premissa normativa + premissa fática + conclusão) "
            "+ citação jurisprudencial inline obrigatória (TRF/STJ do catálogo ou transversal) "
            "+ pedido de exclusão padrão. "
            "Se o status for 'procedente', reforce o reconhecimento da União. "
            "OBRIGATÓRIO: ao menos uma citação de TRF/STJ dentro do argumento."
        )
    )


class GeneratedImpugnacaoContestacao(BaseModel):
    generation_mode: str = Field(
        default="A",
        description=(
            "Modo de redação selecionado conforme Seção 0 do system prompt: "
            "'A' = Mérito por Tese (padrão — contestação com argumentos específicos por benefício); "
            "'B' = Defesa Processual (contestação integralmente genérica — peça curta sem catálogo de teses). "
            "Use os critérios da tabela da Seção 0.3 para decidir."
        ),
    )
    introduction: str = Field(description="Qualificação das partes, identificação do processo e contexto da impugnação")
    preliminary_notes: str = Field(
        description=(
            "Modo A: Seções 1 (Preliminares, se houver) + 3 (Insuficiência técnica da contestação). "
            "Modo B: todo o conteúdo argumentativo — mérito sintético + subseção 1.1 (reconhecimento de erros em situações similares) "
            "+ subseção 1.2 (revelia e ausência de impugnação específica). "
            "No Modo B não há desenvolvimento por tese; toda a argumentação vai aqui."
        )
    )
    benefit_sections: list[ImpugnacaoBenefitThesisSection] = Field(
        default_factory=list,
        description=(
            "Modo A: uma entrada por par benefício+tese na Seção 4 (Mérito). "
            "Modo B: deixar VAZIO [] — não há mérito por tese na defesa processual."
        ),
    )
    general_legal_grounds: str = Field(description="Fundamentos legais e doutrinários gerais aplicáveis")
    jurisprudence: str = Field(
        default="",
        description=(
            "Modo A: apenas jurisprudência macro/transversal adicional, distinta das citações inline já feitas em cada argument. "
            "Modo B: deixar VAZIO — o Modo B não cita jurisprudência de TRF/STJ."
        ),
    )
    requests: str = Field(description="Pedidos finais conforme template da Seção 9 (Modo A) ou Seção 5.10 (Modo B)")
    closing: str = Field(description="Fecho único: 'Nestes termos, pede deferimento. Florianópolis/SC, [data].'")

    def to_full_text(self) -> str:
        parts = []
        is_mode_b = self.generation_mode == "B"

        if is_mode_b:
            parts.append("# IMPUGNAÇÃO À CONTESTAÇÃO DA UNIÃO\n")
            parts.append("> **Modo de redação: B — Defesa Processual** *(auditoria interna)*\n\n")
        else:
            parts.append("# IMPUGNAÇÃO À CONTESTAÇÃO DA UNIÃO\n")

        parts.append(self.introduction + "\n")
        parts.append("\n---\n")
        parts.append(self.preliminary_notes + "\n")

        if self.benefit_sections:
            parts.append("\n## DO MÉRITO\n")
            for i, sec in enumerate(self.benefit_sections, 1):
                parts.append(f"\n### {i}. NB {sec.benefit_number} — {sec.insured_name} | Tese: {sec.thesis_name}\n")
                parts.append(sec.argument + "\n")

        parts.append("\n---\n")
        parts.append(self.general_legal_grounds + "\n")

        if self.jurisprudence:
            parts.append("\n---\n")
            parts.append(self.jurisprudence + "\n")

        parts.append("\n---\n")
        parts.append(self.requests + "\n")
        parts.append("\n---\n")
        parts.append(self.closing + "\n")
        return "".join(parts)

    def to_dict(self) -> dict:
        return self.model_dump()


# ── Manifestação ───────────────────────────────────────────────────────────

class GeneratedManifestacao(BaseModel):
    introduction: str = Field(description="Qualificação das partes e objeto da manifestação")
    merit: str = Field(description="Mérito — argumentação principal da manifestação")
    legal_grounds: str = Field(description="Fundamentos legais e doutrinários")
    jurisprudence: str = Field(default="", description="Jurisprudências e precedentes aplicáveis")
    requests: str = Field(description="Pedidos e requerimentos")
    closing: str = Field(description="Fecho padrão")

    def to_full_text(self) -> str:
        parts = []
        parts.append("# MANIFESTAÇÃO\n")
        parts.append("## I. INTRODUÇÃO\n")
        parts.append(self.introduction + "\n")
        parts.append("\n## II. DO MÉRITO\n")
        parts.append(self.merit + "\n")
        parts.append("\n## III. DOS FUNDAMENTOS\n")
        parts.append(self.legal_grounds + "\n")
        if self.jurisprudence:
            parts.append("\n## IV. DA JURISPRUDÊNCIA\n")
            parts.append(self.jurisprudence + "\n")
        parts.append("\n## V. DOS PEDIDOS\n")
        parts.append(self.requests + "\n")
        parts.append("\n---\n")
        parts.append(self.closing + "\n")
        return "".join(parts)

    def to_dict(self) -> dict:
        return self.model_dump()


# ── Petição Intermediária ──────────────────────────────────────────────────

class GeneratedPeticaoIntermediaria(BaseModel):
    introduction: str = Field(description="Identificação do processo e das partes")
    facts: str = Field(description="Dos fatos — contexto que motiva a petição")
    legal_grounds: str = Field(description="Do direito — fundamentos jurídicos")
    requests: str = Field(description="Dos pedidos")
    closing: str = Field(description="Fecho padrão")

    def to_full_text(self) -> str:
        parts = []
        parts.append("# PETIÇÃO INTERMEDIÁRIA\n")
        parts.append("## I. INTRODUÇÃO\n")
        parts.append(self.introduction + "\n")
        parts.append("\n## II. DOS FATOS\n")
        parts.append(self.facts + "\n")
        parts.append("\n## III. DO DIREITO\n")
        parts.append(self.legal_grounds + "\n")
        parts.append("\n## IV. DOS PEDIDOS\n")
        parts.append(self.requests + "\n")
        parts.append("\n---\n")
        parts.append(self.closing + "\n")
        return "".join(parts)

    def to_dict(self) -> dict:
        return self.model_dump()


# ── Classe Principal ───────────────────────────────────────────────────────

DOCUMENT_TYPE_LABELS = {
    "impugnacao_contestacao": "Impugnação à Contestação da União",
    "manifestacao": "Manifestação",
    "peticao_intermediaria": "Petição Intermediária",
}


class AgentGeneratedDocument:
    """
    Agente para geração de documentos jurídicos por tipo.

    Cada método recebe `selections`: lista de dicts com chaves:
        benefit     → JudicialProcessBenefit
        thesis      → JudicialLegalThesis | None
        contestation → JudicialProcessBenefitThesisContestation | None
    """

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or DEFAULT_MODEL_LEGAL_DRAFTING

    # ── Impugnação à Contestação ──────────────────────────────────────────

    def generate_impugnacao_contestacao(
        self,
        process,
        selections: list[dict],
        instructions: Optional[str] = None,
        contestation_file_path: Optional[str] = None,
        law_firm_id: Optional[int] = None,
    ) -> GeneratedImpugnacaoContestacao:
        """
        Gera Impugnação à Contestação da União.

        Regras específicas:
        - Cada selection representa um par (benefício, tese) com contestação independente
        - Para teses com status 'procedente', reforçar que a União reconheceu a procedência
        - Para teses com status 'improcedente', construir argumentação robusta de refutação
        - contestation_fundamento_uniao é o argumento da União a ser rebatido
        - contestation_trecho_detectado é o trecho literal — usar como ancoragem factual
        - contestation_efeito_fap contextualiza o impacto financeiro no FAP
        - Cada par gera uma seção ImpugnacaoBenefitThesisSection independente
        """
        process_ctx = self._build_process_context(process)
        selections_ctx = self._build_selections_context(selections, include_contestation=True)
        regional_jurisprudence_hint = self._build_regional_jurisprudence_hint(process)
        instructions_block = f"\n\n=== INSTRUÇÕES ADICIONAIS DO ADVOGADO ===\n{instructions}\n" if instructions else ""

        style_references_block = self._build_style_references_block(
            process=process,
            selections=selections,
            law_firm_id=law_firm_id,
        )

        user_prompt_sections = [
            process_ctx,
            selections_ctx,
        ]
        if regional_jurisprudence_hint:
            user_prompt_sections.append(regional_jurisprudence_hint)
        if style_references_block:
            user_prompt_sections.append(style_references_block)

        user_prompt = "\n\n".join(section for section in user_prompt_sections if section)
        user_prompt = (
            f"{user_prompt}"
            f"{instructions_block}\n\n"
            "Com base nos dados acima, gere a Impugnação à Contestação da União seguindo rigorosamente as instruções do sistema."
        )

        normalized_contestation_path = str(contestation_file_path or '').strip()
        if not normalized_contestation_path:
            raise ValueError(
                'Nenhum PDF de contestação foi localizado para este processo. '
                'Faça o upload de uma contestação em PDF antes de gerar a impugnação.'
            )

        file_part = FileAgent().build_openrouter_file_part(normalized_contestation_path)
        llm_messages = [
            {
                "role": "system",
                "content": f"{_IMPUGNACAO_SYSTEM_PROMPT}\n\n{_IMPUGNACAO_INTERNAL_GUARDRAILS}",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    file_part,
                ],
            },
        ]

        system_content = f"{_IMPUGNACAO_SYSTEM_PROMPT}\n\n{_IMPUGNACAO_INTERNAL_GUARDRAILS}"

        print("\n[AgentGeneratedDocument] === PROMPT FINAL (SYSTEM) ===")
        print(system_content)
        print("[AgentGeneratedDocument] === FIM PROMPT FINAL (SYSTEM) ===\n")

        print("\n[AgentGeneratedDocument] === PROMPT FINAL (USER) ===")
        print(user_prompt)
        print("[AgentGeneratedDocument] === FIM PROMPT FINAL (USER) ===")
        print(f"[AgentGeneratedDocument] Tamanho prompt user: {len(user_prompt)} chars")

        llm = ChatOpenAI(model=self.model_name, temperature=0.3).with_structured_output(
            GeneratedImpugnacaoContestacao,
            include_raw=True,
        )
        print("[AgentGeneratedDocument] Gerando Impugnação à Contestação (prompt v2.5.4)...")
        started_at = time.perf_counter()
        try:
            llm_output = llm.invoke(llm_messages)
            parsed_result = llm_output.get("parsed") if isinstance(llm_output, dict) else None
            raw_message = llm_output.get("raw") if isinstance(llm_output, dict) else None

            # Fallback para ambientes onde include_raw não retorna o envelope esperado.
            if parsed_result is None:
                fallback_llm = ChatOpenAI(
                    model=self.model_name,
                    temperature=0.3,
                ).with_structured_output(GeneratedImpugnacaoContestacao)
                parsed_result = fallback_llm.invoke(llm_messages)
                raw_message = None
        except Exception as error:
            elapsed_s = time.perf_counter() - started_at
            try:
                AgentExecutionHistoryService.save_execution_history(
                    agent_name="AgentGeneratedDocument",
                    action_name="generate_impugnacao_contestacao",
                    agent_type="legal_drafting",
                    system_prompt=system_content,
                    user_prompt=user_prompt,
                    model_response=None,
                    full_messages_history=llm_messages,
                    result_data=None,
                    model_name=self.model_name,
                    model_provider="openai",
                    status="error",
                    error_message=str(error),
                    law_firm_id=law_firm_id,
                )
            except Exception:
                logger.exception("Falha ao persistir histórico de erro da geração")
            raise

        elapsed_s = time.perf_counter() - started_at
        print(f"[AgentGeneratedDocument] LLM concluída em {elapsed_s:.2f}s")

        token_usage_id = None
        try:
            token_usage_service = TokenUsageService()
            response_payload = {
                "messages": [raw_message] if raw_message is not None else [],
            }
            _, token_rows = token_usage_service.capture_and_store(
                response_payload=response_payload,
                agent_name="AgentGeneratedDocument",
                action_name="generate_impugnacao_contestacao",
                print_prefix="[AgentGeneratedDocument][TokenUsage]",
                model_name=self.model_name,
                model_provider="openai",
                law_firm_id=law_firm_id,
                latency_ms=int(elapsed_s * 1000),
                status="success",
                metadata_payload={
                    "document_type": "impugnacao_contestacao",
                    "has_style_references": bool(style_references_block),
                },
                return_rows=True,
            )
            if token_rows:
                token_usage_id = token_rows[0].id
        except Exception:
            logger.exception("Falha ao persistir token usage da geração de impugnação")

        try:
            AgentExecutionHistoryService.save_execution_history(
                agent_name="AgentGeneratedDocument",
                action_name="generate_impugnacao_contestacao",
                agent_type="legal_drafting",
                system_prompt=system_content,
                user_prompt=user_prompt,
                model_response=parsed_result.to_full_text() if hasattr(parsed_result, "to_full_text") else str(parsed_result),
                full_messages_history=[llm_messages[0], llm_messages[1], raw_message] if raw_message is not None else llm_messages,
                result_data=parsed_result.to_dict() if hasattr(parsed_result, "to_dict") else None,
                model_name=self.model_name,
                model_provider="openai",
                status="success",
                law_firm_id=law_firm_id,
                agent_token_usage_id=token_usage_id,
            )
        except Exception:
            logger.exception("Falha ao persistir execution history da geração de impugnação")

        return parsed_result

    # ── Manifestação ─────────────────────────────────────────────────────

    def generate_manifestacao(
        self,
        process,
        selections: list[dict],
        instructions: Optional[str] = None,
    ) -> GeneratedManifestacao:
        """
        Gera Manifestação judicial.

        Regras específicas:
        - Conteúdo guiado pelas instructions do advogado
        - Contexto de benefícios/teses listado para referência, sem contestação detalhada
        """
        process_ctx = self._build_process_context(process)
        selections_ctx = self._build_selections_context(selections, include_contestation=False)
        instructions_block = f"\n\n=== OBJETO DA MANIFESTAÇÃO (fornecido pelo advogado) ===\n{instructions}\n" if instructions else ""

        user_prompt = (
            "Você é um advogado especializado em direito previdenciário e FAP. "
            "Gere uma Manifestação judicial completa.\n\n"
            f"{process_ctx}"
            f"\n{selections_ctx}"
            f"{instructions_block}\n\n"
            "=== INSTRUÇÕES ESPECÍFICAS ===\n"
            "1. A manifestação deve ser objetiva e direta ao objeto indicado\n"
            "2. Use linguagem técnica e formal\n"
            "3. Fundamente em dispositivos legais aplicáveis\n"
            "4. Formule pedidos claros e específicos\n"
        )

        llm = ChatOpenAI(model=self.model_name, temperature=0.3).with_structured_output(GeneratedManifestacao)
        print("[AgentGeneratedDocument] Gerando Manifestação...")
        return llm.invoke([
            {"role": "system", "content": "Você é um advogado experiente em direito previdenciário. Gere manifestações jurídicas tecnicamente precisas e bem fundamentadas."},
            {"role": "user", "content": user_prompt},
        ])

    # ── Petição Intermediária ────────────────────────────────────────────

    def generate_peticao_intermediaria(
        self,
        process,
        selections: list[dict],
        instructions: Optional[str] = None,
    ) -> GeneratedPeticaoIntermediaria:
        """
        Gera Petição Intermediária (incidental).

        Regras específicas:
        - Voltada para requerimentos específicos em curso do processo
        - Conteúdo guiado pelas instructions do advogado
        """
        process_ctx = self._build_process_context(process)
        selections_ctx = self._build_selections_context(selections, include_contestation=False)
        instructions_block = f"\n\n=== OBJETO DA PETIÇÃO (fornecido pelo advogado) ===\n{instructions}\n" if instructions else ""

        user_prompt = (
            "Você é um advogado especializado em direito previdenciário. "
            "Gere uma Petição Intermediária completa.\n\n"
            f"{process_ctx}"
            f"\n{selections_ctx}"
            f"{instructions_block}\n\n"
            "=== INSTRUÇÕES ESPECÍFICAS ===\n"
            "1. Identifique claramente o objeto do pedido\n"
            "2. Fundamente com base nos fatos do processo e na legislação aplicável\n"
            "3. Formule pedidos precisos e exequíveis\n"
            "4. Use linguagem técnica e formal\n"
        )

        llm = ChatOpenAI(model=self.model_name, temperature=0.3).with_structured_output(GeneratedPeticaoIntermediaria)
        print("[AgentGeneratedDocument] Gerando Petição Intermediária...")
        return llm.invoke([
            {"role": "system", "content": "Você é um advogado experiente em direito previdenciário. Gere petições jurídicas tecnicamente precisas e bem fundamentadas."},
            {"role": "user", "content": user_prompt},
        ])

    # ── Helpers ───────────────────────────────────────────────────────────

    def _build_process_context(self, process) -> str:
        lines = ["=== DADOS DO PROCESSO ==="]
        if process.process_number:
            lines.append(f"Processo nº: {process.process_number}")
        if process.title:
            lines.append(f"Título: {process.title}")
        if process.tribunal_name:
            lines.append(f"Tribunal/Vara: {process.tribunal_name}")
        if process.judge_name:
            lines.append(f"Juiz(a): {process.judge_name}")
        if process.plaintiff_client:
            lines.append(f"Autor: {process.plaintiff_client.name}")
        if process.defendant:
            lines.append(f"Réu: {process.defendant.name}")
        if process.process_class:
            lines.append(f"Classe processual: {process.process_class}")
        if process.filing_date:
            lines.append(f"Data de distribuição: {process.filing_date.strftime('%d/%m/%Y')}")
        return "\n".join(lines)

    def _build_selections_context(self, selections: list[dict], include_contestation: bool = False) -> str:
        """Constrói contexto textual a partir da lista de selections (benefit+thesis+contestation)."""
        if not selections:
            return ""
        lines = ["=== BENEFÍCIOS E TESES SELECIONADOS ==="]
        for sel in selections:
            benefit = sel.get('benefit')
            thesis = sel.get('thesis')
            contestation = sel.get('contestation')
            if not benefit:
                continue

            thesis_label = thesis.name if thesis else "Sem tese específica"
            lines.append(f"\n--- NB {benefit.benefit_number} | Tese: {thesis_label} ---")
            if benefit.insured_name:
                lines.append(f"Segurado: {benefit.insured_name}")
            if benefit.benefit_type:
                lines.append(f"Tipo de benefício: {benefit.benefit_type}")
            if benefit.fap_vigencia_year:
                lines.append(f"Vigência FAP: {benefit.fap_vigencia_year}")
            if benefit.request_type:
                lines.append(f"Tipo de pedido: {benefit.request_type}")

            if include_contestation and contestation:
                if contestation.contestation_status_label:
                    lines.append(f"Status da Contestação: {contestation.contestation_status_label} ({contestation.contestation_status})")
                if contestation.contestation_fundamento_uniao:
                    lines.append(f"Fundamento da União: {contestation.contestation_fundamento_uniao}")
                if contestation.contestation_efeito_fap:
                    lines.append(f"Efeito no FAP: {contestation.contestation_efeito_fap}")
                if contestation.contestation_trecho_detectado:
                    lines.append(f"Trecho Detectado: {contestation.contestation_trecho_detectado}")
            elif include_contestation and not contestation:
                lines.append("Contestação da União: não registrada para esta tese")

        return "\n".join(lines)

    def _build_style_references_block(
        self,
        process,
        selections: list[dict],
        law_firm_id: Optional[int],
    ) -> str:
        """Recupera trechos da base de peças-modelo do escritório e formata
        como bloco de inspiração de estilo no user_prompt.

        Falhas (Qdrant indisponível, sem referências, etc.) não devem
        interromper a geração — retornamos string vazia.
        """
        if not law_firm_id:
            return ""
        try:
            from app.agents.legal_drafting.impugnacao_reference_retriever import (
                ImpugnacaoReferenceRetriever,
            )

            query_parts = []
            process_number = getattr(process, 'process_number', None) or getattr(process, 'number', None)
            if process_number:
                query_parts.append(f"Processo {process_number}")
            for sel in (selections or [])[:6]:
                benefit = sel.get('benefit') if isinstance(sel, dict) else None
                thesis = sel.get('thesis') if isinstance(sel, dict) else None
                if thesis is not None and getattr(thesis, 'title', None):
                    query_parts.append(thesis.title)
                elif benefit is not None and getattr(benefit, 'request_type', None):
                    query_parts.append(str(benefit.request_type))
            query_text = " | ".join(query_parts) or "impugnação à contestação FAP"

            trf_region = None
            court_name = getattr(getattr(process, 'court', None), 'name', '') or ''
            for region in ('TRF1', 'TRF2', 'TRF3', 'TRF4', 'TRF5', 'TRF6'):
                if region.lower() in court_name.lower():
                    trf_region = region
                    break

            retriever = ImpugnacaoReferenceRetriever()
            chunks = retriever.fetch_style_references(
                law_firm_id=law_firm_id,
                query_text=query_text,
                trf_region=trf_region,
            )
            return retriever.format_block(chunks)
        except Exception as error:
            print(f"[AgentGeneratedDocument] Falha ao carregar referências de estilo: {error}")
            return ""

    def _build_regional_jurisprudence_hint(self, process) -> str:
        """Sugere priorização de jurisprudência do TRF regional conforme foro identificado no processo."""
        region_source = " ".join(
            [
                str(getattr(process, "tribunal_name", "") or ""),
                str(getattr(process, "section", "") or ""),
                str(getattr(process, "origin_unit", "") or ""),
            ]
        ).lower()

        # Mapeamento simples por indícios textuais do foro/região.
        region_patterns = [
            ("TRF1", r"\btrf\s*1\b|1[ªa]?\s*regi[aã]o"),
            ("TRF2", r"\btrf\s*2\b|2[ªa]?\s*regi[aã]o"),
            ("TRF3", r"\btrf\s*3\b|3[ªa]?\s*regi[aã]o|s[aã]o\s*paulo|jfsp"),
            ("TRF4", r"\btrf\s*4\b|4[ªa]?\s*regi[aã]o|rio\s*grande\s*do\s*sul|paran[aá]|santa\s*catarina"),
            ("TRF5", r"\btrf\s*5\b|5[ªa]?\s*regi[aã]o"),
            ("TRF6", r"\btrf\s*6\b|6[ªa]?\s*regi[aã]o|minas\s*gerais"),
        ]

        for region_label, pattern in region_patterns:
            if re.search(pattern, region_source, flags=re.IGNORECASE):
                return (
                    f"=== DIRETRIZ REGIONAL DE JURISPRUDÊNCIA ===\n"
                    f"O foro indica {region_label}. Quando houver precedente desse tribunal no catálogo, "
                    f"priorize ao menos uma citação inline regional na tese/preliminar correspondente."
                )

        return ""

    def dispatch(
        self,
        document_type: str,
        process,
        selections: list[dict],
        instructions: Optional[str] = None,
        contestation_file_path: Optional[str] = None,
        law_firm_id: Optional[int] = None,
    ):
        """
        Despacha para o método correto e retorna (result_dict, full_text).
        Levanta ValueError para tipos desconhecidos.
        """
        if document_type == "impugnacao_contestacao":
            result = self.generate_impugnacao_contestacao(
                process,
                selections,
                instructions,
                contestation_file_path=contestation_file_path,
                law_firm_id=law_firm_id,
            )
        elif document_type == "manifestacao":
            result = self.generate_manifestacao(process, selections, instructions)
        elif document_type == "peticao_intermediaria":
            result = self.generate_peticao_intermediaria(process, selections, instructions)
        else:
            raise ValueError(f"Tipo de documento desconhecido: {document_type}")
        return result.to_dict(), result.to_full_text()
