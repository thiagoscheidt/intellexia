"""
Agente Revisor de Petições FAP - FapPetitionReviewerAgent

Responsabilidade: Revisar petições iniciais de Ação Revisional FAP e identificar
inconsistências, erros, riscos jurídicos e divergências em relação ao manual.

Este agente NÃO atualiza diretamente:
- manuais
- casos de referência
- base oficial de conhecimento

O aprendizado e a evolução de conhecimento pertencem exclusivamente ao módulo de treinamento.
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


class ReviewOutputParseError(Exception):
    """Resposta do modelo não pôde ser convertida no schema esperado da revisão."""


class FindingItem(BaseModel):
    """Um achado identificado na petição"""
    category: str = Field(..., description="Categoria do achado: CAT-1 a CAT-6, CRITICAL, MODERATE, FORMAL")
    severity: str = Field(..., description="Gravidade: CRÍTICO, MODERADO, FORMAL")
    description: str = Field(..., description="Descrição do achado")
    location: Optional[str] = Field(None, description="Localização na petição")
    location_excerpt: Optional[str] = Field(
        None,
        description="Trecho literal curto (10 a 30 palavras) copiado do documento onde o problema está",
    )
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
    focused_review: bool = Field(False, description="Indica se a revisão usou histórico do mesmo identificador")
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
    _NO_ACTIVE_PRIOR_ATTENTION_MARKER = '__NO_ACTIVE_PRIOR_ATTENTION_POINTS__'

    _OUTPUT_SCHEMA_SINGLE = """{
  "theses": [
    {"thesis": "nome da tese identificada", "benefit_number": "número do benefício ou null", "classification": "enquadramento identificado ou null"}
  ],
  "findings": [
    {"category": "categoria do achado (ex.: CAT-1 a CAT-6, CRITICAL, MODERATE, FORMAL)", "severity": "CRÍTICO | MODERADO | FORMAL", "description": "descrição do achado", "location": "localização na petição ou null", "location_excerpt": "trecho LITERAL curto (10 a 30 palavras) COPIADO EXATAMENTE do texto do documento onde o problema está — sem parafrasear; null se não houver trecho específico", "correction": "sugestão de correção ou null", "manual_reference": "seção do manual relacionada ou null", "is_new_pattern": false}
  ],
  "missing_documents": [
    {"document_type": "tipo de documento obrigatório ausente", "thesis": "tese relacionada ou null", "manual_reference": "referência do manual ou null"}
  ],
  "executive_summary": {"total_findings": 0, "critical_findings": 0, "moderate_findings": 0, "formal_findings": 0, "main_legal_risks": ["risco jurídico"], "correction_priority": "prioridade de correção"}
}"""

    _OUTPUT_SCHEMA_COMPARATIVE = """{
  "comparative_changes": [
    {"original_excerpt": "trecho original", "corrected_excerpt": "trecho corrigido", "correction_reason": "motivo da correção", "pattern_in_manual": false, "is_new_pattern": false, "manual_section": "seção do manual ou null"}
  ],
  "findings": [
    {"category": "categoria do achado (ex.: CAT-1 a CAT-6, CRITICAL, MODERATE, FORMAL)", "severity": "CRÍTICO | MODERADO | FORMAL", "description": "descrição do achado", "location": "localização na petição ou null", "location_excerpt": "trecho LITERAL curto (10 a 30 palavras) COPIADO EXATAMENTE do texto do documento onde o problema está — sem parafrasear; null se não houver trecho específico", "correction": "sugestão de correção ou null", "manual_reference": "seção do manual relacionada ou null", "is_new_pattern": false}
  ],
  "executive_summary": {"total_findings": 0, "critical_findings": 0, "moderate_findings": 0, "formal_findings": 0, "main_legal_risks": ["risco jurídico"], "correction_priority": "prioridade de correção"}
}"""

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
        focused_review: bool = False,
        comparative: bool = False,
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
        output_schema = self._OUTPUT_SCHEMA_COMPARATIVE if comparative else self._OUTPUT_SCHEMA_SINGLE
        base_system = f"""Você é um revisor especializado em petições iniciais de Ação Revisional do FAP.

