from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from meilisearch_python_sdk import Client as MeilisearchClient
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from langchain_text_splitters import RecursiveCharacterTextSplitter
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat


load_dotenv()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", "0"))
DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowledge_base")
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
MEILISEARCH_HOST = os.getenv("MEILISEARCH_HOST", "http://localhost:7700")
MEILISEARCH_API_KEY = os.getenv("MEILISEARCH_API_KEY")
MAX_CHARS_PER_CHUNK = int(os.getenv("MAX_CHARS_PER_CHUNK", "1500"))


class KnowledgeIngestionAgent:
    """Recebe e processa arquivos para ingestão na base vetorial."""

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION,
        require_embeddings: bool = True,
        create_missing_indexes: bool = True,
    ):
        if require_embeddings and not EMBEDDING_MODEL:
            raise RuntimeError("EMBEDDING_MODEL não definido no .env")
        if require_embeddings and VECTOR_SIZE <= 0:
            raise RuntimeError("VECTOR_SIZE inválido ou não definido no .env")

        self.collection = collection_name
        self.require_embeddings = require_embeddings
        self.create_missing_indexes = create_missing_indexes
        self.qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60)
        self.meilisearch = MeilisearchClient(MEILISEARCH_HOST, MEILISEARCH_API_KEY)
        self.openai = OpenAI() if self.require_embeddings else None
        if self.create_missing_indexes:
            self._ensure_collection()
            self._ensure_meilisearch_index()

    def _ensure_collection(self) -> None:
        if self.qdrant.collection_exists(self.collection):
            return
        self.qdrant.create_collection(
            collection_name=self.collection,
            vectors_config=rest.VectorParams(size=VECTOR_SIZE, distance=rest.Distance.COSINE),
        )

    def _embed(self, text: str) -> list[float]:
        if not EMBEDDING_MODEL:
            raise RuntimeError("EMBEDDING_MODEL não definido no .env")
        if self.openai is None:
            self.openai = OpenAI()
        response = self.openai.embeddings.create(input=text, model=EMBEDDING_MODEL)
        return response.data[0].embedding

    def _ensure_meilisearch_index(self) -> None:
        self.meilisearch.get_or_create_index(uid=self.collection, primary_key="id")
        self._ensure_meilisearch_filterable_attributes()

    def _wait_for_meilisearch_task(self, task_info, timeout_in_ms: int | None = 10000) -> None:
        task_uid = getattr(task_info, "task_uid", None)
        if task_uid is None:
            return
        self.meilisearch.wait_for_task(task_uid, timeout_in_ms=timeout_in_ms)

    def _ensure_meilisearch_filterable_attributes(self) -> None:
        index = self.meilisearch.index(self.collection)
        filterable_attributes = index.get_filterable_attributes() or []

        if any(attribute == "file_id" for attribute in filterable_attributes if isinstance(attribute, str)):
            return

        updated_filterable_attributes = list(filterable_attributes)
        updated_filterable_attributes.append("file_id")
        task = index.update_filterable_attributes(updated_filterable_attributes)
        self._wait_for_meilisearch_task(task)

    @staticmethod
    def _is_missing_backend_resource_error(error: Exception) -> bool:
        error_message = str(error).lower()
        missing_markers = (
            "not found",
            "does not exist",
            "doesn't exist",
            "index_not_found",
            "collection not found",
            "404",
        )
        return any(marker in error_message for marker in missing_markers)

    def delete_document_by_file_id(self, file_id: int) -> None:
        if file_id is None:
            return

        qdrant_filter = rest.Filter(
            must=[
                rest.FieldCondition(
                    key="file_id",
                    match=rest.MatchValue(value=file_id),
                )
            ]
        )

        try:
            self.qdrant.delete(
                collection_name=self.collection,
                points_selector=qdrant_filter,
                wait=True,
            )
        except Exception as error:
            if not self._is_missing_backend_resource_error(error):
                raise

    def update_lawsuit_number_by_file_id(self, file_id: int, lawsuit_number: str) -> None:
        """Atualiza o campo lawsuit_number nos registros do arquivo no Qdrant e no Meilisearch."""
        if file_id is None:
            return

        normalized_lawsuit_number = str(lawsuit_number or "").strip()

        qdrant_filter = rest.Filter(
            must=[
                rest.FieldCondition(
                    key="file_id",
                    match=rest.MatchValue(value=file_id),
                )
            ]
        )

        try:
            self.qdrant.set_payload(
                collection_name=self.collection,
                payload={"lawsuit_number": normalized_lawsuit_number},
                points=qdrant_filter,
                wait=True,
            )
        except Exception as error:
            if not self._is_missing_backend_resource_error(error):
                raise

        try:
            self._ensure_meilisearch_filterable_attributes()

            points, _ = self.qdrant.scroll(
                collection_name=self.collection,
                scroll_filter=qdrant_filter,
                with_payload=True,
                with_vectors=False,
                limit=10000,
            )

            meili_documents = []
            for point in points or []:
                payload = dict(point.payload or {})
                payload["lawsuit_number"] = normalized_lawsuit_number
                meili_documents.append({"id": str(point.id), **payload})

            delete_task = self.meilisearch.index(self.collection).delete_documents_by_filter(f"file_id = {file_id}")
            self._wait_for_meilisearch_task(delete_task)

            if meili_documents:
                add_task = self.meilisearch.index(self.collection).add_documents(meili_documents)
                self._wait_for_meilisearch_task(add_task)
        except Exception as error:
            if not self._is_missing_backend_resource_error(error):
                raise

        try:
            self._ensure_meilisearch_filterable_attributes()
            task = self.meilisearch.index(self.collection).delete_documents_by_filter(f"file_id = {file_id}")
            self._wait_for_meilisearch_task(task)
        except Exception as error:
            if not self._is_missing_backend_resource_error(error):
                raise

    def _chunk_text(self, text: str, chunk_size: int = MAX_CHARS_PER_CHUNK) -> list[dict]:
        """Divide o texto em chunks, mantendo informações de metadados."""
        print(f"Iniciando Chunking de texto em pedaços de até {chunk_size} caracteres")
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=20)
        texts = text_splitter.split_text(text)
        return [{"text": chunk, "metadata": {}} for chunk in texts]

    def ingest_document(
        self,
        text: str,
        source: str,
        category: str = None,
        description: str = None,
        tags: str = None,
        lawsuit_number: str = None,
        chunks_with_pages: list[dict] = None,
        file_id: int = None,
    ) -> Optional[list[str]]:
        """Ingere documento na base vetorial."""
        if chunks_with_pages:
            chunks = chunks_with_pages
        else:
            cleaned = text.strip()
            if not cleaned:
                return None
            chunks = self._chunk_text(cleaned)

        point_ids: list[str] = []
        total = len(chunks)
        print(f"Dividindo documento '{source}' em {total} chunks")

        points: list[rest.PointStruct] = []
        meilisearch_documents: list[dict] = []
        for idx, chunk_data in enumerate(chunks):
            chunk_text = chunk_data.get("text", chunk_data) if isinstance(chunk_data, dict) else chunk_data
            chunk_page = chunk_data.get("page") if isinstance(chunk_data, dict) else None

            print(
                f"Processando chunk {idx + 1}/{total} ({len(chunk_text)} chars)"
                + (f" - Página {chunk_page}" if chunk_page else "")
            )
            vector = self._embed(chunk_text)
            point_id = str(uuid.uuid4())
            payload = {
                "text": chunk_text,
                "source": source,
                "category": category or "",
                "description": description or "",
                "tags": tags or "",
                "lawsuit_number": lawsuit_number or "",
                "chunk_index": idx,
                "chunk_total": total,
                "ingested_at": datetime.utcnow().isoformat() + "Z",
            }

            if file_id is not None:
                payload["file_id"] = file_id

            if chunk_page is not None:
                payload["page"] = chunk_page

            points.append(rest.PointStruct(id=point_id, vector=vector, payload=payload))
            point_ids.append(point_id)
            meilisearch_documents.append(
                {
                    "id": point_id,
                    **payload,
                }
            )

        self.qdrant.upsert(collection_name=self.collection, points=points, wait=True)
        self.meilisearch.index(self.collection).add_documents(meilisearch_documents)
        return point_ids

    def process_file(
        self,
        file_path: Path,
        source_name: str,
        category: str = None,
        description: str = None,
        tags: str = None,
        lawsuit_number: str = None,
        file_id: int = None,
    ):
        """Processa um arquivo e insere na base de conhecimento com informação de páginas."""
        pipeline_options = PdfPipelineOptions(
            do_ocr=False,
            generate_page_images=False,
            do_table_structure=False,
            enable_parallel_processing=True,
        )

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
        converter = DocumentConverter()

        try:
            result = converter.convert(str(file_path))
            doc = result.document

            chunks_with_pages = []

            if hasattr(doc, "pages") and doc.pages:
                print(f"Documento tem {len(doc.pages)} páginas")

                for page_no in sorted(doc.pages.keys()):
                    page_items = []

                    for item in doc.iterate_items():
                        if not hasattr(item, "text") or not item.text:
                            continue

                        item_page = None
                        if hasattr(item, "prov") and item.prov:
                            prov_list = item.prov if isinstance(item.prov, list) else [item.prov]
                            for prov in prov_list:
                                if prov and hasattr(prov, "bbox"):
                                    bbox = prov.bbox
                                    if hasattr(bbox, "page"):
                                        item_page = bbox.page
                                        break

                        if item_page == page_no:
                            page_items.append(item.text)

                    if page_items:
                        page_text = "\\n".join(page_items)
                        page_chunks = self._chunk_text(page_text)

                        for chunk_data in page_chunks:
                            chunk_data["page"] = page_no
                            chunks_with_pages.append(chunk_data)

                        print(f"Página {page_no}: {len(page_chunks)} chunks")

            if chunks_with_pages:
                print(f"✓ Total: {len(chunks_with_pages)} chunks COM informação de página")
                self.ingest_document(
                    text="",
                    source=source_name,
                    category=category,
                    description=description,
                    tags=tags,
                    lawsuit_number=lawsuit_number,
                    chunks_with_pages=chunks_with_pages,
                    file_id=file_id,
                )
            else:
                print("⚠ Tentando abordagem alternativa: mapeamento por caracteres")

                full_text = doc.export_to_markdown()
                total_chars = len(full_text)

                if hasattr(doc, "pages") and len(doc.pages) > 0:
                    chars_per_page = total_chars // len(doc.pages)

                    chunks = self._chunk_text(full_text)
                    current_char_pos = 0

                    for chunk_data in chunks:
                        chunk_text = chunk_data["text"]
                        estimated_page = min((current_char_pos // chars_per_page) + 1, len(doc.pages))
                        chunk_data["page"] = estimated_page
                        chunks_with_pages.append(chunk_data)
                        current_char_pos += len(chunk_text)

                    print(f"✓ Total: {len(chunks_with_pages)} chunks com página ESTIMADA")
                    self.ingest_document(
                        text="",
                        source=source_name,
                        category=category,
                        description=description,
                        tags=tags,
                        lawsuit_number=lawsuit_number,
                        chunks_with_pages=chunks_with_pages,
                        file_id=file_id,
                    )
                else:
                    print("✗ Processando SEM informação de páginas")
                    self.ingest_document(
                        text=full_text,
                        source=source_name,
                        category=category,
                        description=description,
                        tags=tags,
                        lawsuit_number=lawsuit_number,
                        file_id=file_id,
                    )

            return doc.export_to_markdown()

        except Exception as e:
            print(f"Erro ao processar arquivo: {str(e)}")
            import traceback

            traceback.print_exc()
            return None