"""
Agente Extrator de Documentos Auxiliares do Revisor FAP.

Responsabilidade: ler UM documento auxiliar (CAT, CNIS, INFBEN, print do FAP Web,
laudo etc.), vinculá-lo aos benefícios-âncora informados (planilha de benefícios ou
números achados na petição) e extrair somente os dados relevantes às teses, sempre
com o trecho literal de origem para auditoria humana.

Este agente NÃO revisa a petição — ele apenas destila dados para o revisor cruzar.
"""

import base64
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from app.agents.core.file_agent import FileAgent
from app.services.token_usage_service import TokenUsageService

_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'}


class AuxExtractedFact(BaseModel):
    """Um dado extraído do documento auxiliar."""
    label: str = Field(..., description="Nome do dado (ex.: Data do acidente)")
    value: str = Field(..., description="Valor extraído do documento")
    source_excerpt: Optional[str] = Field(
        None, description="Trecho literal curto do documento de onde o dado saiu")


class AuxRelatedBenefit(BaseModel):
    """Benefício ao qual o documento se refere."""
    benefit_number: str = Field(..., description="Número do benefício como aparece no documento ou na âncora")
    match_reason: str = Field(..., description="Como o vínculo foi identificado (NB citado, NIT, nome do trabalhador...)")
    facts: list[AuxExtractedFact] = Field(default_factory=list)


class AuxDocumentExtraction(BaseModel):
    """Resultado da extração de um documento auxiliar."""
    document_type: str = Field('OUTRO', description="CAT, CNIS, INFBEN, PRINT_FAP, LAUDO, CONTESTACAO ou OUTRO")
    related_benefits: list[AuxRelatedBenefit] = Field(default_factory=list)
    general_summary: str = Field('', description="Resumo objetivo do documento em até 3 frases")
    potential_divergences: list[str] = Field(
        default_factory=list,
        description="Pontos do documento que merecem conferência contra a petição")