IDENTIDADE:
{reviewer_identity or 'Revise petições de FAP com rigor jurídico'}

REGRAS INVIOLÁVEIS:
{reviewer_rules or 'Aplique todas as regras do manual'}

FORMATO DE SAÍDA:
{reviewer_output_format or 'Estruture a resposta em seções claras'}

CONTRATO TÉCNICO DE SAÍDA (OBRIGATÓRIO, prevalece sobre qualquer outra instrução de formato):
Responda EXCLUSIVAMENTE com um único JSON válido, sem nenhum texto fora do JSON e sem cercas de código.
Use EXATAMENTE os nomes de campos abaixo (em inglês); os valores devem ser escritos em português. Campos opcionais podem ser null.
{output_schema}

INSTRUÇÕES OPERACIONAIS:
Ao revisar a petição, valide estritamente com base no MANUAL DE REFERÊNCIA.
Em caso de divergência entre qualquer instrução e o manual, o manual prevalece.
Não invente critérios fora do manual.
{('\n\nMODO DE REVISÃO FOCADA:\nHá pontos de atenção de revisão anterior fornecidos pelo usuário. Nesta execução, não faça uma varredura integral do manual. Use o manual apenas para validar esses pontos já identificados e a checagem obrigatória de consistência do nome da empresa. Não abra novos achados fora desse escopo, salvo divergência atual de razão social.') if focused_review else ''}

VERIFICAÇÃO OBRIGATÓRIA — CONSISTÊNCIA DO NOME DA EMPRESA (prioridade máxima):
Em TODA revisão, independentemente de outras regras e antes de qualquer outra análise, você DEVE:
1. Identificar a razão social exata da empresa autora conforme consta na qualificação inicial (cabeçalho da petição).
2. Varrer TODO o documento — qualificação, síntese fática, pedidos, tabelas, notas de rodapé, trechos de contestação e exemplos — e verificar se o nome da empresa aparece grafado de forma IDÊNTICA em todas as ocorrências.
3. Qualquer divergência de grafia (letras trocadas, suprimidas, acrescidas ou trocadas de ordem) deve ser reportada como achado de gravidade CRÍTICO, indicando a grafia correta, a grafia incorreta encontrada e a localização exata (seção e parágrafo) de cada ocorrência divergente.
4. O mesmo critério se aplica à abreviatura societária (ex.: "S.A." vs "S/A" vs "SA") — deve ser uniforme em todo o documento.
5. Se NÃO houver divergência, NÃO crie achado sobre razão social. A consistência do nome deve permanecer silenciosa e não pode aparecer em findings, resumo executivo ou alertas.
Exemplos de erros típicos: "WHIRLPOOL" grafado como "WHIRPOOL"; "AMBEV S.A." como "AMBEV SA"; nome com letra acentuada vs. sem acento.
Esta verificação NÃO PODE ser omitida em nenhuma hipótese.

MANUAL DE REFERÊNCIA:
{self.manual_content if self.manual_content else 'Manual não carregado'}

CASOS DE REFERÊNCIA:
{self.cases_content if self.cases_content else 'Casos não carregados'}

