from io import BytesIO
from openai import OpenAI
from app.prompts.document_reader_prompt import DocumentReaderPrompt
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

_ = load_dotenv()


class AgentDocumentReader:
    model = None
    prompt = None

    def __init__(self, model_name="gpt-4o"):
        self.model = ChatOpenAI(model=model_name)
        self.prompt = DocumentReaderPrompt()

    def analyze_document(self, file_id=None, text_content=None):
        """
        Analisa um documento através de file_id (PDF, imagens) ou texto extraído (DOCX)
        
        Args:
            file_id: ID do arquivo na OpenAI (para PDFs e outros formatos)
            text_content: Texto extraído do documento (para DOCX)
            
        Returns:
            str: Resumo estruturado do documento
        """
        instruction = """Analise o documento a seguir com olhar técnico-jurídico, como um advogado experiente.
                Extraia e organize todas as informações juridicamente relevantes, incluindo:
                partes envolvidas e suas qualificações;
                dados pessoais e sensíveis, quando existentes;
                dados processuais (número do processo, juízo, fase, prazos e decisões);
                objeto do documento;
                fatos essenciais;
                fundamentos legais;
                pedidos, direitos e obrigações;
                prazos, riscos jurídicos e impactos.
                Ao final, gere um resumo objetivo e estruturado, destacando apenas o que é útil para a tomada de decisão jurídica."""
        
        if text_content:
            # Para DOCX: enviar como texto puro
            result = self.model.invoke(
                [
                    {"role": "system", "content": self.prompt.prompt_template()},
                    {
                        "role": "user",
                        "content": f"{instruction}\n\n**DOCUMENTO:**\n\n{text_content}"
                    }
                ]
            )
        elif file_id:
            # Para PDF e outros: usar file_id
            result = self.model.invoke(
                [
                    {"role": "system", "content": self.prompt.prompt_template()},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": instruction,
                            },
                            {"type": "file", "file_id": file_id},
                        ],
                    },
                ]
            )
        else:
            raise ValueError("É necessário fornecer file_id ou text_content")
        
        return result.content
