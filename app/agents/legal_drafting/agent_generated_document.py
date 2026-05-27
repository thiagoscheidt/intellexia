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
from pydantic import BaseModel, Field, ConfigDict
from langchain_openai import ChatOpenAI
from app.agents.core.file_agent import FileAgent
from app.utils.timezone import now_sp
from app.services.token_usage_service import TokenUsageService
from app.services.agent_execution_history_service import AgentExecutionHistoryService

from app.agents.config import DEFAULT_MODEL_LEGAL_DRAFTING

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
logger = logging.getLogger(__name__)

_PT_BR_MONTHS = {
    1: "janeiro",
    2: "fevereiro",
    3: "marco",
    4: "abril",
    5: "maio",
    6: "junho",
    7: "julho",
    8: "agosto",
    9: "setembro",
    10: "outubro",
    11: "novembro",
    12: "dezembro",
}


def _format_current_date_extenso_sp() -> str:
    """Retorna data corrente de Sao Paulo em formato por extenso."""
    current = now_sp()
    month_name = _PT_BR_MONTHS.get(current.month, str(current.month))
    return f"{current.day} de {month_name} de {current.year}"


def _normalize_closing_with_current_date(closing_text: str) -> str:
    """Forca o fecho a usar a data corrente, preservando cidade/UF quando informado."""
    current_date = _format_current_date_extenso_sp()
    text = str(closing_text or "").strip()
    if not text:
        return (
            "Nestes termos,\n\n"
            "Pede deferimento.\n\n"
            f"Florianopolis/SC, {current_date}."
        )

    location_pattern = r"([A-Za-zÀ-ÿ\s\.\-]+/[A-Z]{2})\s*,\s*[^.\n]+\.?"
    location_match = re.search(location_pattern, text)
    location = location_match.group(1).strip() if location_match else "Florianopolis/SC"

    text_without_date = re.sub(location_pattern, "", text).strip()
    text_without_date = re.sub(r"\n{3,}", "\n\n", text_without_date).rstrip()

    if text_without_date:
        return f"{text_without_date}\n\n{location}, {current_date}."
    return f"{location}, {current_date}."


def _load_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8")


_IMPUGNACAO_SYSTEM_PROMPT = _load_prompt("system_prompt_impugnacao_v2.md")

_IMPUGNACAO_INTERNAL_GUARDRAILS = """
=== REFORÇO INTERNO DE EXECUÇÃO (RUNTIME) ===

1) Numeração arábica SEQUENCIAL é obrigatória — nunca romana (I., II., III.).
- A numeração reflete o documento REAL: conte apenas as seções que efetivamente aparecem.
- Estrutura típica Modo A (com PRELIMINARES, sem PEDIDO RECONHECIDO):
    1. PRELIMINARES  →  1.1, 1.2...
    2. DA INSUFICIÊNCIA TÉCNICA E JURÍDICA DA CONTESTAÇÃO  →  2.1, 2.2...
    3. DO MÉRITO PROPRIAMENTE DITO  →  3.1, 3.2, 3.3...
    4. PEDIDOS (e eventuais seções condicionais antes)
- Se PEDIDO(S) RECONHECIDO(S) presente: acrescenta +1 a todos os números após ele.
- Se PRELIMINARES ausente: todos os números seguintes recuam em 1.
- Defina `merit_section_number` = número real da seção DO MÉRITO no documento.
- O campo `argument` de cada `ImpugnacaoBenefitThesisSection` DEVE começar DIRETAMENTE
  com o cabeçalho no formato `[merit_section_number].[i]. TITULO_EM_MAIÚSCULAS`
  (ex.: `3.1. ACIDENTE DE TRAJETO`) — sem linha em branco nem markdown antes.
  O sistema de renderização NÃO adiciona cabeçalho separado; o `argument` é exibido diretamente.

2) Campos macro do schema não podem aparecer como bloco solto sem título.
- `general_legal_grounds` e `jurisprudence` são campos de consolidação interna.
- No texto final da peça, integre esse conteúdo aos blocos já existentes (introdução, insuficiência técnica e mérito).
- Se houver seção separada, ela deve ter título explícito e numeração hierárquica coerente.

3) Prioridade para jurisprudência regional quando disponível no catálogo.
- Se o foro do processo indicar região específica (ex.: JFSP/TRF3), priorize ao menos uma citação inline do tribunal regional correspondente.
- Jurisprudência de outras regiões deve ser complementar quando houver precedente regional validado.

4) Agrupamento obrigatório por tese no mérito — PROIBIDO mesclar ou omitir teses.
- No Modo A, a seção de mérito deve ser construída por TESE, não por par benefício+tese.
- Para cada tese, agrupe todos os benefícios correspondentes em um único tópico/subseção.
- Em `benefit_sections`, cada item representa uma tese e deve trazer a lista `benefits[]`.
- CRÍTICO: gere EXATAMENTE uma entrada em `benefit_sections` para CADA tese presente no bloco
  "=== BENEFÍCIOS E TESES SELECIONADOS ===". Conte as teses listadas e confirme internamente
  que o número de entradas em `benefit_sections` é igual ao número de teses recebidas.
- É PROIBIDO mesclar duas teses em uma única seção, mesmo que compartilhem benefícios ou
  fundamentos parecidos. Cada rótulo de tese do input gera sua própria seção independente.
- É PROIBIDO omitir uma tese sob qualquer justificativa (redundância, similaridade, ausência
  de argumento específico da União). Se a União não individualizou a tese, isso é argumento
  a seu favor — registre a omissão e construa a argumentação de refutação normalmente.
- Um mesmo benefício pode aparecer em múltiplas teses; isso é esperado e não é motivo para
  colapsar seções.

5) Subseção COMPENSAÇÃO E RESTITUIÇÃO – PROCEDIMENTOS.
- Preencher o campo `compensation_section` SEMPRE que o processo incluir pedido de
  restituição ou compensação tributária (presente em quase todos os casos FAP).
- NÃO incluir o cabeçalho da subseção no texto — o sistema renderiza automaticamente
  '[merit_section_number].[n]. COMPENSAÇÃO E RESTITUIÇÃO – PROCEDIMENTOS'.
- NÃO colocar esse conteúdo dentro de `benefit_sections` nem em `general_legal_grounds`.
- Conteúdo obrigatório: direito à repetição do indébito (arts. 165 e 170 CTN) +
  procedimento de compensação (art. 89 § 4º Lei 8.212/1991) + atualização pela SELIC.

6) Marcadores internos NÃO podem ir para o texto final.
- NÃO inserir no corpo da peça: "⚠️", "nota ao revisor", "placeholder", "dados pendentes".
- Qualquer alerta/recomendação interna deve ir em `internal_review_notes`.
""".strip()