INSTRUÇÕES DO PROJETO:
{self.project_instructions if self.project_instructions else 'Instruções não carregadas'}"""
        
        return base_system

    async def review_petition_single_version(self,
                                            petition_file_path: str,
                                            petition_text: str | None = None,
                                            prior_attention_points: str | None = None,
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
            focused_review=bool(prior_attention_points),
        )
        
        try:
            user_message = self._build_single_user_message(
                auxiliary_documents=auxiliary_documents,
                petition_text=petition_text,
                prior_attention_points=prior_attention_points,
            )

            if petition_text:
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_message),
                ]
                analysis_mode = "extracted_text"
            else:
                petition_file_part = self._build_file_part_for_message(petition_file_path)
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
                analysis_mode = "file_attachment"

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
                    "focused_review": bool(prior_attention_points),
                    "mode": analysis_mode,
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
                    "focused_review": bool(prior_attention_points),
                    "mode": analysis_mode,
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

            parse_errors: list[str] = []
            theses = self._parse_theses(result_dict.get('theses', []), parse_errors)
            findings = self._parse_findings(result_dict.get('findings', []), parse_errors)
            missing_documents = self._parse_missing_documents(result_dict.get('missing_documents', []), parse_errors)
            self._ensure_output_parsed(
                result_dict,
                parsed_items=len(theses) + len(findings) + len(missing_documents),
                list_keys=('theses', 'findings', 'missing_documents'),
                parse_errors=parse_errors,
            )

            # Criar resultado com dados salvaguardados
            result = PetitionReviewResult(
                analysis_type="single_version",
                focused_review=bool(prior_attention_points),
                tokens_used=total_tokens or None,
                cost_usd=float(total_cost) if total_cost else None,
                theses=theses,
                findings=findings,
                missing_documents=missing_documents,
                executive_summary=self._build_executive_summary(
                    result_dict.get('executive_summary', {}), findings),
                new_patterns=[],
            )

            return result

        except ReviewOutputParseError:
            raise
        except Exception as e:
            # Fallback em caso de erro
            return PetitionReviewResult(
                analysis_type="single_version",
                focused_review=bool(prior_attention_points),
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
                                         original_petition_text: str | None = None,
                                         revised_petition_text: str | None = None,
                                         prior_attention_points: str | None = None,
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
            focused_review=bool(prior_attention_points),
            comparative=True,
        )

        try:
            user_message = self._build_comparative_user_message(
                auxiliary_documents=auxiliary_documents,
                original_petition_text=original_petition_text,
                revised_petition_text=revised_petition_text,
                prior_attention_points=prior_attention_points,
                original_file_name=self._extract_file_name(original_petition_file_path),
                revised_file_name=self._extract_file_name(revised_petition_file_path),
            )

            human_content: list[Any] = [
                {
                    "type": "text",
                    "text": user_message,
                }
            ]
            analysis_mode = "file_attachment"

            if not original_petition_text:
                human_content.append(self._build_file_part_for_message(original_petition_file_path))
            else:
                analysis_mode = "hybrid_text"

            if not revised_petition_text:
                human_content.append(self._build_file_part_for_message(revised_petition_file_path))
            else:
                analysis_mode = "hybrid_text"

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_content if len(human_content) > 1 else user_message),
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
                    "focused_review": bool(prior_attention_points),
                    "mode": analysis_mode,
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
                    "focused_review": bool(prior_attention_points),
                    "mode": analysis_mode,
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

            parse_errors: list[str] = []
            comparative_changes = self._parse_comparative_changes(result_dict.get('comparative_changes', []), parse_errors)
            findings = self._parse_findings(result_dict.get('findings', []), parse_errors)
            self._ensure_output_parsed(
                result_dict,
                parsed_items=len(comparative_changes) + len(findings),
                list_keys=('comparative_changes', 'findings'),
                parse_errors=parse_errors,
            )

            result = PetitionReviewResult(
                analysis_type="comparative",
                focused_review=bool(prior_attention_points),
                tokens_used=total_tokens or None,
                cost_usd=float(total_cost) if total_cost else None,
                comparative_changes=comparative_changes,
                findings=findings,
                new_patterns=[],
                executive_summary=self._build_executive_summary(
                    result_dict.get('executive_summary', {}), findings),
            )

            return result

        except ReviewOutputParseError:
            raise
        except Exception as e:
            return PetitionReviewResult(
                analysis_type="comparative",
                focused_review=bool(prior_attention_points),
                executive_summary=ExecutiveSummary(
                    total_findings=0,
                    critical_findings=0,
                    moderate_findings=0,
                    formal_findings=0,
                    correction_priority="Erro na análise"
                )
            )

    # Métodos auxiliares para parsing
    
    def _parse_model_items(self, data: list, model_cls: type[BaseModel], label: str,
                           parse_errors: list[str] | None = None) -> list:
        """Valida itens um a um; item inválido é logado e coletado, sem derrubar os demais."""
        result = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                result.append(model_cls(**item))
            except Exception as exc:
                message = f"{label} descartado por schema inválido (chaves: {sorted(item.keys())}): {exc}"
                print(f"[FapReviewer] {message}")
                if parse_errors is not None:
                    parse_errors.append(message)
        return result

    def _parse_theses(self, data: list, parse_errors: list[str] | None = None) -> list[IdentifiedThesis]:
        """Parse lista de teses"""
        return self._parse_model_items(data, IdentifiedThesis, "thesis", parse_errors)

    def _parse_findings(self, data: list, parse_errors: list[str] | None = None) -> list[FindingItem]:
        """Parse lista de achados"""
        items = [
            item for item in (data if isinstance(data, list) else [])
            if not (isinstance(item, dict) and self._should_ignore_finding(item))
        ]
        return self._parse_model_items(items, FindingItem, "finding", parse_errors)

    def _normalize_review_text(self, value: Any) -> str:
        """Normaliza texto para heurísticas simples de saneamento do output do modelo."""
        text = str(value or "").strip().lower()
        return " ".join(text.split())

    def _should_ignore_finding(self, item: dict[str, Any]) -> bool:
        """Descarta falsos positivos em que o modelo marcou como achado algo explicitamente sem problema."""
        haystack = " ".join(
            self._normalize_review_text(item.get(field))
            for field in ("category", "description", "location", "correction", "manual_reference")
        )

        if not haystack:
            return False

        mentions_company_name = any(
            token in haystack
            for token in (
                "razao social",
                "razão social",
                "nome da empresa",
                "nome da autora",
                "empresa autora",
            )
        )
        if not mentions_company_name:
            return False

        indicates_no_issue = any(
            token in haystack
            for token in (
                "sem divergencia",
                "sem divergências",
                "sem divergencia detectada",
                "sem divergências detectadas",
                "nao ha divergencia",
                "não há divergência",
                "nenhuma divergencia",
                "nenhuma divergência",
                "grafada de forma consistente",
                "grafado de forma consistente",
                "consistente em todo o documento",
                "sem problema",
                "sem inconsistencias",
                "sem inconsistências",
            )
        )
        if not indicates_no_issue:
            return False

        return True

    def _parse_missing_documents(self, data: list, parse_errors: list[str] | None = None) -> list[MissingDocument]:
        """Parse lista de documentos em falta"""
        return self._parse_model_items(data, MissingDocument, "missing_document", parse_errors)

    def _parse_new_patterns(self, data: list, parse_errors: list[str] | None = None) -> list[NewPattern]:
        """Parse lista de padrões novos"""
        return self._parse_model_items(data, NewPattern, "new_pattern", parse_errors)

    def _parse_comparative_changes(self, data: list, parse_errors: list[str] | None = None) -> list[ComparativeAnalysisChange]:
        """Parse lista de alterações comparativas"""
        return self._parse_model_items(data, ComparativeAnalysisChange, "comparative_change", parse_errors)

    def _ensure_output_parsed(self, result_dict: dict, *, parsed_items: int,
                              list_keys: tuple[str, ...], parse_errors: list[str]) -> None:
        """Falha alto quando a resposta do modelo não pôde ser aproveitada.

        Sem isso, uma resposta fora do schema vira revisão "concluída" com zero
        achados — indistinguível de uma petição sem problemas.
        """
        if not result_dict:
            raise ReviewOutputParseError(
                "A resposta do modelo não contém JSON válido para a revisão."
            )
        raw_items = sum(
            len(value) for key in list_keys
            if isinstance((value := result_dict.get(key)), list)
        )
        if raw_items and not parsed_items:
            details = "; ".join(parse_errors[:3]) or "sem detalhes"
            raise ReviewOutputParseError(
                f"A resposta do modelo retornou {raw_items} itens, mas nenhum segue o "
                f"schema esperado da revisão. Erros: {details}"
            )

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

    def _build_executive_summary(self, data: dict, findings: list[FindingItem]) -> ExecutiveSummary:
        """Resumo executivo com totais recontados dos achados efetivamente mantidos.

        O modelo conta os próprios achados, mas o saneamento (ex.: falso positivo
        de razão social) pode descartar itens — sem a recontagem, a tela mostraria
        "1 crítico" com lista sem nenhum.
        """
        summary = self._parse_executive_summary(data)
        severities = [str(f.severity or "").strip().upper() for f in findings]
        summary.total_findings = len(findings)
        summary.critical_findings = sum(1 for s in severities if s == "CRÍTICO")
        summary.moderate_findings = sum(1 for s in severities if s == "MODERADO")
        summary.formal_findings = sum(
            1 for s in severities if s not in ("CRÍTICO", "MODERADO")
        )
        return summary

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
        petition_text: str | None = None,
        prior_attention_points: str | None = None,
    ) -> str:
        aux_text = self._format_auxiliary_documents(auxiliary_documents)
        petition_source = (
            "O conteúdo textual extraído da petição segue abaixo nesta mensagem."
            if petition_text else
            "O documento foi enviado como anexo de arquivo nesta mensagem."
        )
        petition_body = f"\n\nTEXTO DA PETIÇÃO:\n{petition_text}" if petition_text else ""
        if prior_attention_points and prior_attention_points.startswith(self._NO_ACTIVE_PRIOR_ATTENTION_MARKER):
            return f"""Revise esta nova versão de uma petição inicial de FAP já analisada anteriormente.

