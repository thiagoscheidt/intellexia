import os
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field
from dotenv import load_dotenv
from markitdown import MarkItDown
from langchain_openai import ChatOpenAI
from app.agents.file_agent import FileAgent

load_dotenv()


# ==================== Modelos Pydantic ====================

class Entities(BaseModel):
    """Modelo para entidades extraídas do documento"""
    people: List[str] = Field(default_factory=list, description="Pessoas mencionadas")
    organizations: List[str] = Field(default_factory=list, description="Organizações mencionadas")
    locations: List[str] = Field(default_factory=list, description="Localizações mencionadas")


class Party(BaseModel):
    """Modelo para uma parte do processo"""
    name: str = Field(default="", description="Nome da parte")
    role: str = Field(default="", description="Papel da parte (Autor, Réu, etc)")
    lawyers: List[str] = Field(default_factory=list, description="Lista de advogados")


class Parties(BaseModel):
    """Modelo para as partes envolvidas no processo"""
    active_pole: List[Party] = Field(default_factory=list, description="Polo ativo")
    passive_pole: List[Party] = Field(default_factory=list, description="Polo passivo")


class Decision(BaseModel):
    """Modelo para uma decisão específica"""
    subject: str = Field(default="", description="Assunto da decisão")
    result: str = Field(default="", description="Resultado (Procedente, Improcedente, Parcialmente Procedente)")
    reasoning: str = Field(default="", description="Fundamentação breve da decisão")


class FapBenefitAnalysis(BaseModel):
    """Modelo para análise de benefício em processo FAP"""
    benefit_number: str = Field(default="", description="Número do benefício (NB)")
    insured_name: str = Field(default="", description="Nome do segurado")
    accident_type: str = Field(default="", description="Tipo/natureza do acidente")
    result: str = Field(default="", description="Resultado da análise (Aceito, Rejeitado, Parcialmente Aceito)")
    reasoning: str = Field(default="", description="Fundamentação breve da decisão sobre o benefício")


class SentenceInfo(BaseModel):
    """Modelo para informações específicas da sentença judicial"""
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
    operative_part: str = Field(default="", description="Dispositivo da sentença (o que foi decidido)")
    overall_result: str = Field(default="", description="Resultado geral (Procedente, Improcedente, Parcialmente Procedente)")
    decisions: List[Decision] = Field(default_factory=list, description="Decisões específicas sobre cada pedido")
    fap_benefits_analysis: List[FapBenefitAnalysis] = Field(default_factory=list, description="Análise individual de benefícios (apenas para processos FAP)")
    legal_grounds: List[str] = Field(default_factory=list, description="Fundamentos legais utilizados")
    jurisprudence_cited: List[str] = Field(default_factory=list, description="Jurisprudências citadas")
    possible_appeals: List[str] = Field(default_factory=list, description="Recursos possíveis")


class SentenceSummary(BaseModel):
    """Modelo para o resumo completo da sentença judicial"""
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
        """Converte o modelo para dicionário"""
        return self.model_dump(by_alias=True)

    def to_json(self) -> str:
        """Converte o modelo para JSON"""
        return self.model_dump_json(by_alias=True)


# ==================== Classe Principal ====================


