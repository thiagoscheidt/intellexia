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


class LawsuitInfo(BaseModel):
    """Modelo para informações específicas de processo judicial"""
    process_number: str = Field(default="", description="Número do processo")
    case_value: str = Field(default="", description="Valor da causa")
    subjects: List[str] = Field(default_factory=list, description="Assuntos jurídicos")
    origin_court: str = Field(default="", description="Tribunal de origem")
    start_year: str = Field(default="", description="Ano de início")
    nature: str = Field(default="", description="Natureza da ação")
    judicial_power: str = Field(default="", description="Poder judiciário")
    judge: str = Field(default="", description="Nome do juiz")
    parties: Parties = Field(default_factory=Parties, description="Partes envolvidas")


class DocumentSummary(BaseModel):
    """Modelo para o resumo completo do documento"""
    summary: str = Field(description="Resumo geral do documento")
    summary_short: str = Field(default="", description="Resumo curto (2-4 frases)")
    summary_long: str = Field(default="", description="Resumo longo (2-4 parágrafos)")
    key_points: List[str] = Field(default_factory=list, description="Pontos-chave")
    entities: Entities = Field(default_factory=Entities, description="Entidades extraídas")
    dates: List[str] = Field(default_factory=list, description="Datas mencionadas")
    lawsuit_numbers: List[str] = Field(default_factory=list, description="Números de processo")
    language: str = Field(default="pt-BR", description="Idioma do documento")
    notes: str = Field(default="", description="Observações adicionais")
    court_tag: str = Field(default="", description="Tag do tribunal conforme lista pré-definida")
    lawsuit_info: LawsuitInfo = Field(default_factory=LawsuitInfo, description="Informações de processo")

    def to_dict(self) -> dict:
        """Converte o modelo para dicionário"""
        return self.model_dump(by_alias=True)

    def to_json(self) -> str:
        """Converte o modelo para JSON"""
        return self.model_dump_json(by_alias=True)


# ==================== Classe Principal ====================


class AgentDocumentSummary:
    model_name = None

    def __init__(self, model_name: str = "gpt-4o"):
        self.model_name = model_name

    def summarizeDocument(self, file_path: Optional[str] = None, text_content: Optional[str] = None) -> dict:
        """
        Gera um resumo estruturado em JSON para um documento.

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
            print("Iniciando conversão do documento para texto...")
            result = md.convert(file_path)
            extracted_text = result.text_content or ""

        max_chars = int(os.getenv("SUMMARY_MAX_CHARS", "24000"))
        use_file = False
        file_id = None
        if len(extracted_text) > max_chars:
            print("Texto extraído excede o limite máximo, utilizando upload de arquivo para LLM...")
            file_agent = FileAgent()
            file_id = file_agent.upload_file(file_path)
            use_file = True

        user_prompt = (
            "Resuma o documento abaixo. Preserve informações jurídicas relevantes. "
            "Regras de tamanho: summary_short com 2-4 frases objetivas; summary_long com 2-4 parágrafos, "
            "mais completo e detalhado que o resumo curto. "
            "Se não houver dado para algum campo, use lista vazia ou string vazia.\n\n"
            "IMPORTANTE: Se o documento for um PROCESSO JUDICIAL, extraia também as seguintes informações estruturadas no campo 'lawsuit_info':\n"
            "- process_number: número do processo\n"
            "- case_value: valor da causa (com formatação monetária)\n"
            "- subjects: lista de assuntos jurídicos\n"
            "- origin_court: tribunal de origem com cidade/estado\n"
            "- start_year: ano de início do processo\n"
            "- nature: natureza da ação (ex: Procedimento Comum)\n"
            "- judicial_power: poder judiciário (ex: Justiça Federal)\n"
            "- judge: nome do juiz (se não estiver explícito, procurar por 'Signatário')\n"
            "- court_tag: tag do tribunal conforme a lista a seguir (use a CHAVE, ex: TRF1, TJSP). Se não conseguir identificar, deixe vazio:\n"
            "  STF, STJ, TST, TSE, STM, TRF1, TRF2, TRF3, TRF4, TRF5, TRF6, "
            "TJAC, TJAL, TJAM, TJAP, TJBA, TJCE, TJDFT, TJES, TJGO, TJMA, TJMG, TJMS, "
            "TJMT, TJPA, TJPB, TJPE, TJPI, TJPR, TJRJ, TJRN, TJRO, TJRR, TJRS, TJSC, TJSE, TJSP, TJTO\n"
            "- parties: objeto contendo:\n"
            "  - active_pole: array de partes do polo ativo com nome, papel (ex: Autor) e advogados\n"
            "  - passive_pole: array de partes do polo passivo com nome, papel (ex: Parte passiva, Réu) e advogados\n"
            "Se o documento NÃO for um processo judicial, deixe 'lawsuit_info' com todos os campos vazios/nulos.\n\n"
            f"DOCUMENTO:\n{extracted_text}"
        )
        llm = ChatOpenAI(
            model=self.model_name,
            temperature=0.2
        ).with_structured_output(DocumentSummary)

        if use_file and file_id:
            response = llm.invoke([
                {"role": "system", "content": "Você é um assistente jurídico. Gere um resumo técnico, objetivo e estruturado."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt.replace(f"DOCUMENTO:\n{extracted_text}", "DOCUMENTO: (arquivo anexado)")},
                        {"type": "file", "file_id": file_id},
                    ],
                },
            ])
        else:
            response = llm.invoke([
                {"role": "system", "content": "Você é um assistente jurídico. Gere um resumo técnico, objetivo e estruturado."},
                {"role": "user", "content": user_prompt}
            ])

        return response.to_dict()