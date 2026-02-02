from io import BytesIO
from openai import OpenAI
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import json
import os

_ = load_dotenv()


class AgentTextGenerator:
    """
    Agent para geração de textos jurídicos baseado em modelos de arquivo
    """
    
    def __init__(self, model_name="gpt-4o"):
        self.model = ChatOpenAI(model=model_name, temperature=0.3)
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.template_file_id = None
        self.case_context = None

    def set_template_file(self, file_id):
        """
        Define o arquivo modelo que será usado como base para geração
        
        Args:
            file_id (str): ID do arquivo enviado para OpenAI
        """
        self.template_file_id = file_id
        print(file_id)
    
    def set_case_context(self, case_context):
        """
        Define o contexto do caso para geração
        
        Args:
            case_context (dict): Contexto estruturado do caso
        """
        self.case_context = case_context
    
    def generate_petition_with_template(self, case_data, benefits_data, documents_data):
        """
        Gera petição baseada no template fornecido e dados do caso
        
        Args:
            case_data (dict): Dados do caso
            benefits_data (list): Lista de benefícios
            documents_data (list): Lista de documentos
        
        Returns:
            str: Petição gerada em formato markdown
        """
        
        system_prompt = """
Você é um especialista em redação jurídica. Sua tarefa é gerar uma petição/documento jurídico COMPLETO e PROFISSIONAL.

INSTRUÇÕES PARA GERAÇÃO:
1. Use o MODELO FORNECIDO como base estrutural
2. Integre TODAS as informações do caso fornecidas
3. Mantenha a linguagem técnica e formal apropriada
4. Garanta coerência jurídica e sequência lógica
5. Substitua campos/variáveis pelos dados reais do caso
6. Adapte o conteúdo conforme necessário

QUALIDADE ESPERADA:
✅ Texto completo e pronto para uso
✅ Linguagem jurídica correta
✅ Estrutura lógica e coerente  
✅ Todas as informações do caso integradas
✅ Formatação adequada em markdown

IMPORTANTE:
- NÃO deixe campos em branco ou com placeholders
- NÃO adicione comentários explicativos no texto final
- USE APENAS as informações fornecidas sobre o caso
- MANTENHA fidelidade ao modelo estrutural
- GARANTA texto pronto para uso imediato

Gere agora o documento final completo em formato markdown.
"""

        # Preparar dados do caso
        case_info = f"""
DADOS DO CASO:
- Título: {case_data.get('title', '')}
- Cliente: {case_data.get('client_name', '')} - CNPJ: {case_data.get('client_cnpj', '')}
- Tipo: {case_data.get('case_type', '')}
- Valor da Causa: R$ {case_data.get('value_cause', 'Não informado')}
- Fatos: {case_data.get('facts_summary', '')}
- Tese Jurídica: {case_data.get('thesis_summary', '')}
- Vara: {case_data.get('court_name', '')} - {case_data.get('court_city', '')}/{case_data.get('court_state', '')}

BENEFÍCIOS ({len(benefits_data)} no total):
"""
        
        for i, benefit in enumerate(benefits_data, 1):
            case_info += f"""
{i}. Benefício nº {benefit.get('benefit_number', '')} - {benefit.get('benefit_type', '')}
   Segurado: {benefit.get('insured_name', '')}
   NIT: {benefit.get('insured_nit', '')}
   Data do Acidente: {benefit.get('accident_date', '')}
"""

        if documents_data:
            case_info += f"\nDOCUMENTOS ANALISADOS ({len(documents_data)} no total):\n"
            for doc in documents_data:
                case_info += f"- {doc.get('original_filename', '')}: {doc.get('ai_summary', '')}\n"

        # Mensagem para o modelo
        user_message = f"""
Baseado no modelo fornecido e nas informações do caso abaixo, gere a petição/documento jurídico completo.

{case_info}

Gere o texto completo seguindo exatamente a estrutura e formato do modelo, substituindo todas as variáveis pelos dados reais do caso.
"""

        # Usar a API de Assistants para trabalhar com arquivos
        try:
            # Criar um assistant temporário
            assistant = self.openai_client.beta.assistants.create(
                name="Gerador de Petições",
                instructions=system_prompt,
                model="gpt-4o",
                tools=[{"type": "file_search"}],
                tool_resources={
                    "file_search": {
                        "vector_stores": [
                            {
                                "file_ids": [self.template_file_id]
                            }
                        ]
                    }
                }
            )
            
            # Criar um thread
            thread = self.openai_client.beta.threads.create()
            
            # Criar mensagem no thread
            message = self.openai_client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=user_message
            )
            
            # Executar o assistant
            run = self.openai_client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=assistant.id
            )
            
            # Aguardar conclusão
            while run.status in ['queued', 'in_progress']:
                import time
                time.sleep(1)
                run = self.openai_client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id
                )
            
            if run.status == 'completed':
                # Obter mensagens
                messages_response = self.openai_client.beta.threads.messages.list(
                    thread_id=thread.id
                )
                
                # Pegar a última mensagem (resposta do assistant)
                assistant_message = messages_response.data[0]
                response_content = assistant_message.content[0].text.value
                
                # Limpar resources
                self.openai_client.beta.assistants.delete(assistant.id)
                
                return response_content
            else:
                # Fallback para método simples se assistants falharem
                print(f"Assistant run falhou com status: {run.status}")
                return self._generate_simple_fallback(user_message, system_prompt)
                
        except Exception as e:
            print(f"Erro com Assistants API: {e}")
            # Fallback para método simples
            return self._generate_simple_fallback(user_message, system_prompt)
    
    def _generate_simple_fallback(self, user_message, system_prompt):
        """Método fallback sem usar arquivo"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message + "\n\nNOTA: Use um formato de petição padrão profissional."}
        ]
        
        response = self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.3
        )
        
        return response.choices[0].message.content
        
    def generate_simple_petition(self, case_data, benefits_data):
        """
        Gera petição simples sem template (fallback)
        """
        system_prompt = """
Você é um especialista em redação jurídica. Gere uma petição inicial completa e profissional baseada nos dados fornecidos.

Use estrutura padrão:
1. Cabeçalho e qualificação das partes
2. Exposição dos fatos
3. Do direito (fundamentação jurídica)
4. Dos pedidos
5. Requerimentos finais
"""

        case_info = f"""
DADOS PARA PETIÇÃO:
- Cliente: {case_data.get('client_name', '')} - CNPJ: {case_data.get('client_cnpj', '')}
- Tipo de Caso: {case_data.get('case_type', '')}
- Valor: R$ {case_data.get('value_cause', '')}
- Fatos: {case_data.get('facts_summary', '')}
- Vara: {case_data.get('court_name', '')}

BENEFÍCIOS:
"""
        for benefit in benefits_data:
            case_info += f"- {benefit.get('benefit_number', '')} - {benefit.get('insured_name', '')}\n"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Gere uma petição completa com base em:\n{case_info}"}
        ]
        
        response = self.model.invoke(messages)
        print(response.content)
        return response.content