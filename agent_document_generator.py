from io import BytesIO
from openai import OpenAI
from app.prompts.document_reader_prompt import DocumentReaderPrompt
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from docx import Document
from docx.shared import Inches

_ = load_dotenv()


class AgentDocumentGenerator:
    model = None
    prompt = None

    def __init__(self, model_name="gpt-5.2"):
        self.model = ChatOpenAI(model=model_name)
        self.prompt = DocumentReaderPrompt()

    def generate(self, file_id):
        result = self.model.invoke(
            [
                {"role": "system", "content": self.prompt.prompt_template()},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analise o documento e gere um resumo objetivo.",
                        },
                        {"type": "file", "file_id": file_id},
                    ],
                },
            ]
        )
        return result.content

template_text = """
"""

document = Document("modelo_acidente_trajeto.docx")
document.add_heading("Modelo de Documento", 0)


# for table in document.tables:
#     for row in table.rows:
#         for cell in row.cells:
#             for paragraph in cell.paragraphs:
#                 print(paragraph.text)

for table_idx, table in enumerate(document.tables):
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                print(paragraph.text)
    
    # Adiciona nova linha na tabela
    new_row = table.add_row()
    for i, cell in enumerate(new_row.cells):
        if i == 0:
            # Primeira coluna: ID incremental
            cell.text = "1"
        else:
            # Outras colunas: dados mockados
            mock_data = {
                1: "João Silva",
                2: "123.456.789-00",
                3: "15/01/2025",
                4: "R$ 1.500,00",
                5: "Ativo"
            }
            cell.text = mock_data.get(i, f"Dado {i}")

for p in document.paragraphs:
    if p.text.startswith("{{") and p.text.endswith("}}"):
        print("\n", p.text)
    # for run in p.runs:
    #     print(run.text)
# agent = AgentDocumentGenerator()
# response = agent.generate()

document.save("modelo_acidente_trajeto_edit.docx")