class FapAuxiliaryDocumentExtractorAgent:
    """Extrai dados estruturados de um documento auxiliar, guiado pelas teses."""

    _OUTPUT_SCHEMA = """{
  "document_type": "CAT | CNIS | INFBEN | PRINT_FAP | LAUDO | CONTESTACAO | OUTRO",
  "related_benefits": [
    {"benefit_number": "número do benefício",
     "match_reason": "como o vínculo foi identificado (NB citado, NIT, nome do trabalhador...)",
     "facts": [{"label": "nome do dado (ex.: Data do acidente)", "value": "valor extraído", "source_excerpt": "trecho LITERAL curto copiado do documento, ou null"}]}
  ],
  "general_summary": "resumo objetivo do documento em até 3 frases",
  "potential_divergences": ["ponto que merece conferência contra a petição"]
}"""

    def __init__(self,
                 openai_api_key: Optional[str] = None,
                 model: Optional[str] = None,
                 temperature: float = 0.0):
        self.api_key = openai_api_key or os.environ.get('OPENAI_API_KEY')
        self.model_name = model or os.environ.get('FAP_REVIEW_AUX_EXTRACTOR_MODEL', 'gpt-4o-mini')
        self.temperature = temperature
        self.llm = ChatOpenAI(api_key=self.api_key, model=self.model_name, temperature=temperature)
        self.token_usage_service = TokenUsageService()
        self.file_agent = FileAgent()

    async def extract(self, *,
                      file_path: str,
                      file_name: str,
                      document_text: str | None = None,
                      benefit_anchors: list[dict] | None = None,
                      law_firm_id: int | None = None) -> AuxDocumentExtraction:
        """Extrai dados do documento. Levanta exceção só em falha de chamada/parse."""
        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(
            file_name=file_name,
            document_text=document_text,
            benefit_anchors=benefit_anchors or [],
        )

        if document_text:
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
            mode = 'extracted_text'
        else:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=[
                    {"type": "text", "text": user_message},
                    self._build_attachment_part(file_path),
                ]),
            ]
            mode = 'file_attachment'

        start_time = time.time()
        response = await self.llm.ainvoke(messages)
        latency_ms = int((time.time() - start_time) * 1000)

        self.token_usage_service.capture_and_store(
            {"messages": [response]},
            agent_name="FapAuxiliaryDocumentExtractorAgent",
            action_name="extract_auxiliary_document",
            print_prefix="[FapAuxExtractor]",
            model_name=self.model_name,
            model_provider="openai",
            law_firm_id=law_firm_id,
            latency_ms=latency_ms,
            metadata_payload={
                "file_name": file_name,
                "mode": mode,
                "anchors_count": len(benefit_anchors or []),
            },
        )

        data = self._extract_json_dict(str(response.content))
        try:
            return AuxDocumentExtraction(
                document_type=str(data.get('document_type') or 'OUTRO'),
                related_benefits=data.get('related_benefits') or [],
                general_summary=str(data.get('general_summary') or ''),
                potential_divergences=[str(item) for item in data.get('potential_divergences') or []],
            )
        except ValidationError:
            # Degradação graciosa: devolve ao menos o resumo bruto para não perder o documento.
            return AuxDocumentExtraction(
                document_type=str(data.get('document_type') or 'OUTRO'),
                general_summary=str(data.get('general_summary') or '')[:1000],
            )

    def _build_system_prompt(self) -> str:
        return f"""Você é um extrator de dados de documentos que instruem petições de Ação Revisional do FAP (CAT, extratos CNIS/INFBEN, prints do FAP Web, laudos, contestações administrativas).

Sua tarefa: identificar a quais benefícios o documento se refere e extrair APENAS os dados relevantes às teses informadas.

O QUE PROCURAR POR TESE (roteiro de relevância):
- ACIDENTE DE TRAJETO: data, local e descrição do acidente na CAT; indicação de trajeto.
- ERRO DE ESTABELECIMENTO: CNPJ/estabelecimento vinculado ao benefício.
- NEXO TÉCNICO PREVIDENCIÁRIO (inclusive pendente de julgamento): espécie do benefício (B91/B94), CID, NTEP, situação do julgamento.
- PRÉ-FAP: datas relevantes (DDB, DER, data do acidente) para aferir a vigência.
- Sem tese informada: NB, NIT, nome do trabalhador, empregador/CNPJ, espécie, datas de início/fim.

REGRAS INVIOLÁVEIS:
1. Extraia SOMENTE o que estiver escrito no documento. NUNCA invente ou deduza valores.
2. Todo fact deve trazer source_excerpt com o trecho LITERAL (5 a 30 palavras) de onde o dado saiu; se impossível (ex.: imagem), use null.
3. Vincule o documento aos benefícios-âncora quando possível (por NB; na falta, por NIT ou nome do trabalhador — explique em match_reason). Se o documento citar um NB fora da lista de âncoras, inclua-o mesmo assim.
4. Se não conseguir vincular a nenhum benefício, deixe related_benefits vazio e preencha general_summary.
5. Registre em potential_divergences tudo que pareça inconsistente ou digno de conferência contra a petição (datas conflitantes, CNPJ divergente, benefício de espécie diferente da alegada etc.).

CONTRATO TÉCNICO DE SAÍDA (OBRIGATÓRIO):
Responda EXCLUSIVAMENTE com um único JSON válido, sem texto fora do JSON e sem cercas de código.
Use EXATAMENTE os nomes de campos abaixo (em inglês); valores em português. Campos opcionais podem ser null.
{self._OUTPUT_SCHEMA}"""

    def _build_user_message(self, *, file_name: str, document_text: str | None,
                            benefit_anchors: list[dict]) -> str:
        if benefit_anchors:
            anchor_lines = []
            for anchor in benefit_anchors:
                theses = ', '.join(anchor.get('theses') or []) or 'sem tese informada'
                anchor_lines.append(f"- NB {anchor.get('benefit_number')} (teses: {theses})")
            anchors_block = "BENEFÍCIOS-ÂNCORA (vincule o documento a eles quando possível):\n" + "\n".join(anchor_lines)
        else:
            anchors_block = ("BENEFÍCIOS-ÂNCORA: nenhum informado. Identifique você mesmo os números "
                             "de benefício citados no documento.")

        source_block = (
            f"CONTEÚDO DO DOCUMENTO:\n{document_text}"
            if document_text else
            "O documento foi enviado como anexo nesta mensagem."
        )

        return f"""Extraia os dados do documento auxiliar "{file_name}".

{anchors_block}

{source_block}"""

    def _build_attachment_part(self, file_path: str) -> dict:
        """Imagens vão como image_url (data URL); demais formatos como file part."""
        extension = Path(file_path).suffix.lower()
        if extension in _IMAGE_EXTENSIONS:
            mime_type = mimetypes.guess_type(file_path)[0] or 'image/png'
            encoded = base64.b64encode(Path(file_path).read_bytes()).decode('utf-8')
            return {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}}
        return self.file_agent.build_openrouter_file_part(file_path)

    def _extract_json_dict(self, response_text: str) -> dict:
        text = str(response_text or '').strip()
        if text.startswith('```'):
            text = re.sub(r'^```[a-zA-Z]*\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, dict):
                return parsed
        raise ValueError('Resposta do extrator não contém JSON válido')
