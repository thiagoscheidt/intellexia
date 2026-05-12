"""
Agente Revisor de Petições FAP - FapPetitionReviewerAgent

Responsabilidade: Revisar petições iniciais de Ação Revisional FAP e identificar
inconsistências, erros, riscos jurídicos e divergências em relação ao manual.

Este agente NÃO atualiza diretamente:
- manuais
- casos de referência
- base oficial de conhecimento

Ele apenas identifica padrões e encaminha achados ao Agente de Treinamento.
"""

import json
import os
import re
import time
from decimal import Decimal
from typing import Optional, Any
from datetime import datetime
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.core.file_agent import FileAgent
from app.models import AgentTokenUsage
from app.services.agent_execution_history_service import AgentExecutionHistoryService
from app.services.token_usage_service import TokenUsageService


class FindingItem(BaseModel):
    """Um achado identificado na petição"""
    category: str = Field(..., description="Categoria do achado: CAT-1 a CAT-6, CRITICAL, MODERATE, FORMAL")
    severity: str = Field(..., description="Gravidade: CRÍTICO, MODERADO, FORMAL")
    description: str = Field(..., description="Descrição do achado")
    location: Optional[str] = Field(None, description="Localização na petição")
    correction: Optional[str] = Field(None, description="Sugestão de correção")
    manual_reference: Optional[str] = Field(None, description="Seção do manual relacionada")
    is_new_pattern: bool = Field(False, description="Indica se é um padrão novo não coberto pelo manual")


class MissingDocument(BaseModel):
    """Documento obrigatório que está ausente"""
    document_type: str = Field(..., description="Tipo de documento obrigatório")
    thesis: Optional[str] = Field(None, description="Tese relacionada")
    manual_reference: Optional[str] = Field(None, description="Referência da Seção 3 do manual")


class IdentifiedThesis(BaseModel):
    """Tese identificada na petição"""
    thesis: str = Field(..., description="Nome da tese")
    benefit_number: Optional[str] = Field(None, description="Número do benefício")
    classification: Optional[str] = Field(None, description="Enquadramento identificado")


class NewPattern(BaseModel):
    """Padrão novo identificado que não existe no manual"""
    pattern_description: str = Field(..., description="Descrição do padrão")
    recurrence: str = Field(..., description="Comportamento recorrente identificado")
    suggested_update: str = Field(..., description="Proposta de atualização do manual")
    section: Optional[str] = Field(None, description="Seção do manual que deveria ser atualizada")


class ExecutiveSummary(BaseModel):
    """Resumo executivo da análise"""
    total_findings: int = Field(..., description="Total de achados")
    critical_findings: int = Field(..., description="Quantidade de achados críticos")
    moderate_findings: int = Field(..., description="Quantidade de achados moderados")
    formal_findings: int = Field(..., description="Quantidade de achados formais")
    main_legal_risks: list[str] = Field(default_factory=list, description="Principais riscos jurídicos")
    correction_priority: str = Field(..., description="Prioridade de correção")


class ComparativeAnalysisChange(BaseModel):
    """Alteração identificada na análise comparativa"""
    original_excerpt: str = Field(..., description="Trecho original da petição")
    corrected_excerpt: str = Field(..., description="Trecho corrigido")
    correction_reason: str = Field(..., description="Motivo da correção")
    pattern_in_manual: bool = Field(..., description="Se o padrão já existe no manual")
    is_new_pattern: bool = Field(..., description="Se é um padrão novo")
    manual_section: Optional[str] = Field(None, description="Seção do manual")


