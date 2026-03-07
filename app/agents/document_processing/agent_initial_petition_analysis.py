import os
import re
from typing import Optional, List

from pydantic import BaseModel, Field
from dotenv import load_dotenv
from markitdown import MarkItDown
import pdfplumber
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from app.agents.core.file_agent import FileAgent

load_dotenv()


class Entities(BaseModel):
    people: List[str] = Field(default_factory=list, description="Pessoas mencionadas")
    organizations: List[str] = Field(default_factory=list, description="Organizações mencionadas")
    locations: List[str] = Field(default_factory=list, description="Localizações mencionadas")


class Party(BaseModel):
    name: str = Field(default="", description="Nome da parte")
    role: str = Field(default="", description="Papel da parte")
    lawyers: List[str] = Field(default_factory=list, description="Lista de advogados")


class Parties(BaseModel):
    active_pole: List[Party] = Field(default_factory=list, description="Polo ativo")
    passive_pole: List[Party] = Field(default_factory=list, description="Polo passivo")


class Request(BaseModel):
    subject: str = Field(default="", description="Objeto do pedido")
    request_text: str = Field(default="", description="Pedido formulado")
    legal_basis: List[str] = Field(default_factory=list, description="Base legal do pedido")
    urgency: str = Field(default="", description="Tipo de urgência, se houver")


class PetitionInfo(BaseModel):
    process_number: str = Field(default="", description="Número do processo, se houver")
    case_value: str = Field(default="", description="Valor da causa")
    subjects: List[str] = Field(default_factory=list, description="Assuntos jurídicos")
    origin_court: str = Field(default="", description="Tribunal/foro de distribuição, se identificável")
    nature: str = Field(default="", description="Natureza da ação")
    judicial_power: str = Field(default="", description="Poder judiciário")
    court_tag: str = Field(default="", description="Tag do tribunal, se identificável")
    parties: Parties = Field(default_factory=Parties, description="Partes envolvidas")
    facts_summary: str = Field(default="", description="Resumo dos fatos narrados")
    cause_of_action: str = Field(default="", description="Causa de pedir")
    legal_grounds: List[str] = Field(default_factory=list, description="Fundamentos legais invocados")
    all_requests: List[str] = Field(default_factory=list, description="Lista simples com todos os pedidos da petição")
    requests: List[Request] = Field(default_factory=list, description="Pedidos da petição")
    urgency_justification: str = Field(default="", description="Justificativa de tutela de urgência")
    evidence_mentioned: List[str] = Field(default_factory=list, description="Provas e documentos mencionados")
    procedure_requests: List[str] = Field(default_factory=list, description="Pedidos processuais (citação, perícia, gratuidade etc.)")
    estimated_risks: List[str] = Field(default_factory=list, description="Riscos processuais identificados na tese")


class InitialPetitionSummary(BaseModel):
    summary: str = Field(description="Resumo geral da petição inicial")
    summary_short: str = Field(default="", description="Resumo curto (2-4 frases)")
    summary_long: str = Field(default="", description="Resumo longo (2-4 parágrafos)")
    key_points: List[str] = Field(default_factory=list, description="Pontos-chave da petição")
    entities: Entities = Field(default_factory=Entities, description="Entidades extraídas")
    dates: List[str] = Field(default_factory=list, description="Datas mencionadas")
    language: str = Field(default="pt-BR", description="Idioma do documento")
    notes: str = Field(default="", description="Observações adicionais")
    petition_info: PetitionInfo = Field(default_factory=PetitionInfo, description="Informações estruturadas da petição")

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True)


class PetitionRequestsOnly(BaseModel):
    """Modelo simplificado apenas para extração de pedidos"""
    all_requests: List[str] = Field(default_factory=list, description="Lista com todos os pedidos da petição")
    requests_detailed: List[Request] = Field(default_factory=list, description="Pedidos com detalhamento")
    
    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)
    
    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True)


class BenefitRevisionRequest(BaseModel):
    """Modelo para benefício com pedido de revisão"""
    benefit_number: str = Field(default="", description="Número do benefício (NB)")
    nit_number: str = Field(default="", description="Número do NIT")
    insured_name: str = Field(default="", description="Nome do segurado")
    benefit_type: str = Field(default="", description="Tipo do benefício (B91, B92, B93, B94, etc)")
    fap_vigencia_year: str = Field(default="", description="Ano da vigência do FAP")


