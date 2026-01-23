from __future__ import annotations

import os
import uuid
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

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", "0"))
DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowledge_base")
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
MAX_CHARS_PER_CHUNK = int(os.getenv("MAX_CHARS_PER_CHUNK", "1500"))


class ResponseSchema(BaseModel):
    answer: str = Field(description="Resposta gerada para a pergunta")
    sources: list[str] = Field(description="Fontes utilizadas para gerar a resposta")



class KnowledgeIngestor:
    """Converte texto em embedding e armazena no Qdrant."""

    def __init__(self, collection_name: str = DEFAULT_COLLECTION):
        if not EMBEDDING_MODEL:
            raise RuntimeError("EMBEDDING_MODEL não definido no .env")
        if VECTOR_SIZE <= 0:
            raise RuntimeError("VECTOR_SIZE inválido ou não definido no .env")

        self.collection = collection_name
        self.qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60)
        self.openai = OpenAI()
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if self.qdrant.collection_exists(self.collection):
            return
        self.qdrant.create_collection(
            collection_name=self.collection,
            vectors_config=rest.VectorParams(size=VECTOR_SIZE, distance=rest.Distance.COSINE),
        )

    def _embed(self, text: str) -> list[float]:
        response = self.openai.embeddings.create(input=text, model=EMBEDDING_MODEL)
        return response.data[0].embedding

    def _chunk_text(self, text: str, chunk_size: int = MAX_CHARS_PER_CHUNK) -> list[str]:
        print(f"Iniciando Chunking de texto em pedaços de até {chunk_size} caracteres")
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=20)
        texts = text_splitter.split_text(text)
        return texts

    def ingest_document(self, text: str, source: str, category: str = None, description: str = None, tags: str = None) -> Optional[list[str]]:
        cleaned = text.strip()
        if not cleaned:
            return None

        chunks = self._chunk_text(cleaned)
        print(chunks)
        point_ids: list[str] = []
        total = len(chunks)
        print(f"Dividindo documento '{source}' em {total} chunks")

        points: list[rest.PointStruct] = []
        for idx, chunk in enumerate(chunks):
            print(f"Processando chunk {idx + 1}/{total} ({len(chunk)} chars)")
            vector = self._embed(chunk)
            point_id = str(uuid.uuid4())
            payload = {
                "text": chunk,
                "source": source,
                "category": category or "",
                "description": description or "",
                "tags": tags or "",
                "chunk_index": idx,
                "chunk_total": total,
                "ingested_at": datetime.utcnow().isoformat() + "Z",
            }
            points.append(rest.PointStruct(id=point_id, vector=vector, payload=payload))
            point_ids.append(point_id)

        self.qdrant.upsert(collection_name=self.collection, points=points, wait=True)
        return point_ids

    def create_embedding_vector(self, text):
        embedding_request = self.openai.embeddings.create(
            input=text,
            model=EMBEDDING_MODEL
        )
        return embedding_request.data[0].embedding
    
    def ask_knowledge_base(self, question: str) -> dict:
        vector = self.create_embedding_vector(question)

        results = self.qdrant.query_points(
            collection_name=self.collection,
            query=vector
        )
        
        context = "\n".join([item.payload['text'] for item in results.points])
        print(context)
        return {
            "context": context,
            "results": results
        }

    def process_file(self, file_path: Path, source_name: str, category: str = None, description: str = None, tags: str = None):
        """Processa um arquivo e insere na base de conhecimento"""
        # Usa caminho absoluto em string para evitar problemas no conversor
        converter = DocumentConverter()
        try:
            result = converter.convert(str(file_path))
            markdown = result.document.export_to_markdown()
            self.ingest_document(markdown, source=source_name, category=category, description=description, tags=tags)
            return markdown
        except Exception as e:
            print(f"Erro ao processar arquivo: {str(e)}")
            return None
        
    def ask_with_llm(self, question: str) -> dict:
        """
        Consulta a base de conhecimento e usa LLM para gerar resposta.
        
        Args:
            question: A pergunta do usuário
            
        Returns:
            dict com 'answer' (str) e 'sources' (list)
        """
        # Buscar contexto na base vetorial
        context_data = self.ask_knowledge_base(question)

        # Usar LLM para gerar resposta baseada no contexto
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0
        ).with_structured_output(ResponseSchema)

        response = llm.invoke([
            {"role": "system", "content": "Você é um assistente jurídico especializado que responde perguntas com base na base de conhecimento da empresa."},
            {"role": "system", "content": f"Contexto disponível: {context_data['context']}. Se não souber a resposta com base no contexto, informe claramente que não possui essa informação."},
            {"role": "user", "content": question}
        ])
        
        # Extrair fontes únicas (remover duplicatas)
        sources = []
        seen_sources = set()
        for item in context_data['results'].points:
            source = item.payload['source']
            if source not in seen_sources:
                sources.append(source)
                seen_sources.add(source)
        
        return {
            "answer": response.answer,
            "sources": sources
        }