"""
Agente de Treinamento e Evolução da Base FAP - FapTrainingEvolutionAgent

Responsabilidade: Manter e evoluir a base de conhecimento utilizada pelos revisores jurídicos,
consolidando padrões, atualizando o manual e casos de referência.

Este agente é responsável por:
- Atualizar MANUAL_REVISAO_FAP.md
- Atualizar CASOS_REFERENCIA.md
- Gerar novas versões oficiais
- Organizar conhecimento recorrente
"""

import json
import os
from typing import Optional, Tuple
from datetime import datetime
from pydantic import BaseModel, Field

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage


class ManualUpdate(BaseModel):
    """Atualização sugerida no manual"""
    section: str = Field(..., description="Seção do manual a atualizar")
    current_content: str = Field(..., description="Conteúdo atual")
    new_content: str = Field(..., description="Conteúdo novo/revisado")
    justification: str = Field(..., description="Justificativa da atualização")
    version_increment: str = Field(default="patch", description="Como incrementar versão: patch, minor, major")


class CaseReference(BaseModel):
    """Novo caso de referência"""
    case_number: int = Field(..., description="Número sequencial do caso")
    company_name: str = Field(..., description="Nome da empresa")
    junior_lawyer: str = Field(..., description="Advogado júnior responsável")
    vigencies: list[str] = Field(..., description="Vigências tratadas")
    theses: list[str] = Field(..., description="Teses tratadas")
    manual_version: str = Field(..., description="Versão do manual usado: v[X.X]")
    patterns_identified: list[dict] = Field(..., description="Padrões identificados")
    reviewer_decisions: dict = Field(..., description="Decisões de revisão: críticos, deixados passar, tom")
    new_patterns: list[str] = Field(..., description="Padrões novos identificados")


class TrainingResult(BaseModel):
    """Resultado do treinamento/evolução da base"""
    manual_updates_generated: bool = Field(...)
    case_reference_generated: bool = Field(...)
    new_patterns_found: list[str] = Field(default_factory=list)
    manual_version_new: str = Field(...)
    manual_updated_sections: list[str] = Field(default_factory=list)
    case_added: bool = Field(default=False)
    approval_required: bool = Field(...)
    message: str = Field(...)


class FapTrainingEvolutionAgent:
    """
    Agente de Treinamento e Evolução da Base FAP
    
    Responsabilidade: Manter e evoluir continuamente a base de conhecimento
    """

    def __init__(self,
                 openai_api_key: Optional[str] = None,
                 model: str = 'gpt-4o-mini',
                 temperature: float = 0.7):
        """
        Inicializa o agente de treinamento
        
        Args:
            openai_api_key: Chave da API OpenAI
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
        self.manual_version: str = "1.0"

    def load_reference_documents(self,
                                 manual_md: str = "",
                                 cases_md: str = "",
                                 project_instructions_md: str = "",
                                 manual_version: str = "1.0") -> None:
        """
        Carrega os documentos de referência
        
        Args:
            manual_md: Conteúdo do manual
            cases_md: Conteúdo dos casos
            project_instructions_md: Instruções do projeto
            manual_version: Versão atual do manual
        """
        self.manual_content = manual_md
        self.cases_content = cases_md
        self.project_instructions = project_instructions_md
        self.manual_version = manual_version

    def _build_system_prompt(self,
                            training_identity: str = "",
                            training_rules: str = "",
                            training_update_policy: str = "") -> str:
        """
        Constrói o prompt do sistema para o agente de treinamento
        
        Args:
            training_identity: Identidade do agente
            training_rules: Regras do agente
            training_update_policy: Política de atualização
            
        Returns:
            Prompt completo do sistema
        """
        base_system = f"""Você é o Agente de Treinamento e Evolução da Base FAP do escritório Rodriguez & Sousa.

IDENTIDADE:
{training_identity or 'Mantenha e evolua a base de conhecimento'}

REGRAS:
{training_rules or 'Valide todos os padrões antes de atualizar'}

POLÍTICA DE ATUALIZAÇÃO:
{training_update_policy or 'Consolidar padrões recorrentes'}

