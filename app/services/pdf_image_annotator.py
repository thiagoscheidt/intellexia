"""Anotador de imagens em texto extraído de PDF (marcadores de imagem).

Problema: quando o pipeline de ingestão usa o caminho rápido do `pdfplumber`
(PDF com camada de texto), imagens (prints de FAP Web, CNIS, INFBEN, CAT etc.)
são completamente ignoradas — o texto extraído pula direto da frase de
introdução para o parágrafo seguinte, perdendo o elo entre a tese e a prova
visual que a sustenta.

Este serviço usa PyMuPDF (`fitz`) para localizar as imagens de cada página,
descartar "cromo do documento" (papel timbrado, cabeçalho/rodapé, brasão,
assinatura — imagens repetidas em várias páginas que não são prova, ver
`_chrome_xrefs`), casar cada imagem restante com o bloco de texto
imediatamente acima (a "âncora") e inserir um marcador textual —
`[IMAGEM: <descrição>]` ou, sem descrição,
`[IMAGEM — print citado no parágrafo acima]` — na posição correta do fluxo de
texto vindo do `pdfplumber`. Opcionalmente, descreve as imagens via um modelo
de visão barato (lotes numa única chamada multimodal).

Este módulo nunca levanta exceção para o chamador: qualquer falha (PyMuPDF,
render, visão) é registrada em log e o texto original (ou parcialmente
anotado) é devolvido, pois isto roda no meio da ingestão de documentos.

Fora de escopo: salvar as imagens; descrever imagens em documentos de
caso/base de conhecimento (aqui é usado só pela ingestão de peças-modelo).
"""

from __future__ import annotations

import base64
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import fitz  # PyMuPDF

from app.services.token_usage_service import TokenUsageService

_LOG_PREFIX = "[pdf_image_annotator]"

_MAX_ANCHOR_CHARS = 60
_MAX_DESCRIPTION_CHARS = 220

# Marcador sem descrição (visão desligada/falhou ou teto por documento
# atingido). Público para reuso por outros pontos de integração — hoje,
# `ImpugnacaoReferenceIngestor._split_by_headings` converte para este mesmo
# marcador as linhas `<!-- image -->` que vêm do caminho Docling, em vez de
# duplicar a string.
IMAGE_MARKER_PLAIN = "[IMAGEM — print citado no parágrafo acima]"

_WS_RE = re.compile(r"\s+")
_NUMBERED_LINE_RE = re.compile(r"^\s*(\d+)[.)]\s*(.+)$")

_VISION_PROMPT = (
    "Você recebe recortes de imagens extraídas de uma peça jurídica trabalhista/"
    "previdenciária (prints de telas de sistemas como FAP Web, CNIS, INFBEN, CAT, "
    "folha de pagamento, etc.).\n"
    "Para CADA imagem, na ORDEM em que aparecem, escreva UMA linha numerada dizendo "
    "que tipo de tela/documento é e quais dados-chave aparecem (nomes, NB/NIT, datas, "
    "CNPJ, valores). NÃO invente dados que não estejam legíveis — se não der para ler "
    "algo, diga isso brevemente.\n"
    "Responda EXCLUSIVAMENTE no formato abaixo (uma linha por imagem, nesta ordem, "
    "sem texto fora das linhas numeradas):\n"
    "1. <descrição da imagem 1>\n"
    "2. <descrição da imagem 2>\n"
    "..."
)


# ── Configuração via env (lida a cada chamada, para testabilidade) ─────────


