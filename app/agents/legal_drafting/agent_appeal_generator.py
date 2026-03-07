"""
Agente de IA para geração de recursos judiciais
"""

import os
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


# ==================== Modelos Pydantic ====================

class AppealSection(BaseModel):
    """Modelo para uma seção do recurso"""
    title: str = Field(description="Título da seção")
    content: str = Field(description="Conteúdo da seção")


class GeneratedAppeal(BaseModel):
    """Modelo para o recurso gerado"""
    appeal_type: str = Field(description="Tipo de recurso (Apelação, Embargos de Declaração, etc)")
    success_probability_percent: int = Field(description="Probabilidade estimada de êxito (0 a 100)")
    success_probability_rationale: str = Field(description="Justificativa breve e objetiva da probabilidade de êxito")
    introduction: str = Field(description="Introdução do recurso com qualificação das partes")
    facts: str = Field(description="Dos fatos - narrativa do caso")
    grounds: str = Field(description="Dos fundamentos - argumentação jurídica")
    jurisprudence: str = Field(default="", description="Jurisprudências e precedentes aplicáveis")
    requests: str = Field(description="Dos pedidos - o que se pretende com o recurso")
    conclusion: str = Field(description="Conclusão do recurso")
    additional_sections: List[AppealSection] = Field(default_factory=list, description="Seções adicionais conforme tipo de recurso")
    
    def to_full_text(self) -> str:
        """Converte o recurso estruturado em texto completo formatado"""
        sections = []
        
        sections.append(f"RECURSO: {self.appeal_type.upper()}\n")
        sections.append("=" * 80 + "\n")
        
        if self.introduction:
            sections.append("I. INTRODUÇÃO\n")
            sections.append(self.introduction + "\n\n")
        
        if self.facts:
            sections.append("II. DOS FATOS\n")
            sections.append(self.facts + "\n\n")
        
        if self.grounds:
            sections.append("III. DOS FUNDAMENTOS\n")
            sections.append(self.grounds + "\n\n")
        
        if self.jurisprudence:
            sections.append("IV. DA JURISPRUDÊNCIA\n")
            sections.append(self.jurisprudence + "\n\n")
        
        section_num = 5
        for section in self.additional_sections:
            sections.append(f"{section_num}. {section.title.upper()}\n")
            sections.append(section.content + "\n\n")
            section_num += 1
        
        if self.requests:
            sections.append(f"{section_num}. DOS PEDIDOS\n")
            sections.append(self.requests + "\n\n")
        
        if self.conclusion:
            sections.append("CONCLUSÃO\n")
            sections.append(self.conclusion + "\n")
        
        return "".join(sections)
    
    def to_dict(self) -> dict:
        """Converte o modelo para dicionário"""
        return self.model_dump(by_alias=True)
    
    def to_json(self) -> str:
        """Converte o modelo para JSON"""
        return self.model_dump_json(by_alias=True)


# ==================== Classe Principal ====================


