from __future__ import annotations

import os
import uuid
import json
import time
import sys
from pathlib import Path as PathLib
from datetime import datetime
from typing import Optional, List
import tempfile

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

class SectionSchema(BaseModel):
    section_content: str = Field(description="Conteúdo da seção/tópico do documento com os dados substituídos")
    replacements_made: List[str] = Field(description="Lista de substituições realizadas")

class FapSectionGeneratorAgent:
    def __init__(self, law_firm_id: int):
        self.openai = OpenAI()
        self.law_firm_id = law_firm_id
        
    def populate_template_with_case_data(self, case_data: str, template_id: int) -> dict:
        """
        Preenche um template de seção/tópico substituindo dados fictícios pelos dados reais do caso
        
        Args:
            case_data: Dados reais do caso (cliente, benefícios, competências, etc)
            template_id: ID do template no banco de dados
            
        Returns:
            Dict com 'section_content' (seção preenchida) e 'replacements_made' (lista de substituições)
        """
        
        # Buscar template no banco de dados
        with app.app_context():
            template = CaseTemplate.query.filter_by(
                id=template_id,
                law_firm_id=self.law_firm_id,
                is_active=True
            ).first()
            
            if not template:
                raise Exception(f"Template ID {template_id} não encontrado ou inativo para law_firm_id={self.law_firm_id}")
            
            # Ler conteúdo do template
            template_path = PathLib(template.file_path)
            
            if not template_path.exists():
                raise Exception(f"Arquivo do template não encontrado: {template.file_path}")
            
            # Converter documento para markdown usando Docling
            try:
                converter = DocumentConverter()
                result = converter.convert(str(template_path))
                template_content = result.document.export_to_markdown()
            except Exception as e:
                raise Exception(f"Erro ao converter template para markdown: {str(e)}")
            
            print(f"📄 Template carregado: {template.template_name}")
            print(f"📂 Categoria: {template.categoria}")
            print(f"📊 Tamanho do template: {len(template_content)} caracteres\n")
        
        # Usar LLM para fazer as substituições
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0
        ).with_structured_output(SectionSchema)

        response = llm.invoke([
            {"role": "system", "content": f"""
                Você é um agente especialista em geração de seções/tópicos de documentos jurídicos previdenciários.
                Sua tarefa é pegar o template de seção fornecido e substituir TODOS os dados fictícios/exemplos 
                pelos dados reais do caso fornecido.
             
                Regras obrigatórias:
                    - Identifique TODOS os dados fictícios no template (nomes, datas, números, CNPJs, etc)
                    - Substitua cada dado fictício pelo dado real correspondente do caso
                    - Mantenha TODA a estrutura, formatação e texto do template
                    - Se um dado real não estiver disponível, mantenha o campo como [PREENCHER: descrição do campo]
                    - Preserve títulos, seções, parágrafos e formatação markdown
                    - Ajuste concordâncias de gênero/número se necessário
                    - Liste todas as substituições realizadas em replacements_made
                    
                Template de seção/tópico: {template.template_name}
                Categoria: {template.categoria}
                
                CONTEÚDO DO TEMPLATE:
                {template_content}
                
                DADOS REAIS DO CASO:
                {case_data}
                
                Retorne a seção/tópico completa com todos os dados fictícios substituídos pelos dados reais.
                """}
        ])
        
        return {
            "section_content": response.section_content,
            "replacements_made": response.replacements_made
        }


