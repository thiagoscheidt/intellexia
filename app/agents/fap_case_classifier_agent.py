from __future__ import annotations

import os
import uuid
import json
import time
from datetime import datetime
from typing import Optional

from anyio import Path
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import ChatOpenAI
from docling.document_converter import DocumentConverter
from pydantic import BaseModel, Field


load_dotenv()

class ResponseSchema(BaseModel):
    id: int = Field(description="ID do template selecionado")
    nome_arquivo: str = Field(description="Nome do arquivo do template")
    categoria: str = Field(description="Categoria do caso")
    confidence: float = Field(description="Nível de confiança na classificação (0.0 a 1.0)")
    justificativa: str = Field(description="Breve explicação da escolha")
    unable_to_classify: bool = Field(default=False, description="True se não foi possível categorizar com confiança mínima")

class FapCaseClassifierAgent:
    def __init__(self):
        self.openai = OpenAI()

    def determineCategoryTemplate(self):
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0
        ).with_structured_output(ResponseSchema)

        response = llm.invoke([
            {"role": "system", "content": """
                Você é um agente especialista em classificar casos jurídicos relacionados ao FAP, NTEP e benefícios previdenciários. 
                Sua tarefa é analisar a descrição do caso fornecida e identificar qual item da lista abaixo melhor representa o tipo de situação apresentada.
             
                Regras obrigatórias:
                    - Você deve escolher APENAS UM item da lista (ID 1 a 35).
                    - Não crie novos itens ou categorias.
                    - Baseie sua decisão exclusivamente na descrição do caso.
                    - Retorne a resposta somente em formato JSON.
                    - A justificativa deve ser breve (máximo 2 linhas).
                    - Caso o caso não se encaixe perfeitamente em um único item, escolha o mais próximo e reduza o nível de confiança.
                    - Se a confiança for inferior a 0.5 ou se não houver informações suficientes para categorizar, defina "unable_to_classify" como true.
                    - Quando "unable_to_classify" for true, ainda assim escolha a categoria mais próxima possível e explique na justificativa o motivo da incerteza.

                    Lista de opções (use exatamente os IDs e nomes abaixo):
             
                    1. Peticao Inicial.docx — Documento principal  
                    2. Acidente Ocorrido em outra Empresa.docx — Erro de vínculo empregatício  
                    3. Acidente Ocorrido em outro Estabelecimento.docx — Erro de estabelecimento  
                    4. Acidente não Relacionado ao Trabalho.docx — Erro de nexo causal  
                    5. Acidente de Trajeto.docx — Acidente de trajeto  
                    6. Acidente de Trajeto - CAT Erro material.docx — Acidente de trajeto / erro material  
                    7. Acidente de Trajeto - CAT Extemporânea.docx — Acidente de trajeto / CAT fora do prazo  
                    8. 60 Dias - B91.docx — Duplicidade de benefício  
                    9. Exclusão dos bloqueios causados pelo B92.docx — Bloqueio indevido do FAP  
                    10. Revogação da antecipação dos efeitos da tutela.docx — Benefício judicial cancelado  
                    11. B91 com aposentadoria - REVISADA.docx — Benefício concomitante  
                    12. B91 com auxílio-acidente - REVISADA.docx — Benefício concomitante  
                    13. B91 com auxílio-doença - REVISADA.docx — Duplicidade de benefício  
                    14. B92 com aposentadoria - REVISADA.docx — Benefício concomitante  
                    15. B94 com aposentadoria - REVISADA.docx — Benefício concomitante  
                    16. B94 com auxílio-acidente - REVISADA.docx — Duplicidade de benefício  
                    17. Benefício Concomitante.docx — Benefícios concomitantes  
                    18. Bloqueio de malus – B92 – B91 – Acidente de trajeto.docx — Bloqueio indevido do FAP  
                    19. CAT Duplicada.docx — Duplicidade administrativa  
                    20. Convertido B31.docx — Inclusão indevida  
                    21. Convertido para B31 – Acórdão do CRPS.docx — Inclusão indevida  
                    22. Correção da CNAE Preponderante.docx — Erro de CNAE  
                    23. Custo B94 - Benefício Cessado por Óbito.docx — Erro no índice de custo  
                    24. Custo B94 Genérico.docx — Erro metodológico  
                    25. DIB = DCB.docx — Erro cadastral  
                    26. Divergência entre benefício concedido e implementado.docx — Erro judicial  
                    27. Exclusão das admissões que representarem crescimento.docx — Erro na rotatividade  
                    28. Judicial.docx — Benefício judicial  
                    29. Massa Salarial.docx — Erro na massa salarial  
                    30. Média de Vínculos.docx — Erro no número de vínculos  
                    31. Nexo afastado.docx — Nexo técnico afastado  
                    32. NTP Duplicado.docx — Duplicidade de nexo  
                    33. NTP Indevido.docx — Nexo indevido  
                    34. Pre-FAP.docx — Evento fora do período legal  
                    35. Rotatividade.docx — Ilegalidade da rotatividade  

                    Descrição do caso:
                    {{DESCRICAO_DO_CASO}}

                    Formato obrigatório de resposta (somente JSON):

                    {
                        "id": number,
                        "nome_arquivo": "string",
                        "categoria": "string",
                        "confidence": 0.0,
                        "justificativa": "breve explicação",
                        "unable_to_classify": false
                    }
                """}
        ])
        
        return response


def main():
    """Função para testar o classificador de casos FAP"""
    print("=" * 80)
    print("TESTE DO CLASSIFICADOR DE CASOS FAP")
    print("=" * 80)
    
    # Exemplo de descrição de caso para teste
    descricao_caso = """
    Empresa recebeu notificação do FAP onde consta um benefício B91 (auxílio-doença acidentário)
    que foi concedido a um funcionário que sofreu acidente de trajeto indo para o trabalho.
    A CAT foi emitida pela empresa dentro do prazo, mas acreditamos que acidente de trajeto
    não deveria impactar o FAP da empresa.
    """
    
    print("\n📋 DESCRIÇÃO DO CASO:")
    print(descricao_caso)
    print("\n" + "=" * 80)
    
    # Instanciar o agente
    agent = FapCaseClassifierAgent()
    
    print("\n🤖 Processando classificação...\n")
    
    # Executar classificação
    resultado = agent.determineCategoryTemplate()
    
    # Exibir resultado
    print("=" * 80)
    print("RESULTADO DA CLASSIFICAÇÃO")
    print("=" * 80)
    print(f"\n📌 ID: {resultado.id}")
    print(f"📄 Arquivo: {resultado.nome_arquivo}")
    print(f"📂 Categoria: {resultado.categoria}")
    print(f"📊 Confiança: {resultado.confidence:.2f}")
    print(f"⚠️  Incapaz de classificar: {'Sim' if resultado.unable_to_classify else 'Não'}")
    print(f"\n💭 Justificativa:")
    print(f"   {resultado.justificativa}")
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()