def _vision_enabled() -> bool:
    """IMPUGNACAO_IMAGE_VISION_ENABLED ausente = ligada. Desliga com
    'false'/'0'/'no'/'off' (case-insensitive); qualquer outro valor = ligada."""
    raw = os.getenv("IMPUGNACAO_IMAGE_VISION_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() not in {"false", "0", "no", "off"}


def _min_area() -> float:
    try:
        return float(os.getenv("IMPUGNACAO_IMAGE_MIN_AREA", "15000"))
    except (TypeError, ValueError):
        return 15000.0


def _max_described_per_doc() -> int:
    try:
        return int(os.getenv("IMPUGNACAO_IMAGE_MAX_DESCRIBED_PER_DOC", "40"))
    except (TypeError, ValueError):
        return 40


def _vision_batch_size() -> int:
    try:
        return max(1, int(os.getenv("IMPUGNACAO_IMAGE_VISION_BATCH_SIZE", "5")))
    except (TypeError, ValueError):
        return 5


def _vision_model() -> str:
    return os.getenv("IMPUGNACAO_IMAGE_VISION_MODEL", "gpt-4o-mini")


def _render_dpi() -> int:
    try:
        return int(os.getenv("IMPUGNACAO_IMAGE_RENDER_DPI", "150"))
    except (TypeError, ValueError):
        return 150


def _chrome_min_pages() -> int:
    """IMPUGNACAO_IMAGE_CHROME_MIN_PAGES (default 3): a partir de quantas
    páginas distintas um xref é tratado como "cromo do documento" (papel
    timbrado, cabeçalho/rodapé repetido, brasão, linha de assinatura) e
    descartado antes de gerar qualquer marcador — não é prova, é moldura."""
    try:
        return int(os.getenv("IMPUGNACAO_IMAGE_CHROME_MIN_PAGES", "3"))
    except (TypeError, ValueError):
        return 3


# ── Ancoragem (função pura, testável isoladamente) ──────────────────────────


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _build_normalized_map(text: str) -> tuple[str, list[int]]:
    """Colapsa espaços em branco (qualquer sequência -> um único ' ', bordas
    removidas) e devolve, junto do texto normalizado, um mapa índice
    normalizado -> índice (exclusivo) correspondente no texto original."""
    out: list[str] = []
    idx_map: list[int] = []
    prev_space = True  # início tratado como se já tivesse havido espaço (equivale a lstrip)
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                idx_map.append(i + 1)
            prev_space = True
        else:
            out.append(ch)
            idx_map.append(i + 1)
            prev_space = False

    while out and out[-1] == " ":
        out.pop()
        idx_map.pop()

    return "".join(out), idx_map


def _find_anchor_end_index(page_text: str, normalized_anchor: str) -> Optional[int]:
    normalized_page, idx_map = _build_normalized_map(page_text)
    pos = normalized_page.find(normalized_anchor)
    if pos < 0:
        return None
    end_pos = pos + len(normalized_anchor) - 1
    if end_pos < 0 or end_pos >= len(idx_map):
        return None
    return idx_map[end_pos]


def _append_marker_at_end(text: str, marker_text: str) -> str:
    stripped = (text or "").rstrip("\n")
    if stripped:
        return f"{stripped}\n{marker_text}\n"
    return f"{marker_text}\n"


def _splice_marker(before: str, after: str, marker_text: str) -> str:
    before_trimmed = before.rstrip(" \t")
    after_trimmed = after.lstrip(" \t")
    lead = "" if (not before_trimmed or before_trimmed.endswith("\n")) else "\n"
    trail = "" if (not after_trimmed or after_trimmed.startswith("\n")) else "\n"
    return f"{before_trimmed}{lead}{marker_text}{trail}{after_trimmed}"


def insert_marker_after_anchor(page_text: str, anchor: str, marker: str) -> str:
    """Insere `marker` em linha própria logo após a primeira ocorrência de
    `anchor` em `page_text`, comparando com espaços normalizados (as
    extrações de fitz e pdfplumber divergem em espaçamento).

    - âncora vazia ou não encontrada -> marcador no fim do texto.
    - âncora com múltiplas ocorrências -> usa a primeira.
    - nunca quebra palavras: a inserção sempre entra como linha própria
      (marcador cercado por quebras de linha), sem remover nenhum caractere
      do texto original.
    """
    text = page_text or ""
    marker_text = (marker or "").strip()
    if not marker_text:
        return text

    normalized_anchor = _normalize_ws(anchor)
    insert_at = _find_anchor_end_index(text, normalized_anchor) if normalized_anchor else None

    if insert_at is None:
        return _append_marker_at_end(text, marker_text)

    before, after = text[:insert_at], text[insert_at:]
    return _splice_marker(before, after, marker_text)


# ── Coleta de imagens (dedup por xref + filtro de área) ─────────────────────


@dataclass
class _ImageOccurrence:
    page_number: int  # 1-based
    xref: int
    rect: "fitz.Rect"
    area: float


def _collect_images_by_doc(
    doc: "fitz.Document", min_area: float
) -> tuple[dict[int, list[_ImageOccurrence]], list[int]]:
    """Varre o documento inteiro e devolve:
    - ocorrências de imagem por página (1-based), ordenadas de cima para baixo;
    - a ordem de primeira aparição dos xrefs únicos (usada para aplicar o teto
      de descrição por documento e para deduplicar a descrição em si).

    Imagens com área < `min_area` são descartadas (descarta logo, assinatura,
    linhas decorativas).
    """
    occurrences_by_page: dict[int, list[_ImageOccurrence]] = {}
    first_seen_order: list[int] = []
    seen_xrefs: set[int] = set()

    for page_index in range(doc.page_count):
        page = doc[page_index]
        page_number = page_index + 1
        page_occurrences: list[_ImageOccurrence] = []
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                continue
            for rect in rects:
                area = float(rect.width) * float(rect.height)
                if area < min_area:
                    continue
                page_occurrences.append(
                    _ImageOccurrence(page_number=page_number, xref=xref, rect=rect, area=area)
                )
                if xref not in seen_xrefs:
                    seen_xrefs.add(xref)
                    first_seen_order.append(xref)

        if page_occurrences:
            page_occurrences.sort(key=lambda occ: occ.rect.y0)
            occurrences_by_page[page_number] = page_occurrences

    return occurrences_by_page, first_seen_order


def _xref_page_counts(
    occurrences_by_page: dict[int, list[_ImageOccurrence]]
) -> dict[int, set[int]]:
    """{xref: {números de página distintos em que aparece}}."""
    counts: dict[int, set[int]] = {}
    for page_number, occurrences in occurrences_by_page.items():
        for occurrence in occurrences:
            counts.setdefault(occurrence.xref, set()).add(page_number)
    return counts


def _chrome_xrefs(xref_pages: dict[int, set[int]], total_pages: int) -> set[int]:
    """Identifica xrefs que são "cromo do documento" — papel timbrado,
    cabeçalho/rodapé, brasão, linha de assinatura — repetidos em várias
    páginas e que por isso não são prova: não devem gerar marcador nem
    entrar na conta de descrição por visão.

    `xref_pages`: mapa xref -> conjunto de páginas distintas em que aparece
    (ver `_xref_page_counts`). `total_pages`: total de páginas do documento.

    Regra: um xref é cromo se aparece em `IMPUGNACAO_IMAGE_CHROME_MIN_PAGES`
    páginas distintas ou mais (configurável, respeitado tal como setado —
    inclusive abaixo de 3, se um escritório quiser afinar isso para um
    acervo específico), OU se aparece em mais da metade das páginas do
    documento (para pegar cromo em documentos curtos, onde o limiar
    configurado pode nunca ser atingido).

    A segunda condição ("mais da metade") NUNCA dispara com menos de 3
    páginas de ocorrência — mesmo numa peça de 2 páginas onde a mesma
    imagem aparece nas 2 (100% das páginas), isso não é cromo por si só,
    é prova legítima repetida, e não deve ser descartado silenciosamente.
    """
    min_pages_config = _chrome_min_pages()
    safe_total_pages = total_pages if total_pages and total_pages > 0 else 1

    chrome: set[int] = set()
    for xref, pages in xref_pages.items():
        count = len(pages)
        if count >= min_pages_config:
            chrome.add(xref)
            continue
        if count >= 3 and count * 2 > safe_total_pages:
            chrome.add(xref)

    return chrome


def _remove_chrome_occurrences(
    occurrences_by_page: dict[int, list[_ImageOccurrence]],
    first_seen_order: list[int],
    total_pages: int,
) -> tuple[dict[int, list[_ImageOccurrence]], list[int], set[int]]:
    """Aplica `_chrome_xrefs` e remove as ocorrências de imagens de cromo,
    tanto das páginas quanto da ordem de descrição. Loga quantas ocorrências
    foram descartadas, para auditar quando alguém estranhar um print ausente."""
    xref_pages = _xref_page_counts(occurrences_by_page)
    chrome = _chrome_xrefs(xref_pages, total_pages)
    if not chrome:
        return occurrences_by_page, first_seen_order, chrome

    filtered_by_page: dict[int, list[_ImageOccurrence]] = {}
    discarded = 0
    for page_number, occurrences in occurrences_by_page.items():
        kept = [occ for occ in occurrences if occ.xref not in chrome]
        discarded += len(occurrences) - len(kept)
        if kept:
            filtered_by_page[page_number] = kept

    filtered_order = [xref for xref in first_seen_order if xref not in chrome]

    print(
        f"{_LOG_PREFIX} descartadas {discarded} ocorrência(s) de imagem "
        f"({len(chrome)} xref(s) único(s): {sorted(chrome)}) como cromo do "
        f"documento — repetiam em várias páginas (cabeçalho/rodapé/timbrado/"
        f"assinatura), não geram marcador."
    )
    return filtered_by_page, filtered_order, chrome


def _find_anchor_text(page: "fitz.Page", image_rect: "fitz.Rect") -> str:
    """Acha o bloco de texto imediatamente acima da imagem na mesma página e
    devolve o seu "rabo" (últimas ~60 chars, espaços normalizados). Vazio se
    não houver nenhum bloco de texto acima."""
    try:
        blocks = page.get_text("blocks")
    except Exception:
        return ""

    best_y1: Optional[float] = None
    best_text = ""
    for block in blocks:
        if len(block) < 7:
            continue
        x0, y0, x1, y1, text, _block_no, block_type = block[:7]
        if block_type != 0:  # 0 = bloco de texto
            continue
        if not text or not text.strip():
            continue
        if y1 > image_rect.y0 + 1:  # bloco não está acima da imagem
            continue
        if best_y1 is None or y1 > best_y1:
            best_y1 = y1
            best_text = text

    normalized = _normalize_ws(best_text)
    if len(normalized) > _MAX_ANCHOR_CHARS:
        normalized = normalized[-_MAX_ANCHOR_CHARS:]
    return normalized


# ── Marcador ─────────────────────────────────────────────────────────────


def _build_marker(description: Optional[str]) -> str:
    if description:
        desc = description.strip()
        if len(desc) > _MAX_DESCRIPTION_CHARS:
            desc = desc[:_MAX_DESCRIPTION_CHARS].rstrip() + "…"
        return f"[IMAGEM: {desc}]"
    return IMAGE_MARKER_PLAIN


# ── Visão (descrição por lote) ───────────────────────────────────────────


def _render_image_png_b64(page: "fitz.Page", rect: "fitz.Rect", dpi: int) -> Optional[str]:
    try:
        pix = page.get_pixmap(clip=rect, dpi=dpi)
        return base64.b64encode(pix.tobytes("png")).decode("ascii")
    except Exception as exc:
        print(f"{_LOG_PREFIX} falha ao renderizar imagem para visão: {exc}")
        return None


def _parse_numbered_descriptions(text: str, expected_count: int) -> list[str]:
    results: dict[int, str] = {}
    for line in (text or "").splitlines():
        match = _NUMBERED_LINE_RE.match(line)
        if not match:
            continue
        try:
            idx = int(match.group(1))
        except ValueError:
            continue
        results[idx] = match.group(2).strip()
    return [results.get(i + 1, "") for i in range(expected_count)]


def _record_vision_usage(
    completion, *, model_name: str, law_firm_id: Optional[int], latency_ms: int
) -> None:
    try:
        usage = getattr(completion, "usage", None)
        if usage is not None and hasattr(usage, "model_dump"):
            usage_dict = usage.model_dump()
        else:
            usage_dict = usage or {}

        finish_reason = None
        if getattr(completion, "choices", None):
            finish_reason = completion.choices[0].finish_reason

        message = {
            "type": "ai",
            "id": getattr(completion, "id", None),
            "response_metadata": {
                "token_usage": {
                    "prompt_tokens": usage_dict.get("prompt_tokens", 0),
                    "completion_tokens": usage_dict.get("completion_tokens", 0),
                    "total_tokens": usage_dict.get("total_tokens", 0),
                },
                "finish_reason": finish_reason,
                "id": getattr(completion, "id", None),
            },
        }
        TokenUsageService().capture_and_store(
            {"messages": [message]},
            agent_name="PdfImageAnnotator",
            action_name="describe_images",
            print_prefix="[PdfImageAnnotator][TokenUsage]",
            model_name=model_name,
            model_provider="openai",
            law_firm_id=law_firm_id,
            latency_ms=latency_ms,
            status="success",
        )
    except Exception as exc:
        print(f"{_LOG_PREFIX} falha ao registrar token usage: {exc}")


def _describe_image_batch(images_b64: list[str], *, law_firm_id: Optional[int]) -> list[str]:
    """Descreve um lote de imagens numa única chamada multimodal. Devolve uma
    lista de descrições na mesma ordem/quantidade de `images_b64` (string
    vazia quando o parsing não achar a linha correspondente). Lança em caso
    de falha de chamada — quem chama decide como degradar."""
    from openai import OpenAI

    client = OpenAI()
    content: list[dict] = [{"type": "text", "text": _VISION_PROMPT}]
    for b64 in images_b64:
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        )

    model_name = _vision_model()
    started_at = time.perf_counter()
    completion = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": content}],
        temperature=0.0,
    )
    latency_ms = int((time.perf_counter() - started_at) * 1000)

    text = completion.choices[0].message.content if completion.choices else ""
    descriptions = _parse_numbered_descriptions(text or "", len(images_b64))

    _record_vision_usage(completion, model_name=model_name, law_firm_id=law_firm_id, latency_ms=latency_ms)

    return descriptions


