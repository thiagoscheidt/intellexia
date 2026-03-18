import re
import os
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional, List
from rich import print

from dotenv import load_dotenv
from markitdown import MarkItDown
from pydantic import BaseModel, Field
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.services.token_usage_service import TokenUsageService


load_dotenv()


class DocumentExtractionResult(BaseModel):
    process_number: str = Field(default="", description="Número do processo, se encontrado")
    judicial_court: str = Field(default="", description="Vara/juízo/tribunal identificado")
    active_pole: str = Field(default="", description="Polo ativo identificado")
    passive_pole: str = Field(default="", description="Polo passivo identificado")
    suggested_category: str = Field(default="", description="Categoria sugerida para o documento")
    suggested_document_type_key: str = Field(default="", description="Chave do tipo sugerido")
    suggested_document_type_name: str = Field(default="", description="Nome do tipo sugerido")
    classe: str | None = Field(default=None, description="Classe processual (ex: PROCEDIMENTO COMUM CÍVEL). Null se não encontrado com certeza.")
    valor_causa: str | None = Field(default=None, description="Valor da causa conforme consta no documento (ex: R$ 100.000,00). Null se não encontrado com certeza.")
    assuntos: list[str] | None = Field(default=None, description="Lista de assuntos do processo (ex: ['Seguro Acidentes do Trabalho']). Null se não encontrado com certeza.")
    segredo_justica: bool | None = Field(default=None, description="Segredo de justiça: true=SIM, false=NÃO. Null se não encontrado com certeza.")
    justica_gratuita: bool | None = Field(default=None, description="Justiça gratuita concedida/requerida: true=SIM, false=NÃO. Null se não encontrado com certeza.")
    liminar_tutela: bool | None = Field(default=None, description="Pedido de liminar ou antecipação de tutela: true=SIM, false=NÃO. Null se não encontrado com certeza.")


class BenefitRequestItem(BaseModel):
    """Modelo simplificado para benefício extraído de tabelas."""
    benefit_number: str = Field(default="", description="Número do benefício (NB)")
    nit_number: str = Field(default="", description="Número do NIT")
    insured_name: str = Field(default="", description="Nome do segurado")
    benefit_type: str = Field(default="", description="Tipo do benefício (B91, B92, B93, B94, etc)")
    fap_vigencia_year: str = Field(default="", description="Ano(s) da vigência do FAP em CSV (ex: 2018,2019,2020)")
    legal_thesis_id: int | None = Field(default=None, description="ID da tese jurídica associada à seção da tabela")


class BenefitsRequestsExtractionResult(BaseModel):
    """Modelo para resultado da extração de benefícios nas tabelas/pedidos."""
    benefits: List[BenefitRequestItem] = Field(default_factory=list, description="Lista de benefícios identificados")

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True)


class BenefitRequestTypeItem(BaseModel):
    """Classificação do tipo de pedido para um benefício."""
    benefit_number: str = Field(default="", description="Número do benefício (NB)")
    request_type: str = Field(
        default="",
        description="Tipo de pedido: 'exclusao', 'inclusao' ou 'revisao'",
    )


class BenefitRequestTypeClassificationResult(BaseModel):
    """Resultado da classificação de tipos de pedido dos benefícios."""
    benefits: List[BenefitRequestTypeItem] = Field(
        default_factory=list,
        description="Lista de benefícios com seu tipo de pedido classificado",
    )

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True)