def main():
    """Função para testar o gerador de seções/tópicos"""
    
    with app.app_context():
        from app.models import LawFirm
        
        # Buscar primeiro law_firm para teste
        law_firm = LawFirm.query.first()
        
        if not law_firm:
            print("❌ ERRO: Nenhum escritório encontrado no banco de dados!")
            print("   Execute primeiro os scripts de população de dados.")
            return
        
        print("=" * 80)
        print("TESTE DO GERADOR DE SEÇÕES/TÓPICOS FAP")
        print("=" * 80)
        print(f"\n🏢 Escritório: {law_firm.name} (ID: {law_firm.id})")
        
        # Buscar templates disponíveis
        templates = CaseTemplate.query.filter_by(
            law_firm_id=law_firm.id,
            is_active=True
        ).limit(5).all()
        
        if not templates:
            print("\n❌ ERRO: Nenhum template ativo encontrado para este escritório!")
            print("   Execute: python database/populate_case_templates.py")
            return
        
        print(f"\n📋 Templates disponíveis (mostrando 5):")
        for template in templates:
            print(f"   {template.id}. {template.template_name} - {template.categoria}")
        
        # Selecionar primeiro template para teste
        template_id = templates[0].id
        template_name = templates[0].template_name
        
        print(f"\n📄 Template selecionado para teste: {template_name} (ID: {template_id})")
        
        # Dados de exemplo do caso - DADOS REAIS que substituirão os fictícios do template
        case_data = """
        DADOS DO PROCESSO:
        
        CLIENTE:
        - Nome/Razão Social: Metalúrgica Silva & Cia Ltda
        - CNPJ: 12.345.678/0001-90
        - Endereço: Rua das Indústrias, 1500, Distrito Industrial
        - Cidade: São Paulo
        - Estado: SP
        - CEP: 01234-567
        
        ADVOGADO:
        - Nome: Dr. José Carlos Santos
        - OAB: SP 123.456
        - Endereço: Av. Paulista, 1000, sala 501
        - Cidade: São Paulo/SP
        
        PROCESSO:
        - Tipo de Ação: Mandado de Segurança - Revisão FAP
        - Ano FAP: 2020-2022
        - Motivo: Acidente de trajeto incluído indevidamente no FAP
        
        BENEFICIÁRIO/SEGURADO:
        - Nome: João da Silva
        - CPF: 123.456.789-00
        - NIT/PIS: 123.45678.90-1
        - Cargo: Operador de máquinas
        - Data de admissão: 10/01/2015
        
        BENEFÍCIO QUESTIONADO:
        - Tipo: B91 - Auxílio-doença acidentário
        - Número do benefício: 123.456.789
        - NB: 123456789
        - DIB (Data Início): 15/03/2021
        - DCB (Data Cessação): 15/10/2021
        - Valor mensal: R$ 2.500,00
        
        ACIDENTE/CAT:
        - Número CAT: 2021.00.123456
        - Data emissão CAT: 11/03/2021
        - Data do acidente: 10/03/2021 às 07h30
        - Tipo de acidente: Acidente de trajeto (residência-trabalho)
        - Local: Avenida dos Trabalhadores, altura do número 500
        - Descrição: Colisão de motocicleta no trajeto para o trabalho
        - CID: S82.0 - Fratura da patela
        
        FUNDAMENTAÇÃO LEGAL:
        - Lei 8.213/91, Art. 19, §1º (acidente de trajeto não gera responsabilidade do empregador)
        - Lei 10.666/2003 (FAP)
        - Decreto 3.048/99, Art. 336
        - Instrução Normativa INSS/PRES nº 45/2010
        
        COMPETÊNCIAS IMPACTADAS:
        - Ano 2021: março, abril, maio, junho, julho, agosto, setembro, outubro
        - Ano 2022: janeiro, fevereiro, março, abril
        
        VALORES:
        - FAP original: 2,00
        - FAP após correção: 1,50
        - Diferença mensal estimada: R$ 1.200,00
        - Período: 24 meses (2021-2022)
        - Valor total a restituir: R$ 28.800,00
        
        AUTORIDADE COATORA:
        - Superintendente Regional do INSS em São Paulo
        - Agência INSS: São Paulo - Sé
        - Endereço: Praça da Sé, 100 - Centro, São Paulo/SP, CEP 01001-000
        
        VARA/JUÍZO:
        - 1ª Vara Federal de São Paulo
        - Seção Judiciária de São Paulo
        - Endereço: Rua Líbero Badaró, 39 - Centro, São Paulo/SP
        
        PEDIDOS:
        1. Concessão de liminar para suspender exigibilidade da diferença
        2. Revisão do FAP com exclusão do benefício B91 do segurado João da Silva
        3. Restituição dos valores pagos a maior no período (R$ 28.800,00)
        4. Compensação dos valores em contribuições futuras
        5. Condenação em honorários advocatícios e custas processuais
        
        DATA: 26/01/2026
        """
        
        print("\n📋 DADOS DO CASO (REAIS):")
        print(case_data[:500] + "...")
        print("\n" + "=" * 80)
        
        # Instanciar o agente
        agent = FapSectionGeneratorAgent(law_firm_id=law_firm.id)
        
        print("\n🤖 Gerando seção/tópico com substituição de dados...\n")
        print("⏳ Isso pode levar alguns segundos...\n")
        
        try:
            # Gerar seção
            result = agent.populate_template_with_case_data(
                case_data=case_data,
                template_id=template_id
            )
            
            section_content = result["section_content"]
            replacements = result["replacements_made"]
            
            # Exibir resultado
            print("=" * 80)
            print("SEÇÃO/TÓPICO GERADO COM SUCESSO")
            print("=" * 80)
            
            print(f"\n📊 Substituições realizadas ({len(replacements)}):")
            for idx, replacement in enumerate(replacements[:10], 1):  # Mostrar primeiras 10
                print(f"   {idx}. {replacement}")
            if len(replacements) > 10:
                print(f"   ... e mais {len(replacements) - 10} substituições")
            
            print(f"\n📄 SEÇÃO/TÓPICO FINAL (primeiros 1500 caracteres):")
            print("-" * 80)
            print(section_content[:1500])
            if len(section_content) > 1500:
                print("\n... [conteúdo truncado] ...")
            print("-" * 80)
            
            print(f"\n📊 Tamanho total da seção: {len(section_content)} caracteres")
            
            # Converter markdown para Word e salvar
            print("\n" + "=" * 80)
            print("💾 CONVERTENDO PARA WORD E SALVANDO...")
            print("=" * 80)
            
            try:
                # Importar pypandoc (instalar com: pip install pypandoc)
                import pypandoc
                
                # Criar diretório de saída se não existir
                output_dir = root_dir / "uploads" / "generated_sections"
                output_dir.mkdir(parents=True, exist_ok=True)
                
                # Nome do arquivo baseado no template e timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{template_name.replace(' ', '_')}_{timestamp}.docx"
                output_path = output_dir / filename
                
                # Criar arquivo temporário com o markdown
                with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as temp_md:
                    temp_md.write(section_content)
                    temp_md_path = temp_md.name
                
                try:
                    # Converter markdown para docx usando pypandoc
                    pypandoc.convert_file(
                        temp_md_path,
                        'docx',
                        outputfile=str(output_path),
                        extra_args=['--reference-doc=reference.docx'] if (root_dir / 'reference.docx').exists() else []
                    )
                    
                    print(f"\n✅ Arquivo Word salvo com sucesso!")
                    print(f"📁 Localização: {output_path}")
                    print(f"📊 Tamanho: {output_path.stat().st_size / 1024:.2f} KB")
                    
                finally:
                    # Limpar arquivo temporário
                    if os.path.exists(temp_md_path):
                        os.unlink(temp_md_path)
                        
            except ImportError:
                print("\n⚠️  pypandoc não instalado. Para converter para Word, instale:")
                print("   pip install pypandoc")
                print("   Também é necessário ter o Pandoc instalado no sistema.")
                print("   Baixe em: https://pandoc.org/installing.html")
                
                # Salvar apenas o markdown
                output_dir = root_dir / "uploads" / "generated_sections"
                output_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{template_name.replace(' ', '_')}_{timestamp}.md"
                output_path = output_dir / filename
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(section_content)
                
                print(f"\n💾 Arquivo Markdown salvo: {output_path}")
                
            except Exception as e:
                print(f"\n❌ ERRO ao converter para Word: {str(e)}")
                print("   Salvando como markdown...")
                
                # Fallback: salvar como markdown
                output_dir = root_dir / "uploads" / "generated_sections"
                output_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{template_name.replace(' ', '_')}_{timestamp}.md"
                output_path = output_dir / filename
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(section_content)
                
                print(f"💾 Arquivo Markdown salvo: {output_path}")
            
            print("\n" + "=" * 80)
            print("✅ Seção/tópico gerado com sucesso!")
            print("   O template foi preenchido com os dados reais do caso.")
            print("=" * 80)
            
        except Exception as e:
            print(f"❌ ERRO ao gerar seção: {str(e)}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
       