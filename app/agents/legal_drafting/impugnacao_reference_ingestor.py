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
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.document_processor_service import DocumentProcessorService
from app.agents.legal_drafting.impugnacao_reference_thesis_classifier_agent import (
    ImpugnacaoReferenceThesisClassifierAgent,
)


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
IMPUGNACAO_REFERENCES_PAGE_OVERLAP_CHARS = int(
    os.getenv("IMPUGNACAO_REFERENCES_PAGE_OVERLAP_CHARS", "240")
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

# Padrões mais específicos para classificação por página (evita falsos positivos).
_INTRO_HEADING_RE = re.compile(r"introdu|s[ií]ntese|relat[oó]rio", re.IGNORECASE)
_PRELIM_HEADING_RE = re.compile(r"preliminar|prejudicial", re.IGNORECASE)
_MERIT_HEADING_RE = re.compile(r"m[eé]rito|tese", re.IGNORECASE)
_JURIS_HEADING_RE = re.compile(r"jurisprud|precedent|s[uú]mula", re.IGNORECASE)
_REQUESTS_HEADING_RE = re.compile(r"\bdos\s+pedidos\b|\bpedidos\b", re.IGNORECASE)
_CLOSING_HEADING_RE = re.compile(r"fecho|conclus[aã]o|termos\s+em\s+que", re.IGNORECASE)

_INTRO_BODY_RE = re.compile(
    r"excelent[ií]ssim|processo\s*n[ºo]|vem,?\s+respeitosamente|apresentar\s+impugna(?:ç|c)[aã]o\s+[àa]\s+contesta(?:ç|c)[aã]o|trata-se\s+de\s+a[cç][aã]o",
    re.IGNORECASE,
)
_PRELIM_BODY_RE = re.compile(
    r"ilegitimidade\s+passiva|prescri(?:ç|c)[aã]o\s+quinquenal|preliminar|prejudicial\s+de\s+m[eé]rito|incompet[êe]ncia|car[êe]ncia\s+de\s+a[cç][aã]o",
    re.IGNORECASE,
)
_MERIT_BODY_RE = re.compile(
    r"\bm[eé]rito\b|\btese\b|refuta(?:ç|c)[aã]o|impugna(?:ç|c)[aã]o\s+espec[ií]fica|n[aã]o\s+se\s+sustenta|v[ií]cios\s+concretos",
    re.IGNORECASE,
)
_JURIS_BODY_RE = re.compile(
    r"\btrf\d?\b|\bstj\b|\bresp\b|\bac\b|jurisprud[eê]ncia|precedente|s[uú]mula",
    re.IGNORECASE,
)
_REQUESTS_BODY_RE = re.compile(
    r"diante\s+do\s+exposto,?\s+requer|ante\s+o\s+exposto,?\s+requer|requer\s+seja|dos\s+pedidos|pedido\s+de\s+condena(?:ç|c)[aã]o",
    re.IGNORECASE,
)
_CLOSING_BODY_RE = re.compile(
    r"nestes\s+termos|pede\s+deferimento|termos\s+em\s+que", re.IGNORECASE
)

# ── Padrões para extração de blocos de jurisprudência embutidos ────────

# Detecta cabeçalhos típicos de citações jurisprudenciais
_JURIS_CITATION_HEADER_RE = re.compile(
    r'(?:'
    # "TRF4, AC 5015482-..." / "TRF 4 – Ap. nº ..."
    r'TRF\s*\d+\s*[,\-–]?\s*[A-Z]{1,5}\s+(?:n[ºo°]?\s*)?\d[\d\-\.]+'
    r'|'
    # "STJ/STF/TST/TRT – REsp nº ..." / "STJ, AgRg..."
    r'(?:STJ|STF|TST|TRT\s*\d*)\s*[,\-–]?\s*[A-Z]{1,5}\s+(?:n[ºo°]?\s*)?\d[\d\-\.]+'
    r'|'
    # "EMENTA:" no início de linha
    r'^EMENTA:'
    r'|'
    # "AC nº / REsp nº / AMS nº" no início de linha
    r'^(?:AC|APELAÇÃO\s+CÍVEL|AGRAVO\s+DE\s+INSTRUMENTO|RESp|REsp|RESP|AMS)\s+(?:n[ºo°]?\s*)?\d[\d\-\.]+'
    r')',
    re.IGNORECASE | re.MULTILINE,
)

_TRIBUNAL_RE = re.compile(r'\b(TRF\s*\d+|STJ|STF|TST|TRT\s*\d*)\b', re.IGNORECASE)
_CASE_NUMBER_RE = re.compile(
    r'\b(\d{7}-\d{2}\.\d{4}\.\d{1,2}\.\d{2}\.\d{4}|\d{1,10}[-/]\d{4}[-/]\d{1,2}(?:[-/]\d+)+)\b'
)
_RELATOR_RE = re.compile(
    r'Rel(?:\.|ator(?:a)?)?[:\s]+(?:Des(?:embargador(?:a)?)?\.?\s+)?([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇa-záéíóúâêôãõç\s\.]{3,60}?)(?:\s*[,\n\r])',
    re.IGNORECASE,
)

# Detecta rodapés de citação: (GN), (grifo nosso), (...) (TRF4, AC ...) ou (TRF4, AC ..., Rel. ...)
_JURIS_FOOTER_RE = re.compile(
    r'\(GN\)'
    r'|\(grifo\s+nosso\)'
    r'|\(negrito\s+nosso\)'
    r'|\(\.\.\.\)\s*\((?:TRF\s*\d+|STJ|STF|TST)[^)]{5,250}\)'
    r'|\((?:TRF\s*\d+|STJ|STF|TST),\s*\w+\s+\d[\d\-\.]{5,}[^)]{5,250}\)',
    re.IGNORECASE,
)


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
        self.last_document_thesis_catalog_ids: list[str] = []
        self.thesis_classifier_agent = ImpugnacaoReferenceThesisClassifierAgent()
        self._ensure_collection()

    @staticmethod
    def _normalize_for_match(text: str) -> str:
        normalized = unicodedata.normalize('NFKD', str(text or ''))
        normalized = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = normalized.lower()
        normalized = re.sub(r'[^a-z0-9]+', ' ', normalized)
        return re.sub(r'\s+', ' ', normalized).strip()

    @classmethod
    def _extract_thesis_tokens(cls, thesis: dict) -> list[str]:
        raw_parts = [
            thesis.get('key') or '',
            thesis.get('name') or '',
        ]
        token_set = set()
        for part in raw_parts:
            normalized = cls._normalize_for_match(part)
            for token in normalized.split():
                if len(token) < 3:
                    continue
                if token in {'de', 'do', 'da', 'dos', 'das', 'com', 'sem', 'para', 'por', 'que'}:
                    continue
                token_set.add(token)
        return sorted(token_set)

    @classmethod
    def _score_thesis_match(cls, normalized_text: str, thesis: dict) -> int:
        if not normalized_text:
            return 0

        score = 0
        key_phrase = cls._normalize_for_match((thesis.get('key') or '').replace('_', ' '))
        name_phrase = cls._normalize_for_match(thesis.get('name') or '')

        if name_phrase and len(name_phrase) >= 8 and name_phrase in normalized_text:
            score += 12
        if key_phrase and len(key_phrase) >= 8 and key_phrase in normalized_text:
            score += 10

        tokens = cls._extract_thesis_tokens(thesis)
        token_hits = sum(1 for token in tokens if token in normalized_text)
        if token_hits:
            score += min(6, token_hits)

        # Reforço para teses com sinal forte de acidente/benefício/FAP.
        if re.search(r'\bacidente\b|\bbeneficio\b|\bfap\b|\bcat\b|\bnexo\b', normalized_text):
            score += 1

        return score

    @classmethod
    def _match_thesis_catalog_ids(
        cls,
        text: str,
        thesis_catalog: list[dict],
        max_items: int = 6,
        minimum_score: int = 3,
    ) -> list[str]:
        if not text or not thesis_catalog:
            return []

        normalized_text = cls._normalize_for_match(text)
        if not normalized_text:
            return []

        scored: list[tuple[int, str]] = []
        for thesis in thesis_catalog:
            key = str(thesis.get('key') or '').strip()
            if not key:
                continue
            score = cls._score_thesis_match(normalized_text, thesis)
            if score >= minimum_score:
                scored.append((score, key))

        scored.sort(key=lambda item: (-item[0], item[1]))

        matched: list[str] = []
        seen = set()
        for _, key in scored:
            if key in seen:
                continue
            seen.add(key)
            matched.append(key)
            if len(matched) >= max_items:
                break
        return matched

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
        previous_page_text = ""

        for chunk in chunks_with_pages:
            if not isinstance(chunk, dict):
                continue

            page_text = str(chunk.get('text') or '').strip()
            if not page_text:
                continue

            page_no = chunk.get('page')
            section_label = str(chunk.get('section') or '').strip()
            heading = section_label or (f'Página {page_no}' if page_no is not None else '')
            section_kind = cls._classify_section_kind(heading, page_text, page_no=page_no)

            merged_text = page_text
            overlap_chars = max(0, IMPUGNACAO_REFERENCES_PAGE_OVERLAP_CHARS)
            if overlap_chars and previous_page_text:
                previous_tail = previous_page_text[-overlap_chars:].strip()
                if previous_tail:
                    merged_text = f"{previous_tail}\n\n{page_text}".strip()

            segments.append({
                'heading': heading,
                'text': merged_text,
                'section_kind': section_kind,
                'page': page_no,
                'section': section_label or None,
            })

            previous_page_text = page_text

        return segments

    @staticmethod
    def _extract_text(file_path: str | Path) -> str:
        result = ImpugnacaoReferenceIngestor._process_document(file_path)
        return (result.full_text or "").strip()

    # ── Segmentação ────────────────────────────────────────────────────

    @classmethod
    def _classify_section_kind(cls, heading: str, text: str = "", page_no: Optional[int] = None) -> str:
        """Classifica a seção com base em heading + conteúdo + posição da página.

        Regras:
        - Dá mais peso a headings explícitos.
        - Evita marcar `requests` apenas porque apareceu a palavra "pedido" em páginas de introdução/mérito.
        - Em primeira página com abertura típica de petição, prioriza `introduction`.
        """
        normalized_heading = (heading or "").strip()
        normalized_text = (text or "")[:6000]

        # 1) Fecho tem precedência alta por ser muito específico.
        if _CLOSING_HEADING_RE.search(normalized_heading) or _CLOSING_BODY_RE.search(normalized_text):
            return "closing"

        # 2) Primeira página com abertura típica -> introdução.
        if page_no in (0, 1):
            intro_hits = 0
            if _INTRO_HEADING_RE.search(normalized_heading):
                intro_hits += 1
            if _INTRO_BODY_RE.search(normalized_text):
                intro_hits += 1
            if re.search(r"impugna(?:ç|c)[aã]o\s+[àa]\s+contesta(?:ç|c)[aã]o", normalized_text, re.IGNORECASE):
                intro_hits += 1
            if intro_hits >= 2:
                return "introduction"

        # 3) Pontuação por sinais de heading + corpo.
        scores = {
            "introduction": 0,
            "preliminary": 0,
            "merit_by_thesis": 0,
            "jurisprudence": 0,
            "requests": 0,
        }

        if _INTRO_HEADING_RE.search(normalized_heading):
            scores["introduction"] += 5
        if _PRELIM_HEADING_RE.search(normalized_heading):
            scores["preliminary"] += 5
        if _MERIT_HEADING_RE.search(normalized_heading):
            scores["merit_by_thesis"] += 5
        if _JURIS_HEADING_RE.search(normalized_heading):
            scores["jurisprudence"] += 5
        if _REQUESTS_HEADING_RE.search(normalized_heading):
            scores["requests"] += 6

        if _INTRO_BODY_RE.search(normalized_text):
            scores["introduction"] += 2
        if _PRELIM_BODY_RE.search(normalized_text):
            scores["preliminary"] += 2
        if _MERIT_BODY_RE.search(normalized_text):
            scores["merit_by_thesis"] += 2
        if _JURIS_BODY_RE.search(normalized_text):
            scores["jurisprudence"] += 2
        if _REQUESTS_BODY_RE.search(normalized_text):
            scores["requests"] += 2

        # Penalização leve para "requests" em páginas iniciais sem heading de pedidos.
        if page_no in (0, 1, 2) and not _REQUESTS_HEADING_RE.search(normalized_heading):
            scores["requests"] = max(0, scores["requests"] - 2)

        best_kind, best_score = max(scores.items(), key=lambda item: item[1])
        if best_score >= 2:
            return best_kind

        # 4) Fallback legado (mantém compatibilidade para textos atípicos).
        lower_heading = normalized_heading.lower()
        lower_text = normalized_text.lower()
        for kind, pattern in _SECTION_KIND_HINTS:
            if re.search(pattern, lower_heading):
                return kind
        for kind, pattern in _SECTION_KIND_HINTS:
            if re.search(pattern, lower_text):
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

    def _classify_theses_with_ai(
        self,
        *,
        file_path: str | Path,
        thesis_catalog: list[dict],
        segments: list[dict],
    ) -> tuple[list[str], dict[int, list[str]]]:
        if not thesis_catalog or not segments:
            return [], {}

        try:
            result = self.thesis_classifier_agent.classify(
                file_path=str(file_path),
                thesis_catalog=thesis_catalog,
                segments=segments,
            )
            document_ids = result.document_thesis_catalog_ids or []
            by_chunk: dict[int, list[str]] = {}
            for chunk in result.chunk_classifications or []:
                by_chunk[int(chunk.order_in_doc)] = list(chunk.thesis_catalog_ids or [])

            print(
                "[ImpugnacaoReferenceIngestor] Classificação IA de teses concluída "
                f"(documento={len(document_ids)} | chunks={len(by_chunk)})."
            )
            return document_ids, by_chunk
        except Exception as error:
            print(f"[ImpugnacaoReferenceIngestor] Falha na classificação IA de teses: {error}")
            return [], {}

    # ── Extração de jurisprudência embutida ────────────────────────────

    @classmethod
    def _is_citation_para(cls, para: str) -> bool:
        """Retorna True se o parágrafo parece conteúdo de citação jurisprudencial."""
        para = para.strip()
        if not para:
            return False
        first_line = para.split('\n')[0].strip()
        # Linha predominantemente em CAIXA ALTA (cabeçalho de ementa)
        alpha_chars = [c for c in first_line if c.isalpha()]
        if alpha_chars and sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) > 0.65 and len(first_line) > 20:
            return True
        # Ratio decidendi numerado
        if re.match(r'^\d+\.', para):
            return True
        # Rodapé de atribuição: (...) (TRF4...) ou (TRF4, AC...)
        if re.match(r'^\(\.\.\.', para) or re.match(r'^\((?:TRF|STJ|STF)', para, re.IGNORECASE):
            return True
        # Contém referência de tribunal + número de processo
        if re.search(r'\bTRF\d?\b|\bSTJ\b|\bAC\s+\d|\bREsp\b', para[:200], re.IGNORECASE):
            return True
        return False

    @classmethod
    def _extract_embedded_jurisprudence(cls, text: str) -> list[dict]:
        """Detecta e extrai blocos de citações jurisprudenciais embutidos no texto.

        Usa duas estratégias:
        - Header-first: detecta início de citação pelo tribunal/AC no começo da linha.
        - Footer-first: detecta (GN) / (...) (TRF...) no final e caminha de volta.

        Retorna lista de dicts: text, tribunal, case_number, relator.
        """
        found_ranges: list[tuple[int, int]] = []

        def _overlaps(s: int, e: int) -> bool:
            return any(s < fe and e > fs for fs, fe in found_ranges)

        def _make_block(block_start: int, block_end: int) -> Optional[dict]:
            if _overlaps(block_start, block_end):
                return None
            block_text = text[block_start:block_end].strip()
            if len(block_text) < 120:
                return None
            tribunal_m = _TRIBUNAL_RE.search(block_text[:400])
            tribunal = tribunal_m.group(1).upper().replace(' ', '') if tribunal_m else None
            case_m = _CASE_NUMBER_RE.search(block_text[:600])
            case_number = case_m.group(1) if case_m else None
            relator_m = _RELATOR_RE.search(block_text)
            relator = relator_m.group(1).strip().upper() if relator_m else None
            found_ranges.append((block_start, block_end))
            return {'text': block_text, 'tribunal': tribunal, 'case_number': case_number, 'relator': relator}

        results: list[dict] = []

        # ── Estratégia 1: header-first ─────────────────────────────────
        seen_starts: set[int] = set()
        for match in _JURIS_CITATION_HEADER_RE.finditer(text):
            line_start = text.rfind('\n', 0, match.start())
            block_start = (line_start + 1) if line_start >= 0 else 0
            if block_start in seen_starts:
                continue
            seen_starts.add(block_start)

            # Avança para incluir parágrafos contíguos que ainda parecem citação
            pos = match.end()
            for _ in range(6):
                sep = text.find('\n\n', pos)
                if sep < 0:
                    pos = len(text)
                    break
                next_para = text[sep + 2: sep + 400].lstrip('\n')
                if cls._is_citation_para(next_para):
                    pos = sep + 2
                else:
                    pos = sep
                    break

            block = _make_block(block_start, pos)
            if block:
                results.append(block)

        # ── Estratégia 2: footer-first (GN / (...)(TRF...) no rodapé) ──
        for match in _JURIS_FOOTER_RE.finditer(text):
            block_end = match.end()
            search_from = max(0, match.start() - 3500)
            window = text[search_from:match.start()]

            # Encontra separadores \n\n de trás para frente
            seps = [m.start() for m in re.finditer(r'\n\n', window)]
            citation_start_in_window = 0  # fallback: início da janela

            for sep in reversed(seps):
                after_sep = window[sep + 2: sep + 400].lstrip('\n')
                if cls._is_citation_para(after_sep):
                    citation_start_in_window = sep + 2
                else:
                    break  # chegou no texto argumentativo, para

            block = _make_block(search_from + citation_start_in_window, block_end)
            if block:
                results.append(block)

        return results

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
        thesis_catalog: Optional[list[dict]] = None,
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

        full_document_text = ''
        if processed_document is not None:
            full_document_text = str(getattr(processed_document, 'full_text', '') or '').strip()
        if not full_document_text and provided_text:
            full_document_text = provided_text
        if not full_document_text:
            full_document_text = '\n\n'.join(seg.get('text') or '' for seg in segments)

        catalog = thesis_catalog or []
        document_thesis_catalog_ids, ai_chunk_thesis_map = self._classify_theses_with_ai(
            file_path=file_path,
            thesis_catalog=catalog,
            segments=segments,
        )

        # Fallback determinístico para cenários de falha no agente.
        if not document_thesis_catalog_ids:
            document_thesis_catalog_ids = self._match_thesis_catalog_ids(
                full_document_text,
                catalog,
                max_items=10,
                minimum_score=3,
            )
        self.last_document_thesis_catalog_ids = document_thesis_catalog_ids

        print(
            f"[ImpugnacaoReferenceIngestor] {len(segments)} chunks segmentados "
            f"para reference_id={reference_id} (modo={segmentation_mode})"
        )

        chunk_records: list[dict] = []
        points: list[rest.PointStruct] = []
        ingested_at = datetime.utcnow().isoformat() + "Z"
        # Extracted jurisprudence blocks get order numbers starting after all main segments.
        extracted_juris_order = len(segments) * 2

        for order, seg in enumerate(segments):
            chunk_text = seg["text"]
            if not chunk_text or len(chunk_text) < 40:
                continue

            chunk_scope = f"{seg.get('heading', '')}\n\n{chunk_text}".strip()
            chunk_thesis_catalog_ids = list(ai_chunk_thesis_map.get(order) or [])

            if not chunk_thesis_catalog_ids:
                chunk_thesis_catalog_ids = self._match_thesis_catalog_ids(
                    chunk_scope,
                    catalog,
                    max_items=5,
                    minimum_score=3,
                )
            if not chunk_thesis_catalog_ids and document_thesis_catalog_ids:
                chunk_thesis_catalog_ids = document_thesis_catalog_ids[:2]
            primary_thesis_catalog_id = (
                chunk_thesis_catalog_ids[0]
                if chunk_thesis_catalog_ids
                else (document_thesis_catalog_ids[0] if document_thesis_catalog_ids else None)
            )

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
                "thesis_catalog_ids": chunk_thesis_catalog_ids,
                "thesis_catalog_id": primary_thesis_catalog_id,
                "document_thesis_catalog_ids": document_thesis_catalog_ids,
                "status": "active",
                "order_in_doc": order,
                "ingested_at": ingested_at,
            }

            points.append(rest.PointStruct(id=point_id, vector=vector, payload=payload))
            chunk_records.append({
                "qdrant_point_id": point_id,
                "section_kind": payload["section_kind"],
                "thesis_catalog_id": primary_thesis_catalog_id,
                "thesis_catalog_ids": chunk_thesis_catalog_ids,
                "document_thesis_catalog_ids": document_thesis_catalog_ids,
                "benefit_type": None,
                "chunk_chars": len(chunk_text),
                "order_in_doc": order,
                "preview_text": chunk_text[:280],
                "full_text": chunk_text,
            })

            # Extract embedded jurisprudence citations from mérito/general chunks.
            # These produce *additional* jurisprudence chunks alongside the original.
            if seg.get("section_kind") in ("merit_by_thesis", "general", "preliminary"):
                juris_blocks = self._extract_embedded_jurisprudence(chunk_text)
                for jblock in juris_blocks:
                    jtext = jblock["text"]
                    jpoint_id = str(uuid.uuid4())
                    jvector = self._embed(jtext)
                    jpayload = {
                        "text": jtext,
                        "heading": jblock.get("case_number") or "jurisprudência",
                        "section_kind": "jurisprudence",
                        "page": seg.get("page"),
                        "section": seg.get("section"),
                        "reference_id": int(reference_id),
                        "law_firm_id": int(law_firm_id),
                        "reference_title": title,
                        "trf_region": (trf_region or "").upper() or None,
                        "generation_mode": (generation_mode or "").upper() or None,
                        "quality_score": float(quality_score) if quality_score is not None else None,
                        "thesis_catalog_ids": chunk_thesis_catalog_ids,
                        "thesis_catalog_id": primary_thesis_catalog_id,
                        "document_thesis_catalog_ids": document_thesis_catalog_ids,
                        "tribunal": jblock.get("tribunal"),
                        "case_number": jblock.get("case_number"),
                        "relator": jblock.get("relator"),
                        "is_extracted_juris": True,
                        "parent_order_in_doc": order,
                        "status": "active",
                        "order_in_doc": extracted_juris_order,
                        "ingested_at": ingested_at,
                    }
                    points.append(rest.PointStruct(id=jpoint_id, vector=jvector, payload=jpayload))
                    chunk_records.append({
                        "qdrant_point_id": jpoint_id,
                        "section_kind": "jurisprudence",
                        "thesis_catalog_id": primary_thesis_catalog_id,
                        "thesis_catalog_ids": chunk_thesis_catalog_ids,
                        "document_thesis_catalog_ids": document_thesis_catalog_ids,
                        "benefit_type": None,
                        "chunk_chars": len(jtext),
                        "order_in_doc": extracted_juris_order,
                        "preview_text": jtext[:280],
                        "full_text": jtext,
                    })
                    extracted_juris_order += 1
                if juris_blocks:
                    print(
                        f"[ImpugnacaoReferenceIngestor] {len(juris_blocks)} bloco(s) de "
                        f"jurisprudência extraído(s) do chunk #{order} (section_kind={seg.get('section_kind')})"
                    )

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
