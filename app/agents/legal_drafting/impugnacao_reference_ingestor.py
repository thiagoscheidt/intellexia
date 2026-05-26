"""Ingestor de peças-modelo de impugnação.

Coleção Qdrant DEDICADA (independente da knowledge_base normal).
Sem anonimização (decisão do usuário).
Segmentação prioritária por página (1 página = 1 chunk), com fallback
por regex de headings + chunk_size.

Multi-tenancy: law_firm_id sempre persistido no payload do Qdrant para
permitir filtro hard nas buscas.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.document_processor_service import DocumentProcessorService


load_dotenv()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
VECTOR_SIZE = int(os.getenv("VECTOR_SIZE", "0"))
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
IMPUGNACAO_REFERENCES_COLLECTION = os.getenv(
    "IMPUGNACAO_REFERENCES_COLLECTION", "impugnacao_models"
)
IMPUGNACAO_REFERENCES_MAX_CHUNK_CHARS = int(
    os.getenv("IMPUGNACAO_REFERENCES_MAX_CHUNK_CHARS", "2200")
)


# Headings típicos de peças do escritório: "1.", "1.1", "2.1.3", "I -", "II.",
# títulos em CAIXA ALTA com 3+ palavras.
_HEADING_NUMERIC_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})[\.\)\-:]?\s+\S")
_HEADING_ROMAN_RE = re.compile(r"^\s*([IVXLCM]{1,5})[\.\)\-:]\s+\S")
_HEADING_CAPS_RE = re.compile(r"^\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s\-]{8,})\s*$")
_HEADING_MARKDOWN_NUMERIC_RE = re.compile(r"^\s*#{1,4}\s*(\d{1,2}(?:\.\d{1,2}){0,3})[\.\)\-:]?\s+\S")
_HEADING_MARKDOWN_CAPS_RE = re.compile(r"^\s*#{1,4}\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s\-]{8,}\s*$")
_HEADING_MARKDOWN_GENERIC_RE = re.compile(r"^\s*#{1,4}\s+\S")

# Heurísticas de section_kind por palavra-chave no heading.
_SECTION_KIND_HINTS = [
    ("introduction", r"introdu|\bda\s+s[ií]ntese\b|excelent|ju[ií]z|vara\s+federal|qualificada\s+nos\s+autos"),
    ("preliminary", r"prelim|tempestiv|legitim"),
    ("merit_by_thesis", r"\bm[eé]rito\b|\btese\b|impugna(?:ção|cao)\s+espec|raz(?:ões|oes)\s+de\s+impugna"),
    ("jurisprudence", r"jurisprud|precedent|s[uú]mula"),
    ("requests", r"pedido|requer\b|requeriment"),
    ("closing", r"termos\s+em\s+que|nestes\s+termos|p\.\s*deferimento|encerr|conclus"),
]


class ImpugnacaoReferenceIngestor:
    """Recebe DOCX/PDF de peça-modelo e indexa em coleção Qdrant dedicada."""

    def __init__(self, collection_name: Optional[str] = None):
        if not EMBEDDING_MODEL:
            raise RuntimeError("EMBEDDING_MODEL não definido no .env")
        if VECTOR_SIZE <= 0:
            raise RuntimeError("VECTOR_SIZE inválido ou não definido no .env")

        self.collection = collection_name or IMPUGNACAO_REFERENCES_COLLECTION
        self.qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60)
        self.openai = OpenAI()
        self._ensure_collection()

    # ── Setup ──────────────────────────────────────────────────────────

    def _ensure_collection(self) -> None:
        if self.qdrant.collection_exists(self.collection):
            return
        self.qdrant.create_collection(
            collection_name=self.collection,
            vectors_config=rest.VectorParams(size=VECTOR_SIZE, distance=rest.Distance.COSINE),
        )

    # ── Extração de texto ──────────────────────────────────────────────

    @staticmethod
    def _process_document(file_path: str | Path):
        path = Path(file_path)
        processor = DocumentProcessorService()
        return processor.process_document(str(path))

    @classmethod
    def _build_segments_from_pages(cls, processed_document) -> list[dict]:
        chunks_with_pages = getattr(processed_document, 'chunks_with_pages', None) or []
        segments: list[dict] = []

        for chunk in chunks_with_pages:
            if not isinstance(chunk, dict):
                continue

            page_text = str(chunk.get('text') or '').strip()
            if not page_text:
                continue

            page_no = chunk.get('page')
            section_label = str(chunk.get('section') or '').strip()
            heading = section_label or (f'Página {page_no}' if page_no is not None else '')
            section_kind = cls._classify_section_kind(heading, page_text)

            segments.append({
                'heading': heading,
                'text': page_text,
                'section_kind': section_kind,
                'page': page_no,
                'section': section_label or None,
            })

        return segments

    @staticmethod
    def _extract_text(file_path: str | Path) -> str:
        result = ImpugnacaoReferenceIngestor._process_document(file_path)
        return (result.full_text or "").strip()

    # ── Segmentação ────────────────────────────────────────────────────

    @classmethod
    def _classify_section_kind(cls, heading: str, text: str = "") -> str:
        # Prioriza sinais do heading; se não houver match, usa início do texto.
        normalized_heading = (heading or "").lower()
        normalized_text = (text or "")[:1200].lower()
        for kind, pattern in _SECTION_KIND_HINTS:
            if re.search(pattern, normalized_heading):
                return kind
        for kind, pattern in _SECTION_KIND_HINTS:
            if re.search(pattern, normalized_text):
                return kind
        return "general"

    @classmethod
    def _split_by_headings(cls, text: str) -> list[dict]:
        """Quebra texto em segmentos sempre que detectar um heading.

        Retorna lista de dicts: {'heading', 'text', 'section_kind'}.
        Quando não há nenhum heading reconhecido, retorna o texto inteiro como
        um único segmento 'general'.
        """
        lines = text.splitlines()
        segments: list[dict] = []
        current_heading = ""
        current_buffer: list[str] = []

        def _flush():
            if not current_buffer:
                return
            joined = "\n".join(current_buffer).strip()
            if not joined:
                return
            section_kind = cls._classify_section_kind(current_heading, joined)
            segments.append({
                "heading": current_heading.strip(),
                "text": joined,
                "section_kind": section_kind,
            })

        for raw_line in lines:
            line = raw_line.rstrip()
            if re.match(r"^\s*<!--\s*image\s*-->\s*$", line, flags=re.IGNORECASE):
                continue
            line_for_heading = re.sub(r"^\s*<!--\s*image\s*-->\s*", "", line, flags=re.IGNORECASE)
            is_heading = bool(
                _HEADING_NUMERIC_RE.match(line_for_heading)
                or _HEADING_ROMAN_RE.match(line_for_heading)
                or _HEADING_MARKDOWN_NUMERIC_RE.match(line_for_heading)
                or _HEADING_MARKDOWN_CAPS_RE.match(line_for_heading)
                or (len(line_for_heading) < 180 and _HEADING_MARKDOWN_GENERIC_RE.match(line_for_heading))
                or (len(line_for_heading) < 120 and _HEADING_CAPS_RE.match(line_for_heading))
            )
            if is_heading and current_buffer:
                _flush()
                current_buffer = []
                current_heading = line_for_heading
            elif is_heading and not current_buffer:
                current_heading = line_for_heading
            else:
                current_buffer.append(line)

        _flush()

        if not segments:
            segments = [{
                "heading": "",
                "text": text.strip(),
                "section_kind": cls._classify_section_kind("", text),
            }]

        return segments

    @classmethod
    def _split_long_segment(cls, segment: dict, max_chars: int) -> list[dict]:
        body = segment["text"]
        if len(body) <= max_chars:
            return [segment]
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=max_chars,
            chunk_overlap=120,
            separators=["\n\n", "\n", ". ", " "],
        )
        parts = splitter.split_text(body)
        return [
            {
                "heading": segment.get("heading", ""),
                "text": part.strip(),
                "section_kind": segment.get("section_kind", "general"),
            }
            for part in parts
            if part and part.strip()
        ]

    # ── Embedding ──────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        response = self.openai.embeddings.create(input=text, model=EMBEDDING_MODEL)
        return response.data[0].embedding

    # ── Ingestão principal ─────────────────────────────────────────────

    def ingest_file(
        self,
        *,
        file_path: str | Path,
        reference_id: int,
        law_firm_id: int,
        title: str,
        trf_region: Optional[str] = None,
        generation_mode: Optional[str] = None,
        quality_score: Optional[float] = None,
        text: Optional[str] = None,
        processed_document=None,
    ) -> list[dict]:
        """Processa o arquivo e indexa todos os chunks no Qdrant.

        Quando `text` for fornecido, evita reextrair o conteúdo do arquivo.
        Retorna lista de metadados por chunk (para persistir em
        impugnacao_reference_chunks).
        """
        provided_text = (text or '').strip()

        if processed_document is None:
            try:
                processed_document = self._process_document(file_path)
            except Exception as error:
                print(f"[ImpugnacaoReferenceIngestor] Falha ao processar com paginação: {error}")

        page_segments: list[dict] = []
        if processed_document is not None:
            page_segments = self._build_segments_from_pages(processed_document)

        if page_segments:
            segments = page_segments
            segmentation_mode = 'page'
        else:
            fallback_text = provided_text
            if not fallback_text and processed_document is not None:
                fallback_text = str(getattr(processed_document, 'full_text', '') or '').strip()
            if not fallback_text:
                fallback_text = self._extract_text(file_path)

            if not fallback_text:
                print(f"[ImpugnacaoReferenceIngestor] Texto vazio em {file_path}")
                return []

            raw_segments = self._split_by_headings(fallback_text)

            # Fallback: quebrar segmentos muito grandes
            segments = []
            for seg in raw_segments:
                segments.extend(self._split_long_segment(seg, IMPUGNACAO_REFERENCES_MAX_CHUNK_CHARS))
            segmentation_mode = 'heading'

        if not segments:
            print(f"[ImpugnacaoReferenceIngestor] Nenhum segmento válido em {file_path}")
            return []

        print(
            f"[ImpugnacaoReferenceIngestor] {len(segments)} chunks segmentados "
            f"para reference_id={reference_id} (modo={segmentation_mode})"
        )

        chunk_records: list[dict] = []
        points: list[rest.PointStruct] = []
        ingested_at = datetime.utcnow().isoformat() + "Z"

        for order, seg in enumerate(segments):
            chunk_text = seg["text"]
            if not chunk_text or len(chunk_text) < 40:
                continue

            point_id = str(uuid.uuid4())
            vector = self._embed(chunk_text)

            payload = {
                "text": chunk_text,
                "heading": seg.get("heading", ""),
                "section_kind": seg.get("section_kind", "general"),
                "page": seg.get("page"),
                "section": seg.get("section"),
                "reference_id": int(reference_id),
                "law_firm_id": int(law_firm_id),
                "reference_title": title,
                "trf_region": (trf_region or "").upper() or None,
                "generation_mode": (generation_mode or "").upper() or None,
                "quality_score": float(quality_score) if quality_score is not None else None,
                "status": "active",
                "order_in_doc": order,
                "ingested_at": ingested_at,
            }

            points.append(rest.PointStruct(id=point_id, vector=vector, payload=payload))
            chunk_records.append({
                "qdrant_point_id": point_id,
                "section_kind": payload["section_kind"],
                "thesis_catalog_id": None,
                "benefit_type": None,
                "chunk_chars": len(chunk_text),
                "order_in_doc": order,
                "preview_text": chunk_text[:280],
            })

        if points:
            self.qdrant.upsert(collection_name=self.collection, points=points, wait=True)

        return chunk_records

    # ── Manutenção ─────────────────────────────────────────────────────

    def delete_by_reference_id(self, reference_id: int) -> None:
        try:
            self.qdrant.delete(
                collection_name=self.collection,
                points_selector=rest.Filter(
                    must=[rest.FieldCondition(key="reference_id", match=rest.MatchValue(value=int(reference_id)))]
                ),
                wait=True,
            )
        except Exception as error:
            print(f"[ImpugnacaoReferenceIngestor] Falha ao deletar reference {reference_id}: {error}")

    def set_status_by_reference_id(self, reference_id: int, status: str) -> None:
        try:
            self.qdrant.set_payload(
                collection_name=self.collection,
                payload={"status": status},
                points=rest.Filter(
                    must=[rest.FieldCondition(key="reference_id", match=rest.MatchValue(value=int(reference_id)))]
                ),
                wait=True,
            )
        except Exception as error:
            print(f"[ImpugnacaoReferenceIngestor] Falha ao atualizar status: {error}")
