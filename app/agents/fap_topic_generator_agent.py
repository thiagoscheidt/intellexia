from __future__ import annotations

import os
import uuid
import json
import time
from datetime import datetime
from typing import Optional

from anyio import Path
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import ChatOpenAI
from docling.document_converter import DocumentConverter
from pydantic import BaseModel, Field


load_dotenv()

class ResponseSchema(BaseModel):
    id: int = Field(description="ID do template selecionado")
    nome_arquivo: str = Field(description="Nome do arquivo do template")
    categoria: str = Field(description="Categoria do caso")
    confidence: float = Field(description="Nível de confiança na classificação (0.0 a 1.0)")
    justificativa: str = Field(description="Breve explicação da escolha")
    unable_to_classify: bool = Field(default=False, description="True se não foi possível categorizar com confiança mínima")

class FapTopicGeneratorAgent:
    def __init__(self):
        self.openai = OpenAI()
    def generateTopic(self, case_description: str, template_content: str) -> list[str]:
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0
        )
       