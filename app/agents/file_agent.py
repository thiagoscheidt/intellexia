import requests
from io import BytesIO
from openai import OpenAI
from dotenv import load_dotenv

_ = load_dotenv()


class FileAgent:
    def __init__(self):
        self.client = OpenAI()

    def upload_file(self, file_url: str):
        # Baixa o arquivo da URL
        response = requests.get(file_url)
        response.raise_for_status()

        file_content = BytesIO(response.content)
        file_name = file_url.split("/")[-1]

        # Upload correto para Assistants API
        result = self.client.files.create(
            file=(file_name, file_content), purpose="assistants"
        )
        return result.id