class AgentAppealGenerator:
    """Agente de IA para gerar recursos judiciais com base na análise de sentença"""
    
    model_name = None

    def __init__(self, model_name: str = "gpt-5-mini"):
        self.model_name = model_name

    def generate_appeal(
        self,
        appeal_type: str,
        sentence_analysis: dict,
        user_notes: Optional[str] = None,
        petition_content: Optional[str] = None
    ) -> dict:
        """
        Gera um recurso judicial estruturado com base na análise da sentença.

        Args:
            appeal_type: Tipo de recurso (Apelação, Embargos de Declaração, Agravo, etc)
            sentence_analysis: Dicionário com a análise completa da sentença
            user_notes: Observações e argumentos adicionais fornecidos pelo usuário
            petition_content: Conteúdo da petição inicial (opcional, para contexto)

        Returns:
            dict: Recurso gerado estruturado
        """
        if not sentence_analysis:
            raise ValueError("É necessário fornecer a análise da sentença")
        
        # Extrair informações relevantes da análise
        sentence_info = sentence_analysis.get('sentence_info', {})
        
        # Preparar contexto da sentença
        sentence_context = self._prepare_sentence_context(sentence_analysis)
        
        # Preparar contexto das observações do usuário
        user_context = ""
        if user_notes:
            user_context = (
                "\n\n=== ARGUMENTOS E OBSERVAÇÕES DO USUÁRIO ===\n"
                "O usuário forneceu os seguintes argumentos e observações para fundamentar o recurso:\n"
                f"{user_notes}\n\n"
                "IMPORTANTE: Incorpore esses argumentos de forma natural e técnica no recurso.\n"
            )
        
        # Preparar contexto da petição inicial
        petition_context = ""
        if petition_content:
            petition_context = (
                "\n\n=== CONTEXTO DA PETIÇÃO INICIAL ===\n"
                "Use o conteúdo abaixo como contexto para fundamentar o recurso:\n"
                f"{petition_content[:2000]}...\n\n"  # Limitar para não exceder tokens
            )
        
        # Preparar prompt específico para o tipo de recurso
        appeal_instructions = self._get_appeal_specific_instructions(appeal_type)
        
        user_prompt = (
            f"Você é um advogado especializado em elaboração de recursos judiciais. "
            f"Gere um {appeal_type} completo e bem fundamentado com base nas informações abaixo.\n\n"
            f"{sentence_context}"
            f"{user_context}"
            f"{petition_context}"
            f"\n=== INSTRUÇÕES ESPECÍFICAS PARA {appeal_type.upper()} ===\n"
            f"{appeal_instructions}\n\n"
            "=== PROBABILIDADE DE ÊXITO ===\n"
            "Calcule a probabilidade de êxito do recurso em percentual (0 a 100).\n"
            "Regras:\n"
            "- Seja conservador e objetivo\n"
            "- Baseie a estimativa somente nos elementos presentes na sentença e nos argumentos fornecidos\n"
            "- Forneça uma justificativa breve (2-4 frases)\n\n"
            "=== ESTRUTURA DO RECURSO ===\n"
            "Gere o recurso com as seguintes seções:\n\n"
            "1. INTRODUÇÃO:\n"
            "   - Qualificação das partes\n"
            "   - Identificação do processo e da sentença recorrida\n"
            "   - Manifestação de inconformismo\n\n"
            "2. DOS FATOS:\n"
            "   - Narrativa clara e objetiva do caso\n"
            "   - Contextualização dos acontecimentos relevantes\n\n"
            "3. DOS FUNDAMENTOS:\n"
            "   - Argumentação jurídica sólida e bem fundamentada\n"
            "   - Análise dos dispositivos legais aplicáveis\n"
            "   - Demonstração do direito da parte recorrente\n"
            "   - Refutação dos fundamentos da sentença (se aplicável)\n\n"
            "4. DA JURISPRUDÊNCIA:\n"
            "   - Citação de jurisprudências relevantes\n"
            "   - Precedentes dos tribunais superiores\n"
            "   - Súmulas aplicáveis\n\n"
            "5. DOS PEDIDOS:\n"
            "   - Pedidos claros e específicos\n"
            "   - Requerimentos processuais necessários\n\n"
            "6. CONCLUSÃO:\n"
            "   - Síntese dos argumentos\n"
            "   - Reforço do pedido principal\n\n"
            "IMPORTANTE:\n"
            "- Use linguagem técnica, formal e respeitosa\n"
            "- Fundamente todos os argumentos em lei, doutrina ou jurisprudência\n"
            "- Seja específico e objetivo\n"
            "- Evite argumentos genéricos ou vagos\n"
            "- Estruture o texto de forma lógica e progressiva\n"
            "- Cite artigos de lei, súmulas e precedentes sempre que possível\n"
        )
        
        print("[Agente] Gerando recurso judicial com IA...")
        
        llm = ChatOpenAI(
            model=self.model_name,
            temperature=0.3  # Um pouco mais de criatividade para redação
        ).with_structured_output(GeneratedAppeal)

        response = llm.invoke([
            {
                "role": "system",
                "content": (
                    "Você é um advogado experiente especializado em recursos judiciais. "
                    "Gere recursos bem fundamentados, tecnicamente precisos e persuasivos."
                )
            },
            {"role": "user", "content": user_prompt}
        ])

        return response.to_dict()
    
    def _prepare_sentence_context(self, sentence_analysis: dict) -> str:
        """Prepara o contexto da análise da sentença para o prompt"""
        sentence_info = sentence_analysis.get('sentence_info', {})
        
        context = "=== INFORMAÇÕES DA SENTENÇA ANALISADA ===\n\n"
        
        # Informações básicas
        if sentence_info.get('process_number'):
            context += f"Processo nº: {sentence_info['process_number']}\n"
        if sentence_info.get('judge'):
            context += f"Juiz/Magistrado: {sentence_info['judge']}\n"
        if sentence_info.get('origin_court'):
            context += f"Tribunal: {sentence_info['origin_court']}\n"
        if sentence_info.get('judgment_date'):
            context += f"Data da sentença: {sentence_info['judgment_date']}\n"
        
        # Partes
        parties = sentence_info.get('parties', {})
        if parties:
            context += "\nPartes:\n"
            active_pole = parties.get('active_pole', [])
            passive_pole = parties.get('passive_pole', [])
            
            for party in active_pole:
                context += f"  - {party.get('role', 'Parte')}: {party.get('name', '')}\n"
            for party in passive_pole:
                context += f"  - {party.get('role', 'Parte')}: {party.get('name', '')}\n"
        
        # Resultado geral
        if sentence_info.get('overall_result'):
            context += f"\nResultado geral: {sentence_info['overall_result']}\n"
        
        # Dispositivo
        if sentence_info.get('operative_part'):
            context += f"\nDispositivo da sentença:\n{sentence_info['operative_part']}\n"
        
        # Decisões específicas
        decisions = sentence_info.get('decisions', [])
        if decisions:
            context += "\nDecisões específicas:\n"
            for i, decision in enumerate(decisions, 1):
                context += f"{i}. {decision.get('subject', '')}: {decision.get('result', '')}\n"
                if decision.get('reasoning'):
                    context += f"   Fundamentação: {decision.get('reasoning', '')}\n"
        
        # Fundamentos legais
        legal_grounds = sentence_info.get('legal_grounds', [])
        if legal_grounds:
            context += f"\nFundamentos legais utilizados:\n"
            for ground in legal_grounds[:5]:  # Limitar para não exceder
                context += f"  - {ground}\n"
        
        # Jurisprudências citadas
        jurisprudence = sentence_info.get('jurisprudence_cited', [])
        if jurisprudence:
            context += f"\nJurisprudências citadas na sentença:\n"
            for juris in jurisprudence[:5]:
                context += f"  - {juris}\n"
        
        return context
    
    def _get_appeal_specific_instructions(self, appeal_type: str) -> str:
        """Retorna instruções específicas baseadas no tipo de recurso"""
        
        instructions = {
            "Apelação": (
                "A Apelação é o recurso cabível contra sentenças. Deve:\n"
                "- Impugnar especificamente os fundamentos da sentença\n"
                "- Demonstrar o erro de julgamento\n"
                "- Apresentar teses alternativas ou complementares\n"
                "- Requerer a reforma total ou parcial da decisão\n"
                "- Observar os requisitos de admissibilidade (tempestividade, preparo, legitimidade)"
            ),
            "Embargos de Declaração": (
                "Os Embargos de Declaração visam esclarecer obscuridade, eliminar contradição ou suprir omissão. Deve:\n"
                "- Apontar especificamente a obscuridade, contradição ou omissão\n"
                "- Demonstrar onde a decisão foi omissa, contraditória ou obscura\n"
                "- Requerer o esclarecimento ou complementação da decisão\n"
                "- Ser objetivo e direto ao apontar o vício\n"
                "- Evitar rediscussão do mérito (salvo se houver contradição manifesta)"
            ),
            "Agravo de Instrumento": (
                "O Agravo de Instrumento é cabível contra decisões interlocutórias. Deve:\n"
                "- Demonstrar a urgência e a lesão grave de difícil reparação\n"
                "- Impugnar especificamente os fundamentos da decisão agravada\n"
                "- Instruir com as peças obrigatórias\n"
                "- Apresentar fundamentação jurídica sólida\n"
                "- Requerer efeito suspensivo (se cabível)"
            ),
            "Recurso Especial": (
                "O Recurso Especial é dirigido ao STJ e deve demonstrar:\n"
                "- Violação de lei federal\n"
                "- Divergência jurisprudencial entre tribunais\n"
                "- Prequestionamento da matéria\n"
                "- Fundamentação específica e técnica\n"
                "- Demonstração do acórdão recorrido e dos paradigmas"
            ),
            "Recurso Extraordinário": (
                "O Recurso Extraordinário é dirigido ao STF e deve demonstrar:\n"
                "- Questão constitucional\n"
                "- Repercussão geral do tema\n"
                "- Prequestionamento da matéria constitucional\n"
                "- Violação direta à Constituição Federal\n"
                "- Demonstração do acórdão recorrido e fundamentação específica"
            )
        }
        
        return instructions.get(
            appeal_type,
            "Elabore o recurso de forma técnica, fundamentada e persuasiva, "
            "observando os requisitos legais e jurisprudenciais aplicáveis."
        )