# ── Impugnação à Contestação da União ─────────────────────────────────────

class ImpugnacaoBenefitItem(BaseModel):
    """Benefício consolidado dentro de uma tese de mérito."""
    model_config = ConfigDict(extra='forbid')

    benefit_number: str = ""
    nit_number: str = ""
    insured_name: str = ""
    benefit_type: str = ""
    fap_vigencia_year: str = ""
    request_type: str = ""
    contestation_status_label: str = ""
    judicial_decisions: list[str] = Field(default_factory=list)

class ImpugnacaoBenefitThesisSection(BaseModel):
    model_config = ConfigDict(extra='forbid')

    thesis_name: str = Field(description="Nome da tese jurídica (um tópico de mérito por tese)")
    benefit_number: str = Field(
        default="",
        description="[LEGADO] Mantido por compatibilidade. Preferir campo benefits[].",
    )
    insured_name: str = Field(
        default="",
        description="[LEGADO] Mantido por compatibilidade. Preferir campo benefits[].",
    )
    benefits: list[ImpugnacaoBenefitItem] = Field(
        default_factory=list,
        description=(
            "Lista de benefícios desta tese. Cada item deve conter, quando disponível: "
            "benefit_number, nit_number, insured_name, benefit_type, fap_vigencia_year, "
            "request_type, contestation_status_label, judicial_decisions (lista de strings)."
        ),
    )
    argument: str = Field(
        description=(
            "Argumentação jurídica para esta tese (agrupando todos os benefícios da tese), "
            "seguindo a estrutura: identificação do pedido + tabela consolidada dos benefícios "
            "da tese + síntese do fundamento da União "
            "+ refutação técnica (premissa normativa + premissa fática + conclusão) "
            "+ citação jurisprudencial inline obrigatória (TRF/STJ do catálogo ou transversal) "
            "+ pedido de exclusão padrão. "
            "Se o status for 'procedente', reforce o reconhecimento da União. "
            "OBRIGATÓRIO: ao menos uma citação de TRF/STJ dentro do argumento."
        )
    )


