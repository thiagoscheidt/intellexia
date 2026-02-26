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

from flask import current_app, has_app_context
from app.models import db, FapReason


load_dotenv()

class ResponseSchema(BaseModel):
    id: Optional[int] = Field(description="ID do motivo FAP selecionado")
    display_name: Optional[str] = Field(description="Nome do motivo FAP")
    description: Optional[str] = Field(description="Descrição do motivo FAP")
    confidence: float = Field(description="Nível de confiança na classificação (0.0 a 1.0)")
    justificativa: str = Field(description="Breve explicação da escolha")
    unable_to_classify: bool = Field(default=False, description="True se não foi possível classificar com confiança mínima")

class FapCaseClassifierAgent:
    def __init__(self, law_firm_id: int):
        self.openai = OpenAI()
        self.law_firm_id = law_firm_id

    def _should_return_null_reason(self, benefit_description: str) -> bool:
        text = (benefit_description or "").lower()
        if not text:
            return True

        null_tokens = [
            "nada consta",
            "não consta",
            "nao consta",
            "típico",
            "tipico",
            "nl",
            "n/l",
            "sem observação",
            "sem observacao",
            "sem observações",
            "sem observacoes",
        ]
        uncertainty_tokens = [
            "não tenho certeza",
            "nao tenho certeza",
            "incerto",
            "incerteza",
            "dúvida",
            "duvida",
            "não há certeza",
            "nao ha certeza",
        ]

        return any(token in text for token in null_tokens + uncertainty_tokens)

    def determineFapReason(self, benefit_description: str):
        """
        Determina o motivo FAP mais adequado para um caso
        
        Args:
            benefit_description: Descrição do benefício com observações
            
        Returns:
            ResponseSchema com id, display_name, description, confidence, justificativa e unable_to_classify
        """

        description_text = (benefit_description or "").strip()
        if self._should_return_null_reason(description_text):
            return ResponseSchema(
                id=None,
                display_name=None,
                description=None,
                confidence=0.0,
                justificativa=(
                    "Observação indica ausência de motivo (ex.: nada consta, típico ou NL)."
                ),
                unable_to_classify=True,
            )
        
        # Buscar motivos FAP do banco de dados para este law_firm
        if has_app_context():
            fap_reasons = FapReason.query.filter_by(
                law_firm_id=self.law_firm_id,
                is_active=True
            ).order_by(FapReason.id).all()
        else:
            with current_app.app_context():
                fap_reasons = FapReason.query.filter_by(
                    law_firm_id=self.law_firm_id,
                    is_active=True
                ).order_by(FapReason.id).all()

        if not fap_reasons:
            raise Exception(f"Nenhum motivo FAP ativo encontrado para law_firm_id={self.law_firm_id}")

        # Gerar lista de motivos no formato do prompt
        reasons_list = []
        for idx, reason in enumerate(fap_reasons, 1):
            description = reason.description or "(sem descrição)"
            reasons_list.append(
                f"{idx}. {reason.display_name} — {description}"
            )
        
        reasons_text = "\n".join(reasons_list)
        
        llm = ChatOpenAI(
            model="gpt-5-mini-mini",
            temperature=0
        ).with_structured_output(ResponseSchema)

        response = llm.invoke([
            {"role": "system", "content": f"""
                Você é um agente especialista em classificar casos jurídicos relacionados ao FAP, NTEP e benefícios previdenciários.
                Sua tarefa é analisar a descrição do caso fornecida e identificar qual motivo FAP da lista abaixo melhor representa a situação apresentada.
             
                Regras obrigatórias:
                    - Você deve escolher APENAS UM item da lista (ID 1 a {len(fap_reasons)}).
                    - Não crie novos motivos.
                    - Baseie sua decisão exclusivamente na descrição do caso.
                    - Retorne a resposta somente em formato JSON.
                    - A justificativa deve ser breve (máximo 2 linhas).
                    - Caso o caso não se encaixe perfeitamente em um único item, escolha o motivo mais próximo e reduza o nível de confiança.
                    - Se a confiança for inferior a 0.5 ou se não houver informações suficientes para classificar, defina "unable_to_classify" como true.
                    - Quando "unable_to_classify" for true, retorne id, display_name e description como null.
                    - Se a descrição indicar que não há motivo claro (ex.: observação com "nada consta", "típico" ou "NL"), defina "unable_to_classify" como true e retorne os campos de motivo como null.

                    Lista de opções (use exatamente os IDs e nomes abaixo):
             
                    {reasons_text}

                    Descrição do caso:
                    {description_text}

                    Formato obrigatório de resposta (somente JSON):

                    {{
                        "id": null,
                        "display_name": null,
                        "description": null,
                        "confidence": 0.0,
                        "justificativa": "breve explicação",
                        "unable_to_classify": false
                    }}
                """}
        ])
        
        return response


def main():
    """Função para testar o classificador de casos FAP"""
    from main import app
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
        
        # Verificar se há motivos FAP cadastrados
        reasons_count = FapReason.query.filter_by(
            law_firm_id=law_firm.id,
            is_active=True
        ).count()
        
        print(f"📋 Motivos FAP disponíveis: {reasons_count}")
        
        if reasons_count == 0:
            print("\n❌ ERRO: Nenhum motivo FAP ativo encontrado para este escritório!")
            print("   Verifique a tabela fap_reasons para este escritório.")
            return
        
        # Exemplo de descrição de benefício para teste
        descricao_beneficio = """
        Empresa recebeu notificação do FAP onde consta um benefício B91 (auxílio-doença acidentário)
        que foi concedido a um funcionário que sofreu acidente de trajeto indo para o trabalho.
        A CAT foi emitida pela empresa dentro do prazo, mas acreditamos que acidente de trajeto
        não deveria impactar o FAP da empresa.
        """
        
        print("\n📋 DESCRIÇÃO DO BENEFÍCIO:")
        print(descricao_beneficio)
        print("\n" + "=" * 80)
        
        # Instanciar o agente
        agent = FapCaseClassifierAgent(law_firm_id=law_firm.id)
        
        print("\n🤖 Processando classificação...\n")
        
        try:
            # Executar classificação
            resultado = agent.determineFapReason(descricao_beneficio)
            
            # Exibir resultado
            print("=" * 80)
            print("RESULTADO DA CLASSIFICAÇÃO")
            print("=" * 80)
            print(f"\n📌 ID: {resultado.id}")
            print(f"📄 Motivo: {resultado.display_name}")
            print(f"📝 Descrição: {resultado.description}")
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