def _describe_images(
    doc: "fitz.Document",
    occurrences_by_page: dict[int, list[_ImageOccurrence]],
    xrefs_to_describe: list[int],
    batch_size: int,
    dpi: int,
    law_firm_id: Optional[int],
) -> dict[int, str]:
    xref_to_first_occurrence: dict[int, _ImageOccurrence] = {}
    for occurrences in occurrences_by_page.values():
        for occurrence in occurrences:
            xref_to_first_occurrence.setdefault(occurrence.xref, occurrence)

    ordered = [xref for xref in xrefs_to_describe if xref in xref_to_first_occurrence]
    descriptions: dict[int, str] = {}

    for batch_start in range(0, len(ordered), batch_size):
        batch_xrefs = ordered[batch_start : batch_start + batch_size]
        images_b64: list[str] = []
        valid_xrefs: list[int] = []
        for xref in batch_xrefs:
            occurrence = xref_to_first_occurrence[xref]
            page = doc[occurrence.page_number - 1]
            b64 = _render_image_png_b64(page, occurrence.rect, dpi)
            if b64 is None:
                continue
            images_b64.append(b64)
            valid_xrefs.append(xref)

        if not images_b64:
            continue

        try:
            batch_descriptions = _describe_image_batch(images_b64, law_firm_id=law_firm_id)
        except Exception as exc:
            print(f"{_LOG_PREFIX} falha na descrição de lote de imagens: {exc}")
            continue

        for xref, description in zip(valid_xrefs, batch_descriptions):
            if description:
                descriptions[xref] = description

    return descriptions


