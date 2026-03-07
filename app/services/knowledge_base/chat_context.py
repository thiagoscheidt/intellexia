import os
import re
from datetime import datetime

import pdfplumber
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from markitdown import MarkItDown
from werkzeug.utils import secure_filename

from app.agents.knowledge_base.query_enhancer_agent import QueryEnhancerAgent

ATTACHMENT_LARGE_TOKEN_THRESHOLD = 10000


def estimate_token_count(text: str) -> int:
    """Estimativa simples de tokens para controle de tamanho de contexto."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def extract_attachment_text(file_path: str, max_chars: int = 12000) -> str:
    """Extrai texto puro de um anexo para uso no contexto do chat (sem OCR)."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext in {'.txt', '.md', '.csv', '.json', '.xml', '.html', '.htm', '.log'}:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file_ref:
            return file_ref.read(max_chars)

    if ext in {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.gif'}:
        return ""

    try:
        converter = MarkItDown()
        result = converter.convert(file_path)
        extracted_text = getattr(result, 'text_content', '') or ''
        return extracted_text[:max_chars]
    except Exception:
        return ""


def extract_attachment_tables(file_path: str, max_rows: int = 80) -> str:
    """Extrai linhas de tabelas relevantes de PDFs, quando possível."""
    if os.path.splitext(file_path)[1].lower() != '.pdf':
        return ""

    try:
        nit_re = re.compile(r"\b\d{11}\b")
        benefit_type_re = re.compile(r"\bB\d{2}\b", re.IGNORECASE)
        benefit_number_re = re.compile(r"\b\d{9,11}\b")
        year_re = re.compile(r"\b(20\d{2})\b")

        rows = []
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
                        rows.append(header_text)
                        rows.extend(data_rows)
                        rows.append("")

        if not rows:
            return ""

        return "\n".join(rows[:max_rows]).strip()
    except Exception:
        return ""


def extract_relevant_chunks_with_faiss(text: str, query: str, k: int = 6) -> str:
    """Seleciona trechos mais relevantes com FAISS a partir do texto extraído."""
    if not text or not text.strip() or not query or not query.strip():
        return ""

    try:
        splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=150)
        documents = splitter.create_documents([text])
        if not documents:
            return ""

        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        vectorstore = FAISS.from_documents(documents, embeddings)
        results = vectorstore.similarity_search(query, k=min(k, len(documents)))

        if not results:
            return ""

        return "\n\n---TRECHO RELEVANTE---\n\n".join([result.page_content for result in results])
    except Exception:
        return ""


def build_attachments_context(
    uploaded_files,
    law_firm_id: int,
    user_id: int,
    question: str,
    history: list[dict] | None = None,
) -> tuple[str, list[str]]:
    """Salva anexos recebidos e monta contexto textual + IDs de arquivos enviados ao provedor."""
    if not uploaded_files:
        return "", []

    upload_dir = f"uploads/chat_attachments/{law_firm_id}/{user_id}"
    os.makedirs(upload_dir, exist_ok=True)

    context_blocks = []
    uploaded_provider_file_ids = []
    total_chars = 0
    max_total_chars = 30000
    query_enhancer = QueryEnhancerAgent()
    improved_query = query_enhancer.enhance_question(question, history=history)

    for raw_file in uploaded_files:
        if not raw_file or not raw_file.filename:
            continue

        safe_name = secure_filename(raw_file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        file_name = f"{timestamp}_{safe_name}"
        file_path = os.path.join(upload_dir, file_name)
        raw_file.save(file_path)

        extracted_text = (extract_attachment_text(file_path=file_path, max_chars=120000) or "").strip()
        tables_text = extract_attachment_tables(file_path=file_path)
        relevant_chunks = extract_relevant_chunks_with_faiss(
            text=extracted_text,
            query=improved_query or question,
            k=6,
        )
        estimated_tokens = estimate_token_count(extracted_text)

        if estimated_tokens > ATTACHMENT_LARGE_TOKEN_THRESHOLD:
            info_parts = [
                f"[ANEXO: {safe_name}]",
                f"Arquivo grande detectado (~{estimated_tokens} tokens).",
                "Estratégia aplicada: busca semântica local com FAISS (sem envio via file_id).",
                f"Pergunta otimizada para busca: {improved_query or question}",
            ]

            if tables_text:
                info_parts.append(f"Tabelas extraídas:\n{tables_text[:8000]}")

            if relevant_chunks:
                info_parts.append(f"Trechos relevantes por FAISS (baseados na pergunta):\n{relevant_chunks[:12000]}")
            elif extracted_text:
                info_parts.append(f"Prévia extraída (fallback):\n{extracted_text[:4000]}")

            context_blocks.append("\n".join(info_parts))
            continue

        if not extracted_text:
            context_blocks.append(f"[ANEXO: {safe_name}]\nNão foi possível extrair conteúdo textual deste arquivo.")
            continue

        remaining = max_total_chars - total_chars
        if remaining <= 0:
            break

        if len(extracted_text) > remaining:
            extracted_text = extracted_text[:remaining]

        attachment_parts = [f"[ANEXO: {safe_name}]"]
        if tables_text:
            attachment_parts.append(f"Tabelas extraídas:\n{tables_text[:8000]}")
        if estimated_tokens > ATTACHMENT_LARGE_TOKEN_THRESHOLD and relevant_chunks:
            attachment_parts.append(f"Trechos relevantes por FAISS (baseados na pergunta):\n{relevant_chunks[:12000]}")
        elif estimated_tokens > ATTACHMENT_LARGE_TOKEN_THRESHOLD:
            attachment_parts.append(f"Pergunta otimizada para busca: {improved_query or question}")
            attachment_parts.append(extracted_text[:4000])
        else:
            attachment_parts.append(extracted_text)

        context_blocks.append("\n".join(attachment_parts))
        total_chars += len(extracted_text)

    return "\n\n---\n\n".join(context_blocks), uploaded_provider_file_ids