MANUAL ATUAL (v{self.manual_version}):
{self.manual_content[:2000] if self.manual_content else 'Manual não carregado'}

CASOS DE REFERÊNCIA:
{self.cases_content[:1500] if self.cases_content else 'Casos não carregados'}"""
        
        return base_system

    async def process_reviewer_findings(self,
                                       reviewer_findings: dict,
                                       approval_required: bool = True,
                                       training_identity: str = "",
                                       training_rules: str = "",
                                       training_update_policy: str = "") -> TrainingResult:
        """
        Processa os achados do revisor para evolução da base
        
        Args:
            reviewer_findings: Achados do agente revisor (dict com estrutura PetitionReviewResult)
            approval_required: Se requer aprovação antes de publicar
            training_identity: Identidade do agente
            training_rules: Regras do agente
            training_update_policy: Política de atualização
            
        Returns:
            Resultado do treinamento/evolução
        """
        system_prompt = self._build_system_prompt(training_identity, training_rules, training_update_policy)
        
        new_patterns = reviewer_findings.get('new_patterns', [])
        findings = reviewer_findings.get('findings', [])
        
        user_message = f"""Processe estes achados do revisor para evolução da base de conhecimento.

ACHADOS DO REVISOR:
Padrões novos identificados: {len(new_patterns)}
Total de achados: {len(findings)}

NOVOS PADRÕES:
{json.dumps(new_patterns, ensure_ascii=False, indent=2)}

ACHADOS GERAIS:
{json.dumps(findings[:5], ensure_ascii=False, indent=2)}

TAREFAS:
1. Avaliar se os padrões novos devem ser incorporados ao manual
2. Sugerir atualizações específicas do manual
3. Propor novo caso de referência se relevante
4. Indicar mudanças de versão necessárias

Retorne em JSON com:
- manual_updates (array de atualizações sugeridas)
- case_reference_data (novo caso de referência ou null)
- version_increment (patch/minor/major)
- message (mensagem resumida)"""
        
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content
            
            # Extrair JSON
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
            
            # Calcular nova versão
            version_parts = self.manual_version.split('.')
            version_increment = result_dict.get('version_increment', 'patch')
            new_version = self._increment_version(self.manual_version, version_increment)
            
            return TrainingResult(
                manual_updates_generated=bool(result_dict.get('manual_updates')),
                case_reference_generated=bool(result_dict.get('case_reference_data')),
                new_patterns_found=[p.get('pattern_description', '') for p in new_patterns],
                manual_version_new=new_version,
                manual_updated_sections=[u.get('section', '') for u in result_dict.get('manual_updates', [])],
                case_added=bool(result_dict.get('case_reference_data')),
                approval_required=approval_required,
                message=result_dict.get('message', 'Análise concluída sem atualizações')
            )
            
        except Exception as e:
            return TrainingResult(
                manual_updates_generated=False,
                case_reference_generated=False,
                manual_version_new=self.manual_version,
                approval_required=approval_required,
                message=f"Erro no processamento: {str(e)}"
            )

    async def generate_updated_manual(self,
                                     updates: list[dict],
                                     training_identity: str = "",
                                     training_rules: str = "") -> str:
        """
        Gera versão atualizada do manual com as mudanças
        
        Args:
            updates: Lista de atualizações a aplicar
            training_identity: Identidade do agente
            training_rules: Regras do agente
            
        Returns:
            Conteúdo completo do manual atualizado
        """
        system_prompt = f"""Você é o Agente de Treinamento FAP.

IDENTIDADE:
{training_identity or 'Mantenha coerência no manual'}

REGRAS:
{training_rules or 'Preserve estrutura existente'}

MANUAL ATUAL (v{self.manual_version}):
{self.manual_content}"""
        
        user_message = f"""Atualize o manual com estas mudanças, preservando toda a estrutura e versionamento:

ATUALIZAÇÕES A APLICAR:
{json.dumps(updates, ensure_ascii=False, indent=2)}