PETIÇÃO A REVISAR:
{petition_source}

{petition_body}

{aux_text}

CONTEXTO DO HISTÓRICO:
Os pontos de atenção anteriores deste identificador foram marcados pelo usuário como não úteis e não devem ser cobrados novamente.

OBJETIVO DESTA REVISÃO FOCADA:
1. Não reabra pontos de atenção antigos marcados como não úteis.
2. Não faça nova varredura geral do manual nem gere novos achados fora desse escopo.
3. Exceção obrigatória: continue validando a consistência do nome da empresa em todo o documento e reporte divergências atuais como CRÍTICO.

Estruture a resposta em JSON válido com a seguinte estrutura:
- theses (array de teses identificadas)
- findings (array de achados; deixe vazio se não houver divergência atual de razão social)
- missing_documents (array de documentos em falta; deixe vazio)
- executive_summary (resumo executivo)"""

        if prior_attention_points:
            return f"""Revise esta nova versão de uma petição inicial de FAP já analisada anteriormente.

PETIÇÃO A REVISAR:
{petition_source}

{petition_body}

{aux_text}

PONTOS DE ATENÇÃO IDENTIFICADOS NA REVISÃO ANTERIOR:
{prior_attention_points}

OBJETIVO DESTA REVISÃO FOCADA:
1. Verifique se cada ponto de atenção acima foi corrigido na versão atual.
2. Se um ponto permanecer pendente, reporte-o em findings com localização atual e correção esperada.
3. Se um ponto tiver sido resolvido, não o reporte novamente.
4. Não faça nova varredura geral do manual nem gere novos achados fora dessa lista.
5. Exceção obrigatória: continue validando a consistência do nome da empresa em todo o documento e reporte divergências atuais como CRÍTICO.

