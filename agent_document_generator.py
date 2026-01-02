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
document.save("modelo_acidente_trajeto_edit.docx")

for table in document.tables:
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                print(paragraph.text)

for p in document.paragraphs:
    if p.text.startswith("{{") and p.text.endswith("}}"):
        print("Found template placeholder:", p.text)
    # for run in p.runs:
    #     print(run.text)
# agent = AgentDocumentGenerator()
# response = agent.generate()