"""Arquivos que já são texto (Markdown, texto puro): lidos direto, sem conversão.

Fica fora do DocumentProcessorService de propósito: aquele módulo carrega o
Docling na importação, e quem só precisa ler um .md (servidor MCP, tela de
visualização) não deve pagar por isso.
"""
from __future__ import annotations

from pathlib import Path

TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


def is_text_file(file_path: str | Path) -> bool:
    return Path(str(file_path or "")).suffix.lower() in TEXT_SUFFIXES


def read_text_file(file_path: str | Path) -> str:
    """Conteúdo de um arquivo de texto: UTF-8 (com ou sem BOM); senão, cp1252."""
    raw = Path(file_path).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")