Retorne o manual COMPLETO atualizado com um JSON no final contendo:
- timestamp: data/hora da atualização
- version_changed_from: versão anterior
- sections_updated: seções modificadas
- new_patterns_added: quantos padrões novos foram adicionados"""
        
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message)
            ]
            
            response = self.llm.invoke(messages)
            return response.content
            
        except Exception as e:
            return f"Erro ao gerar manual atualizado: {str(e)}"

    async def generate_case_reference(self,
                                     company_name: str,
                                     junior_lawyer: str,
                                     vigencies: list[str],
                                     theses: list[str],
                                     patterns: list[dict],
                                     reviewer_decisions: dict,
                                     new_patterns: list[str],
                                     training_identity: str = "") -> str:
        """
        Gera novo caso de referência
        
        Args:
            company_name: Nome da empresa
            junior_lawyer: Advogado júnior
            vigencies: Vigências tratadas
            theses: Teses tratadas
            patterns: Padrões identificados
            reviewer_decisions: Decisões do revisor
            new_patterns: Padrões novos
            training_identity: Identidade do agente
            
        Returns:
            Conteúdo do novo caso de referência formatado
        """
        system_prompt = f"""Você é o Agente de Treinamento FAP responsável por consolidar casos de referência.

{training_identity or ''}

CASOS DE REFERÊNCIA EXISTENTES:
{self.cases_content[:1500]}"""
        
        next_case_number = self._get_next_case_number()
        
        user_message = f"""Gere um novo caso de referência para adicionar ao CASOS_REFERENCIA.md.

DADOS DO CASO:
- Número sequencial: {next_case_number}
- Empresa: {company_name}
- Advogado Júnior: {junior_lawyer}
- Vigências: {', '.join(vigencies)}
- Teses: {', '.join(theses)}
- Versão do Manual: v{self.manual_version}
- Padrões identificados: {json.dumps(patterns[:3], ensure_ascii=False)}
- Padrões novos: {json.dumps(new_patterns, ensure_ascii=False)}

Formato obrigatório:
```
CASO [N] — [NOME DA EMPRESA]

Advogado júnior: [nome]
Revisor: Isrhael
Vigências: [vigências]
Teses: [lista]
Manual gerado: v[X.X]

## Padrões identificados
[tabela]

## Decisões de julgamento
- Priorizou: [...]
- Deixou passar: [...]
- Tom e nível: [...]

## Padrões novos
[lista]

## Contexto adicional
[informações]
```"""
        
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message)
            ]
            
            response = self.llm.invoke(messages)
            return response.content
            
        except Exception as e:
            return f"Erro ao gerar caso de referência: {str(e)}"

    # Métodos auxiliares

    def _increment_version(self, current_version: str, increment_type: str) -> str:
        """
        Incrementa a versão do manual
        
        Args:
            current_version: Versão atual (ex: "1.2.3")
            increment_type: Tipo de incremento: patch, minor, major
            
        Returns:
            Nova versão
        """
        try:
            parts = [int(x) for x in current_version.split('.')]
            while len(parts) < 3:
                parts.append(0)
            
            if increment_type == 'major':
                parts[0] += 1
                parts[1] = 0
                parts[2] = 0
            elif increment_type == 'minor':
                parts[1] += 1
                parts[2] = 0
            else:  # patch
                parts[2] += 1
            
            return '.'.join(str(p) for p in parts)
        except Exception:
            return "1.0.0"

    def _get_next_case_number(self) -> int:
        """
        Retorna o próximo número de caso
        
        Returns:
            Número do próximo caso
        """
        try:
            # Procurar por CASO [N] no conteúdo
            import re
            matches = re.findall(r'CASO \[(\d+)\]', self.cases_content)
            if matches:
                return max(int(m) for m in matches) + 1
            return 1
        except Exception:
            return 1

    def check_manual_updates(self) -> str:
        """
        Verifica se há atualizações pendentes no manual
        
        Returns:
            Mensagem sobre status das atualizações
        """
        if not self.manual_content:
            return "Manual não carregado"
        
        try:
            case_count = len([l for l in self.cases_content.split('\n') if 'CASO [' in l])
            return f"Manual v{self.manual_version} com {case_count} casos de referência"
        except Exception:
            return "Erro ao verificar status"