class AgentSentenceSummary:
    model_name = None

    def __init__(self, model_name: str = "gpt-4o"):
        self.model_name = model_name

    def summarizeSentence(self, file_path: Optional[str] = None, text_content: Optional[str] = None) -> dict:
        """
        Gera um resumo estruturado em JSON para uma sentença judicial.

        Args:
            file_path: Caminho do arquivo a ser convertido (PDF/DOCX/etc).
            text_content: Texto já extraído do documento.

        Returns:
            dict: Payload JSON pronto para persistência.
        """
        if not file_path and not text_content:
            raise ValueError("É necessário fornecer file_path ou text_content")

        extracted_text = ""
        if text_content:
            extracted_text = text_content if isinstance(text_content, str) else str(text_content)
        else:
            md = MarkItDown()
            print("Iniciando conversão da sentença para texto...")
            result = md.convert(file_path)
            extracted_text = result.text_content or ""

        max_chars = int(os.getenv("SUMMARY_MAX_CHARS", "50000"))
        use_file = False
        file_id = None
        if len(extracted_text) > max_chars:
            print("Texto extraído excede o limite máximo, utilizando upload de arquivo para LLM...")
            file_agent = FileAgent()
            file_id = file_agent.upload_file(file_path)
            use_file = True

        user_prompt = (
            "Resuma a sentença judicial abaixo. Preserve informações jurídicas relevantes. "
            "Regras de tamanho: summary_short com 2-4 frases objetivas; summary_long com 2-4 parágrafos, "
            "mais completo e detalhado que o resumo curto. "
            "Se não houver dado para algum campo, use lista vazia ou string vazia.\n\n"
            "IMPORTANTE: Extraia as seguintes informações estruturadas no campo 'sentence_info':\n"
            "- process_number: número do processo\n"
            "- case_value: valor da causa (com formatação monetária)\n"
            "- subjects: lista de assuntos jurídicos\n"
            "- origin_court: tribunal de origem com cidade/estado\n"
            "- judgment_date: data da sentença (formato DD/MM/YYYY)\n"
            "- start_year: ano de início do processo\n"
            "- nature: natureza da ação (ex: Procedimento Comum)\n"
            "- judicial_power: poder judiciário (ex: Justiça Federal)\n"
            "- judge: nome do juiz/magistrado\n"
            "- court_tag: tag do tribunal conforme a lista (use a CHAVE, ex: TRF1, TJSP). Se não identificar, deixe vazio:\n"
            "  STF, STJ, TST, TSE, STM, TRF1, TRF2, TRF3, TRF4, TRF5, TRF6, "
            "TJAC, TJAL, TJAM, TJAP, TJBA, TJCE, TJDFT, TJES, TJGO, TJMA, TJMG, TJMS, "
            "TJMT, TJPA, TJPB, TJPE, TJPI, TJPR, TJRJ, TJRN, TJRO, TJRR, TJRS, TJSC, TJSE, TJSP, TJTO\n"
            "- parties: objeto contendo:\n"
            "  - active_pole: array de partes do polo ativo com nome, papel e advogados\n"
            "  - passive_pole: array de partes do polo passivo com nome, papel e advogados\n"
            "- operative_part: dispositivo da sentença (o que foi decidido, preferencialmente copiado literalmente)\n"
            "- overall_result: resultado geral (Procedente, Improcedente, Parcialmente Procedente)\n"
            "  IMPORTANTE: seja consistente com as decisões individuais:\n"
            "  - Se TODOS os pedidos forem Procedentes → overall_result = 'Procedente'\n"
            "  - Se TODOS os pedidos forem Improcedentes → overall_result = 'Improcedente'\n"
            "  - Se houver MIX de resultados → overall_result = 'Parcialmente Procedente'\n"
            "- decisions: array de decisões específicas sobre cada pedido com:\n"
            "  - subject: o pedido/questão\n"
            "  - result: resultado (Procedente/Improcedente/Parcialmente Procedente)\n"
            "  - reasoning: fundamentação breve\n"
            "- fap_benefits_analysis: SE FOR PROCESSO FAP (Revisão de FAP), array com análise de cada benefício:\n"
            "  - benefit_number: número do benefício (NB)\n"
            "  - insured_name: nome do segurado\n"
            "  - accident_type: tipo/natureza do acidente\n"
            "  - result: resultado (Aceito, Rejeitado, Parcialmente Aceito)\n"
            "  - reasoning: fundamentação breve da decisão sobre o benefício\n"
            "  (Se NÃO for processo FAP, deixe este campo como array vazio)\n"
            "- legal_grounds: lista de legislações, artigos e fundamentos utilizados\n"
            "- jurisprudence_cited: lista de jurisprudências citadas (ex: Súmula 123 STF)\n"
            "- possible_appeals: lista de recursos possíveis (Apelação, Agravo, Embargos, etc)\n\n"
            f"SENTENÇA:\n{extracted_text}"
        )
        
        print("Enviado para IA")
        llm = ChatOpenAI(
            model=self.model_name,
            temperature=0.2
        ).with_structured_output(SentenceSummary)

        if use_file and file_id:
            response = llm.invoke([
                {"role": "system", "content": "Você é um assistente jurídico especializado em análise de sentenças. Gere um resumo técnico, objetivo e estruturado."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt.replace(f"SENTENÇA:\n{extracted_text}", "SENTENÇA: (arquivo anexado)")},
                        {"type": "file", "file_id": file_id},
                    ],
                },
            ])
        else:
            response = llm.invoke([
                {"role": "system", "content": "Você é um assistente jurídico especializado em análise de sentenças. Gere um resumo técnico, objetivo e estruturado."},
                {"role": "user", "content": user_prompt}
            ])

        return response.to_dict()
