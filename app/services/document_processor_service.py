from __future__ import annotations

import re
import unicodedata
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
    def _detect_sections(text: str) -> list[str]:
        """Retorna todas as seções numeradas detectadas em uma página (sem duplicar)."""
        matches = re.findall(
            r'^(?:#{1,3}\s+)?(\d+\.\s+[^\n]+)$',
            text,
            re.MULTILINE,
        )
        unique_sections: list[str] = []
        seen: set[str] = set()
        for item in matches:
            section_name = str(item).strip()
            if section_name and section_name not in seen:
                seen.add(section_name)
                unique_sections.append(section_name)
        return unique_sections

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

        def _normalize_header_token(value: str) -> str:
            normalized = unicodedata.normalize('NFKD', str(value or '').strip().lower())
            return ''.join(ch for ch in normalized if not unicodedata.combining(ch))

        def _is_year_token(value: str) -> bool:
            return bool(re.fullmatch(r'\d{4}', str(value or '').strip()))

        def _is_benefit_type_token(value: str) -> bool:
            return bool(re.fullmatch(r'B\d{2}', str(value or '').strip().upper()))

        def _is_benefit_number_token(value: str) -> bool:
            return bool(re.fullmatch(r'\d{9,11}', str(value or '').strip()))

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

                        compact_header = [h for h in header_cells if h.strip()]
                        compact_header_norm = [_normalize_header_token(h) for h in compact_header]
                        vigencia_idx = next(
                            (
                                idx for idx, token in enumerate(compact_header_norm)
                                if 'vigencia' in token or ('fap' in token and 'vig' in token)
                            ),
                            None,
                        )
                        tipo_idx = next((idx for idx, token in enumerate(compact_header_norm) if 'tipo' in token), None)
                        beneficio_idx = next(
                            (idx for idx, token in enumerate(compact_header_norm) if 'beneficio' in token or token == 'nb'),
                            None,
                        )
                        item_idx = next((idx for idx, token in enumerate(compact_header_norm) if token.startswith('item')), None)
                        diferenca_idx = next(
                            (
                                idx for idx, token in enumerate(compact_header_norm)
                                if 'diferenca' in token or ('dcb' in token and 'dib' in token)
                            ),
                            None,
                        )
                        cnpj_idx = next((idx for idx, token in enumerate(compact_header_norm) if 'cnpj' in token), None)
                        empregado_idx = next(
                            (
                                idx for idx, token in enumerate(compact_header_norm)
                                if 'empregado' in token or 'segurado' in token or 'beneficiario' in token
                            ),
                            None,
                        )
                        nit_idx = next((idx for idx, token in enumerate(compact_header_norm) if 'nit' in token), None)

                        carry_values = {
                            'cnpj': '',
                            'empregado': '',
                            'nit': '',
                        }
                        rendered_rows: list[str] = [" | ".join(compact_header)]
                        data_rows_with_multiple_values = 0

                        for row in table[data_start_idx:]:
                            if not row:
                                continue

                            # Monta dados compactos: remove células None/vazias para alinhar
                            # posicionalmente com o header compacto, corrigindo PDFs com
                            # células mergeadas que criam colunas fantasma vazias no header.
                            compact_values = [
                                str(cell).strip()
                                for cell in row
                                if cell and str(cell).strip()
                            ]

                            # Alguns PDFs quebram "Vigência FAP" em duas células (ex.: 2019 | 2020).
                            # Mescla o par antes do mapeamento posicional.
                            while (
                                vigencia_idx is not None
                                and vigencia_idx + 1 < len(compact_values)
                                and _is_year_token(compact_values[vigencia_idx])
                                and _is_year_token(compact_values[vigencia_idx + 1])
                            ):
                                compact_values[vigencia_idx] = (
                                    f"{compact_values[vigencia_idx]}-{compact_values[vigencia_idx + 1]}"
                                )
                                del compact_values[vigencia_idx + 1]

                            # Realinha linhas com colspan/rowspan onde CNPJ/Empregado/NIT ficam vazios
                            # e o tipo/benefício deslocam para a esquerda.
                            if tipo_idx is not None and tipo_idx < len(compact_header):
                                type_positions = [
                                    i for i, val in enumerate(compact_values)
                                    if _is_benefit_type_token(val)
                                ]
                                if type_positions:
                                    first_type_pos = type_positions[0]
                                    if first_type_pos < tipo_idx:
                                        compact_values = (
                                            compact_values[:first_type_pos]
                                            + [""] * (tipo_idx - first_type_pos)
                                            + compact_values[first_type_pos:]
                                        )

                            if beneficio_idx is not None and beneficio_idx < len(compact_header):
                                if beneficio_idx < len(compact_values):
                                    if not _is_benefit_number_token(compact_values[beneficio_idx]):
                                        for probe_idx in range(beneficio_idx + 1, len(compact_values)):
                                            if _is_benefit_number_token(compact_values[probe_idx]):
                                                compact_values.insert(
                                                    beneficio_idx,
                                                    compact_values.pop(probe_idx),
                                                )
                                                break

                            # Se o número do benefício caiu em coluna anterior (ex.: CNPJ),
                            # move para a coluna correta quando Benefício estiver vazio.
                            if (
                                beneficio_idx is not None
                                and beneficio_idx < len(compact_values)
                                and not str(compact_values[beneficio_idx] or '').strip()
                            ):
                                for probe_idx in range(0, beneficio_idx):
                                    probe_val = str(compact_values[probe_idx] or '').strip()
                                    if _is_benefit_number_token(probe_val) and not cnpj_re.search(probe_val):
                                        compact_values[beneficio_idx] = probe_val
                                        compact_values[probe_idx] = ''
                                        break

                            row_cells = [
                                compact_values[i] if i < len(compact_values) else ""
                                for i in range(len(compact_header))
                            ]

                            # Carry-over seletivo para colunas que costumam vir com rowspan.
                            # Mantém último valor não vazio de CNPJ/Empregado/NIT e replica
                            # apenas nessas colunas quando a célula atual vier vazia.
                            for field_name, field_idx in (
                                ('cnpj', cnpj_idx),
                                ('empregado', empregado_idx),
                                ('nit', nit_idx),
                            ):
                                if field_idx is None or field_idx >= len(row_cells):
                                    continue

                                current_value = str(row_cells[field_idx] or '').strip()
                                if current_value:
                                    is_valid_for_field = (
                                        (field_name == 'cnpj' and bool(cnpj_re.search(current_value)))
                                        or (field_name == 'empregado' and bool(re.search(r'[A-Za-zÀ-ÿ]', current_value)))
                                        or (field_name == 'nit' and bool(nit_re.search(current_value)))
                                    )
                                    if is_valid_for_field:
                                        carry_values[field_name] = current_value
                                elif carry_values[field_name]:
                                    row_cells[field_idx] = carry_values[field_name]

                            # Linhas de continuação como "48 dias" devem ser mescladas
                            # na linha anterior, preenchendo a coluna de diferença.
                            is_continuation_days_row = False
                            if item_idx is not None and item_idx < len(row_cells):
                                item_value = str(row_cells[item_idx] or '').strip().lower()
                                is_continuation_days_row = bool(re.fullmatch(r'\d+\s*dias?', item_value))

                            if (
                                is_continuation_days_row
                                and diferenca_idx is not None
                                and len(rendered_rows) > 1
                            ):
                                prev_cells = [part.strip() for part in rendered_rows[-1].split(' | ')]
                                if len(prev_cells) == len(compact_header):
                                    prev_cells[diferenca_idx] = str(row_cells[item_idx] or '').strip()
                                    rendered_rows[-1] = ' | '.join(prev_cells)
                                    continue

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

                    # Verifica se esta página contém uma ou mais seções numeradas.
                    detected_sections = self._detect_sections(page_text)
                    if detected_sections:
                        current_section = detected_sections[-1]
                        page_section = ", ".join(detected_sections)
                        print(f"[DocumentProcessorService] Seções detectadas na pág {page_no}: {page_section}")
                    else:
                        page_section = current_section

                    pages.append(PageContent(page=page_no, text=page_text, section=page_section))
                    if page_text.strip():
                        chunks_with_pages.append({"text": page_text, "page": page_no, "section": page_section})

            full_text = doc.export_to_markdown()
            tables = self._extract_tables_from_pdf(file_path, pages)
            print(tables)
            exit()
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
