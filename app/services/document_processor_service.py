from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

import pdfplumber
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
    section: str | None = None


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
    tables: list[dict] = field(default_factory=list)


class DocumentProcessorService:
    """
    Serviço responsável por extrair e converter o conteúdo de arquivos,
    incluindo informações de paginação e busca semântica local com FAISS.

    Métodos principais:
    - convert_with_markitdown  → converte o arquivo inteiro com MarkItDown
    - convert_with_docling     → converte o arquivo com Docling (markdown)
    - process_document             → extração completa com páginas e chunks
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
    # Detecção de seção
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_section(text: str) -> str | None:
        """
        Retorna o título da seção encontrada no texto da página, ou None.
        Reconhece padrões como:
          ## 10. ACIDENTE OCORRIDO ANTES DE ABRIL DE 2007
          9. HISTÓRICO DO BENEFÍCIO
        A linha deve começar por um heading markdown opcional (## / ###)
        seguido de um número, ponto e texto.
        """
        match = re.search(
            r'^(?:#{1,3}\s+)?(\d+\.\s+[^\n]+)$',
            text,
            re.MULTILINE,
        )
        if match:
            return match.group(1).strip()
        return None

    @staticmethod
    def _extract_item_page(item: Any) -> int | None:
        if not hasattr(item, "prov") or not item.prov:
            return None

        prov_list = item.prov if isinstance(item.prov, list) else [item.prov]
        for prov in prov_list:
            if prov and hasattr(prov, "page_no"):
                return prov.page_no
            if prov and hasattr(prov, "bbox") and hasattr(prov.bbox, "page"):
                return prov.bbox.page

        return None

    def _extract_tables_from_pdf(self, file_path: str | Path, pages: list[PageContent] | None = None) -> list[dict]:
        """Extrai tabelas com pdfplumber preservando o header e o mapeamento por coluna."""
        tables: list[dict] = []
        seen: set[tuple[int, tuple[str, ...]]] = set()
        page_section_map = {p.page: p.section for p in (pages or [])}

        cnpj_re = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
        nit_re = re.compile(r"\b\d{11}\b")
        benefit_type_re = re.compile(r"\bB\d{2}\b", re.IGNORECASE)
        benefit_number_re = re.compile(r"\b\d{9,11}\b")
        date_re = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")

        def _looks_like_data_row(cells: list[str]) -> bool:
            non_empty = [cell for cell in cells if cell]
            if not non_empty:
                return False

            first_value = non_empty[0]
            if re.match(r"^\d{1,4}$", first_value):
                return True

            joined = " | ".join(non_empty)
            return bool(
                cnpj_re.search(joined)
                or nit_re.search(joined)
                or benefit_type_re.search(joined)
                or benefit_number_re.search(joined)
                or date_re.search(joined)
            )

        try:
            with pdfplumber.open(str(file_path)) as pdf:
                for idx, page in enumerate(pdf.pages, start=1):
                    section = page_section_map.get(idx)
                    page_tables = page.extract_tables() or []
                    for table in page_tables:
                        if not table or len(table) < 2:
                            continue

                        header_row = table[0] or []
                        header_cells = [str(cell).strip() if cell else "" for cell in header_row]

                        # Alguns PDFs quebram o header em 2+ linhas (ex.: "Vigência do" + "FAP").
                        # Aqui mesclamos linhas textuais de continuação antes de processar os dados.
                        data_start_idx = 1
                        while data_start_idx < len(table):
                            candidate_row = table[data_start_idx] or []
                            candidate_cells = [str(cell).strip() if cell else "" for cell in candidate_row]
                            non_empty_cells = [
                                (col_idx, value)
                                for col_idx, value in enumerate(candidate_cells)
                                if value
                            ]

                            if not non_empty_cells:
                                data_start_idx += 1
                                continue

                            looks_like_data_row = _looks_like_data_row(candidate_cells)
                            sparse_textual_row = len(non_empty_cells) <= max(3, len(header_cells) // 2)

                            is_header_continuation = (
                                not looks_like_data_row
                                and sparse_textual_row
                            )

                            if not is_header_continuation:
                                break

                            for col_idx, value in non_empty_cells:
                                if col_idx >= len(header_cells):
                                    continue
                                if header_cells[col_idx]:
                                    header_cells[col_idx] = f"{header_cells[col_idx]} {value}".strip()
                                else:
                                    header_cells[col_idx] = value

                            data_start_idx += 1

                        non_empty_header_count = sum(1 for cell in header_cells if cell)
                        if non_empty_header_count < 2:
                            continue

                        rendered_rows: list[str] = [" | ".join(header_cells)]
                        data_rows_with_multiple_values = 0

                        for row in table[data_start_idx:]:
                            if not row:
                                continue

                            row_cells: list[str] = []
                            for col_idx, header_name in enumerate(header_cells):
                                if not header_name:
                                    continue
                                value = ""
                                if col_idx < len(row):
                                    value = str(row[col_idx]).strip() if row[col_idx] else ""
                                row_cells.append(value)

                            if any(row_cells):
                                if sum(1 for value in row_cells if value) >= 2:
                                    data_rows_with_multiple_values += 1
                                rendered_rows.append(" | ".join(row_cells))

                        # Evita capturar citações/blocos textuais que o pdfplumber interpreta como tabela.
                        if len(rendered_rows) <= 1 or data_rows_with_multiple_values == 0:
                            continue

                        normalized_rows = [row.strip() for row in rendered_rows if row.strip()]
                        dedupe_key = (idx, tuple(normalized_rows))
                        if dedupe_key in seen:
                            continue
                        seen.add(dedupe_key)

                        tables.append(
                            {
                                "page": idx,
                                "section": section,
                                "text": normalized_rows,
                            }
                        )
        except Exception as exc:
            print(f"[DocumentProcessorService][pdfplumber] Falha ao extrair tabelas: {exc}")

        return tables

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

    def process_document(self, file_path: str | Path) -> DocumentProcessResult:
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
        tables: list[dict] = []

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
                current_section: str | None = None
                for page_no in sorted(doc.pages.keys()):
                    page_items: list[str] = []

                    for entry in doc.iterate_items():
                        item = entry[0] if isinstance(entry, tuple) else entry

                        if not hasattr(item, "text") or not item.text:
                            continue

                        item_page = self._extract_item_page(item)

                        if item_page == page_no:
                            page_items.append(item.text)

                    page_text = "\n".join(page_items)

                    # Verifica se esta página abre uma nova seção numerada
                    detected = self._detect_section(page_text)
                    if detected:
                        current_section = detected
                        print(f"[DocumentProcessorService] Seção detectada na pág {page_no}: {current_section}")

                    pages.append(PageContent(page=page_no, text=page_text, section=current_section))
                    if page_text.strip():
                        chunks_with_pages.append({"text": page_text, "page": page_no, "section": current_section})

            full_text = doc.export_to_markdown()
            tables = self._extract_tables_from_pdf(file_path, pages)
            print(f"[DocumentProcessorService][pdfplumber] Tabelas detectadas: {len(tables)}")

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
            tables=tables,
        )

    # ------------------------------------------------------------------
    # RAG com FAISS em memória
    # ------------------------------------------------------------------

    def build_faiss_index(self, text: str | None = None, file_path: str | Path | None = None) -> FAISS:
        """
        Constrói um índice FAISS em memória a partir de texto ou arquivo.

        - Se `text` for fornecido, indexa diretamente.
        - Se `file_path` for fornecido, converte com MarkItDown e indexa.
        - Preserva metadado `page` quando construído via `process_document`.
        """
        if text is None and file_path is None:
            raise ValueError("Forneça `text` ou `file_path`")

        if text is None:
            result = self.process_document(file_path)
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