class PetitionReviewResult(BaseModel):
    """Resultado completo da revisão de petição"""
    execution_id: Optional[int] = None
    analysis_type: str = Field(..., description="'single_version' ou 'comparative'")
    tokens_used: Optional[int] = Field(None, description="Total de tokens utilizados na execução")
    cost_usd: Optional[float] = Field(None, description="Custo estimado da execução em USD")
    
    # Teses identificadas
    theses: list[IdentifiedThesis] = Field(default_factory=list)
    
    # Análise comparativa (se aplicável)
    comparative_changes: list[ComparativeAnalysisChange] = Field(default_factory=list)
    
    # Achados por categoria
    findings: list[FindingItem] = Field(default_factory=list)
    
    # Documentos em falta
    missing_documents: list[MissingDocument] = Field(default_factory=list)
    
    # Resumo executivo
    executive_summary: ExecutiveSummary = Field(...)
    
    # Padrões novos identificados
    new_patterns: list[NewPattern] = Field(default_factory=list)
    
    # Metadados
    analysis_timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class FapPetitionReviewerAgent:
    """
    Agente Revisor de Petições FAP
    
    Responsabilidade exclusiva: Revisar petições iniciais e identificar inconsistências
    sem atualizar diretamente nenhum documento oficial.
    """

    _PROMPT_LOG_MAX_CHARS = int(os.environ.get('TOKEN_PROMPT_LOG_MAX_CHARS', '12000'))
    _REVIEW_CHUNK_MAX_CHARS = int(os.environ.get('FAP_REVIEW_CHUNK_MAX_CHARS', '12000'))
    _REVIEW_CHUNK_OVERLAP_CHARS = int(os.environ.get('FAP_REVIEW_CHUNK_OVERLAP_CHARS', '1200'))
    _AUX_PREVIEW_LIMIT = int(os.environ.get('FAP_REVIEW_AUX_PREVIEW_LIMIT', '5'))
    _SECTION_TITLE_MAX_CHARS = int(os.environ.get('FAP_REVIEW_SECTION_TITLE_MAX_CHARS', '160'))

    def __init__(self, 
                 openai_api_key: Optional[str] = None,
                    model: str = 'gpt-4o-mini',
                 temperature: float = 0.0):
        """
        Inicializa o agente revisor
        
        Args:
            openai_api_key: Chave da API OpenAI (se None, usa variável de ambiente)
            model: Modelo LLM a usar
            temperature: Temperatura do modelo (padrão: 0.0 para determinismo)
        """
        self.api_key = openai_api_key or os.environ.get('OPENAI_API_KEY')
        self.model_name = model
        self.temperature = temperature
        
        # Com gpt-4o + temperature=0.0, OpenAI oferece determinismo
        # temperature=0.0 = máximo determinismo para o modelo (limites dependem do modelo)
        self.llm = ChatOpenAI(
            api_key=self.api_key,
            model=model,
            temperature=temperature
        )
        
        self.token_usage_service = TokenUsageService()
        self.file_agent = FileAgent()
        
        self.manual_content: str = ""
        self.cases_content: str = ""
        self.project_instructions: str = ""

    def load_reference_documents(self,
                                 manual_md: str = "",
                                 cases_md: str = "",
                                 project_instructions_md: str = "") -> None:
        """
        Carrega os documentos de referência dinamicamente
        
        Args:
            manual_md: Conteúdo do manual (MANUAL_REVISAO_FAP.md)
            cases_md: Conteúdo dos casos (CASOS_REFERENCIA.md)
            project_instructions_md: Conteúdo das instruções do projeto
        """
        self.manual_content = manual_md
        self.cases_content = cases_md
        self.project_instructions = project_instructions_md

    def _build_system_prompt(
        self,
        reviewer_identity: str = "",
        reviewer_rules: str = "",
        reviewer_output_format: str = "",
    ) -> str:
        """
        Constrói o prompt do sistema carregando dinamicamente da configuração
        
        Args:
            reviewer_identity: Identidade do revisor (REVISOR_IDENTITY.md)
            reviewer_rules: Regras do revisor (REVISOR_RULES.md)
            reviewer_output_format: Formato de saída (REVISOR_OUTPUT_FORMAT.md)
            
        Returns:
            Prompt completo do sistema
        """
        base_system = f"""Você é um revisor especializado em petições iniciais de Ação Revisional do FAP.

IDENTIDADE:
{reviewer_identity or 'Revise petições de FAP com rigor jurídico'}

REGRAS INVIOLÁVEIS:
{reviewer_rules or 'Aplique todas as regras do manual'}

FORMATO DE SAÍDA:
{reviewer_output_format or 'Estruture a resposta em seções claras'}

INSTRUÇÕES OPERACIONAIS:
Ao revisar a petição, valide estritamente com base no MANUAL DE REFERÊNCIA.
Em caso de divergência entre qualquer instrução e o manual, o manual prevalece.
Não invente critérios fora do manual.

MANUAL DE REFERÊNCIA:
{self.manual_content if self.manual_content else 'Manual não carregado'}

CASOS DE REFERÊNCIA:
{self.cases_content if self.cases_content else 'Casos não carregados'}

INSTRUÇÕES DO PROJETO:
{self.project_instructions if self.project_instructions else 'Instruções não carregadas'}"""
        
        return base_system

    async def review_petition_single_version(self,
                                            petition_file_path: str,
                                            auxiliary_documents: list[dict] = None,
                                            reviewer_identity: str = "",
                                            reviewer_rules: str = "",
                                            reviewer_output_format: str = "",
                                            execution_id: int | None = None,
                                            user_id: int | None = None,
                                            law_firm_id: int | None = None) -> PetitionReviewResult:
        """
        Revisa uma única versão de petição contra o manual
        
        Args:
            petition_file_path: Caminho do PDF/arquivo da petição
            auxiliary_documents: Documentos auxiliares opcionais
            reviewer_identity: Identidade do revisor
            reviewer_rules: Regras do revisor
            reviewer_output_format: Formato de saída
            
        Returns:
            Resultado estruturado da revisão
        """
        system_prompt = self._build_system_prompt(
            reviewer_identity,
            reviewer_rules,
            reviewer_output_format,
        )
        
        try:
            petition_file_part = self._build_file_part_for_message(petition_file_path)

            user_message = self._build_single_user_message(
                auxiliary_documents=auxiliary_documents,
            )

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=[
                    {
                        "type": "text",
                        "text": user_message,
                    },
                    petition_file_part,
                ])
            ]

            start_time = time.time()
            response = self.llm.invoke(messages)
            latency_ms = int((time.time() - start_time) * 1000)
            response_text = response.content

            # Capturar e persistir logs de tokens
            response_payload = self._build_response_payload(response)
            token_entries = self.token_usage_service.extract_entries(
                response_payload,
                model_name=self.model_name,
            )
            total_tokens = sum(entry.total_tokens for entry in token_entries)
            total_cost = sum((entry.estimated_cost_usd for entry in token_entries), Decimal("0"))
            self.token_usage_service.capture_and_store(
                response_payload,
                agent_name="FapPetitionReviewerAgent",
                action_name="review_petition_single_version",
                print_prefix="[FapReviewer]",
                model_name=self.model_name,
                model_provider="openai",
                latency_ms=latency_ms,
                metadata_payload={
                    "petition_file_path": petition_file_path,
                    "petition_file_name": self._extract_file_name(petition_file_path),
                    "auxiliary_documents_count": len(auxiliary_documents or []),
                    "mode": "file_attachment",
                    "llm_input": {
                        "system_prompt": self._truncate_for_log(system_prompt),
                        "user_prompt": self._truncate_for_log(user_message),
                    },
                    "prompt_versions": {
                        "reviewer_identity": self._truncate_for_log(reviewer_identity),
                        "reviewer_rules": self._truncate_for_log(reviewer_rules),
                        "reviewer_output_format": self._truncate_for_log(reviewer_output_format),
                    },
                }
            )

            # Persistir histórico completo e vincular ao token usage
            request_id = self._extract_response_request_id(response)
            token_usage_id = self._find_token_usage_id_for_request(
                action_name="review_petition_single_version",
                law_firm_id=law_firm_id,
                request_id=request_id,
            )
            AgentExecutionHistoryService.save_execution_history(
                agent_name="FapPetitionReviewerAgent",
                action_name="review_petition_single_version",
                agent_type="fap_review_reviewer",
                system_prompt=system_prompt,
                user_prompt=user_message,
                model_response=response_text,
                full_messages_history=[*messages, response],
                result_data={
                    "execution_id": execution_id,
                    "analysis_type": "single_version",
                    "mode": "file_attachment",
                    "petition_file_name": self._extract_file_name(petition_file_path),
                },
                model_name=self.model_name,
                model_provider="openai",
                status="success",
                user_id=user_id,
                law_firm_id=law_firm_id,
                chat_session_id=None,
                agent_token_usage_id=token_usage_id,
            )

            result_dict = self._extract_json_dict_from_response(response_text)
            
            # Criar resultado com dados salvaguardados
            result = PetitionReviewResult(
                analysis_type="single_version",
                tokens_used=total_tokens or None,
                cost_usd=float(total_cost) if total_cost else None,
                theses=self._parse_theses(result_dict.get('theses', [])),
                findings=self._parse_findings(result_dict.get('findings', [])),
                missing_documents=self._parse_missing_documents(result_dict.get('missing_documents', [])),
                executive_summary=self._parse_executive_summary(result_dict.get('executive_summary', {})),
                new_patterns=self._parse_new_patterns(result_dict.get('new_patterns', [])),
            )
            
            return result
            
        except Exception as e:
            # Fallback em caso de erro
            return PetitionReviewResult(
                analysis_type="single_version",
                executive_summary=ExecutiveSummary(
                    total_findings=0,
                    critical_findings=0,
                    moderate_findings=0,
                    formal_findings=0,
                    correction_priority="Erro na análise"
                )
            )

    async def review_petition_comparative(self,
                                         original_petition_file_path: str,
                                         revised_petition_file_path: str,
                                         auxiliary_documents: list[dict] = None,
                                         reviewer_identity: str = "",
                                         reviewer_rules: str = "",
                                         reviewer_output_format: str = "",
                                         execution_id: int | None = None,
                                         user_id: int | None = None,
                                         law_firm_id: int | None = None) -> PetitionReviewResult:
        """
        Realiza análise comparativa entre duas versões de petição
        
        Args:
            original_petition_file_path: Caminho da versão original da petição
            revised_petition_file_path: Caminho da versão revisada da petição
            auxiliary_documents: Documentos auxiliares opcionais
            reviewer_identity: Identidade do revisor
            reviewer_rules: Regras do revisor
            reviewer_output_format: Formato de saída
            
        Returns:
            Resultado estruturado da análise comparativa
        """
        system_prompt = self._build_system_prompt(
            reviewer_identity,
            reviewer_rules,
            reviewer_output_format,
        )
        
        try:
            original_file_part = self._build_file_part_for_message(original_petition_file_path)
            revised_file_part = self._build_file_part_for_message(revised_petition_file_path)

            user_message = self._build_comparative_user_message(
                auxiliary_documents=auxiliary_documents,
            )

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=[
                    {
                        "type": "text",
                        "text": user_message,
                    },
                    original_file_part,
                    revised_file_part,
                ])
            ]

            start_time = time.time()
            response = self.llm.invoke(messages)
            latency_ms = int((time.time() - start_time) * 1000)
            response_text = response.content

            # Capturar e persistir logs de tokens
            response_payload = self._build_response_payload(response)
            token_entries = self.token_usage_service.extract_entries(
                response_payload,
                model_name=self.model_name,
            )
            total_tokens = sum(entry.total_tokens for entry in token_entries)
            total_cost = sum((entry.estimated_cost_usd for entry in token_entries), Decimal("0"))
            self.token_usage_service.capture_and_store(
                response_payload,
                agent_name="FapPetitionReviewerAgent",
                action_name="review_petition_comparative",
                print_prefix="[FapReviewer]",
                model_name=self.model_name,
                model_provider="openai",
                latency_ms=latency_ms,
                metadata_payload={
                    "original_petition_file_path": original_petition_file_path,
                    "revised_petition_file_path": revised_petition_file_path,
                    "original_file_name": self._extract_file_name(original_petition_file_path),
                    "revised_file_name": self._extract_file_name(revised_petition_file_path),
                    "auxiliary_documents_count": len(auxiliary_documents or []),
                    "mode": "file_attachment",
                    "llm_input": {
                        "system_prompt": self._truncate_for_log(system_prompt),
                        "user_prompt": self._truncate_for_log(user_message),
                    },
                    "prompt_versions": {
                        "reviewer_identity": self._truncate_for_log(reviewer_identity),
                        "reviewer_rules": self._truncate_for_log(reviewer_rules),
                        "reviewer_output_format": self._truncate_for_log(reviewer_output_format),
                    },
                }
            )

            # Persistir histórico completo e vincular ao token usage
            request_id = self._extract_response_request_id(response)
            token_usage_id = self._find_token_usage_id_for_request(
                action_name="review_petition_comparative",
                law_firm_id=law_firm_id,
                request_id=request_id,
            )
            AgentExecutionHistoryService.save_execution_history(
                agent_name="FapPetitionReviewerAgent",
                action_name="review_petition_comparative",
                agent_type="fap_review_reviewer",
                system_prompt=system_prompt,
                user_prompt=user_message,
                model_response=response_text,
                full_messages_history=[*messages, response],
                result_data={
                    "execution_id": execution_id,
                    "analysis_type": "comparative",
                    "mode": "file_attachment",
                    "original_file_name": self._extract_file_name(original_petition_file_path),
                    "revised_file_name": self._extract_file_name(revised_petition_file_path),
                },
                model_name=self.model_name,
                model_provider="openai",
                status="success",
                user_id=user_id,
                law_firm_id=law_firm_id,
                chat_session_id=None,
                agent_token_usage_id=token_usage_id,
            )

            result_dict = self._extract_json_dict_from_response(response_text)
            
            result = PetitionReviewResult(
                analysis_type="comparative",
                tokens_used=total_tokens or None,
                cost_usd=float(total_cost) if total_cost else None,
                comparative_changes=self._parse_comparative_changes(result_dict.get('comparative_changes', [])),
                findings=self._parse_findings(result_dict.get('findings', [])),
                new_patterns=self._parse_new_patterns(result_dict.get('new_patterns', [])),
                executive_summary=self._parse_executive_summary(result_dict.get('executive_summary', {})),
            )
            
            return result
            
        except Exception as e:
            return PetitionReviewResult(
                analysis_type="comparative",
                executive_summary=ExecutiveSummary(
                    total_findings=0,
                    critical_findings=0,
                    moderate_findings=0,
                    formal_findings=0,
                    correction_priority="Erro na análise"
                )
            )

    # Métodos auxiliares para parsing
    
    def _parse_theses(self, data: list) -> list[IdentifiedThesis]:
        """Parse lista de teses"""
        result = []
        try:
            for item in data:
                if isinstance(item, dict):
                    result.append(IdentifiedThesis(**item))
        except Exception:
            pass
        return result

    def _parse_findings(self, data: list) -> list[FindingItem]:
        """Parse lista de achados"""
        result = []
        try:
            for item in data:
                if isinstance(item, dict):
                    result.append(FindingItem(**item))
        except Exception:
            pass
        return result

    def _parse_missing_documents(self, data: list) -> list[MissingDocument]:
        """Parse lista de documentos em falta"""
        result = []
        try:
            for item in data:
                if isinstance(item, dict):
                    result.append(MissingDocument(**item))
        except Exception:
            pass
        return result

    def _parse_new_patterns(self, data: list) -> list[NewPattern]:
        """Parse lista de padrões novos"""
        result = []
        try:
            for item in data:
                if isinstance(item, dict):
                    result.append(NewPattern(**item))
        except Exception:
            pass
        return result

    def _parse_comparative_changes(self, data: list) -> list[ComparativeAnalysisChange]:
        """Parse lista de alterações comparativas"""
        result = []
        try:
            for item in data:
                if isinstance(item, dict):
                    result.append(ComparativeAnalysisChange(**item))
        except Exception:
            pass
        return result

    def _parse_executive_summary(self, data: dict) -> ExecutiveSummary:
        """Parse resumo executivo"""
        try:
            return ExecutiveSummary(**data)
        except Exception:
            return ExecutiveSummary(
                total_findings=0,
                critical_findings=0,
                moderate_findings=0,
                formal_findings=0,
                correction_priority="N/A"
            )

    def _build_response_payload(self, response: Any) -> dict[str, Any]:
        """
        Converte a resposta do LangChain em payload esperado pelo TokenUsageService
        
        Args:
            response: Resposta do LLM (AIMessage ou similar)
            
        Returns:
            Dict com estrutura {"messages": [response]}
        """
        return {"messages": [response]}

    def _split_text_into_chunks(self, text: str) -> list[dict[str, str]]:
        """Divide texto em blocos de seção e, se necessário, subchunks com sobreposição."""
        if not text:
            return [{"section": "Documento vazio", "text": ""}]

        text = str(text)
        max_chars = max(1000, self._REVIEW_CHUNK_MAX_CHARS)
        overlap = max(0, min(self._REVIEW_CHUNK_OVERLAP_CHARS, max_chars // 2))

        section_blocks = self._split_text_into_sections(text)
        chunks: list[dict[str, str]] = []

        for block in section_blocks:
            section_name = str(block.get("section") or "Seção não identificada")
            section_text = str(block.get("text") or "")

            if len(section_text) <= max_chars:
                if section_text.strip():
                    chunks.append({"section": section_name, "text": section_text})
                continue

            part_texts: list[str] = []
            start = 0
            while start < len(section_text):
                end = min(start + max_chars, len(section_text))
                chunk = section_text[start:end]
                if chunk.strip():
                    part_texts.append(chunk)
                if end >= len(section_text):
                    break
                start = max(0, end - overlap)

            total_parts = len(part_texts)
            for part_idx, part in enumerate(part_texts, start=1):
                label = f"{section_name} (parte {part_idx}/{total_parts})" if total_parts > 1 else section_name
                chunks.append({"section": label, "text": part})

        return chunks or [{"section": "Documento completo", "text": text}]

    def _split_text_into_sections(self, text: str) -> list[dict[str, str]]:
        """Separa texto por títulos numerados de seção (formato markdown/jurídico)."""
        heading_pattern = re.compile(r'(?m)^(?:#{1,3}[ \t]+)?(\d+\.[ \t]+[^\n]+)$')
        matches = list(heading_pattern.finditer(text))

        valid_matches: list[re.Match[str]] = []
        for match in matches:
            candidate = str(match.group(1) or "").strip()
            if self._is_valid_section_title(candidate):
                valid_matches.append(match)

        if not valid_matches:
            return [{"section": "Documento completo", "text": text}]

        sections: list[dict[str, str]] = []

        first_start = valid_matches[0].start()
        if first_start > 0:
            preamble = text[:first_start].strip()
            if preamble:
                sections.append({"section": "Preâmbulo", "text": preamble})

        for idx, match in enumerate(valid_matches):
            start = match.start()
            end = valid_matches[idx + 1].start() if idx + 1 < len(valid_matches) else len(text)
            section_text = text[start:end].strip()
            section_title = str(match.group(1) or "").strip()

            if section_text:
                sections.append({"section": section_title, "text": section_text})

        return sections or [{"section": "Documento completo", "text": text}]

    def _is_valid_section_title(self, candidate: str) -> bool:
        """Filtra falsos positivos de seção para evitar quebra indevida de chunks."""
        title = " ".join(str(candidate or "").strip().split())
        if not title:
            return False

        if len(title) > self._SECTION_TITLE_MAX_CHARS:
            return False

        if re.search(r'\.{3,}\s*\d+\s*$', title):
            return False

        if re.search(r'["“”]|\(p\.\s*\d+|RE\s*n[ºo]', title, re.IGNORECASE):
            return False

        letters = [ch for ch in title if ch.isalpha()]
        if letters and len(letters) >= 20:
            upper_count = sum(1 for ch in letters if ch.isupper())
            lower_count = sum(1 for ch in letters if ch.islower())
            if lower_count > upper_count:
                return False

        if len(title) > 80 and title.count(",") >= 2:
            return False

        return True

    def _format_auxiliary_documents(self, auxiliary_documents: list[dict] | None) -> str:
        """Monta resumo enxuto dos documentos auxiliares para manter contexto sem poluir prompt."""
        if not auxiliary_documents:
            return ""

        docs = auxiliary_documents[:self._AUX_PREVIEW_LIMIT]
        names = []
        for doc in docs:
            if isinstance(doc, dict):
                names.append(str(doc.get("name") or "arquivo_sem_nome"))
            else:
                names.append(str(doc))

        suffix = ""
        if len(auxiliary_documents) > len(docs):
            suffix = f" (+{len(auxiliary_documents) - len(docs)} arquivos)"

        return f"DOCUMENTOS AUXILIARES ({len(auxiliary_documents)} arquivos){suffix}: " + ", ".join(names)

    def _build_single_user_message(
        self,
        *,
        auxiliary_documents: list[dict] | None,
    ) -> str:
        aux_text = self._format_auxiliary_documents(auxiliary_documents)
        return f"""Revise esta petição inicial de FAP contra o manual.

PETIÇÃO A REVISAR:
O documento foi enviado como anexo de arquivo nesta mensagem.

{aux_text}

Identifique:
1. Todas as inconsistências com o manual
2. Erros críticos, moderados e formais
3. Documentos obrigatórios em falta
4. Padrões novos não cobertos pelo manual
5. Riscos jurídicos

Estruture a resposta em JSON válido com a seguinte estrutura:
- theses (array de teses identificadas)
- findings (array de achados)
- missing_documents (array de documentos em falta)
- executive_summary (resumo executivo)
- new_patterns (padrões novos)"""

    def _build_comparative_user_message(
        self,
        *,
        auxiliary_documents: list[dict] | None,
    ) -> str:
        aux_text = self._format_auxiliary_documents(auxiliary_documents)
        return f"""Revise comparativamente estas duas versões de petição de FAP.

As duas versões (original e revisada) foram enviadas como anexos de arquivo nesta mensagem.

{aux_text}

Para cada alteração identificada:
1. Transcreva trecho original e corrigido
2. Explique motivo da correção
3. Indique se padrão já existe no manual
4. Indique se é padrão novo

Estruture em JSON com:
- comparative_changes (array de alterações)
- findings (achados gerais)
- new_patterns (padrões novos)
- executive_summary (resumo)"""

    def _build_file_part_for_message(self, file_path: str) -> dict[str, Any]:
        """Monta o bloco de arquivo no formato aceito pelo OpenRouter."""
        path = str(file_path or "").strip()
        if not path:
            raise ValueError("Caminho de arquivo inválido")

        # URLs públicas também são válidas para OpenRouter.
        if path.startswith("http://") or path.startswith("https://"):
            return self.file_agent.build_openrouter_file_part(path)

        if not Path(path).exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {path}")
        return self.file_agent.build_openrouter_file_part(path)

    def _extract_file_name(self, file_path: str) -> str:
        """Extrai nome amigável de arquivo para logs/metadados."""
        path = str(file_path or "").strip()
        if not path:
            return ""
        if path.startswith("http://") or path.startswith("https://"):
            return path.rstrip("/").split("/")[-1]
        return Path(path).name

    def _extract_json_dict_from_response(self, response_text: str) -> dict:
        """Extrai JSON da resposta textual do modelo."""
        if not isinstance(response_text, str) or not response_text.strip():
            return {}

        try:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start != -1 and json_end > json_start:
                parsed = json.loads(response_text[json_start:json_end])
                return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

        return {}

    def _merge_unique_dict_items(self, all_dicts: list[dict], key: str) -> list[dict]:
        """Une listas de dicts removendo duplicidades por serialização JSON estável."""
        unique: dict[str, dict] = {}
        for item_dict in all_dicts:
            items = item_dict.get(key, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if signature not in unique:
                    unique[signature] = item
        return list(unique.values())

    def _merge_result_dicts(self, all_dicts: list[dict]) -> dict:
        """Consolida resultados de múltiplos chunks em um único dicionário."""
        merged: dict[str, Any] = {
            "theses": self._merge_unique_dict_items(all_dicts, "theses"),
            "findings": self._merge_unique_dict_items(all_dicts, "findings"),
            "missing_documents": self._merge_unique_dict_items(all_dicts, "missing_documents"),
            "new_patterns": self._merge_unique_dict_items(all_dicts, "new_patterns"),
            "comparative_changes": self._merge_unique_dict_items(all_dicts, "comparative_changes"),
        }

        total = len(merged["findings"])
        critical = 0
        moderate = 0
        formal = 0
        for finding in merged["findings"]:
            sev = str(finding.get("severity") or "").upper()
            if "CRÍTICO" in sev or "CRITICO" in sev:
                critical += 1
            elif "MODERADO" in sev:
                moderate += 1
            else:
                formal += 1

        merged["executive_summary"] = {
            "total_findings": total,
            "critical_findings": critical,
            "moderate_findings": moderate,
            "formal_findings": formal,
            "main_legal_risks": [],
            "correction_priority": "ALTA" if critical > 0 else "MÉDIA" if moderate > 0 else "BAIXA",
        }

        return merged

    def _truncate_for_log(self, text: str, max_chars: int | None = None) -> str:
        """Limita payload textual para evitar metadados gigantes no banco."""
        if not isinstance(text, str):
            return ""
        limit = max_chars or self._PROMPT_LOG_MAX_CHARS
        if len(text) <= limit:
            return text
        return f"{text[:limit]}\n\n...[truncated {len(text) - limit} chars]"

    def _extract_response_request_id(self, response: Any) -> str:
        """Extrai request_id/id da resposta do modelo quando disponível."""
        response_id = getattr(response, "id", None)
        if isinstance(response_id, str) and response_id.strip():
            return response_id.strip()

        response_metadata = getattr(response, "response_metadata", None)
        if isinstance(response_metadata, dict):
            request_id = response_metadata.get("request_id") or response_metadata.get("id")
            if isinstance(request_id, str) and request_id.strip():
                return request_id.strip()

        return ""

    def _find_token_usage_id_for_request(
        self,
        *,
        action_name: str,
        law_firm_id: int | None,
        request_id: str,
    ) -> int | None:
        """Localiza o último token usage do agente para vincular histórico detalhado."""
        query = AgentTokenUsage.query.filter_by(
            agent_name="FapPetitionReviewerAgent",
            action_name=action_name,
        )

        if law_firm_id is not None:
            query = query.filter_by(law_firm_id=law_firm_id)

        if request_id:
            query = query.filter_by(request_id=request_id)

        row = query.order_by(AgentTokenUsage.id.desc()).first()
        return row.id if row else None
