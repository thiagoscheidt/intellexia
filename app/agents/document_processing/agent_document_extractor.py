import re
import os
import time
from pathlib import Path
from typing import Any, Optional, List
from rich import print
from gliner2 import GLiNER2 as Gliner2

from dotenv import load_dotenv
from markitdown import MarkItDown
import pdfplumber
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


class BenefitRequestItem(BaseModel):
    """Modelo simplificado para benefício extraído de tabelas."""
    benefit_number: str = Field(default="", description="Número do benefício (NB)")
    nit_number: str = Field(default="", description="Número do NIT")
    insured_name: str = Field(default="", description="Nome do segurado")
    benefit_type: str = Field(default="", description="Tipo do benefício (B91, B92, B93, B94, etc)")
    fap_vigencia_year: str = Field(default="", description="Ano da vigência do FAP")


class BenefitsRequestsExtractionResult(BaseModel):
    """Modelo para resultado da extração de benefícios nas tabelas/pedidos."""
    benefits: List[BenefitRequestItem] = Field(default_factory=list, description="Lista de benefícios identificados")
    general_revision_context: str = Field(default="", description="Contexto geral da revisão de todos os benefícios")

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
        )

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
            '  "suggested_document_type_name": ""\n'
            "}"
        )

        print(user_prompt)  # Log do prompt para debug

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

    def extract_table_text_from_petition(self, file_path: Optional[str] = None, text_content: Optional[str] = None) -> str:
        """
        Extrai tabelas de benefícios do PDF e retorna como texto formatado.
        Sem análise de IA - apenas extração de tabelas.
        """
        if not file_path and not text_content:
            raise ValueError("É necessário fornecer file_path ou text_content")

        if file_path and os.path.splitext(file_path)[1].lower() == ".pdf":
            print("Extraindo tabelas com pdfplumber...")
            table_rows = self._extract_benefits_table_rows_pdfplumber(file_path)

            if table_rows:
                formatted_text = "\n".join(table_rows)
                print(f"✓ Tabelas extraídas: {len(table_rows)} linhas")
                return formatted_text

            print("⚠ Nenhuma tabela de benefícios encontrada no PDF")
            return ""

        print("⚠ Arquivo não é PDF ou não fornecido")
        return ""
    def extract_benefits_from_tables(
            self
    ):
        tables = self.document_data.get('tables', [])
        extractor = Gliner2.from_pretrained("fastino/gliner2-base-v1")

        text = "iPhone 15 Pro Max with 256GB storage, A17 Pro chip, priced at $1199. Available in titanium and black colors."
        result = extractor.extract_json(
            text,
            {
                "product": [
                    "name::str::Full product name and model",
                    "storage::str::Storage capacity like 256GB or 1TB", 
                    "processor::str::Chip or processor information",
                    "price::str::Product price with currency",
                    "colors::list::Available color options"
                ]
            }
        )

        pass
    
    def extract_benefits_from_petition(
        self,
        file_path: Optional[str] = None,
        text_content: Optional[str] = None,
    ) -> dict:
        """
        Extrai benefícios a partir das tabelas do PDF via pdfplumber.
        Se não houver tabelas, retorna resultado vazio sem busca no vetor.
        """
        effective_file_path = file_path or (str(self.file_path) if self.file_path else None)

        table_rows: List[str] = []
        if effective_file_path and os.path.splitext(effective_file_path)[1].lower() == ".pdf":
            print("Extraindo tabelas com pdfplumber...")
            table_rows = self._extract_benefits_table_rows_pdfplumber(effective_file_path)

        if not table_rows:
            print("⚠ Nenhuma tabela de benefícios encontrada.")
            return BenefitsRequestsExtractionResult().model_dump()

        print(f"Tabelas detectadas: {len(table_rows)} linhas")
        relevant_text = "\n".join(table_rows)

        user_prompt = (
            "Extraia os benefícios previdenciários/acidentários das tabelas abaixo.\n\n"
            "INSTRUÇÕES PARA MAPEAMENTO DE COLUNAS:\n"
            "As tabelas podem ter estruturas diferentes. Você deve:\n"
            "1. Observar o header (primeira linha) de cada tabela para entender quais são as colunas\n"
            "2. Identificar as colunas relevantes por seu significado e nome, não por posição fixa\n"
            "3. Buscar pelas seguintes colunas (os nomes podem variar):\n"
            "   - VIGÊNCIA FAP, Vigência, Year, Ano, FAP, Período → para fap_vigencia_year\n"
            "   - NIT, NIT do Segurado → para nit_number\n"
            "   - SEGURADO, Empregado, Nome, Beneficiário, Titular → para insured_name\n"
            "   - TIPO, Tipo de Benefício, Código, B-type → para benefit_type (B91, B92, B93, B94, etc)\n"
            "   - BENEFÍCIO, Nº Benefício, Número Benefício, NB → para benefit_number\n\n"
            "PROCESSAMENTO:\n"
            "Para cada linha de dados da tabela, extraia os 5 campos acima conforme seus nomes reais:\n"
            "- benefit_number: número do benefício\n"
            "- nit_number: número do NIT (11 dígitos)\n"
            "- insured_name: nome completo do segurado/beneficiário\n"
            "- benefit_type: tipo do benefício (B91, B92, B93, B94, B31, B42, B46, etc)\n"
            "- fap_vigencia_year: ano da vigência (2022, 2023, etc)\n\n"
            "No campo 'general_revision_context', descreva o contexto geral dos benefícios listados nas tabelas.\n\n"
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
                    "table_rows_count": len(table_rows),
                },
            )
            structured_response = response_payload.get("structured_response")
            if not structured_response:
                raise RuntimeError("Resposta estruturada de benefícios não retornada pelo agente")
            return structured_response.model_dump()
        except Exception:
            return BenefitsRequestsExtractionResult().model_dump()

    @staticmethod
    def _extract_benefits_table_rows_pdfplumber(file_path: str) -> List[str]:
        """
        Extrai tabelas procurando por padrões nas linhas de dados.
        Normaliza quebras de linha e formata consistentemente.
        """
        nit_re = re.compile(r"\b\d{11}\b")
        benefit_type_re = re.compile(r"\bB\d{2}\b", re.IGNORECASE)
        benefit_number_re = re.compile(r"\b\d{9,11}\b")
        year_re = re.compile(r"\b(20\d{2})\b")

        rows_with_headers: List[tuple[str, list[str]]] = []

        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables() or []
                    for table in tables:
                        if not table or len(table) < 2:
                            continue

                        header_row = table[0]
                        header_text = " | ".join([str(cell).strip() if cell else "" for cell in header_row])

                        data_rows = []
                        for row in table[1:]:
                            if not row:
                                continue

                            row_text = " | ".join([str(cell).strip() if cell else "" for cell in row if cell])
                            if not row_text:
                                continue

                            has_nit = nit_re.search(row_text)
                            has_benefit_type = benefit_type_re.search(row_text)
                            has_benefit_number = benefit_number_re.search(row_text)
                            has_year = year_re.search(row_text)

                            if has_nit and has_benefit_type and has_benefit_number and has_year:
                                if row_text not in data_rows:
                                    data_rows.append(row_text)

                        if data_rows:
                            rows_with_headers.append((header_text, data_rows))
        except Exception as exc:
            print(f"Falha ao extrair tabelas com pdfplumber: {exc}")

        result = []
        for header, data_rows in rows_with_headers:
            result.append(header)
            result.extend(data_rows)
            result.append("")

        return result
