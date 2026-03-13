from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from markitdown import MarkItDown
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass
class PageContent:
    page: int
    text: str


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_CHUNK_SIZE = 1500
DEFAULT_CHUNK_OVERLAP = 100


@dataclass
class FaissSearchResult:
    text: str
    page: int | None
    score: float | None


@dataclass
class DocumentProcessResult:
    file_path: str
    total_pages: int
    full_text: str
    pages: list[PageContent] = field(default_factory=list)
    chunks_with_pages: list[dict] = field(default_factory=list)


class DocumentProcessorService:
    """
    Serviço responsável por extrair e converter o conteúdo de arquivos,
    incluindo informações de paginação e busca semântica local com FAISS.

    Métodos principais:
    - convert_with_markitdown  → converte o arquivo inteiro com MarkItDown
    - convert_with_docling     → converte o arquivo com Docling (markdown)
    - process_file             → extração completa com páginas e chunks
    - build_faiss_index        → indexa texto ou arquivo no FAISS em memória
    - search                   → busca semântica nos chunks indexados
    """

    def __init__(
        self,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        self.embedding_model = embedding_model
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    # ------------------------------------------------------------------
    # Conversão
    # ------------------------------------------------------------------

    def convert_with_markitdown(self, file_path: str | Path) -> str:
        """Converte o arquivo inteiro com MarkItDown e retorna o texto."""
        md = MarkItDown()
        result = md.convert(str(file_path))
        return (result.text_content or "") if result else ""

    def convert_with_docling(self, file_path: str | Path) -> str:
        """
        Converte o arquivo com Docling e retorna o conteúdo em markdown.
        Usa OCR desativado e processamento paralelo habilitado para PDFs.
        """
        pipeline_options = PdfPipelineOptions(
            do_ocr=False,
            generate_page_images=False,
            do_table_structure=False,
            enable_parallel_processing=True,
        )
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )

        result = converter.convert(str(file_path))
        return result.document.export_to_markdown()

    def process_file(self, file_path: str | Path) -> DocumentProcessResult:
        """
        Extrai o conteúdo completo do arquivo com informações de página.

        Estratégia:
        1. Tenta extrair página a página via Docling (mais preciso para PDFs).
        2. Se não conseguir mapear páginas, faz fallback para MarkItDown página a página.
        3. Monta `chunks_with_pages` prontos para ingestão no formato
           [{"text": "...", "page": N}, ...].
        """
        file_path = Path(file_path)
        chunks_with_pages: list[dict] = []
        pages: list[PageContent] = []

        try:
            pipeline_options = PdfPipelineOptions(
                do_ocr=False,
                generate_page_images=False,
                do_table_structure=False,
                enable_parallel_processing=True,
            )
            converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
            )
            result = converter.convert(str(file_path))
            doc = result.document

            total_pages = len(doc.pages) if hasattr(doc, "pages") and doc.pages else 0
            print(f"[DocumentProcessorService][docling] {total_pages} páginas detectadas")

            if total_pages > 0:
                for page_no in sorted(doc.pages.keys()):
                    page_items: list[str] = []

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

                    page_text = "\n".join(page_items)
                    pages.append(PageContent(page=page_no, text=page_text))
                    if page_text.strip():
                        chunks_with_pages.append({"text": page_text, "page": page_no})

            full_text = doc.export_to_markdown()

        except Exception as exc:
            print(f"[DocumentProcessorService][docling] Falha: {exc}. Tentando MarkItDown.")
            full_text = ""
            total_pages = 0

        if not chunks_with_pages:
            print("[DocumentProcessorService] Nenhum chunk extraído pelo Docling.")

        return DocumentProcessResult(
            file_path=str(file_path),
            total_pages=total_pages,
            full_text=full_text,
            pages=pages,
            chunks_with_pages=chunks_with_pages,
        )

    # ------------------------------------------------------------------
    # RAG com FAISS em memória
    # ------------------------------------------------------------------

    def build_faiss_index(self, text: str | None = None, file_path: str | Path | None = None) -> FAISS:
        """
        Constrói um índice FAISS em memória a partir de texto ou arquivo.

        - Se `text` for fornecido, indexa diretamente.
        - Se `file_path` for fornecido, converte com MarkItDown e indexa.
        - Preserva metadado `page` quando construído via `process_file`.
        """
        if text is None and file_path is None:
            raise ValueError("Forneça `text` ou `file_path`")

        if text is None:
            result = self.process_file(file_path)
            documents_with_meta = []
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )
            for chunk in result.chunks_with_pages:
                docs = splitter.create_documents([chunk["text"]], metadatas=[{"page": chunk.get("page")}])
                documents_with_meta.extend(docs)
        else:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )
            documents_with_meta = splitter.create_documents([text])

        if not documents_with_meta:
            raise ValueError("Nenhum conteúdo para indexar")

        embeddings = HuggingFaceEmbeddings(model_name=self.embedding_model)
        vectorstore = FAISS.from_documents(documents_with_meta, embeddings)
        print(f"[DocumentProcessorService] FAISS indexado: {len(documents_with_meta)} chunks")
        return vectorstore

    def search(self, vectorstore: FAISS, query: str, k: int = 6) -> List[FaissSearchResult]:
        """
        Executa busca semântica no índice FAISS e retorna os trechos mais relevantes.
        Inclui número da página quando disponível nos metadados.
        """
        raw = vectorstore.similarity_search_with_score(query, k=k)
        results: List[FaissSearchResult] = []
        for doc, score in raw:
            results.append(
                FaissSearchResult(
                    text=doc.page_content,
                    page=doc.metadata.get("page"),
                    score=float(score),
                )
            )
        return results

    def search_text(self, vectorstore: FAISS, query: str, k: int = 6, separator: str = "\n\n---\n\n") -> str:
        """Atalho: retorna os trechos relevantes já concatenados como string."""
        results = self.search(vectorstore, query, k=k)
        return separator.join(r.text for r in results)