class BenefitsExtractionResult(BaseModel):
    """Modelo para resultado da extração de benefícios"""
    benefits: List[BenefitRevisionRequest] = Field(default_factory=list, description="Lista de benefícios identificados")
    general_revision_context: str = Field(default="", description="Contexto geral da revisão de todos os benefícios")
    
    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)
    
    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True)


class BenefitRequestItem(BaseModel):
    """Modelo simplificado para benefício extraído de pedidos"""
    benefit_number: str = Field(default="", description="Número do benefício (NB)")
    nit_number: str = Field(default="", description="Número do NIT")
    insured_name: str = Field(default="", description="Nome do segurado")
    benefit_type: str = Field(default="", description="Tipo do benefício (B91, B92, B93, B94, etc)")
    fap_vigencia_year: str = Field(default="", description="Ano da vigência do FAP")


class BenefitsRequestsExtractionResult(BaseModel):
    """Modelo para resultado da extração de benefícios nos pedidos"""
    benefits: List[BenefitRequestItem] = Field(default_factory=list, description="Lista de benefícios identificados")
    general_revision_context: str = Field(default="", description="Contexto geral da revisão de todos os benefícios")

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True)


class AgentInitialPetitionAnalysis:
    model_name = None

    def __init__(self, model_name: str = "gpt-5-mini"):
        self.model_name = model_name

    def extract_petition_requests(self, file_path: Optional[str] = None, text_content: Optional[str] = None) -> dict:
        """
        Extrai apenas os pedidos de uma petição inicial usando FAISS para buscar trechos relevantes.
        
        Args:
            file_path: Caminho do arquivo da petição
            text_content: Texto já extraído da petição
            
        Returns:
            dict: Dicionário com all_requests (lista simples) e requests_detailed (lista detalhada)
        """
        if not file_path and not text_content:
            raise ValueError("É necessário fornecer file_path ou text_content")

        # ==============================
        # 1. EXTRAIR TEXTO DO DOCUMENTO
        # ==============================
        extracted_text = ""
        if text_content:
            extracted_text = text_content if isinstance(text_content, str) else str(text_content)
        else:
            md = MarkItDown()
            print("Iniciando conversão da petição para extração de pedidos...")
            result = md.convert(file_path)
            extracted_text = result.text_content or ""

        if not extracted_text.strip():
            raise ValueError("Não foi possível extrair texto do documento")

        print(f"Texto extraído: {len(extracted_text)} caracteres")

        # ==============================
        # 2. FOCAR NO FINAL DA PETIÇÃO
        # Pedidos geralmente ficam nos últimos 40% do documento
        # ==============================
        text_for_search = extracted_text[int(len(extracted_text) * 0.6):]
        print(f"Focando nos últimos 40% do documento: {len(text_for_search)} caracteres")

        # ==============================
        # 3. QUEBRAR EM CHUNKS
        # ==============================
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=2000,
            chunk_overlap=150
        )
        documents = splitter.create_documents([text_for_search])
        print(f"Total de chunks criados: {len(documents)}")

        # ==============================
        # 4. EMBEDDINGS LOCAIS (HuggingFace)
        # ==============================
        print("Carregando modelo de embeddings local...")
        embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

        # ==============================
        # 5. CRIAR FAISS EM MEMÓRIA
        # ==============================
        print("Criando índice FAISS em memória...")
        vectorstore = FAISS.from_documents(documents, embeddings)

        # ==============================
        # 6. BUSCAR TRECHOS RELEVANTES SOBRE PEDIDOS
        # ==============================
        query = """
        Trecho da petição inicial onde o advogado faz os pedidos ao juiz,
        incluindo requerimentos finais, condenações, solicitações, tutelas de urgência,
        pedidos principais, subsidiários e acessórios, citação do réu, honorários advocatícios.
        """
        
        print("Buscando trechos relevantes sobre pedidos...")
        results = vectorstore.similarity_search(query, k=6)
        
        # Combinar os trechos encontrados
        relevant_text = "\n\n---TRECHO---\n\n".join([r.page_content for r in results])
        print(f"Trechos relevantes encontrados: {len(results)} chunks, {len(relevant_text)} caracteres")

        # ==============================
        # 7. ENVIAR APENAS TRECHOS RELEVANTES PARA O LLM
        # ==============================
        user_prompt = (
            "Extraia TODOS os pedidos dos trechos da petição inicial abaixo.\n\n"
            "INSTRUÇÕES:\n"
            "1. all_requests: array simples com TODOS os pedidos (principais, subsidiários, acessórios) em formato de texto direto\n"
            "2. requests_detailed: array de objetos com:\n"
            "   - subject: objeto/tema do pedido\n"
            "   - request_text: texto completo do pedido\n"
            "   - legal_basis: lista de fundamentos legais específicos deste pedido\n"
            "   - urgency: tipo de urgência (Tutela Antecipada, Liminar, etc.) - deixe vazio se não aplicável\n\n"
            "Inclua pedidos explícitos e implícitos (ex: condenação em honorários, custas, citação do réu).\n"
            "Seja completo e objetivo.\n\n"
            f"TRECHOS RELEVANTES DA PETIÇÃO:\n\n{relevant_text}"
        )

        llm = ChatOpenAI(
            model=self.model_name,
            temperature=0.1,
        ).with_structured_output(PetitionRequestsOnly)

        print("Enviando trechos para análise pelo LLM...")
        response = llm.invoke([
            {
                "role": "system",
                "content": "Você é um assistente jurídico especializado em análise de petições. Extraia TODOS os pedidos de forma completa e estruturada.",
            },
            {"role": "user", "content": user_prompt},
        ])

        print("✓ Extração de pedidos concluída")
        return response.to_dict()

    def extract_table_text_from_petition(self, file_path: Optional[str] = None, text_content: Optional[str] = None) -> str:
        """
        Extrai tabelas de benefícios do PDF e retorna como texto formatado.
        Sem análise de IA - apenas extração de tabelas.
        
        Args:
            file_path: Caminho do arquivo da petição
            text_content: Texto já extraído da petição (ignorado se file_path for fornecido)
            
        Returns:
            str: Texto formatado com as tabelas extraídas (headers + dados)
        """
        if not file_path and not text_content:
            raise ValueError("É necessário fornecer file_path ou text_content")

        # ==============================
        # 1. EXTRAIR TABELAS DO PDF
        # ==============================
        if file_path and os.path.splitext(file_path)[1].lower() == ".pdf":
            print("Extraindo tabelas com pdfplumber...")
            table_rows = self._extract_benefits_table_rows_pdfplumber(file_path)
            
            if table_rows:
                formatted_text = "\n".join(table_rows)
                print(f"✓ Tabelas extraídas: {len(table_rows)} linhas")
                return formatted_text
            else:
                print("⚠ Nenhuma tabela de benefícios encontrada no PDF")
                return ""
        else:
            print("⚠ Arquivo não é PDF ou não fornecido")
            return ""

    def extract_benefits_and_reasons_from_requests(self, file_path: Optional[str] = None, text_content: Optional[str] = None) -> dict:
        """
        Extrai benefícios e motivos de revisão focando na parte de pedidos da petição.
        Estrutura baseada em extract_benefits_and_reasons, mas com estratégia de busca
        semelhante à extract_petition_requests.

        Args:
            file_path: Caminho do arquivo da petição
            text_content: Texto já extraído da petição

        Returns:
            dict: Dicionário com lista de benefícios e seus motivos de revisão
        """
        if not file_path and not text_content:
            raise ValueError("É necessário fornecer file_path ou text_content")

        # ==============================
        # 1. EXTRAIR TEXTO DO DOCUMENTO
        # ==============================
        extracted_text = ""
        if text_content:
            extracted_text = text_content if isinstance(text_content, str) else str(text_content)
        else:
            md = MarkItDown()
            print("Iniciando conversão da petição para extração de benefícios (foco em pedidos)...")
            result = md.convert(file_path)
            extracted_text = result.text_content or ""

        if not extracted_text.strip():
            raise ValueError("Não foi possível extrair texto do documento")

        print(f"Texto extraído: {len(extracted_text)} caracteres")

        # ==============================
        # 2. USAR O DOCUMENTO INTEIRO
        # ==============================
        text_for_search = extracted_text
        print(f"Usando documento inteiro: {len(text_for_search)} caracteres")

        # ==============================
        # 2.1 EXTRAIR TABELAS COM PDFPLUMBER (SE FOR PDF)
        # ==============================
        table_rows: List[str] = []
        if file_path and os.path.splitext(file_path)[1].lower() == ".pdf":
            print("Extraindo tabelas com pdfplumber...")
            table_rows = self._extract_benefits_table_rows_pdfplumber(file_path)

        if table_rows:
            print(f"Tabelas detectadas: {len(table_rows)} linhas")
            relevant_text = "\n".join(table_rows)
        else:
            relevant_text = ""
        # ==============================
        # 3. QUEBRAR EM CHUNKS E USAR FAISS (SE NAO HOUVER TABELAS)
        # ==============================
        if not relevant_text:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=2000,
                chunk_overlap=150
            )
            documents = splitter.create_documents([text_for_search])
            print(f"Total de chunks criados: {len(documents)}")

            # ==============================
            # 4. EMBEDDINGS LOCAIS
            # ==============================
            print("Carregando modelo de embeddings local...")
            embeddings = HuggingFaceEmbeddings(
                model_name="sentence-transformers/all-MiniLM-L6-v2"
            )

            # ==============================
            # 5. CRIAR FAISS EM MEMÓRIA
            # ==============================
            print("Criando índice FAISS em memória...")
            vectorstore = FAISS.from_documents(documents, embeddings)

            # ==============================
            # 6. BUSCAR TRECHOS RELEVANTES SOBRE BENEFÍCIOS
            # ==============================
            query = """
            Trechos que contem tabelas ou listas com beneficios e segurados, incluindo:
            Vigencias do FAP, CNPJ, Empregado/Segurado, NIT, Tipo do beneficio (B91, B92, B93, B94),
            numero do beneficio, acidentes de trabalho, CAT, revisao de FAP.
            """

            print("Buscando trechos relevantes sobre benefícios...")
            results = vectorstore.similarity_search(query, k=8)

            relevant_text = "\n\n---TRECHO---\n\n".join([r.page_content for r in results])
            print(f"Trechos relevantes encontrados: {len(results)} chunks, {len(relevant_text)} caracteres")

        # ==============================
        # 7. ENVIAR PARA O LLM
        # ==============================
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

        llm = ChatOpenAI(
            model=self.model_name,
            temperature=0.1,
        ).with_structured_output(BenefitsRequestsExtractionResult)

        print("Enviando tabelas para análise pelo LLM...")
        response = llm.invoke([
            {
                "role": "system",
                "content": "Você é um assistente jurídico especializado em processos previdenciários e revisão de FAP. Extraia benefícios de tabelas, mapeando autonomamente as colunas com base em seus nomes e significados.",
            },
            {"role": "user", "content": user_prompt},
        ])

        print("✓ Extração de benefícios concluída")
        return response.to_dict()

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

        rows_with_headers: List[tuple] = []  # (header, data_rows)

        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables() or []
                    for table in tables:
                        if not table or len(table) < 2:
                            continue
                        
                        # Usar primeiro row como header (sem processamento)
                        header_row = table[0]
                        header_text = " | ".join([str(cell).strip() if cell else "" for cell in header_row])
                        
                        data_rows = []
                        # Processar linhas de dados (a partir da 2ª linha)
                        for row in table[1:]:
                            if not row:
                                continue
                            
                            # Converter todos para string e juntar
                            row_text = " | ".join([str(cell).strip() if cell else "" for cell in row if cell])
                            
                            if not row_text:
                                continue
                            
                            # Validar se a linha tem os padrões esperados (todos necessários)
                            has_nit = nit_re.search(row_text)
                            has_benefit_type = benefit_type_re.search(row_text)
                            has_benefit_number = benefit_number_re.search(row_text)
                            has_year = year_re.search(row_text)
                            
                            if has_nit and has_benefit_type and has_benefit_number and has_year:
                                # Linha válida - adicionar sem processamento
                                if row_text not in data_rows:
                                    data_rows.append(row_text)
                        
                        if data_rows:
                            rows_with_headers.append((header_text, data_rows))
        except Exception as exc:
            print(f"Falha ao extrair tabelas com pdfplumber: {exc}")
            import traceback
            traceback.print_exc()

        # Formatar resultado: header + dados para cada tabela
        result = []
        for header, data_rows in rows_with_headers:
            result.append(header)
            result.extend(data_rows)
            result.append("")  # Linha vazia separando tabelas
        
        return result

    def analyze_initial_petition(self, file_path: Optional[str] = None, text_content: Optional[str] = None) -> dict:
        if not file_path and not text_content:
            raise ValueError("É necessário fornecer file_path ou text_content")

        extracted_text = ""
        if text_content:
            extracted_text = text_content if isinstance(text_content, str) else str(text_content)
        else:
            md = MarkItDown()
            print("Iniciando conversão da petição inicial para texto...")
            result = md.convert(file_path)
            extracted_text = result.text_content or ""

        max_chars = int(os.getenv("SUMMARY_MAX_CHARS", "50000"))
        use_file = False
        file_id = None

        if len(extracted_text) > max_chars:
            print("Texto extraído excede o limite máximo, utilizando upload de arquivo para LLM...")
            file_agent = FileAgent()
            file_id = file_agent.upload_file(file_path)
            use_file = True

        user_prompt = (
            "Resuma a petição inicial abaixo com foco técnico-jurídico. "
            "Regras de tamanho: summary_short com 2-4 frases objetivas; summary_long com 2-4 parágrafos, "
            "mais completo e detalhado que o resumo curto. "
            "Se não houver dado para algum campo, use lista vazia ou string vazia.\n\n"
            "IMPORTANTE: Extraia as seguintes informações estruturadas no campo 'petition_info':\n"
            "- process_number: número do processo (se mencionado)\n"
            "- case_value: valor da causa (com formatação monetária)\n"
            "- subjects: lista de assuntos jurídicos\n"
            "- origin_court: tribunal/foro de distribuição (com cidade/estado, se houver)\n"
            "- nature: natureza da ação (ex: Procedimento Comum, Ação Ordinária)\n"
            "- judicial_power: poder judiciário (ex: Justiça Federal, Justiça Estadual)\n"
            "- court_tag: tag do tribunal conforme lista (usar CHAVE: STF, STJ, TST, TSE, STM, TRF1-TRF6, "
            "TJAC, TJAL, TJAM, TJAP, TJBA, TJCE, TJDFT, TJES, TJGO, TJMA, TJMG, TJMS, TJMT, TJPA, TJPB, "
            "TJPE, TJPI, TJPR, TJRJ, TJRN, TJRO, TJRR, TJRS, TJSC, TJSE, TJSP, TJTO). Se não identificar, deixe vazio.\n"
            "- parties: objeto contendo:\n"
            "  - active_pole: array de partes do polo ativo com nome, papel e advogados\n"
            "  - passive_pole: array de partes do polo passivo com nome, papel e advogados\n"
            "- facts_summary: resumo dos fatos narrados (1-2 parágrafos)\n"
            "- cause_of_action: causa de pedir (próxima e remota)\n"
            "- legal_grounds: lista de leis, artigos, princípios, precedentes e súmulas invocadas\n"
            "- all_requests: array simples com TODOS os pedidos formulados na petição (incluindo principais, subsidiários e acessórios)\n"
            "- requests: array de pedidos com:\n"
            "  - subject: objeto do pedido\n"
            "  - request_text: pedido formulado\n"
            "  - legal_basis: lista da base legal do pedido\n"
            "  - urgency: tipo de urgência (se houver)\n"
            "- urgency_justification: fundamento para tutela de urgência (se houver)\n"
            "- evidence_mentioned: lista de provas/documentos citados\n"
            "- procedure_requests: pedidos processuais (citação, perícia, gratuidade, inversão do ônus, etc.)\n"
            "- estimated_risks: riscos de improcedência, preliminares frágeis ou pontos vulneráveis\n\n"
            f"PETIÇÃO INICIAL:\n{extracted_text}"
        )

        llm = ChatOpenAI(
            model=self.model_name,
            temperature=0.2,
        ).with_structured_output(InitialPetitionSummary)

        if use_file and file_id:
            response = llm.invoke([
                {
                    "role": "system",
                    "content": "Você é um assistente jurídico especializado em análise de petições iniciais. Gere um resumo técnico, objetivo e estruturado.",
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_prompt.replace(
                                f"PETIÇÃO INICIAL:\n{extracted_text}",
                                "PETIÇÃO INICIAL: (arquivo anexado)",
                            ),
                        },
                        {"type": "file", "file_id": file_id},
                    ],
                },
            ])
        else:
            response = llm.invoke([
                {
                    "role": "system",
                    "content": "Você é um assistente jurídico especializado em análise de petições iniciais. Gere um resumo técnico, objetivo e estruturado.",
                },
                {"role": "user", "content": user_prompt},
            ])

        return response.to_dict()