Estruture a resposta em JSON válido com a seguinte estrutura:
- theses (array de teses identificadas)
- findings (array de achados ainda pendentes na nova versão)
- missing_documents (array de documentos ainda em falta)
- executive_summary (resumo executivo)"""

        return f"""Revise esta petição inicial de FAP contra o manual.

PETIÇÃO A REVISAR:
{petition_source}

{petition_body}

{aux_text}

Identifique:
1. CONSISTÊNCIA DO NOME DA EMPRESA — verifique se a razão social da empresa autora está grafada de forma IDÊNTICA em TODAS as ocorrências do documento (qualificação, corpo, tabelas, notas, pedidos). Reporte qualquer divergência como CRÍTICO com a localização exata.
Se a razão social estiver consistente em todo o documento, não gere finding nem alerta sobre esse ponto.
2. Todas as demais inconsistências com o manual
3. Erros críticos, moderados e formais
4. Documentos obrigatórios em falta
5. Riscos jurídicos

Estruture a resposta em JSON válido com a seguinte estrutura:
- theses (array de teses identificadas)
- findings (array de achados)
- missing_documents (array de documentos em falta)
- executive_summary (resumo executivo)"""

    def _build_comparative_user_message(
        self,
        *,
        auxiliary_documents: list[dict] | None,
        original_petition_text: str | None = None,
        revised_petition_text: str | None = None,
        prior_attention_points: str | None = None,
        original_file_name: str = "",
        revised_file_name: str = "",
    ) -> str:
        aux_text = self._format_auxiliary_documents(auxiliary_documents)
        original_source = (
            f"VERSÃO ORIGINAL ({original_file_name or 'documento original'}) enviada como texto extraído abaixo."
            if original_petition_text else
            f"VERSÃO ORIGINAL ({original_file_name or 'documento original'}) enviada como anexo de arquivo nesta mensagem."
        )
        revised_source = (
            f"VERSÃO REVISADA ({revised_file_name or 'documento revisado'}) enviada como texto extraído abaixo."
            if revised_petition_text else
            f"VERSÃO REVISADA ({revised_file_name or 'documento revisado'}) enviada como anexo de arquivo nesta mensagem."
        )
        original_body = f"\n\nTEXTO DA VERSÃO ORIGINAL:\n{original_petition_text}" if original_petition_text else ""
        revised_body = f"\n\nTEXTO DA VERSÃO REVISADA:\n{revised_petition_text}" if revised_petition_text else ""
        if prior_attention_points and prior_attention_points.startswith(self._NO_ACTIVE_PRIOR_ATTENTION_MARKER):
            return f"""Revise comparativamente estas duas versões de petição de FAP.