# ── API pública ───────────────────────────────────────────────────────────


def annotate_pages_with_images(
    pdf_path: str,
    page_texts: list[tuple[int, str]],
    *,
    describe: Optional[bool] = None,
    law_firm_id: Optional[int] = None,
) -> list[tuple[int, str]]:
    """Insere marcadores de imagem no texto das páginas, na posição do fluxo.

    page_texts: [(numero_pagina, texto)] como sai do pdfplumber.
    describe=None -> lê IMPUGNACAO_IMAGE_VISION_ENABLED (default LIGADA).
    Nunca levanta: qualquer falha devolve os textos originais (ou com
    marcador sem descrição), porque isto roda no meio da ingestão.
    """
    if not page_texts:
        return page_texts

    try:
        return _annotate_pages_with_images(
            pdf_path, page_texts, describe=describe, law_firm_id=law_firm_id
        )
    except Exception as exc:
        print(f"{_LOG_PREFIX} falha ao anotar imagens em '{pdf_path}': {exc}")
        return page_texts


def _annotate_pages_with_images(
    pdf_path: str,
    page_texts: list[tuple[int, str]],
    *,
    describe: Optional[bool],
    law_firm_id: Optional[int],
) -> list[tuple[int, str]]:
    should_describe = _vision_enabled() if describe is None else bool(describe)
    min_area = _min_area()
    max_described = _max_described_per_doc()
    batch_size = _vision_batch_size()
    dpi = _render_dpi()

    doc = fitz.open(pdf_path)
    try:
        occurrences_by_page, first_seen_order = _collect_images_by_doc(doc, min_area)
        if not occurrences_by_page:
            return page_texts

        occurrences_by_page, first_seen_order, _chrome = _remove_chrome_occurrences(
            occurrences_by_page, first_seen_order, doc.page_count
        )
        if not occurrences_by_page:
            return page_texts

        descriptions_by_xref: dict[int, str] = {}
        if should_describe and first_seen_order:
            xrefs_to_describe = first_seen_order[:max_described]
            try:
                descriptions_by_xref = _describe_images(
                    doc, occurrences_by_page, xrefs_to_describe, batch_size, dpi, law_firm_id
                )
            except Exception as exc:
                print(f"{_LOG_PREFIX} falha geral na descrição por visão: {exc}")
                descriptions_by_xref = {}

        page_text_map: dict[int, str] = dict(page_texts)

        for page_number, occurrences in occurrences_by_page.items():
            if page_number not in page_text_map:
                continue
            page = doc[page_number - 1]
            text = page_text_map[page_number]
            for occurrence in occurrences:
                try:
                    description = descriptions_by_xref.get(occurrence.xref)
                    marker = _build_marker(description)
                    anchor = _find_anchor_text(page, occurrence.rect)
                    text = insert_marker_after_anchor(text, anchor, marker)
                except Exception as exc:
                    print(f"{_LOG_PREFIX} falha ao anotar imagem xref={occurrence.xref}: {exc}")
            page_text_map[page_number] = text

        return [(page_number, page_text_map.get(page_number, original_text)) for page_number, original_text in page_texts]
    finally:
        doc.close()
