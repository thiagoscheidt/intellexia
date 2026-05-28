"""Agente para padronizar e exportar documentos para DOCX no padrão do escritório.

Responsabilidades:
1. (Opcional) Normalizar o texto do documento com LLM mini para reduzir ruído de formatação.
2. Aplicar template templates_padrao/modelo_documento.docx (cabeçalho/rodapé/margens).
3. Gerar stream DOCX pronto para download.
"""

from __future__ import annotations

import os
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
    "Nunca altere pedidos, fundamentos, valores, NBs, NITs, CNPJs ou números processuais."
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
        title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

        text = str(document_text or "")
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                doc.add_paragraph("")
                continue

            if line.startswith("# "):
                heading = line[2:].strip()
                if title_style:
                    p = doc.add_paragraph(heading, style=title_style)
                else:
                    p = doc.add_heading(heading, level=1)
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                continue

            if line.startswith("## ") or line.startswith("### "):
                heading = line[3:].strip() if line.startswith("## ") else line[4:].strip()
                if subtitle_style:
                    p = doc.add_paragraph(heading, style=subtitle_style)
                else:
                    p = doc.add_heading(heading, level=2)
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                continue

            if line.startswith("---"):
                p = doc.add_paragraph("_" * 60)
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                continue

            if body_style:
                p = doc.add_paragraph(line, style=body_style)
            else:
                p = doc.add_paragraph(line)
                run = p.runs[0] if p.runs else p.add_run(line)
                run.font.name = "Segoe UI"
                run.font.size = Pt(11)
            p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

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