class AgentDocumentExtractor:
    """Extrai dados de documentos jurídicos reutilizando texto e vetor já processados."""

    def __init__(
        self,
        model_name: str = "gpt-5-mini",
        model_provider: str | None = None,
        chunk_size: int = 1800,
        chunk_overlap: int = 150,
        file_id: int | None = None,
        file_path: str | Path | None = None,
        law_firm_id: int | None = None,
        document_data: Any | None = None,
        document_faiss_vector: Any | None = None,
    ):
        self.model_name = model_name
        self.model_provider = model_provider or os.getenv("DOCUMENT_EXTRACTOR_MODEL_PROVIDER", "openai")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.file_id = file_id
        self.file_path = file_path
        self.law_firm_id = law_firm_id
        self.document_data = document_data
        self.document_faiss_vector = document_faiss_vector
        self.chat_model = ChatOpenAI(
            model=self.model_name,
            temperature=0,
        )
        self.token_usage_service = TokenUsageService()

    def _build_extraction_agent(self):
        return create_agent(
            model=self.chat_model,
            tools=[],
            system_prompt="Você é um extrator de dados jurídicos. Retorne apenas os campos solicitados.",
            response_format=ToolStrategy(DocumentExtractionResult),
        )

    def _build_benefits_extraction_agent(self):
        return create_agent(
            model=self.chat_model,
            tools=[],
            system_prompt=(
                "Você é um assistente jurídico especializado em processos previdenciários "
                "e revisão de FAP. Extraia benefícios de tabelas, mapeando autonomamente "
                "as colunas com base em seus nomes e significados."
            ),
            response_format=ToolStrategy(BenefitsRequestsExtractionResult),
        )

    def _build_benefit_request_type_agent(self):
        return create_agent(
            model=self.chat_model,
            tools=[],
            system_prompt=(
                "Você é um assistente jurídico especializado em processos previdenciários e FAP. "
                "Sua tarefa é classificar o tipo de pedido feito em relação a cada benefício "
                "mencionado na petição. Os tipos possíveis são:\n"
                "- 'exclusao': o autor pede para excluir o benefício do cálculo do FAP\n"
                "- 'inclusao': o autor pede para incluir o benefício no cálculo do FAP\n"
                "- 'revisao': o autor pede revisão/recálculo do benefício sem indicar exclusão ou inclusão\n"
                "Retorne apenas os campos solicitados."
            ),
            response_format=ToolStrategy(BenefitRequestTypeClassificationResult),
        )

    def _extract_text(self, file_path: str | Path | None = None) -> str:
        text_from_document_data = self._get_document_data_full_text()
        if text_from_document_data:
            return text_from_document_data

        if not file_path:
            return ""

        markdown = MarkItDown()
        result = markdown.convert(str(file_path))
        return (result.text_content or "").strip()

    def _get_document_data_full_text(self) -> str:
        if self.document_data is None:
            return ""

        if isinstance(self.document_data, dict):
            return str(self.document_data.get("full_text", "") or "").strip()

        return str(getattr(self.document_data, "full_text", "") or "").strip()

    @staticmethod
    def _estimate_vector_chunks_count(vectorstore: Any) -> int:
        if vectorstore is None:
            return 0

        try:
            if hasattr(vectorstore, "index") and hasattr(vectorstore.index, "ntotal"):
                return int(vectorstore.index.ntotal)
        except Exception:
            pass

        try:
            if hasattr(vectorstore, "docstore") and hasattr(vectorstore.docstore, "_dict"):
                return int(len(vectorstore.docstore._dict))
        except Exception:
            pass

        return 0

    def _initial_chunks_context(
        self,
        text: str,
        max_chunks: int = 6,
        max_chars: int = 8000,
    ) -> str:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        documents = splitter.create_documents([text])
        if not documents:
            return ""

        initial_text = "\n\n---CHUNK INICIAL---\n\n".join(
            doc.page_content for doc in documents[:max_chunks]
        )
        return initial_text[:max_chars]

    def _semantic_search(self, vectorstore, query: str, k: int = 6) -> str:
        if vectorstore is None:
            return ""

        try:
            results = vectorstore.similarity_search(query, k=k)
            if not results:
                return ""
            return "\n\n---TRECHO RELEVANTE---\n\n".join(r.page_content for r in results)
        except Exception:
            return ""

    def _normalize_document_types(self, judicial_document_types: list[Any] | None) -> list[dict[str, str]]:
        if not judicial_document_types:
            return []

        normalized: list[dict[str, str]] = []
        for item in judicial_document_types:
            if isinstance(item, dict):
                normalized.append(
                    {
                        "key": str(item.get("key", "") or "").strip(),
                        "name": str(item.get("name", "") or "").strip(),
                        "phase": str(item.get("phase", "") or "").strip(),
                    }
                )
                continue

            key = str(getattr(item, "key", "") or "").strip()
            name = str(getattr(item, "name", "") or "").strip()
            phase_name = ""
            phase_obj = getattr(item, "phase", None)
            if phase_obj is not None:
                phase_name = str(getattr(phase_obj, "name", "") or "").strip()

            normalized.append({"key": key, "name": name, "phase": phase_name})

        return [d for d in normalized if d["key"] or d["name"]]

    def _load_document_types_from_db(self, law_firm_id: int | None = None) -> list[dict[str, str]]:
        try:
            from app.models import JudicialDocumentType, JudicialPhase

            query = JudicialDocumentType.query.filter_by(is_active=True)
            if law_firm_id is not None:
                query = query.filter_by(law_firm_id=law_firm_id)

            items = query.join(
                JudicialPhase,
                JudicialPhase.id == JudicialDocumentType.phase_id,
            ).order_by(
                JudicialPhase.display_order.asc(),
                JudicialDocumentType.display_order.asc(),
                JudicialDocumentType.name.asc(),
            ).all()

            return self._normalize_document_types(items)
        except Exception:
            return []

    def _normalize_categories(self, knowledge_categories: list[Any] | None) -> list[str]:
        if not knowledge_categories:
            return []

        normalized: list[str] = []
        for item in knowledge_categories:
            if isinstance(item, dict):
                name = str(item.get("name", "") or "").strip()
            else:
                name = str(getattr(item, "name", "") or "").strip()

            if name:
                normalized.append(name)

        return normalized

    def _load_categories_from_db(self, law_firm_id: int | None = None) -> list[str]:
        try:
            from app.models import KnowledgeCategory

            query = KnowledgeCategory.query.filter_by(is_active=True)
            if law_firm_id is not None:
                query = query.filter_by(law_firm_id=law_firm_id)

            items = query.order_by(
                KnowledgeCategory.display_order.asc(),
                KnowledgeCategory.name.asc(),
            ).all()

            return self._normalize_categories(items)
        except Exception:
            return []

    def _load_legal_theses_from_db(self, law_firm_id: int | None = None) -> list[dict[str, str | int]]:
        try:
            from app.models import JudicialLegalThesis

            query = JudicialLegalThesis.query.filter_by(is_active=True)
            if law_firm_id is not None:
                query = query.filter_by(law_firm_id=law_firm_id)

            items = query.order_by(JudicialLegalThesis.name.asc()).all()
            return [
                {
                    "id": int(item.id),
                    "key": str(item.key or "").strip(),
                    "name": str(item.name or "").strip(),
                    "description": str(item.description or "").strip(),
                }
                for item in items
            ]
        except Exception:
            return []

    def _fallback_from_regex(self, text: str) -> DocumentExtractionResult:
        process_number_pattern = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
        process_number = ""
        match = process_number_pattern.search(text)
        if match:
            process_number = match.group(0)

        court_match = re.search(r"(?im)^(.*vara.*)$", text)
        judicial_court = court_match.group(1).strip() if court_match else ""

        active_match = re.search(r"(?im)(polo\s+ativo|autor(?:a)?):?\s*(.+)", text)
        passive_match = re.search(r"(?im)(polo\s+passivo|r[eé]u):?\s*(.+)", text)

        active_pole = active_match.group(2).strip() if active_match else ""
        passive_pole = passive_match.group(2).strip() if passive_match else ""

        return DocumentExtractionResult(
            process_number=process_number,
            judicial_court=judicial_court,
            active_pole=active_pole,
            passive_pole=passive_pole,
            suggested_category="",
            suggested_document_type_key="",
            suggested_document_type_name="",
            classe=None,
            valor_causa=None,
            assuntos=None,
            segredo_justica=None,
            justica_gratuita=None,
            liminar_tutela=None,
        )

    def _get_document_data_tables(self) -> list[dict]:
        if self.document_data is None:
            return []

        raw_tables: Any = []
        if isinstance(self.document_data, dict):
            raw_tables = self.document_data.get("tables", []) or []
        else:
            raw_tables = getattr(self.document_data, "tables", []) or []

        if not isinstance(raw_tables, list):
            return []

        normalized_tables: list[dict] = []
        for item in raw_tables:
            if not isinstance(item, dict):
                continue
            page = item.get("page")
            section = item.get("section")
            text_value = item.get("text")

            if isinstance(text_value, list):
                rows = [str(row).strip() for row in text_value if str(row).strip()]
            elif isinstance(text_value, str):
                rows = [line.strip() for line in text_value.splitlines() if line.strip()]
            else:
                rows = []

            if not rows:
                continue

            rows = self._normalize_table_rows_with_carryover(rows)

            normalized_tables.append(
                {
                    "page": page,
                    "section": str(section).strip() if section else "",
                    "rows": rows,
                }
            )

        return normalized_tables

    def _filter_out_pedidos_section(self, tables: list[dict]) -> list[dict]:
        """Remove tabelas de pedidos e filtra benefícios de outras seções por NB presente em pedidos."""
        benefit_text_keywords = (
            "vigência",
            "vigencia",
            "fap",
            "nit",
            "segurado",
            "beneficiário",
            "beneficiario",
            "nb",
        )
        benefit_type_re = re.compile(r"\bb\d{2}\b", re.IGNORECASE)
        normalized_keywords = tuple(self._normalize_text_token(k) for k in benefit_text_keywords)
        benefit_number_re = re.compile(r"\b\d{9,11}\b")

        def _extract_row_benefit_numbers(row: str) -> set[str]:
            numbers: set[str] = set()
            for raw_number in benefit_number_re.findall(str(row or "")):
                digits = re.sub(r"\D", "", raw_number)
                if len(digits) >= 9:
                    numbers.add(digits)
            return numbers

        pedidos_benefit_numbers: set[str] = set()
        non_pedidos_tables: list[dict] = []

        for table in tables:
            section_raw = str(table.get("section") or "").strip()
            section = self._normalize_text_token(section_raw)
            rows = table.get("rows", [])

            is_pedidos_section = bool(re.search(r"\bpedidos\b", section))
            if is_pedidos_section:
                table_text = self._normalize_text_token("\n".join(str(row) for row in rows))
                has_benefit_content = (
                    any(keyword in table_text for keyword in normalized_keywords)
                    or bool(benefit_type_re.search(table_text))
                )
                if has_benefit_content:
                    for row in rows[1:]:
                        pedidos_benefit_numbers.update(_extract_row_benefit_numbers(str(row)))
                continue

            non_pedidos_tables.append(table)

        filtered_tables: list[dict] = []
        for table in non_pedidos_tables:
            rows = table.get("rows", [])
            if not rows:
                continue

            # Se não houver seção de pedidos identificada, mantém comportamento atual.
            if not pedidos_benefit_numbers:
                filtered_tables.append(table)
                continue

            header = str(rows[0])
            kept_rows = [header]
            for row in rows[1:]:
                row_numbers = _extract_row_benefit_numbers(str(row))
                if not row_numbers:
                    continue
                if row_numbers.intersection(pedidos_benefit_numbers):
                    kept_rows.append(str(row))

            if len(kept_rows) > 1:
                filtered_table = dict(table)
                filtered_table["rows"] = kept_rows
                filtered_tables.append(filtered_table)

        return filtered_tables

    def _tables_to_prompt_text(self, tables: list[dict]) -> str:
        blocks: list[str] = []
        for table in tables:
            page = table.get("page")
            section = table.get("section")
            rows = table.get("rows", [])
            if not rows:
                continue

            header_parts = []
            if page is not None:
                header_parts.append(f"Página {page}")
            if section:
                header_parts.append(f"Seção: {section}")
            if header_parts:
                blocks.append(f"[{' | '.join(header_parts)}]")

            blocks.extend(rows)
            blocks.append("")
        return "\n".join(blocks).strip()

    @staticmethod
    def _normalize_text_token(value: str) -> str:
        text = str(value or "").strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return text

    @staticmethod
    def _split_pipe_row(row: str) -> list[str]:
        return [cell.strip() for cell in str(row).split("|")]

    @staticmethod
    def _looks_like_cnpj(value: str) -> bool:
        digits = re.sub(r"\D", "", str(value or ""))
        return len(digits) == 14

    @staticmethod
    def _looks_like_nit(value: str) -> bool:
        digits = re.sub(r"\D", "", str(value or ""))
        return len(digits) == 11

    @staticmethod
    def _looks_like_benefit_type(value: str) -> bool:
        return bool(re.fullmatch(r"B\d{2}", str(value or "").strip().upper()))

    @staticmethod
    def _looks_like_benefit_number(value: str) -> bool:
        digits = re.sub(r"\D", "", str(value or ""))
        return len(digits) >= 9

    @staticmethod
    def _looks_like_year(value: str) -> bool:
        return bool(re.fullmatch(r"\d{4}", str(value or "").strip()))

    @staticmethod
    def _looks_like_date(value: str) -> bool:
        return bool(re.fullmatch(r"\d{2}/\d{2}/\d{4}", str(value or "").strip()))

    @staticmethod
    def _looks_like_name_or_company(value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        if AgentDocumentExtractor._looks_like_benefit_type(text):
            return False
        if re.fullmatch(r"\d+", re.sub(r"\D", "", text) or ""):
            return False
        return bool(re.search(r"[A-Za-zÀ-ÿ]", text))

    def _guess_header_indexes(self, header_cells: list[str]) -> dict[str, int]:
        indexes: dict[str, int] = {}
        for idx, raw_cell in enumerate(header_cells):
            cell = self._normalize_text_token(raw_cell)
            if not cell:
                continue

            if "item" in cell and "item" not in indexes:
                indexes["item"] = idx
            elif "vig" in cell and "vigencia" not in indexes:
                indexes["vigencia"] = idx
            elif "cnpj" in cell and "cnpj" not in indexes:
                indexes["cnpj"] = idx
            elif ("empregado" in cell or "segurado" in cell or "beneficiario" in cell) and "empregado" not in indexes:
                indexes["empregado"] = idx
            elif cell == "nit" and "nit" not in indexes:
                indexes["nit"] = idx
            elif "tipo" in cell and "tipo" not in indexes:
                indexes["tipo"] = idx
            elif ("beneficio" in cell or cell == "nb") and "beneficio" not in indexes:
                indexes["beneficio"] = idx
            elif ("acidente" in cell and "data" in cell) and "data_acidente" not in indexes:
                indexes["data_acidente"] = idx

        return indexes

    def _normalize_table_rows_with_carryover(self, rows: list[str]) -> list[str]:
        """Normaliza linhas pipe-delimited aplicando carry-over para colunas mescladas."""
        if not rows or "|" not in rows[0]:
            return rows

        header_cells = self._split_pipe_row(rows[0])
        if len(header_cells) < 5:
            return rows

        indexes = self._guess_header_indexes(header_cells)
        if not indexes:
            return rows

        row_len = len(header_cells)
        carryover = {
            "cnpj": "",
            "empregado": "",
            "nit": "",
            "data_acidente": "",
        }

        normalized_rows: list[str] = [" | ".join(header_cells)]
        for raw_row in rows[1:]:
            if "|" not in raw_row:
                normalized_rows.append(raw_row)
                continue

            cells = self._split_pipe_row(raw_row)
            if len(cells) < row_len:
                cells.extend([""] * (row_len - len(cells)))
            elif len(cells) > row_len:
                cells = cells[:row_len]

            vig_idx = indexes.get("vigencia")
            cnpj_idx = indexes.get("cnpj")
            emp_idx = indexes.get("empregado")
            nit_idx = indexes.get("nit")
            tipo_idx = indexes.get("tipo")
            ben_idx = indexes.get("beneficio")
            date_idx = indexes.get("data_acidente")

            if vig_idx is not None and cnpj_idx is not None:
                vig_value = cells[vig_idx]
                cnpj_value = cells[cnpj_idx]
                if self._looks_like_year(vig_value) and self._looks_like_year(cnpj_value):
                    cells[vig_idx] = f"{vig_value},{cnpj_value}"
                    cells[cnpj_idx] = ""

            if tipo_idx is not None and (not cells[tipo_idx]):
                for probe_idx, probe in enumerate(cells):
                    if self._looks_like_benefit_type(probe):
                        cells[tipo_idx] = probe
                        if probe_idx != tipo_idx:
                            cells[probe_idx] = ""
                        break

            if ben_idx is not None and (not cells[ben_idx]):
                for probe_idx, probe in enumerate(cells):
                    if self._looks_like_benefit_number(probe):
                        cells[ben_idx] = probe
                        if probe_idx != ben_idx:
                            cells[probe_idx] = ""
                        break

            if cnpj_idx is not None:
                if cells[cnpj_idx] and self._looks_like_cnpj(cells[cnpj_idx]):
                    carryover["cnpj"] = cells[cnpj_idx]
                elif (not cells[cnpj_idx]) and carryover["cnpj"]:
                    cells[cnpj_idx] = carryover["cnpj"]

            if emp_idx is not None:
                if cells[emp_idx] and self._looks_like_name_or_company(cells[emp_idx]):
                    carryover["empregado"] = cells[emp_idx]
                elif (not cells[emp_idx]) and carryover["empregado"]:
                    cells[emp_idx] = carryover["empregado"]

            if nit_idx is not None:
                if cells[nit_idx] and self._looks_like_nit(cells[nit_idx]):
                    carryover["nit"] = cells[nit_idx]
                elif (not cells[nit_idx]) and carryover["nit"]:
                    cells[nit_idx] = carryover["nit"]

            if date_idx is not None:
                if cells[date_idx] and self._looks_like_date(cells[date_idx]):
                    carryover["data_acidente"] = cells[date_idx]
                elif (not cells[date_idx]) and carryover["data_acidente"]:
                    cells[date_idx] = carryover["data_acidente"]

            normalized_rows.append(" | ".join(cells))

        return normalized_rows

    def _postprocess_benefits_with_carryover(self, benefits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Preenche campos vazios no resultado extraído sem sobrescrever valores já informados."""
        if not benefits:
            return benefits

        last_values_by_thesis: dict[Any, dict[str, str]] = {}
        normalized: list[dict[str, Any]] = []

        for item in benefits:
            benefit = dict(item or {})
            thesis_key = benefit.get("legal_thesis_id")
            state = last_values_by_thesis.setdefault(thesis_key, {"nit": "", "insured_name": ""})

            current_nit = str(benefit.get("nit_number") or "").strip()
            current_name = str(benefit.get("insured_name") or "").strip()

            if not current_nit and state["nit"]:
                benefit["nit_number"] = state["nit"]
            elif self._looks_like_nit(current_nit):
                state["nit"] = current_nit

            if not current_name and state["insured_name"]:
                benefit["insured_name"] = state["insured_name"]
            elif self._looks_like_name_or_company(current_name):
                state["insured_name"] = current_name

            normalized.append(benefit)

        return normalized

    def extract_document_data(
        self,
        file_path: str | Path | None = None,
        judicial_document_types: list[Any] | None = None,
        knowledge_categories: list[Any] | None = None,
        law_firm_id: int | None = None,
    ) -> dict:
        effective_file_path = file_path or self.file_path
        effective_law_firm_id = law_firm_id if law_firm_id is not None else self.law_firm_id

        if not effective_file_path:
            raise ValueError("É necessário fornecer file_path no init ou em extract_document_data")

        text = self._extract_text(effective_file_path)
        if not text:
            return DocumentExtractionResult().model_dump()

        vectorstore = self.document_faiss_vector
        chunks_count = self._estimate_vector_chunks_count(vectorstore)

        normalized_types = self._normalize_document_types(judicial_document_types)
        if not normalized_types:
            normalized_types = self._load_document_types_from_db(law_firm_id=effective_law_firm_id)

        normalized_categories = self._normalize_categories(knowledge_categories)
        if not normalized_categories:
            normalized_categories = self._load_categories_from_db(law_firm_id=effective_law_firm_id)

        types_prompt = "\n".join(
            f"- key: {item['key']} | nome: {item['name']} | fase: {item['phase']}"
            for item in normalized_types
        ) or "(lista não informada)"

        categories_prompt = "\n".join(
            f"- {category_name}"
            for category_name in normalized_categories
        ) or "(lista não informada)"

        document_types_semantic_hint = "; ".join(
            filter(
                None,
                [
                    f"{item['name']} ({item['key']})" if item.get("key") else item.get("name", "")
                    for item in normalized_types
                ],
            )
        )
        doc_type_query = (
            "Que tipo de documento jurídico é este? "
            "Classifique priorizando estritamente os tipos cadastrados em JudicialDocumentType. "
            "Tipos disponíveis: "
            f"{document_types_semantic_hint}."
            if document_types_semantic_hint
            else "Que tipo de documento jurídico é este? petição inicial, contestação, sentença, recurso, despacho etc"
        )

        header_context = self._initial_chunks_context(
            text,
            max_chunks=6,
            max_chars=8000,
        )

        doc_type_context = self._semantic_search(
            vectorstore,
            doc_type_query,
        )[:6000]

        user_prompt = (
            "Você é um assistente especializado em análise de documentos jurídicos brasileiros.\n"
            "Analise o trecho do documento abaixo e extraia as informações estruturadas solicitadas.\n\n"
            "INSTRUÇÕES IMPORTANTES:\n"
            "- Utilize apenas as informações presentes no texto.\n"
            "- Se não encontrar um campo com segurança, retorne string vazia.\n"
            "- NÃO invente dados.\n\n"
            "EXTRAÇÃO DAS PARTES:\n"
            "- Para 'active_pole' identifique o AUTOR da ação (polo ativo).\n"
            "- Para 'passive_pole' identifique o RÉU da ação (polo passivo).\n"
            "- Retorne o NOME COMPLETO da pessoa, empresa ou órgão.\n"
            "- NÃO retorne apenas 'autor', 'autora', 'réu', 'ré', etc.\n\n"
            "Exemplos corretos:\n"
            "Autor: João da Silva\n"
            "Réu: Banco do Brasil S.A.\n\n"
            "Também podem aparecer termos equivalentes como:\n"
            "- requerente / requerido\n"
            "- impetrante / impetrado\n"
            "- exequente / executado\n"
            "- reclamante / reclamado\n\n"
            "NÚMERO DO PROCESSO:\n"
            "- Normalmente segue o padrão CNJ:\n"
            "0000000-00.0000.0.00.0000\n\n"
            "VARA / JUÍZO:\n"
            "- Pode aparecer como Vara, Juízo, Tribunal ou Seção Judiciária.\n\n"
            "CLASSE PROCESSUAL (classe):\n"
            "- Ex: PROCEDIMENTO COMUM CÍVEL, MANDADO DE SEGURANÇA, AÇÃO CIVIL PÚBLICA.\n"
            "- Retorne null se não encontrar com certeza.\n\n"
            "VALOR DA CAUSA (valor_causa):\n"
            "- Mantenha o formato original do documento (ex: R$ 100.000,00).\n"
            "- Retorne null se não encontrar com certeza.\n\n"
            "ASSUNTOS (assuntos):\n"
            "- Lista de assuntos/temas processuais presentes no cabeçalho do documento.\n"
            "- Ex: ['Seguro Acidentes do Trabalho', 'Acidente de Trabalho'].\n"
            "- Retorne null se não encontrar com certeza.\n\n"
            "SEGREDO DE JUSTIÇA (segredo_justica):\n"
            "- true = sim/sigiloso, false = não/público.\n"
            "- Retorne null se não encontrar com certeza.\n\n"
            "JUSTIÇA GRATUITA (justica_gratuita):\n"
            "- true = sim/requerida/deferida, false = não.\n"
            "- Retorne null se não encontrar com certeza.\n\n"
            "LIMINAR / TUTELA ANTECIPADA (liminar_tutela):\n"
            "- true = há pedido de liminar ou antecipação de tutela, false = não há.\n"
            "- Retorne null se não encontrar com certeza.\n\n"
            "TIPO DO DOCUMENTO:\n"
            "- Identifique o tipo do documento (ex: Petição Inicial, Contestação, Sentença).\n"
            "- Escolha apenas entre os tipos cadastrados abaixo.\n"
            "- Se não houver confiança suficiente, deixe vazio.\n\n"
            "CATEGORIA DO CONHECIMENTO:\n"
            "- Defina a categoria em suggested_category.\n"
            "- Escolha apenas entre as categorias cadastradas abaixo.\n"
            "- Se não houver confiança suficiente, deixe vazio.\n\n"
            "TIPOS CADASTRADOS (JudicialDocumentType):\n"
            f"{types_prompt}\n\n"
            "CATEGORIAS CADASTRADAS (KnowledgeCategory):\n"
            f"{categories_prompt}\n\n"
            "TRECHO DO DOCUMENTO:\n"
            f"{header_context}\n\n"
            "TRECHO SEMÂNTICO PARA TIPO/CATEGORIA:\n"
            f"{doc_type_context}\n\n"
            "Retorne o resultado no seguinte formato JSON:\n"
            "{\n"
            '  "process_number": "",\n'
            '  "judicial_court": "",\n'
            '  "active_pole": "",\n'
            '  "passive_pole": "",\n'
            '  "suggested_category": "",\n'
            '  "suggested_document_type_key": "",\n'
            '  "suggested_document_type_name": "",\n'
            '  "classe": null,\n'
            '  "valor_causa": null,\n'
            '  "assuntos": null,\n'
            '  "segredo_justica": null,\n'
            '  "justica_gratuita": null,\n'
            '  "liminar_tutela": null\n'
            "}"
        )

        try:
            extraction_agent = self._build_extraction_agent()
            call_started_at = time.time()
            response_payload = extraction_agent.invoke(
                {
                    "messages": [
                        {"role": "user", "content": user_prompt},
                    ]
                }
            )
            latency_ms = int((time.time() - call_started_at) * 1000)
            self.token_usage_service.capture_and_store(
                response_payload,
                agent_name="AgentDocumentExtractor",
                action_name="extract_document_data.create_agent",
                print_prefix="[AgentDocumentExtractor][extract_document_data][tokens]",
                model_name=self.model_name,
                model_provider=self.model_provider,
                latency_ms=latency_ms,
                status="success",
                metadata_payload={
                    "source_file": str(effective_file_path),
                    "file_id": self.file_id,
                    "chunks_count": chunks_count,
                },
            )
            structured_response = response_payload.get("structured_response")
            if not structured_response:
                raise RuntimeError("Resposta estruturada não retornada pelo agente")
            payload = structured_response.model_dump()
        except Exception:
            payload = self._fallback_from_regex(text).model_dump()

        payload["chunks_count"] = chunks_count
        payload["source_file"] = str(effective_file_path)
        return payload

    def extract_benefits_from_petition(
        self,
        file_path: Optional[str] = None,
        text_content: Optional[str] = None,
    ) -> dict:
        """
        Extrai benefícios usando as tabelas já presentes em document_data.
        Se não houver tabelas, retorna resultado vazio sem busca no vetor.
        """
        effective_file_path = file_path or (str(self.file_path) if self.file_path else None)
        effective_law_firm_id = self.law_firm_id

        tables = self._get_document_data_tables()
        tables = self._filter_out_pedidos_section(tables)
        if not tables:
            print("⚠ Nenhuma tabela encontrada em document_data.")
            return BenefitsRequestsExtractionResult().model_dump()

        legal_theses = self._load_legal_theses_from_db(law_firm_id=effective_law_firm_id)
        legal_theses_prompt = "\n".join(
            f"- id: {item['id']} | key: {item['key']} | nome: {item['name']} | descrição: {item['description']}"
            for item in legal_theses
        ) or "(lista não informada)"

        relevant_text = self._tables_to_prompt_text(tables)
        total_rows = sum(len(table.get("rows", [])) for table in tables)
        print(f"Tabelas detectadas em document_data: {len(tables)} tabelas / {total_rows} linhas")

        user_prompt = (
            "Extraia os benefícios previdenciários/acidentários das tabelas abaixo.\n\n"
            "INSTRUÇÕES PARA MAPEAMENTO DE COLUNAS:\n"
            "As tabelas podem ter estruturas diferentes. Você deve:\n"
            "1. Observar o header (primeira linha) de cada tabela para entender quais são as colunas\n"
            "2. Identificar as colunas relevantes por seu significado e nome, não por posição fixa\n"
            "3. Observar a seção informada no cabeçalho [Página X | Seção: ...] para mapear a tese jurídica\n"
            "4. Buscar pelas seguintes colunas (os nomes podem variar):\n"
            "   - VIGÊNCIA FAP, Vigência, Year, Ano, FAP, Período → para fap_vigencia_year\n"
            "   - NIT, NIT do Segurado → para nit_number\n"
            "   - SEGURADO, Empregado, Nome, Beneficiário, Titular → para insured_name\n"
            "   - TIPO, Tipo de Benefício, Código, B-type → para benefit_type (B01 a B99, ex: B31, B42, B91, B94)\n"
            "   - BENEFÍCIO, Nº Benefício, Número Benefício, NB → para benefit_number\n\n"
            "ATENÇÃO - VIGÊNCIA FAP: priorize SEMPRE a coluna da própria tabela para extrair fap_vigencia_year.\n"
            "A vigência pode vir como ano único, intervalo ou lista de anos.\n"
            "Formato obrigatório de saída para fap_vigencia_year: anos em CSV, separados por vírgula, sem espaços.\n"
            "Regras de normalização:\n"
            "  a) Ano único (ex: 2018) -> 2018\n"
            "  b) Intervalo (ex: 2018-2020, 2018 a 2020) -> 2018,2019,2020\n"
            "  c) Lista/sequência (ex: 2018/2019/2020 ou 2018, 2019 e 2020) -> 2018,2019,2020\n"
            "  d) Se não houver ano na tabela, deixe em branco\n\n"
            "TESES JURÍDICAS CADASTRADAS (use o id para preencher legal_thesis_id):\n"
            f"{legal_theses_prompt}\n\n"
            "PROCESSAMENTO:\n"
            "Para cada linha de dados da tabela, extraia os campos abaixo conforme seus nomes reais:\n"
            "- benefit_number: número do benefício\n"
            "- nit_number: número do NIT (11 dígitos)\n" 
            "- insured_name: nome completo do segurado/beneficiário\n"
            "- benefit_type: tipo do benefício (B91, B92, B93, B94, B31, B42, B46, etc)\n"
            "- fap_vigencia_year: ano(s) da vigência em CSV (ex: 2022,2023,2024)\n\n"
            "Mapeamento de tese:\n"
            "- legal_thesis_id: escolha APENAS um id da lista de teses cadastradas, de acordo com a seção da tabela.\n"
            "- Se não houver confiança suficiente para mapear, retorne null.\n\n"
            "Se não houver benefícios ou tabelas, retorne lista vazia em 'benefits'.\n"
            "Se algum campo não estiver disponível na tabela, deixe em branco (\"\").\n\n"
            f"TABELAS DA PETIÇÃO:\n\n{relevant_text}"
        )

        try:
            benefits_agent = self._build_benefits_extraction_agent()
            call_started_at = time.time()
            response_payload = benefits_agent.invoke(
                {
                    "messages": [
                        {"role": "user", "content": user_prompt},
                    ]
                }
            )
            latency_ms = int((time.time() - call_started_at) * 1000)
            self.token_usage_service.capture_and_store(
                response_payload,
                agent_name="AgentDocumentExtractor",
                action_name="extract_benefits_from_petition.create_agent",
                print_prefix="[AgentDocumentExtractor][extract_benefits][tokens]",
                model_name=self.model_name,
                model_provider=self.model_provider,
                latency_ms=latency_ms,
                status="success",
                metadata_payload={
                    "source_file": effective_file_path,
                    "file_id": self.file_id,
                    "tables_count": len(tables),
                    "table_rows_count": total_rows,
                },
            )
            structured_response = response_payload.get("structured_response")
            if not structured_response:
                raise RuntimeError("Resposta estruturada de benefícios não retornada pelo agente")
            result = structured_response.model_dump()
            result["benefits"] = self._postprocess_benefits_with_carryover(result.get("benefits", []))
            return result
        except Exception:
            return BenefitsRequestsExtractionResult().model_dump()

    def _get_document_data_chunks(self) -> list[dict]:
        if self.document_data is None:
            return []
        if isinstance(self.document_data, dict):
            return list(self.document_data.get("chunks_with_pages", []) or [])
        return list(getattr(self.document_data, "chunks_with_pages", []) or [])

    def _extract_pedidos_section_text(self) -> str:
        """
        Extrai o texto da seção de pedidos usando os dados já processados em document_data.

        Usa chunks_with_pages (filtrados por section='pedidos') e as tabelas da mesma seção,
        ambos já segmentados pelo DocumentProcessorService — sem regex no full_text.
        """
        parts: list[str] = []

        # Chunks de texto da seção de pedidos
        pedidos_chunks = [
            chunk for chunk in self._get_document_data_chunks()
            if re.search(r"\bpedidos\b", self._normalize_text_token(str(chunk.get("section") or "")))
        ]
        if pedidos_chunks:
            parts.append("\n\n".join(str(chunk.get("text", "")) for chunk in pedidos_chunks))

        # Tabelas da seção de pedidos
        pedidos_tables = [
            t for t in self._get_document_data_tables()
            if re.search(r"\bpedidos\b", self._normalize_text_token(str(t.get("section") or "")))
        ]
        if pedidos_tables:
            parts.append(self._tables_to_prompt_text(pedidos_tables))

        return "\n\n---\n\n".join(parts)[:10000]

    def classify_benefit_request_types(self, benefits: List[dict]) -> dict:
        """
        Classifica o tipo de pedido (exclusão, inclusão ou revisão) para cada benefício.

        O contexto é extraído diretamente da seção de pedidos já segmentada em
        document_data.chunks_with_pages e document_data.tables, sem releitura de arquivo
        ou busca semântica genérica.

        Args:
            benefits: Lista de dicts com pelo menos 'benefit_number'.

        Returns:
            Dict com estrutura de BenefitRequestTypeClassificationResult.
        """
        if not benefits:
            return BenefitRequestTypeClassificationResult().model_dump()

        pedidos_context = self._extract_pedidos_section_text()

        # Fallback: usa os últimos chunks do documento (pedidos aparecem no final da petição)
        if not pedidos_context:
            chunks = self._get_document_data_chunks()
            if chunks:
                last_chunks = chunks[-4:]
                pedidos_context = "\n\n".join(str(c.get("text", "")) for c in last_chunks)[:6000]

        benefits_list_text = "\n".join(
            f"- NB: {b.get('benefit_number', '')} | Tipo: {b.get('benefit_type', '')} | Segurado: {b.get('insured_name', '')}"
            for b in benefits
        )

        user_prompt = (
            "Com base no texto da seção de pedidos da petição abaixo, classifique o tipo de pedido feito para cada benefício.\n\n"
            "TIPOS DE PEDIDO POSSÍVEIS:\n"
            "- 'exclusao': o autor pede para EXCLUIR o benefício do cálculo do FAP\n"
            "- 'inclusao': o autor pede para INCLUIR o benefício no cálculo do FAP\n"
            "- 'revisao': revisão/recálculo sem indicar exclusão ou inclusão clara\n\n"
            "INSTRUÇÕES:\n"
            "- Analise o texto da seção de pedidos para identificar o que o autor pede para cada NB.\n"
            "- Retorne um item para CADA benefício da lista, mesmo que o tipo seja incerto (use 'revisao' como padrão).\n"
            "- O campo 'benefit_number' deve corresponder exatamente ao NB fornecido.\n\n"
            "BENEFÍCIOS A CLASSIFICAR:\n"
            f"{benefits_list_text}\n\n"
            "SEÇÃO DE PEDIDOS DA PETIÇÃO:\n"
            f"{pedidos_context}"
        )

        print(user_prompt)

        try:
            classification_agent = self._build_benefit_request_type_agent()
            call_started_at = time.time()
            response_payload = classification_agent.invoke(
                {
                    "messages": [
                        {"role": "user", "content": user_prompt},
                    ]
                }
            )
            latency_ms = int((time.time() - call_started_at) * 1000)
            self.token_usage_service.capture_and_store(
                response_payload,
                agent_name="AgentDocumentExtractor",
                action_name="classify_benefit_request_types.create_agent",
                print_prefix="[AgentDocumentExtractor][classify_benefit_request_types][tokens]",
                model_name=self.model_name,
                model_provider=self.model_provider,
                latency_ms=latency_ms,
                status="success",
                metadata_payload={
                    "file_id": self.file_id,
                    "benefits_count": len(benefits),
                },
            )
            structured_response = response_payload.get("structured_response")
            print(structured_response)
            if not structured_response:
                raise RuntimeError("Resposta estruturada não retornada pelo agente")
            return structured_response.model_dump()
        except Exception:
            fallback = [
                BenefitRequestTypeItem(benefit_number=str(b.get("benefit_number", "")), request_type="revisao")
                for b in benefits
            ]
            return BenefitRequestTypeClassificationResult(benefits=fallback).model_dump()