class GeneratedImpugnacaoContestacao(BaseModel):
    model_config = ConfigDict(extra='forbid')

    generation_mode: str = Field(
        default="A",
        description=(
            "Modo de redação selecionado conforme Seção 0 do system prompt: "
            "'A' = Mérito por Tese (padrão — contestação com argumentos específicos por benefício); "
            "'B' = Defesa Processual (contestação integralmente genérica — peça curta sem catálogo de teses). "
            "Use os critérios da tabela da Seção 0.3 para decidir."
        ),
    )
    merit_section_number: int = Field(
        default=3,
        description=(
            "Número SEQUENCIAL real da seção 'DO MÉRITO PROPRIAMENTE DITO' no documento final. "
            "Compute contando apenas as seções que efetivamente aparecem: "
            "1 = PRELIMINARES (se presente); +1 = PEDIDO(S) RECONHECIDO(S) (se presente); "
            "+1 = DA INSUFICIÊNCIA TÉCNICA (sempre no Modo A); +1 = DO MÉRITO. "
            "Exemplos: com PRELIMINARES + sem PEDIDO RECONHECIDO → 3; "
            "sem PRELIMINARES → 2; com PRELIMINARES + PEDIDO RECONHECIDO → 4."
        ),
    )
    introduction: str = Field(description="Qualificação das partes, identificação do processo e contexto da impugnação")
    preliminary_notes: str = Field(
        description=(
            "Modo A: seções antes do mérito (PRELIMINARES se houver, numeradas a partir de 1; "
            "DA INSUFICIÊNCIA TÉCNICA no número sequencial correto). "
            "A última linha deve ser a frase de transição 'À luz desses parâmetros, passa-se à análise específica...'. "
            "Modo B: todo o conteúdo argumentativo — mérito sintético + subseção 1.1 + subseção 1.2. "
            "No Modo B não há desenvolvimento por tese; toda a argumentação vai aqui."
        )
    )
    benefit_sections: list[ImpugnacaoBenefitThesisSection] = Field(
        default_factory=list,
        description=(
            "Modo A: uma entrada por TESE na seção DO MÉRITO (número = merit_section_number), "
            "com benefícios agrupados em benefits[]. "
            "Cada `argument` DEVE começar com o cabeçalho '[merit_section_number].[i]. NOME_EM_MAIÚSCULAS' "
            "(ex.: '3.1. ACIDENTE DE TRAJETO') — sem linha em branco antes. "
            "Modo B: deixar VAZIO [] — não há mérito por tese na defesa processual."
        ),
    )
    compensation_section: str = Field(
        default="",
        description=(
            "Conteúdo da subseção 'COMPENSAÇÃO E RESTITUIÇÃO – PROCEDIMENTOS', "
            "renderizada como ÚLTIMA subseção de DO MÉRITO (após todas as teses). "
            "Preencher SEMPRE que o processo incluir pedido de restituição ou compensação tributária. "
            "NÃO incluir o cabeçalho da subseção aqui — ele é adicionado automaticamente pelo sistema. "
            "Conteúdo esperado: direito à repetição do indébito (arts. 165 e 170 CTN), "
            "procedimento de compensação (art. 89 § 4º Lei 8.212/1991), atualização pela SELIC. "
            "Deixar VAZIO apenas se não houver pedido de restituição/compensação no processo."
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
    internal_review_notes: str = Field(
        default="",
        description=(
            "Observações internas para revisão humana/UI. "
            "NÃO incluir no corpo da peça final; este campo é exibido separadamente."
        ),
    )

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

        if self.benefit_sections or self.compensation_section:
            merit_num = getattr(self, 'merit_section_number', 3)
            parts.append(f"\n## {merit_num}. DO MÉRITO PROPRIAMENTE DITO\n")
            for sec in self.benefit_sections:
                parts.append("\n" + sec.argument + "\n")
            if self.compensation_section:
                comp_idx = len(self.benefit_sections) + 1
                parts.append(
                    f"\n{merit_num}.{comp_idx}. COMPENSAÇÃO E RESTITUIÇÃO – PROCEDIMENTOS\n\n"
                )
                parts.append(self.compensation_section + "\n")

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


def _sanitize_generated_impugnacao(
    result: GeneratedImpugnacaoContestacao,
) -> GeneratedImpugnacaoContestacao:
    """Remove marcadores internos do texto final e consolida notas para revisão."""
    notes: list[str] = []

    def _clean(text: str) -> str:
        if not text:
            return ""

        cleaned_lines: list[str] = []
        for raw_line in str(text).splitlines():
            line = raw_line.strip()
            if not line:
                cleaned_lines.append(raw_line)
                continue

            if re.search(
                r"⚠️|nota\s+ao\s+revisor|placeholder|dados\s+pendentes|revis[aã]o\s+humana\s+recomendada",
                line,
                flags=re.IGNORECASE,
            ):
                notes.append(line)
                continue

            cleaned_lines.append(raw_line)

        cleaned = "\n".join(cleaned_lines)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    result.introduction = _clean(result.introduction)
    result.preliminary_notes = _clean(result.preliminary_notes)
    result.general_legal_grounds = _clean(result.general_legal_grounds)
    result.jurisprudence = _clean(result.jurisprudence)
    result.requests = _clean(result.requests)
    result.closing = _normalize_closing_with_current_date(_clean(result.closing))

    for section in result.benefit_sections:
        section.argument = _clean(section.argument)

    if result.internal_review_notes:
        notes.append(result.internal_review_notes.strip())

    dedup: list[str] = []
    seen = set()
    for item in notes:
        key = re.sub(r"\s+", " ", item).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        dedup.append(item.strip())

    result.internal_review_notes = "\n".join(dedup)[:4000]
    return result


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
        contestation_summary_payload: Optional[dict] = None,
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
        contestation_summary_ctx = self._build_contestation_summary_context(contestation_summary_payload)
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
        if contestation_summary_ctx:
            user_prompt_sections.append(contestation_summary_ctx)
        if regional_jurisprudence_hint:
            user_prompt_sections.append(regional_jurisprudence_hint)
        if style_references_block:
            user_prompt_sections.append(style_references_block)

        user_prompt = "\n\n".join(section for section in user_prompt_sections if section)
        user_prompt = (
            f"{user_prompt}"
            f"{instructions_block}\n\n"
            "Com base nos dados acima, gere a Impugnação à Contestação da União seguindo rigorosamente as instruções do sistema.\n"
            "Priorize objetividade: sem repetições, sem transcrever blocos longos e com redação técnica concisa.\n"
            "Mantenha o conteúdo completo, mas com parágrafos curtos e foco nos pontos essenciais."
        )

        user_prompt = self._shrink_user_prompt(user_prompt)

        file_part = None
        normalized_contestation_path = str(contestation_file_path or '').strip()
        if normalized_contestation_path:
            try:
                file_part = FileAgent().build_openrouter_file_part(normalized_contestation_path)
            except Exception as error:
                print(f"[AgentGeneratedDocument] Falha ao anexar arquivo da contestação: {error}")

        llm_messages = [
            {
                "role": "system",
                "content": f"{_IMPUGNACAO_SYSTEM_PROMPT}\n\n{_IMPUGNACAO_INTERNAL_GUARDRAILS}",
            },
            {
                "role": "user",
                "content": (
                    [{"type": "text", "text": user_prompt}, file_part]
                    if file_part is not None
                    else user_prompt
                ),
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
        print("[AgentGeneratedDocument] Resumo da contestação na chamada: SIM")
        print(f"[AgentGeneratedDocument] Anexo PDF na chamada: {'SIM' if file_part is not None else 'NÃO'}")

        llm = ChatOpenAI(
            model=self.model_name,
            temperature=0.3
        ).with_structured_output(
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
            # Erro comum: JSON truncado/inválido quando a saída fica longa.
            # Fazemos 1 retry com contenção de tokens e instrução de concisão.
            err_text = str(error or "")
            if "json_invalid" in err_text.lower() or "invalid json" in err_text.lower():
                try:
                    print("[AgentGeneratedDocument] JSON inválido detectado; retry com contenção de tokens...")
                    compact_user_prompt = (
                        f"{user_prompt}\n\n"
                        "=== MODO DE CONTENÇÃO DE TOKENS ===\n"
                        "Retorne JSON VÁLIDO e COMPLETO no schema. "
                        "Seja objetivo: parágrafos mais curtos, sem repetições, "
                        "mantendo qualidade técnica e todos os campos obrigatórios. "
                        "Reduza o volume total de texto e elimine redundâncias."
                    )
                    compact_user_prompt = self._shrink_user_prompt(compact_user_prompt)

                    compact_messages = [
                        {
                            "role": "system",
                            "content": system_content,
                        },
                        {
                            "role": "user",
                            "content": (
                                [{"type": "text", "text": compact_user_prompt}, file_part]
                                if file_part is not None
                                else compact_user_prompt
                            ),
                        },
                    ]
                    retry_llm = ChatOpenAI(
                        model=self.model_name,
                        temperature=0.2,
                    ).with_structured_output(GeneratedImpugnacaoContestacao)
                    parsed_result = retry_llm.invoke(compact_messages)
                    raw_message = None
                    llm_messages = compact_messages
                    user_prompt = compact_user_prompt
                    print("[AgentGeneratedDocument] Retry concluído com sucesso.")
                except Exception:
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
            else:
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

        if isinstance(parsed_result, GeneratedImpugnacaoContestacao):
            parsed_result = _sanitize_generated_impugnacao(parsed_result)

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
                    "has_contestation_summary": bool(contestation_summary_ctx),
                    "has_contestation_file": bool(file_part),
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
        """Constrói contexto textual agrupado por tese (múltiplos benefícios por tese)."""
        if not selections:
            return ""

        original_count = len(selections)
        if original_count > 40:
            selections = selections[:40]

        lines = ["=== BENEFÍCIOS E TESES SELECIONADOS (AGRUPADO POR TESE) ==="]
        if original_count > len(selections):
            lines.append(
                f"Observação: contexto resumido para {len(selections)} de {original_count} seleções "
                "(limite configurado em 40)."
            )

        grouped: dict[str, list[dict]] = {}
        for sel in selections:
            benefit = sel.get('benefit')
            thesis = sel.get('thesis')
            contestation = sel.get('contestation')
            if not benefit:
                continue

            thesis_label = (thesis.name if thesis else "Sem tese específica").strip()
            grouped.setdefault(thesis_label, []).append({
                'benefit': benefit,
                'contestation': contestation,
            })

        for thesis_label, rows in grouped.items():
            count = len(rows)
            lines.append(f"\n{count} {'benefício' if count == 1 else 'benefícios'}")
            lines.append(thesis_label.upper())
            lines.append(
                "NB\tNIT\tSegurado\tTipo\tVigência FAP\tTipo de Pedido\t"
                "Decisão da União\tDecisões Judiciais"
            )

            for row in rows:
                benefit = row['benefit']
                contestation = row.get('contestation')

                # Helpers: prefer contestation record; fall back to benefit direct fields
                def _cont_val(cont_attr: str, ben_attr: str | None = None):
                    if contestation:
                        v = getattr(contestation, cont_attr, None)
                        if v:
                            return v
                    if ben_attr:
                        return getattr(benefit, ben_attr, None) or None
                    return None

                status_uniao = "—"
                if include_contestation:
                    status_uniao = (
                        _cont_val('contestation_status_label', 'contestation_status_label')
                        or _cont_val('contestation_status', 'contestation_status')
                        or "—"
                    )

                decisions = "Não teve decisão"
                if include_contestation and contestation and contestation.contestation_decision:
                    compact = " ".join(str(contestation.contestation_decision).split())
                    decisions = compact[:240] + ("..." if len(compact) > 240 else "")

                lines.append(
                    f"{benefit.benefit_number or '—'}\t"
                    f"{benefit.nit_number or '—'}\t"
                    f"{benefit.insured_name or '—'}\t"
                    f"{benefit.benefit_type or '—'}\t"
                    f"{benefit.fap_vigencia_year or '—'}\t"
                    f"{benefit.request_type or '—'}\t"
                    f"{status_uniao}\t"
                    f"{decisions}"
                )

                if include_contestation:
                    fundamento = _cont_val('contestation_fundamento_uniao', 'contestation_fundamento_uniao')
                    efeito = _cont_val('contestation_efeito_fap', 'contestation_efeito_fap')
                    trecho = _cont_val('contestation_trecho_detectado', 'contestation_trecho_detectado')
                    if fundamento:
                        lines.append(f"Fundamento da União: {self._clip_text(fundamento)}")
                    if efeito:
                        lines.append(f"Efeito no FAP: {self._clip_text(efeito)}")
                    if trecho:
                        lines.append(f"Trecho Detectado: {self._clip_text(trecho)}")

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

            trf_region = None
            court_name = getattr(getattr(process, 'court', None), 'name', '') or ''
            if not court_name:
                court_name = str(getattr(process, 'tribunal_name', '') or '')
            for region in ('TRF1', 'TRF2', 'TRF3', 'TRF4', 'TRF5', 'TRF6'):
                if region.lower() in court_name.lower():
                    trf_region = region
                    break

            section_plans = [
                (
                    "INTRODUCAO",
                    [('introduction', 3), ('general', 1), ('preliminary', 1)],
                    "Abertura da peça, qualificação das partes e síntese da controvérsia.",
                ),
                (
                    "PRELIMINARES",
                    [('preliminary', 3), ('jurisprudence', 2), ('general', 1)],
                    "Preliminares, prejudiciais e vícios processuais da contestação.",
                ),
                (
                    "MERITO",
                    [('merit_by_thesis', 4), ('jurisprudence', 2), ('general', 1)],
                    "Estrutura argumentativa de mérito e refutação técnica por tese.",
                ),
                (
                    "PEDIDOS",
                    [('requests', 3), ('general', 1), ('jurisprudence', 1)],
                    "Fechamento dos pedidos, procedência, provas, honorários e intimações.",
                ),
            ]

            focused_kind_plan = [
                ('merit_by_thesis', 5),
                ('jurisprudence', 2),
                ('requests', 1),
            ]

            grouped: dict[str, list[dict]] = {}
            thesis_key_by_label: dict[str, str] = {}
            for sel in (selections or []):
                if not isinstance(sel, dict):
                    continue
                thesis = sel.get('thesis')
                thesis_name = None
                thesis_key = None
                if thesis is not None:
                    thesis_name = getattr(thesis, 'title', None) or getattr(thesis, 'name', None)
                    thesis_key = getattr(thesis, 'key', None)
                thesis_label = (str(thesis_name).strip() if thesis_name else 'Sem tese específica')
                grouped.setdefault(thesis_label, []).append(sel)
                if thesis_key and thesis_label not in thesis_key_by_label:
                    thesis_key_by_label[thesis_label] = str(thesis_key).strip()

            retriever = ImpugnacaoReferenceRetriever()

            style_blocks: list[str] = [
                "=== REFERENCIAS JURIDICAS DE ESTILO (POR SECAO E POR TESE) ===",
                "Use os exemplos abaixo como guia de escrita do escritório.",
                "Nao copie fatos concretos de outros casos (nomes, NITs, CNPJs, datas de acidente).",
                "EXCECAO OBRIGATORIA: blocos JURISPRUDENCIA_REGIONAL e JURISPRUDENCIA_COMPLEMENTAR "
                "sao decisoes reais — cite-as INLINE no texto da tese correspondente, "
                "usando o numero do processo, o tribunal e o relator exatamente como aparecem no bloco.",
            ]

            max_total_chars = 22000
            max_section_chars = 2200
            max_thesis_chars = 4500

            process_summary = self._clip_text(self._build_process_context(process), max_chars=700)
            selections_summary = self._clip_text(
                self._build_selections_context(selections, include_contestation=True),
                max_chars=1600,
            )

            # 1) Busca por seção da peça (introdução, preliminares, mérito e pedidos).
            for section_label, kind_plan, section_focus in section_plans:
                section_query = (
                    f"Seção da peça: {section_label} | "
                    f"Objetivo: {section_focus} | "
                    f"Contexto do processo: {process_summary} | "
                    f"Seleções do caso: {selections_summary}"
                )
                section_chunks = retriever.fetch_style_references(
                    law_firm_id=law_firm_id,
                    query_text=section_query,
                    trf_region=trf_region,
                    kind_plan=kind_plan,
                    max_chunks=5,
                    max_chars=max_section_chars,
                )
                section_block = self._build_section_style_reference_block(
                    section_label=section_label,
                    chunks=section_chunks,
                    max_chars=max_section_chars,
                )
                if not section_block:
                    continue

                projected_size = len("\n".join(style_blocks)) + len(section_block) + 2
                if projected_size > max_total_chars and len(style_blocks) > 3:
                    break
                style_blocks.append(section_block)

            # 2) Busca equivalente por tese (núcleo do mérito).
            for thesis_label, thesis_rows in grouped.items():
                thesis_catalog_tag = thesis_key_by_label.get(thesis_label)
                query_parts = [
                    f"Tese principal do caso: {thesis_label}",
                    "Buscar exemplos EQUIVALENTES de redação e fundamentação para essa tese.",
                    "Priorizar padrão de mérito por tese do escritório.",
                ]
                if thesis_catalog_tag:
                    query_parts.append(f"Tag de tese categorizada no RAG: {thesis_catalog_tag}")

                for sel in thesis_rows[:6]:
                    benefit = sel.get('benefit')
                    contestation = sel.get('contestation')

                    if benefit is not None:
                        if getattr(benefit, 'request_type', None):
                            query_parts.append(f"Pedido: {benefit.request_type}")
                        if getattr(benefit, 'benefit_type', None):
                            query_parts.append(f"Tipo benefício: {benefit.benefit_type}")
                        if getattr(benefit, 'fap_vigencia_year', None):
                            query_parts.append(f"Vigência FAP: {benefit.fap_vigencia_year}")

                    if contestation is not None:
                        status_label = (
                            getattr(contestation, 'contestation_status_label', None)
                            or getattr(contestation, 'contestation_status', None)
                        )
                        if status_label:
                            query_parts.append(f"Status União: {status_label}")

                        fundamento = getattr(contestation, 'contestation_fundamento_uniao', None)
                        if fundamento:
                            query_parts.append(
                                "Fundamento União: "
                                f"{self._clip_text(fundamento, max_chars=180)}"
                            )

                query_text = " | ".join(query_parts) or f"Tese: {thesis_label}"

                chunks = retriever.fetch_style_references(
                    law_firm_id=law_firm_id,
                    query_text=query_text,
                    trf_region=trf_region,
                    thesis_catalog_id=thesis_catalog_tag,
                    kind_plan=focused_kind_plan,
                    max_chunks=6,
                )
                if not chunks:
                    continue

                thesis_block = self._build_budgeted_thesis_reference_block(
                    thesis_label=thesis_label,
                    chunks=chunks,
                    trf_region=trf_region,
                    max_chars=max_thesis_chars,
                )
                if not thesis_block:
                    continue

                # Evita estourar contexto global do bloco de referências.
                projected_size = len("\n".join(style_blocks)) + len(thesis_block) + 2
                if projected_size > max_total_chars and len(style_blocks) > 3:
                    break

                style_blocks.append(thesis_block)

            if len(style_blocks) <= 3:
                return ""

            block = "\n".join(style_blocks)
            if len(block) > max_total_chars:
                block = self._prune_rag_block(block, max_chars=max_total_chars)

            return block
        except Exception as error:
            print(f"[AgentGeneratedDocument] Falha ao carregar referências de estilo: {error}")
            return ""

    def _build_section_style_reference_block(
        self,
        *,
        section_label: str,
        chunks: list[dict],
        max_chars: int,
    ) -> str:
        """Monta bloco de referências de estilo para uma seção específica da peça."""
        if not chunks:
            return ""

        parts = [f"\n<SECAO nome=\"{section_label}\">"]
        total_chars = len(parts[0])
        seen = set()
        item_count = 0

        for chunk in chunks:
            text = self._compact_reference_text(chunk.get("text") or "", max_chars=700)
            if not text:
                continue

            normalized_key = re.sub(r"\s+", " ", text).strip().lower()
            if normalized_key in seen:
                continue
            seen.add(normalized_key)

            item_count += 1
            meta = []
            if chunk.get("section_kind"):
                meta.append(f"secao: {chunk['section_kind']}")
            if chunk.get("trf_region"):
                meta.append(f"regiao: {chunk['trf_region']}")
            if chunk.get("quality_score") is not None:
                meta.append(f"qualidade: {chunk['quality_score']}")
            meta_str = " | ".join(meta) if meta else "sem metadados"

            heading = (chunk.get("heading") or "").strip()
            entry_lines = [f"[item {item_count} | {meta_str}]"]
            if heading:
                entry_lines.append(f"[heading original: {heading}]")
            entry_lines.append(text)
            entry_lines.append("")
            entry_text = "\n".join(entry_lines)

            if total_chars + len(entry_text) > max_chars and item_count > 1:
                break

            parts.append(entry_text)
            total_chars += len(entry_text)

        if item_count == 0:
            return ""

        parts.append("</SECAO>")
        return "\n".join(parts)

    def _build_budgeted_thesis_reference_block(
        self,
        *,
        thesis_label: str,
        chunks: list[dict],
        trf_region: Optional[str],
        max_chars: int,
    ) -> str:
        """Monta bloco de referência por tese com orçamento por seção."""
        if not chunks:
            return ""

        budgets = {
            "EXEMPLO_ESTRUTURA_TESE": 1600,
            "JURISPRUDENCIA_REGIONAL": 1800,
            "JURISPRUDENCIA_COMPLEMENTAR": 900,
            "PADRAO_PEDIDO_DA_TESE": 900,
            "REFERENCIAS_COMPLEMENTARES": 600,
        }

        regional = (trf_region or "").strip().upper()
        categories = {
            "EXEMPLO_ESTRUTURA_TESE": [],
            "JURISPRUDENCIA_REGIONAL": [],
            "JURISPRUDENCIA_COMPLEMENTAR": [],
            "PADRAO_PEDIDO_DA_TESE": [],
            "REFERENCIAS_COMPLEMENTARES": [],
        }

        for chunk in chunks:
            kind = (chunk.get("section_kind") or "").strip().lower()
            chunk_region = (chunk.get("trf_region") or "").strip().upper()

            if kind == "merit_by_thesis":
                categories["EXEMPLO_ESTRUTURA_TESE"].append(chunk)
            elif kind == "jurisprudence":
                if regional and chunk_region == regional:
                    categories["JURISPRUDENCIA_REGIONAL"].append(chunk)
                elif chunk_region.startswith("TRF"):
                    categories["JURISPRUDENCIA_REGIONAL"].append(chunk)
                else:
                    categories["JURISPRUDENCIA_COMPLEMENTAR"].append(chunk)
            elif kind == "requests":
                categories["PADRAO_PEDIDO_DA_TESE"].append(chunk)
            else:
                categories["REFERENCIAS_COMPLEMENTARES"].append(chunk)

        parts = [f"\n<TESE nome=\"{thesis_label}\">"]
        total_chars = len(parts[0])

        def append_section(tag_name: str, section_chunks: list[dict], max_items: int, budget: int) -> None:
            nonlocal total_chars
            if not section_chunks or budget <= 0 or max_items <= 0:
                return

            local_parts = [f"<{tag_name}>"]
            used_chars = 0
            seen = set()
            item_count = 0

            for chunk in section_chunks:
                if item_count >= max_items:
                    break
                text = self._compact_reference_text(
                    chunk.get("text") or "",
                    max_chars=max(250, budget // max_items),
                )
                if not text:
                    continue

                normalized_key = re.sub(r"\s+", " ", text).strip().lower()
                if normalized_key in seen:
                    continue
                seen.add(normalized_key)

                heading = (chunk.get("heading") or "").strip()
                meta = []
                if chunk.get("section_kind"):
                    meta.append(f"secao: {chunk['section_kind']}")
                if chunk.get("trf_region"):
                    meta.append(f"regiao: {chunk['trf_region']}")
                if chunk.get("thesis_catalog_id"):
                    meta.append(f"tese_tag: {chunk['thesis_catalog_id']}")
                if chunk.get("quality_score") is not None:
                    meta.append(f"qualidade: {chunk['quality_score']}")
                if chunk.get("tribunal"):
                    meta.append(f"tribunal: {chunk['tribunal']}")
                if chunk.get("case_number"):
                    meta.append(f"processo: {chunk['case_number']}")
                if chunk.get("relator"):
                    meta.append(f"relator: {chunk['relator']}")
                if chunk.get("orgao_julgador"):
                    meta.append(f"orgao: {chunk['orgao_julgador']}")
                if chunk.get("data_julgamento"):
                    meta.append(f"julgado_em: {chunk['data_julgamento']}")
                if chunk.get("fundamento_principal"):
                    meta.append(f"fundamento: {chunk['fundamento_principal']}")
                meta_str = " | ".join(meta) if meta else "sem metadados"

                entry_lines = [f"[item {item_count + 1} | {meta_str}]"]
                if heading:
                    entry_lines.append(f"[heading original: {heading}]")
                entry_lines.append(text)
                entry_lines.append("")

                entry_text = "\n".join(entry_lines)
                if used_chars + len(entry_text) > budget and item_count > 0:
                    break

                local_parts.append(entry_text)
                used_chars += len(entry_text)
                item_count += 1

            if item_count == 0:
                return

            local_parts.append(f"</{tag_name}>")
            section_text = "\n".join(local_parts)
            if total_chars + len(section_text) <= max_chars:
                parts.append(section_text)
                total_chars += len(section_text)

        append_section(
            "EXEMPLO_ESTRUTURA_TESE",
            categories["EXEMPLO_ESTRUTURA_TESE"],
            max_items=1,
            budget=budgets["EXEMPLO_ESTRUTURA_TESE"],
        )
        append_section(
            "JURISPRUDENCIA_REGIONAL",
            categories["JURISPRUDENCIA_REGIONAL"],
            max_items=2,
            budget=budgets["JURISPRUDENCIA_REGIONAL"],
        )
        append_section(
            "JURISPRUDENCIA_COMPLEMENTAR",
            categories["JURISPRUDENCIA_COMPLEMENTAR"],
            max_items=1,
            budget=budgets["JURISPRUDENCIA_COMPLEMENTAR"],
        )
        append_section(
            "PADRAO_PEDIDO_DA_TESE",
            categories["PADRAO_PEDIDO_DA_TESE"],
            max_items=1,
            budget=budgets["PADRAO_PEDIDO_DA_TESE"],
        )
        append_section(
            "REFERENCIAS_COMPLEMENTARES",
            categories["REFERENCIAS_COMPLEMENTARES"],
            max_items=1,
            budget=budgets["REFERENCIAS_COMPLEMENTARES"],
        )

        parts.append(
            "<INSTRUCAO_DE_USO>"
            "Priorize EXEMPLO_ESTRUTURA_TESE para estrutura argumentativa. "
            "Para JURISPRUDENCIA_REGIONAL e JURISPRUDENCIA_COMPLEMENTAR: "
            "incorpore cada decisao como citacao inline real na tese — "
            "mencione o tribunal, o numero do processo e o relator exatamente como estao no bloco. "
            "Formato sugerido: 'Conforme [Tribunal], [tipo] n. [numero], Rel. [Relator]: [trecho da ementa]'. "
            "Nao apenas mencione que existe jurisprudencia — transcreva a essencia da decisao."
            "</INSTRUCAO_DE_USO>"
        )
        parts.append("</TESE>")

        return "\n".join(parts)

    def _compact_reference_text(self, text: str, max_chars: int = 1000) -> str:
        """Compacta texto de referência preservando conteúdo jurídico útil."""
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized:
            return ""
        if len(normalized) <= max_chars:
            return normalized

        # Prioriza sentenças com sinais de jurisprudência/fundamento.
        sentences = re.split(r"(?<=[.!?])\s+", normalized)
        if len(sentences) <= 1:
            return normalized[:max_chars].rstrip() + "..."

        priority_patterns = [
            r"\bTRF\b|\bSTJ\b|\bREsp\b|\bAC\b|\bprocesso\b",
            r"\bart\.\b|\bCPC\b|\bLINDB\b|\blei\b|\bônus\b",
            r"\bfap\b|\bbenef[ií]cio\b|\bnexo\b|\bc[aá]lculo\b",
        ]

        prioritized: list[str] = []
        others: list[str] = []
        for sentence in sentences:
            s = sentence.strip()
            if not s:
                continue
            if any(re.search(pattern, s, flags=re.IGNORECASE) for pattern in priority_patterns):
                prioritized.append(s)
            else:
                others.append(s)

        ordered = prioritized + others
        result = []
        total = 0
        for sentence in ordered:
            add_len = len(sentence) + (1 if result else 0)
            if total + add_len > max_chars:
                break
            result.append(sentence)
            total += add_len

        if not result:
            return normalized[:max_chars].rstrip() + "..."

        compacted = " ".join(result).strip()
        if len(compacted) < len(normalized):
            compacted = compacted.rstrip() + "..."
        return compacted

    def _build_contestation_summary_context(self, contestation_summary_payload: Optional[dict]) -> str:
        """Monta bloco textual do resumo estruturado da contestação para reduzir custo de contexto."""
        payload = contestation_summary_payload if isinstance(contestation_summary_payload, dict) else {}
        summary_text = self._clip_text(payload.get("summary_text") or "", max_chars=3500)
        summary_short = self._clip_text(payload.get("summary_short") or "", max_chars=900)
        summary_long = self._clip_text(payload.get("summary_long") or "", max_chars=5500)
        key_points = [str(item).strip() for item in (payload.get("key_points") or []) if str(item).strip()][:18]
        requests = [str(item).strip() for item in (payload.get("requests") or []) if str(item).strip()][:20]
        union_arguments_by_thesis = payload.get("union_arguments_by_thesis")
        if not isinstance(union_arguments_by_thesis, list):
            union_arguments_by_thesis = []
        notes = self._clip_text(payload.get("notes") or "", max_chars=1200)

        if not any([
            summary_text,
            summary_short,
            summary_long,
            key_points,
            requests,
            union_arguments_by_thesis,
            notes,
        ]):
            return ""

        lines = [
            "=== RESUMO ESTRUTURADO DA CONTESTACAO (FONTE PRINCIPAL) ===",
            "Use este resumo como base central para identificar argumentos, pedidos e pontos controvertidos da contestação.",
            "Nao invente fatos fora deste bloco e dos dados estruturados de benefícios/teses.",
        ]

        if summary_short:
            lines.append("\nResumo executivo:")
            lines.append(summary_short)
        if summary_long:
            lines.append("\nResumo completo:")
            lines.append(summary_long)
        if summary_text and summary_text not in (summary_short, summary_long):
            lines.append("\nResumo adicional:")
            lines.append(summary_text)
        if key_points:
            lines.append("\nPontos-chave identificados:")
            lines.extend([f"- {item}" for item in key_points])
        if requests:
            lines.append("\nPedidos identificados na contestação:")
            lines.extend([f"- {item}" for item in requests])
        if union_arguments_by_thesis:
            lines.append("\nArgumentos da União por tese:")
            for item in union_arguments_by_thesis[:18]:
                if not isinstance(item, dict):
                    continue
                thesis_name = self._clip_text(item.get("thesis") or "Tese não identificada", max_chars=180)
                status = self._clip_text(item.get("status") or "nao identificado", max_chars=80)
                lines.append(f"- Tese: {thesis_name} | Status: {status}")
                arguments = item.get("arguments") or []
                if isinstance(arguments, list):
                    for argument in arguments[:5]:
                        argument_text = self._clip_text(str(argument or "").strip(), max_chars=320)
                        if argument_text:
                            lines.append(f"  - {argument_text}")
        if notes:
            lines.append("\nObservações técnicas:")
            lines.append(notes)

        return "\n".join(lines)

    def _prune_rag_block(self, block: str, max_chars: int = 20000) -> str:
        """Poda bloco RAG com prioridade semântica antes de corte cego."""
        text = str(block or "")
        if len(text) <= max_chars:
            return text

        # Primeiro remove seções complementares menos críticas.
        text = re.sub(
            r"\n<REFERENCIAS_COMPLEMENTARES>.*?</REFERENCIAS_COMPLEMENTARES>",
            "",
            text,
            flags=re.DOTALL,
        )
        if len(text) <= max_chars:
            return text

        text = re.sub(
            r"\n<JURISPRUDENCIA_COMPLEMENTAR>.*?</JURISPRUDENCIA_COMPLEMENTAR>",
            "",
            text,
            flags=re.DOTALL,
        )
        if len(text) <= max_chars:
            return text

        # Como último recurso, corte controlado sem inserir aviso extra.
        return text[:max_chars]

    def _clip_text(self, value: str, max_chars: Optional[int] = None) -> str:
        text = " ".join(str(value or "").split())
        limit = max_chars or 400
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

    def _shrink_user_prompt(self, prompt: str) -> str:
        """Reduz o prompt de usuário para evitar estouro de contexto/tokens."""
        text = str(prompt or "")
        if len(text) <= 60000:
            return text

        marker = "=== REFERÊNCIAS DE ESTILO"
        marker_index = text.find(marker)
        if marker_index < 0:
            marker_index = text.find("=== REFERENCIAS JURIDICAS DE ESTILO")
        if marker_index > 0:
            head = text[:marker_index]
            tail = text[marker_index:]
            keep_tail = int(60000 * 0.35)
            keep_head = 60000 - keep_tail
            shrunk = (
                head[:keep_head]
                + "\n\n[Contexto intermediário truncado por limite de tamanho.]\n\n"
                + tail[:keep_tail]
            )
            if len(shrunk) <= 60000:
                return shrunk

        return (
            text[:60000]
            + "\n\n[Prompt truncado automaticamente para respeitar o limite de contexto.]"
        )

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
        contestation_summary_payload: Optional[dict] = None,
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
                contestation_summary_payload=contestation_summary_payload,
                law_firm_id=law_firm_id,
            )
        elif document_type == "manifestacao":
            result = self.generate_manifestacao(process, selections, instructions)
        elif document_type == "peticao_intermediaria":
            result = self.generate_peticao_intermediaria(process, selections, instructions)
        else:
            raise ValueError(f"Tipo de documento desconhecido: {document_type}")
        return result.to_dict(), result.to_full_text()
