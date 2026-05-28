"""Agente para padronizar e exportar documentos para DOCX no padrão do escritório.

Responsabilidades:
1. (Opcional) Normalizar o texto do documento com LLM mini para reduzir ruído de formatação.
2. Aplicar template templates_padrao/modelo_documento.docx (cabeçalho/rodapé/margens).
3. Gerar stream DOCX pronto para download.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agents.config import DEFAULT_MODEL_MINI
from app.services.token_usage_service import TokenUsageService


class NormalizedDocxText(BaseModel):
    """Saída de normalização para exportação em DOCX."""

    normalized_text: str = Field(
        description=(
            "Texto final normalizado para DOCX, preservando integralmente o conteúdo jurídico. "
            "Pode usar marcações simples em Markdown (#, ##, ###, ---)."
        )
    )


_SYSTEM_PROMPT = (
    "Você normaliza textos jurídicos para exportação DOCX. "
    "Preserve conteúdo e sentido jurídico integralmente, sem resumir nem omitir seções. "
    "Apenas padronize quebras de linha, títulos e legibilidade. "
    "Nunca altere pedidos, fundamentos, valores, NBs, NITs, CNPJs ou números processuais. "
    "Preserve tabelas markdown com pipes exatamente como tabelas estruturadas."
)

_BOLD_MARKDOWN_RE = re.compile(r"(\*\*([^*]+)\*\*|__([^_]+)__)" )
_PLAIN_HEADING_RE = re.compile(
    r"^(?:"
    r"(?:[IVXLCDM]{1,8}|\d+(?:\.\d+)*)\.\s+[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ0-9][A-ZÁÉÍÓÚÀÂÊÔÃÕÇ0-9\s\-/,&().]{2,}"
    r"|"
    r"[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ0-9][A-ZÁÉÍÓÚÀÂÊÔÃÕÇ0-9\s\-/,&().]{3,}"
    r")$"
)


class OfficeDocxExportAgent:
    """Padroniza texto e exporta DOCX com template do escritório."""

    def __init__(self, model_name: Optional[str] = None, temperature: float = 0.0):
        self.model_name = model_name or os.getenv("DOCX_EXPORT_NORMALIZER_MODEL", DEFAULT_MODEL_MINI)
        self.temperature = temperature
        self.token_usage_service = TokenUsageService()

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parents[3]

    @classmethod
    def _template_path(cls) -> Path:
        return cls._project_root() / "templates_padrao" / "modelo_documento.docx"

    @staticmethod
    def _pick_style(style_names: list[str], candidates: list[str]) -> str | None:
        for candidate in candidates:
            if candidate in style_names:
                return candidate
        return None

    @staticmethod
    def _strip_heading_number(text: str) -> str:
        value = str(text or "").strip()
        value = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", value)
        return value.strip()

    @staticmethod
    def _normalize_md_emphasis(text: str) -> str:
        value = str(text or "")
        value = value.replace("**", "")
        value = value.replace("__", "")
        return value

    @classmethod
    def _is_plain_heading(cls, line: str) -> bool:
        value = str(line or "").strip()
        if not value or len(value) > 120:
            return False
        if value.startswith(("-", "*", ">", "|")):
            return False
        if value.startswith("RECURSO:"):
            return True
        if re.fullmatch(r"(?:[IVXLCDM]{1,8}|\d+(?:\.\d+)*)\.\s+.+", value):
            return True
        if value.isupper() and _PLAIN_HEADING_RE.fullmatch(value):
            return True
        return False

    @staticmethod
    def _is_table_row(line: str) -> bool:
        stripped = str(line or "").strip()
        return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2

    @staticmethod
    def _parse_table_cells(line: str) -> list[str]:
        stripped = str(line or "").strip().strip("|")
        return [cell.strip() for cell in stripped.split("|")]

    @staticmethod
    def _is_separator_row(line: str) -> bool:
        stripped = str(line or "").strip()
        return bool(re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", stripped))

    def _flush_markdown_table(self, doc, table_rows: list[list[str]], body_style: str | None) -> None:
        if not table_rows:
            return

        max_cols = max(len(row) for row in table_rows)
        if max_cols == 0:
            return

        table = doc.add_table(rows=len(table_rows), cols=max_cols)
        table.style = "Table Grid" if "Table Grid" in [s.name for s in doc.styles] else table.style

        for row_index, row_values in enumerate(table_rows):
            for col_index in range(max_cols):
                cell = table.rows[row_index].cells[col_index]
                cell_text = row_values[col_index] if col_index < len(row_values) else ""
                cell.text = self._normalize_md_emphasis(cell_text)
                for paragraph in cell.paragraphs:
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if row_index == 0 else WD_ALIGN_PARAGRAPH.LEFT
                    for run in paragraph.runs:
                        run.font.name = "Segoe UI"
                        run.font.size = Pt(10)
                        if row_index == 0:
                            run.bold = True

        doc.add_paragraph("")

    def _append_plain_line(self, doc, line: str, body_style: str | None) -> None:
        line = self._normalize_md_emphasis(line)
        if body_style:
            p = doc.add_paragraph(line, style=body_style)
        else:
            p = doc.add_paragraph(line)
            run = p.runs[0] if p.runs else p.add_run(line)
            run.font.name = "Segoe UI"
            run.font.size = Pt(11)
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    def _append_rich_line(self, doc, line: str, body_style: str | None) -> None:
        paragraph = doc.add_paragraph(style=body_style) if body_style else doc.add_paragraph()
        paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

        text = str(line or "")
        cursor = 0
        has_content = False

        for match in _BOLD_MARKDOWN_RE.finditer(text):
            before = text[cursor:match.start()]
            if before:
                run = paragraph.add_run(before)
                run.font.name = "Segoe UI"
                run.font.size = Pt(11)
                has_content = True

            bold_text = match.group(2) or match.group(3) or ""
            if bold_text:
                run = paragraph.add_run(bold_text)
                run.font.name = "Segoe UI"
                run.font.size = Pt(11)
                run.bold = True
                has_content = True

            cursor = match.end()

        remaining = text[cursor:]
        if remaining or not has_content:
            run = paragraph.add_run(remaining if remaining else text)
            run.font.name = "Segoe UI"
            run.font.size = Pt(11)

        return paragraph

    def _append_heading(self, doc, heading: str, level: int, title_style: str | None, subtitle_style: str | None):
        clean_heading = self._normalize_md_emphasis(self._strip_heading_number(heading))

        if level == 1:
            if title_style:
                paragraph = doc.add_paragraph(clean_heading, style=title_style)
            else:
                paragraph = doc.add_heading(clean_heading, level=1)
            target_size = 16
        else:
            if subtitle_style:
                paragraph = doc.add_paragraph(clean_heading, style=subtitle_style)
            else:
                paragraph = doc.add_heading(clean_heading, level=2)
            target_size = 13

        if not paragraph.runs:
            paragraph.add_run(clean_heading)

        for run in paragraph.runs:
            run.font.name = "Segoe UI"
            run.font.size = Pt(target_size)
            run.bold = True

        paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        return paragraph

    def _normalize_for_docx(self, document_title: str, document_text: str, law_firm_id: Optional[int] = None) -> str:
        """Normaliza o texto com LLM mini. Em falha, retorna texto original."""
        source_text = str(document_text or "").strip()
        if not source_text:
            return ""

        llm = ChatOpenAI(
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=8_000,
        ).with_structured_output(NormalizedDocxText, include_raw=True)

        user_prompt = (
            "Normalize o texto abaixo para exportação em DOCX.\n"
            "Regras:\n"
            "- Preserve todo o conteúdo jurídico.\n"
            "- Não resuma, não corte, não invente.\n"
            "- Pode manter títulos em markdown (#, ##, ###) e separadores (---).\n"
            "- Remova apenas ruído de formatação e quebras excessivas.\n\n"
            f"Título do documento: {document_title}\n\n"
            "=== TEXTO ORIGINAL ===\n"
            f"{source_text}"
        )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        started = time.perf_counter()
        raw_message = None
        try:
            output = llm.invoke(messages)
            raw_message = output.get("raw") if isinstance(output, dict) else None
            parsed = output.get("parsed") if isinstance(output, dict) else None
            normalized = str(getattr(parsed, "normalized_text", "") or "").strip()
            return normalized or source_text
        except Exception:
            return source_text
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            try:
                self.token_usage_service.capture_and_store(
                    response_payload={"messages": [raw_message]} if raw_message is not None else None,
                    agent_name="OfficeDocxExportAgent",
                    action_name="normalize_for_docx",
                    print_prefix="[OfficeDocxExportAgent][TokenUsage]",
                    model_name=self.model_name,
                    model_provider="openai",
                    law_firm_id=law_firm_id,
                    latency_ms=elapsed_ms,
                    status="success" if raw_message is not None else "error",
                    metadata_payload={"document_title": document_title[:120]},
                )
            except Exception:
                pass

    def _render_docx_with_template(self, document_title: str, document_text: str) -> BytesIO:
        template_path = self._template_path()

        if template_path.exists():
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                temp_path = Path(tmp.name)
            try:
                shutil.copy2(str(template_path), str(temp_path))
                doc = Document(str(temp_path))
            finally:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
        else:
            doc = Document()
            for section in doc.sections:
                section.top_margin = Inches(1)
                section.bottom_margin = Inches(1)
                section.left_margin = Inches(1.25)
                section.right_margin = Inches(1.25)

        style_names = [style.name for style in doc.styles if style.type == 1]
        title_style = self._pick_style(style_names, ["Título", "Titulo", "Heading 1", "Título 1"])
        subtitle_style = self._pick_style(style_names, ["Título 2", "Titulo 2", "Heading 2", "Subtítulo"])
        body_style = self._pick_style(style_names, ["Corpo de Texto", "Corpo de texto", "Normal", "Body Text"])

        for _ in range(len(doc.paragraphs)):
            paragraph = doc.paragraphs[0]
            paragraph._element.getparent().remove(paragraph._element)

        if title_style:
            title_paragraph = doc.add_paragraph(str(document_title or "DOCUMENTO GERADO").upper(), style=title_style)
        else:
            title_paragraph = doc.add_paragraph()
            title_run = title_paragraph.add_run(str(document_title or "DOCUMENTO GERADO").upper())
            title_run.font.name = "Segoe UI"
            title_run.font.size = Pt(16)
            title_run.bold = True
        if not title_paragraph.runs:
            title_paragraph.add_run(str(document_title or "DOCUMENTO GERADO").upper())
        for run in title_paragraph.runs:
            run.font.name = "Segoe UI"
            run.font.size = Pt(16)
            run.bold = True
        title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

        text = str(document_text or "")
        lines = text.splitlines()
        pending_table: list[list[str]] = []
        in_table = False

        def flush_table() -> None:
            nonlocal pending_table, in_table
            if pending_table:
                self._flush_markdown_table(doc, pending_table, body_style)
            pending_table = []
            in_table = False

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                flush_table()
                doc.add_paragraph("")
                continue

            if self._is_separator_row(line):
                continue

            if self._is_table_row(line):
                cells = self._parse_table_cells(line)
                if cells:
                    pending_table.append(cells)
                    in_table = True
                continue

            flush_table()

            if line.startswith("# "):
                self._append_heading(doc, line[2:].strip(), level=1, title_style=title_style, subtitle_style=subtitle_style)
                continue

            if line.startswith("## ") or line.startswith("### "):
                heading = line[3:].strip() if line.startswith("## ") else line[4:].strip()
                self._append_heading(doc, heading, level=2, title_style=title_style, subtitle_style=subtitle_style)
                continue

            if self._is_plain_heading(line):
                heading_level = 1 if line.upper().startswith("RECURSO:") else 2
                self._append_heading(doc, line, level=heading_level, title_style=title_style, subtitle_style=subtitle_style)
                continue

            if line.startswith("---"):
                p = doc.add_paragraph("_" * 60)
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                continue

            if "**" in line or "__" in line:
                self._append_rich_line(doc, line, body_style)
            else:
                self._append_plain_line(doc, line, body_style)

        flush_table()

        output = BytesIO()
        doc.save(output)
        output.seek(0)
        return output

    def export_generated_document(
        self,
        *,
        document_title: str,
        document_text: str,
        run_ai_normalization: bool = True,
        law_firm_id: Optional[int] = None,
    ) -> BytesIO:
        """Exporta documento gerado para DOCX no padrão do escritório."""
        text = str(document_text or "")
        if run_ai_normalization:
            text = self._normalize_for_docx(
                document_title=document_title,
                document_text=text,
                law_firm_id=law_firm_id,
            )
        return self._render_docx_with_template(document_title=document_title, document_text=text)

    def export_appeal_content(
        self,
        *,
        appeal_content: dict,
        run_ai_normalization: bool = True,
        law_firm_id: Optional[int] = None,
    ) -> BytesIO:
        """Converte payload estruturado de recurso em DOCX no padrão do escritório."""
        appeal_type = str(appeal_content.get("appeal_type") or "RECURSO JUDICIAL").strip()
        sections: list[str] = [f"# {appeal_type}"]

        if appeal_content.get("introduction"):
            sections.append("## I. INTRODUÇÃO")
            sections.append(str(appeal_content["introduction"]))

        if appeal_content.get("facts"):
            sections.append("## II. DOS FATOS")
            sections.append(str(appeal_content["facts"]))

        if appeal_content.get("grounds"):
            sections.append("## III. DOS FUNDAMENTOS")
            sections.append(str(appeal_content["grounds"]))

        if appeal_content.get("jurisprudence"):
            sections.append("## IV. DA JURISPRUDÊNCIA")
            sections.append(str(appeal_content["jurisprudence"]))

        section_num = 5
        for section in appeal_content.get("additional_sections", []) or []:
            title = str(section.get("title") or "SEÇÃO ADICIONAL").strip().upper()
            content = str(section.get("content") or "").strip()
            if content:
                sections.append(f"## {section_num}. {title}")
                sections.append(content)
                section_num += 1

        if appeal_content.get("requests"):
            sections.append(f"## {section_num}. DOS PEDIDOS")
            sections.append(str(appeal_content["requests"]))

        if appeal_content.get("conclusion"):
            sections.append("## CONCLUSÃO")
            sections.append(str(appeal_content["conclusion"]))

        merged_text = "\n\n".join(part for part in sections if part)
        return self.export_generated_document(
            document_title=appeal_type,
            document_text=merged_text,
            run_ai_normalization=run_ai_normalization,
            law_firm_id=law_firm_id,
        )
