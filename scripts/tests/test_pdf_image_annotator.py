"""Teste do anotador de marcadores de imagem (pdf_image_annotator).

Puro Python — sem rede, sem banco, sem app Flask, sem chamada de visão/OpenAI.
Cobre a função pura de ancoragem, a leitura do env de liga/desliga da visão, a
coleta de imagens (filtro de área + dedup por xref) sobre um PDF sintético
criado com PyMuPDF e a classificação de "cromo do documento" (papel timbrado/
cabeçalho repetido, que não deve virar marcador).

Rodar: uv run python scripts/tests/test_pdf_image_annotator.py
"""
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import fitz  # PyMuPDF
from PIL import Image

from app.services.pdf_image_annotator import (
    _chrome_xrefs,
    _collect_images_by_doc,
    _vision_enabled,
    insert_marker_after_anchor,
)

FAILS = []


def check(label, got, expected):
    if got != expected:
        FAILS.append(f"{label}: esperado {expected!r}, obtido {got!r}")
        print(f"  ✗ {label}: esperado {expected!r}, obtido {got!r}")
    else:
        print(f"  ✓ {label}")


def check_true(label, cond, detail=""):
    if not cond:
        FAILS.append(f"{label} {detail}")
        print(f"  ✗ {label} {detail}")
    else:
        print(f"  ✓ {label}")


# ── insert_marker_after_anchor ──────────────────────────────────────────

print("\n== insert_marker_after_anchor ==")

MARKER = "[IMAGEM: print do extrato CNIS]"

# 1. âncora presente -> marcador logo após, em linha própria, resto preservado
text = "Introdução do argumento por decorrer de acidente de trajeto: Segue o parágrafo seguinte."
anchor = "por decorrer de acidente de trajeto:"
result = insert_marker_after_anchor(text, anchor, MARKER)
check(
    "âncora presente: marcador inserido logo após, em linha própria",
    result,
    "Introdução do argumento por decorrer de acidente de trajeto:\n"
    "[IMAGEM: print do extrato CNIS]\nSegue o parágrafo seguinte.",
)
check_true("âncora presente: preserva texto anterior", result.startswith("Introdução do argumento"))
check_true("âncora presente: preserva texto posterior", result.endswith("Segue o parágrafo seguinte."))

# 2. âncora com espaçamento diferente do texto -> normalização funciona
text_multispace = "Texto acaba aqui:  por   decorrer\nde acidente  de trajeto:\nPróximo parágrafo aqui."
anchor_singlespace = "por decorrer de acidente de trajeto:"
result2 = insert_marker_after_anchor(text_multispace, anchor_singlespace, MARKER)
check_true(
    "âncora com espaçamento diferente: casa via normalização",
    "[IMAGEM: print do extrato CNIS]" in result2 and "Próximo parágrafo aqui." in result2,
    f"-> {result2!r}",
)
check_true(
    "âncora com espaçamento diferente: marcador entra antes do próximo parágrafo",
    result2.index(MARKER) < result2.index("Próximo parágrafo aqui."),
)

# 3. âncora vazia -> fim do texto
text3 = "Texto qualquer da página."
result3 = insert_marker_after_anchor(text3, "", MARKER)
check("âncora vazia: marcador no fim", result3, "Texto qualquer da página.\n[IMAGEM: print do extrato CNIS]\n")

# 4. âncora ausente -> fim do texto
text4 = "Texto qualquer da página, sem a frase procurada."
result4 = insert_marker_after_anchor(text4, "frase que não existe no texto", MARKER)
check(
    "âncora ausente: marcador no fim",
    result4,
    "Texto qualquer da página, sem a frase procurada.\n[IMAGEM: print do extrato CNIS]\n",
)

# 5. âncora repetida -> usa a primeira ocorrência
text5 = "abc REPETIDA def REPETIDA ghi"
result5 = insert_marker_after_anchor(text5, "REPETIDA", MARKER)
expected5 = "abc REPETIDA\n[IMAGEM: print do extrato CNIS]\ndef REPETIDA ghi"
check("âncora repetida: usa a primeira ocorrência", result5, expected5)

# 6. inserção não quebra palavras: sem espaço entre âncora e o que vem depois
text6 = "Texto termina em trajeto:Próximo texto colado sem espaço."
result6 = insert_marker_after_anchor(text6, "trajeto:", MARKER)
check(
    "não quebra palavras: marcador em linha própria mesmo sem espaço na origem",
    result6,
    "Texto termina em trajeto:\n[IMAGEM: print do extrato CNIS]\nPróximo texto colado sem espaço.",
)
check_true("não quebra palavras: 'trajeto:' preservado intacto", "trajeto:" in result6)
check_true("não quebra palavras: 'Próximo' preservado intacto", "Próximo" in result6)


# ── _vision_enabled ──────────────────────────────────────────────────────

print("\n== _vision_enabled (env IMPUGNACAO_IMAGE_VISION_ENABLED) ==")

_ORIGINAL_ENV = os.environ.get("IMPUGNACAO_IMAGE_VISION_ENABLED")


def _set_env(value):
    if value is None:
        os.environ.pop("IMPUGNACAO_IMAGE_VISION_ENABLED", None)
    else:
        os.environ["IMPUGNACAO_IMAGE_VISION_ENABLED"] = value


try:
    _set_env(None)
    check("ausente -> True", _vision_enabled(), True)

    for value in ["false", "0", "no", "off", "FALSE", "False", "NO", "Off"]:
        _set_env(value)
        check(f"{value!r} -> False", _vision_enabled(), False)

    for value in ["true", "1", "sim", "ligado", "qualquer-outra-coisa"]:
        _set_env(value)
        check(f"{value!r} -> True", _vision_enabled(), True)
finally:
    _set_env(_ORIGINAL_ENV)


