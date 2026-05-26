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
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()
from app.agents.config import DEFAULT_MODEL_LEGAL_DRAFTING

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8")


_IMPUGNACAO_SYSTEM_PROMPT = _load_prompt("system_prompt_impugnacao_v2.md")


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
        instructions_block = f"\n\n=== INSTRUÇÕES ADICIONAIS DO ADVOGADO ===\n{instructions}\n" if instructions else ""

        user_prompt = (
            f"{process_ctx}"
            f"\n\n{selections_ctx}"
            f"{instructions_block}\n\n"
            "Com base nos dados acima, gere a Impugnação à Contestação da União seguindo rigorosamente as instruções do sistema."
        )

        llm = ChatOpenAI(model=self.model_name, temperature=0.3).with_structured_output(
            GeneratedImpugnacaoContestacao
        )
        print("[AgentGeneratedDocument] Gerando Impugnação à Contestação (prompt v2.0)...")
        return llm.invoke([
            {"role": "system", "content": _IMPUGNACAO_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ])

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

    def dispatch(self, document_type: str, process, selections: list[dict], instructions: Optional[str] = None):
        """
        Despacha para o método correto e retorna (result_dict, full_text).
        Levanta ValueError para tipos desconhecidos.
        """
        if document_type == "impugnacao_contestacao":
            result = self.generate_impugnacao_contestacao(process, selections, instructions)
        elif document_type == "manifestacao":
            result = self.generate_manifestacao(process, selections, instructions)
        elif document_type == "peticao_intermediaria":
            result = self.generate_peticao_intermediaria(process, selections, instructions)
        else:
            raise ValueError(f"Tipo de documento desconhecido: {document_type}")
        return result.to_dict(), result.to_full_text()