{original_source}
{revised_source}

{original_body}
{revised_body}

{aux_text}

CONTEXTO DO HISTÓRICO:
Os pontos de atenção anteriores deste identificador foram marcados pelo usuário como não úteis e não devem ser cobrados novamente.

OBJETIVO DESTA REVISÃO FOCADA:
1. Não reabra pontos de atenção antigos marcados como não úteis.
2. Não faça nova varredura geral do manual nem gere novos achados fora desse escopo.
3. Exceção obrigatória: continue validando a consistência do nome da empresa nas duas versões e reporte divergências atuais como CRÍTICO.

Estruture em JSON com:
- comparative_changes (array de alterações; deixe vazio se não houver divergência atual relevante)
- findings (achados; deixe vazio se não houver divergência atual de razão social)
- executive_summary (resumo)"""

        if prior_attention_points:
            return f"""Revise comparativamente estas duas versões de petição de FAP.

{original_source}
{revised_source}

{original_body}
{revised_body}

{aux_text}

PONTOS DE ATENÇÃO IDENTIFICADOS NA REVISÃO ANTERIOR:
{prior_attention_points}

OBJETIVO DESTA REVISÃO FOCADA:
1. Use a versão revisada como referência principal para verificar se os pontos de atenção anteriores foram corrigidos.
2. Quando útil, compare com a versão original para demonstrar a correção ou a persistência do problema.
3. Não faça nova varredura geral do manual nem gere novos achados fora dessa lista.
4. Exceção obrigatória: continue validando a consistência do nome da empresa nas duas versões e reporte divergências atuais como CRÍTICO.

Estruture em JSON com:
- comparative_changes (array de alterações relevantes aos pontos anteriores)
- findings (achados ainda pendentes)
- executive_summary (resumo)"""

        return f"""Revise comparativamente estas duas versões de petição de FAP.

{original_source}
{revised_source}

{original_body}
{revised_body}

{aux_text}

VERIFICAÇÃO PRÉVIA OBRIGATÓRIA: antes de analisar as diferenças entre as versões, verifique em AMBOS os documentos se a razão social da empresa autora está grafada de forma idêntica em todas as ocorrências. Reporte eventuais inconsistências como achado CRÍTICO.

Para cada alteração identificada:
1. Transcreva trecho original e corrigido
2. Explique motivo da correção
3. Indique se padrão já existe no manual

Estruture em JSON com:
- comparative_changes (array de alterações)
- findings (achados gerais)
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
        merged_findings = [
            item for item in self._merge_unique_dict_items(all_dicts, "findings")
            if not self._should_ignore_finding(item)
        ]
        merged: dict[str, Any] = {
            "theses": self._merge_unique_dict_items(all_dicts, "theses"),
            "findings": merged_findings,
            "missing_documents": self._merge_unique_dict_items(all_dicts, "missing_documents"),
            "new_patterns": [],
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