# ── _collect_images_by_doc: filtro de área + dedup por xref ────────────

print("\n== _collect_images_by_doc (filtro de área + dedup por xref) ==")


def _png_bytes(size, color):
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


BIG_IMAGE_BYTES = _png_bytes((300, 300), (200, 30, 30))  # área grande na página (>= 15000 pt2)
TINY_IMAGE_BYTES = _png_bytes((10, 10), (30, 200, 30))  # área minúscula (< 15000 pt2)

doc = fitz.open()

page1 = doc.new_page(width=595, height=842)
page1.insert_text((50, 50), "Texto acima da imagem grande na página 1, terminando aqui:")
rect_big_p1 = fitz.Rect(50, 80, 350, 380)  # 300x300 = 90000 pt2
page1.insert_image(rect_big_p1, stream=BIG_IMAGE_BYTES)
rect_tiny_p1 = fitz.Rect(400, 80, 410, 90)  # 10x10 = 100 pt2
page1.insert_image(rect_tiny_p1, stream=TINY_IMAGE_BYTES)

page2 = doc.new_page(width=595, height=842)
page2.insert_text((50, 50), "Cabeçalho repetido na página 2, terminando aqui:")
rect_big_p2 = fitz.Rect(50, 80, 350, 380)
# mesma imagem (mesmos bytes) inserida de novo -> PyMuPDF costuma deduplicar o xref
page2.insert_image(rect_big_p2, stream=BIG_IMAGE_BYTES)

try:
    occurrences_by_page, first_seen_order = _collect_images_by_doc(doc, min_area=15000.0)

    check_true("página 1: só a imagem grande passa o filtro de área", len(occurrences_by_page.get(1, [])) == 1)
    check_true("página 2: a imagem repetida também passa o filtro", len(occurrences_by_page.get(2, [])) == 1)

    xref_p1 = occurrences_by_page[1][0].xref
    xref_p2 = occurrences_by_page[2][0].xref
    check(
        "mesma imagem repetida em 2 páginas -> mesmo xref (dedup natural do PyMuPDF)",
        xref_p2,
        xref_p1,
    )
    check(
        "dedup por xref: só 1 entrada única na ordem de descrição",
        len(first_seen_order),
        1,
    )

    total_occurrences = sum(len(v) for v in occurrences_by_page.values())
    check("total de ocorrências mantidas após filtro de área: 2 (grande na p1 + grande na p2)", total_occurrences, 2)
finally:
    doc.close()


# ── _chrome_xrefs: classificação de cromo do documento ──────────────────

print("\n== _chrome_xrefs (papel timbrado / cabeçalho repetido não vira marcador) ==")

# xref em 3 páginas -> cromo (limiar default = 3)
xref_pages_3_of_8 = {101: {1, 2, 3}}
check(
    "xref em 3 páginas (doc de 8) -> cromo",
    _chrome_xrefs(xref_pages_3_of_8, total_pages=8),
    {101},
)

# xref em 2 páginas -> NÃO é cromo, MESMO num PDF de 2 páginas (100% das páginas).
# É o caso que motivou a correção: prova legítima repetida não pode ser descartada
# só porque aparece em "mais da metade" de um documento curto.
xref_pages_2_of_2 = {202: {1, 2}}
check(
    "xref em 2 páginas de um PDF de 2 páginas -> NÃO é cromo (piso de 3 protege)",
    _chrome_xrefs(xref_pages_2_of_2, total_pages=2),
    set(),
)

# xref em 1 página -> não é cromo
xref_pages_1 = {303: {5}}
check(
    "xref em 1 página -> não é cromo",
    _chrome_xrefs(xref_pages_1, total_pages=10),
    set(),
)

# documento de 10 páginas, xref em 6 -> cromo
xref_pages_6_of_10 = {404: {1, 2, 3, 4, 5, 6}}
check(
    "xref em 6 páginas de um doc de 10 páginas -> cromo",
    _chrome_xrefs(xref_pages_6_of_10, total_pages=10),
    {404},
)

# mistura: só o xref de cromo é descartado, o legítimo permanece
mixed = {101: {1, 2, 3, 4}, 505: {2}}
check(
    "mistura: só o xref repetido (cromo) entra no conjunto, o de 1 página não",
    _chrome_xrefs(mixed, total_pages=8),
    {101},
)

# env IMPUGNACAO_IMAGE_CHROME_MIN_PAGES respeitado (inclusive abaixo de 3)
_ORIGINAL_CHROME_ENV = os.environ.get("IMPUGNACAO_IMAGE_CHROME_MIN_PAGES")
try:
    os.environ["IMPUGNACAO_IMAGE_CHROME_MIN_PAGES"] = "2"
    check(
        "env=2: xref em 2 páginas vira cromo (limiar configurado é respeitado)",
        _chrome_xrefs({606: {1, 2}}, total_pages=8),
        {606},
    )
finally:
    if _ORIGINAL_CHROME_ENV is None:
        os.environ.pop("IMPUGNACAO_IMAGE_CHROME_MIN_PAGES", None)
    else:
        os.environ["IMPUGNACAO_IMAGE_CHROME_MIN_PAGES"] = _ORIGINAL_CHROME_ENV

# confirma que o env voltou ao estado original (não vaza pros testes acima)
check(
    "env restaurado ao valor original após o teste",
    os.environ.get("IMPUGNACAO_IMAGE_CHROME_MIN_PAGES"),
    _ORIGINAL_CHROME_ENV,
)


# ── resultado ─────────────────────────────────────────────────────────────

print()
if FAILS:
    print(f"FALHOU: {len(FAILS)} check(s) com problema")
    for fail in FAILS:
        print(f"  - {fail}")
    sys.exit(1)

print("OK: todos os checks passaram")
