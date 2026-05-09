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
from typing import Optional
from datetime import datetime
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field


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

    def __init__(self, 
                 openai_api_key: Optional[str] = None,
                 model: str = 'gpt-4o-mini',
                 temperature: float = 0.7):
        """
        Inicializa o agente revisor
        
        Args:
            openai_api_key: Chave da API OpenAI (se None, usa variável de ambiente)
            model: Modelo LLM a usar
            temperature: Temperatura do modelo
        """
        self.api_key = openai_api_key or os.environ.get('OPENAI_API_KEY')
        self.model_name = model
        self.temperature = temperature
        
        self.llm = ChatOpenAI(
            api_key=self.api_key,
            model=model,
            temperature=temperature
        )
        
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

    def _build_system_prompt(self, reviewer_identity: str = "", reviewer_rules: str = "", reviewer_output_format: str = "") -> str:
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

MANUAL DE REFERÊNCIA:
{self.manual_content[:3000] if self.manual_content else 'Manual não carregado'}

CASOS DE REFERÊNCIA:
{self.cases_content[:2000] if self.cases_content else 'Casos não carregados'}"""
        
        return base_system

    async def review_petition_single_version(self,
                                            petition_content: str,
                                            auxiliary_documents: list[dict] = None,
                                            reviewer_identity: str = "",
                                            reviewer_rules: str = "",
                                            reviewer_output_format: str = "") -> PetitionReviewResult:
        """
        Revisa uma única versão de petição contra o manual
        
        Args:
            petition_content: Conteúdo da petição
            auxiliary_documents: Documentos auxiliares opcionais
            reviewer_identity: Identidade do revisor
            reviewer_rules: Regras do revisor
            reviewer_output_format: Formato de saída
            
        Returns:
            Resultado estruturado da revisão
        """
        system_prompt = self._build_system_prompt(reviewer_identity, reviewer_rules, reviewer_output_format)
        
        user_message = f"""Revise esta petição inicial de FAP contra o manual.

PETIÇÃO A REVISAR:
{petition_content[:5000]}

{f'DOCUMENTOS AUXILIARES ({len(auxiliary_documents)} arquivos):' + str(auxiliary_documents[:500]) if auxiliary_documents else ''}

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
        
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content
            
            # Tentar extrair JSON da resposta
            try:
                # Procurar por JSON na resposta
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = response_text[json_start:json_end]
                    result_dict = json.loads(json_str)
                else:
                    result_dict = {}
            except json.JSONDecodeError:
                result_dict = {}
            
            # Criar resultado com dados salvaguardados
            result = PetitionReviewResult(
                analysis_type="single_version",
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
                                         original_petition: str,
                                         revised_petition: str,
                                         auxiliary_documents: list[dict] = None,
                                         reviewer_identity: str = "",
                                         reviewer_rules: str = "",
                                         reviewer_output_format: str = "") -> PetitionReviewResult:
        """
        Realiza análise comparativa entre duas versões de petição
        
        Args:
            original_petition: Versão original da petição
            revised_petition: Versão revisada da petição
            auxiliary_documents: Documentos auxiliares opcionais
            reviewer_identity: Identidade do revisor
            reviewer_rules: Regras do revisor
            reviewer_output_format: Formato de saída
            
        Returns:
            Resultado estruturado da análise comparativa
        """
        system_prompt = self._build_system_prompt(reviewer_identity, reviewer_rules, reviewer_output_format)
        
        user_message = f"""Revise comparativamente estas duas versões de petição de FAP.

VERSÃO ORIGINAL:
{original_petition[:5000]}

VERSÃO REVISADA:
{revised_petition[:5000]}

{f'DOCUMENTOS AUXILIARES ({len(auxiliary_documents)} arquivos):' + str(auxiliary_documents[:500]) if auxiliary_documents else ''}

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
        
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content
            
            # Tentar extrair JSON
            try:
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = response_text[json_start:json_end]
                    result_dict = json.loads(json_str)
                else:
                    result_dict = {}
            except json.JSONDecodeError:
                result_dict = {}
            
            result = PetitionReviewResult(
                analysis_type="comparative",
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
