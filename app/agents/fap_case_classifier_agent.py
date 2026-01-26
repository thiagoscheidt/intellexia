from __future__ import annotations

import os
import uuid
import json
import time
import sys
from pathlib import Path as PathLib
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

# Adicionar o diretório raiz ao path para imports do app
root_dir = PathLib(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from app.models import db, CaseTemplate
from main import app


load_dotenv()

class ResponseSchema(BaseModel):
    id: int = Field(description="ID do template selecionado")
    nome_arquivo: str = Field(description="Nome do arquivo do template")
    categoria: str = Field(description="Categoria do caso")
    confidence: float = Field(description="Nível de confiança na classificação (0.0 a 1.0)")
    justificativa: str = Field(description="Breve explicação da escolha")
    unable_to_classify: bool = Field(default=False, description="True se não foi possível categorizar com confiança mínima")

class FapCaseClassifierAgent:
    def __init__(self, law_firm_id: int):
        self.openai = OpenAI()
        self.law_firm_id = law_firm_id

    def determineCategoryTemplate(self, case_description: str):
        """
        Determina a categoria e template mais adequado para um caso FAP
        
        Args:
            case_description: Descrição do caso a ser classificado
            
        Returns:
            ResponseSchema com id, nome_arquivo, categoria, confidence, justificativa e unable_to_classify
        """
        
        # Buscar templates do banco de dados para este law_firm
        with app.app_context():
            templates = CaseTemplate.query.filter_by(
                law_firm_id=self.law_firm_id,
                is_active=True
            ).order_by(CaseTemplate.id).all()
            
            if not templates:
                raise Exception(f"Nenhum template ativo encontrado para law_firm_id={self.law_firm_id}")
            
            # Gerar lista de templates no formato do prompt
            templates_list = []
            for idx, template in enumerate(templates, 1):
                templates_list.append(
                    f"{idx}. {template.template_name} — {template.categoria}"
                )
            
            templates_text = "\n".join(templates_list)
        
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0
        ).with_structured_output(ResponseSchema)

        response = llm.invoke([
            {"role": "system", "content": f"""
                Você é um agente especialista em classificar casos jurídicos relacionados ao FAP, NTEP e benefícios previdenciários. 
                Sua tarefa é analisar a descrição do caso fornecida e identificar qual item da lista abaixo melhor representa o tipo de situação apresentada.
             
                Regras obrigatórias:
                    - Você deve escolher APENAS UM item da lista (ID 1 a {len(templates)}).
                    - Não crie novos itens ou categorias.
                    - Baseie sua decisão exclusivamente na descrição do caso.
                    - Retorne a resposta somente em formato JSON.
                    - A justificativa deve ser breve (máximo 2 linhas).
                    - Caso o caso não se encaixe perfeitamente em um único item, escolha o mais próximo e reduza o nível de confiança.
                    - Se a confiança for inferior a 0.5 ou se não houver informações suficientes para categorizar, defina "unable_to_classify" como true.
                    - Quando "unable_to_classify" for true, ainda assim escolha a categoria mais próxima possível e explique na justificativa o motivo da incerteza.

                    Lista de opções (use exatamente os IDs e nomes abaixo):
             
                    {templates_text}

                    Descrição do caso:
                    {case_description}

                    Formato obrigatório de resposta (somente JSON):

                    {{
                        "id": number,
                        "nome_arquivo": "string",
                        "categoria": "string",
                        "confidence": 0.0,
                        "justificativa": "breve explicação",
                        "unable_to_classify": false
                    }}
                """}
        ])
        
        return response


def main():
    """Função para testar o classificador de casos FAP"""
    
    with app.app_context():
        from app.models import LawFirm
        
        # Buscar primeiro law_firm para teste
        law_firm = LawFirm.query.first()
        
        if not law_firm:
            print("❌ ERRO: Nenhum escritório encontrado no banco de dados!")
            print("   Execute primeiro os scripts de população de dados.")
            return
        
        print("=" * 80)
        print("TESTE DO CLASSIFICADOR DE CASOS FAP")
        print("=" * 80)
        print(f"\n🏢 Escritório: {law_firm.name} (ID: {law_firm.id})")
        
        # Verificar se há templates cadastrados
        templates_count = CaseTemplate.query.filter_by(
            law_firm_id=law_firm.id,
            is_active=True
        ).count()
        
        print(f"📋 Templates disponíveis: {templates_count}")
        
        if templates_count == 0:
            print("\n❌ ERRO: Nenhum template ativo encontrado para este escritório!")
            print("   Execute: python database/populate_case_templates.py")
            return
        
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
        agent = FapCaseClassifierAgent(law_firm_id=law_firm.id)
        
        print("\n🤖 Processando classificação...\n")
        
        try:
            # Executar classificação
            resultado = agent.determineCategoryTemplate(descricao_caso)
            
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
        except Exception as e:
            print(f"❌ ERRO ao classificar: {str(e)}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()