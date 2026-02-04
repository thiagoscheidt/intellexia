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


class Request(BaseModel):
    """Modelo para um pedido específico"""
    description: str = Field(default="", description="Descrição do pedido")
    urgency: str = Field(default="", description="Tipo de urgência (Medida Cautelar, etc)")


class PetitionInfo(BaseModel):
    """Modelo para informações específicas da petição inicial"""
    process_number: str = Field(default="", description="Número do processo (se houver)")
    case_value: str = Field(default="", description="Valor da causa")
    subjects: List[str] = Field(default_factory=list, description="Assuntos jurídicos")
    nature: str = Field(default="", description="Natureza da ação")
    judicial_power: str = Field(default="", description="Poder judiciário")
    parties: Parties = Field(default_factory=Parties, description="Partes envolvidas")
    facts_alleged: str = Field(default="", description="Fatos alegados pelas partes")
    legal_grounds: List[str] = Field(default_factory=list, description="Fundamentos legais utilizados")
    requests: List[Request] = Field(default_factory=list, description="Pedidos feitos na petição")
    urgency_justification: str = Field(default="", description="Justificativa para pedidos de urgência")
    cause_of_action: str = Field(default="", description="Causa de pedir (próxima e remota)")


class PetitionSummary(BaseModel):
    """Modelo para o resumo completo da petição inicial"""
    summary: str = Field(description="Resumo geral da petição")
    summary_short: str = Field(default="", description="Resumo curto (2-4 frases)")
    summary_long: str = Field(default="", description="Resumo longo (2-4 parágrafos)")
    key_points: List[str] = Field(default_factory=list, description="Pontos-chave da petição")
    entities: Entities = Field(default_factory=Entities, description="Entidades extraídas")
    dates: List[str] = Field(default_factory=list, description="Datas mencionadas")
    language: str = Field(default="pt-BR", description="Idioma do documento")
    notes: str = Field(default="", description="Observações adicionais")
    petition_info: PetitionInfo = Field(default_factory=PetitionInfo, description="Informações da petição")

    def to_dict(self) -> dict:
        """Converte o modelo para dicionário"""
        return self.model_dump(by_alias=True)

    def to_json(self) -> str:
        """Converte o modelo para JSON"""
        return self.model_dump_json(by_alias=True)


# ==================== Classe Principal ====================


class AgentPetitionSummary:
    model_name = None

    def __init__(self, model_name: str = "gpt-4o"):
        self.model_name = model_name

    def summarizePetition(self, file_path: Optional[str] = None, text_content: Optional[str] = None) -> dict:
        """
        Gera um resumo estruturado em JSON para uma petição inicial.

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
            print("Iniciando conversão da petição para texto...")
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
            "Resuma a petição inicial abaixo. Preserve informações jurídicas relevantes. "
            "Regras de tamanho: summary_short com 2-4 frases objetivas; summary_long com 2-4 parágrafos, "
            "mais completo e detalhado que o resumo curto. "
            "Se não houver dado para algum campo, use lista vazia ou string vazia.\n\n"
            "IMPORTANTE: Extraia as seguintes informações estruturadas no campo 'petition_info':\n"
            "- process_number: número do processo (se mencionado)\n"
            "- case_value: valor da causa (com formatação monetária)\n"
            "- subjects: lista de assuntos jurídicos principais\n"
            "- nature: natureza da ação (ex: Procedimento Comum, Ação Ordinária)\n"
            "- judicial_power: poder judiciário (ex: Justiça Estadual, Justiça Federal)\n"
            "- parties: objeto contendo:\n"
            "  - active_pole: array de partes do polo ativo (Autor) com nome, papel e advogados\n"
            "  - passive_pole: array de partes do polo passivo (Réu/Demandado) com nome, papel e advogados\n"
            "- facts_alleged: descrição dos fatos alegados pelas partes (1-2 parágrafos)\n"
            "- legal_grounds: lista de fundamentos legais, doutrinas e jurisprudências utilizadas\n"
            "- requests: array de pedidos com:\n"
            "  - description: descrição do pedido\n"
            "  - urgency: tipo de urgência (ex: Medida Cautelar, Tutela Antecipada) - deixar vazio se não houver\n"
            "- urgency_justification: justificativa para pedidos urgentes (se houver)\n"
            "- cause_of_action: explicação da causa de pedir (próxima e remota)\n\n"
            f"PETIÇÃO:\n{extracted_text}"
        )
        
        llm = ChatOpenAI(
            model=self.model_name,
            temperature=0.2
        ).with_structured_output(PetitionSummary)

        if use_file and file_id:
            response = llm.invoke([
                {"role": "system", "content": "Você é um assistente jurídico especializado em análise de petições. Gere um resumo técnico, objetivo e estruturado."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt.replace(f"PETIÇÃO:\n{extracted_text}", "PETIÇÃO: (arquivo anexado)")},
                        {"type": "file", "file_id": file_id},
                    ],
                },
            ])
        else:
            response = llm.invoke([
                {"role": "system", "content": "Você é um assistente jurídico especializado em análise de petições. Gere um resumo técnico, objetivo e estruturado."},
                {"role": "user", "content": user_prompt}
            ])

        return response.to_dict()
