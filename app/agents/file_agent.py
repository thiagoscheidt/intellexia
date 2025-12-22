import requests
from io import BytesIO
from openai import OpenAI
from dotenv import load_dotenv

_ = load_dotenv()


class FileAgent:
    def __init__(self):
        self.client = OpenAI()

    def upload_file(self, file_path: str):
        """
        Faz upload de um arquivo para a OpenAI.
        
        Args:
            file_path: Pode ser uma URL (http/https) ou caminho local do arquivo
        """
        if file_path.startswith('http://') or file_path.startswith('https://'):
            # Baixa o arquivo da URL
            response = requests.get(file_path)
            response.raise_for_status()
            file_content = BytesIO(response.content)
            file_name = file_path.split("/")[-1]
        elif file_path.startswith('file://'):
            # Remove o prefixo file:// e abre o arquivo local
            local_path = file_path.replace('file://', '')
            with open(local_path, 'rb') as f:
                file_content = BytesIO(f.read())
            file_name = local_path.split("/")[-1].split("\\")[-1]
        else:
            # Assume que é um caminho local direto
            with open(file_path, 'rb') as f:
                file_content = BytesIO(f.read())
            file_name = file_path.split("/")[-1].split("\\")[-1]

        # Upload correto para Assistants API
        result = self.client.files.create(
            file=(file_name, file_content), purpose="assistants"
        )
        return result.id
