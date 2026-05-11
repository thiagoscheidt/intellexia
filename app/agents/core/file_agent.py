import base64
import mimetypes
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from openai import OpenAI

_ = load_dotenv()


class FileAgent:
    def __init__(self):
        self.base_url = str(os.getenv('OPENAI_BASE_URL', '') or '').strip().lower()
        self.is_openrouter = 'openrouter.ai' in self.base_url
        self.client = None if self.is_openrouter else OpenAI()

    def build_openrouter_file_part(self, file_path: str) -> dict:
        """
        Constrói o payload de arquivo para OpenRouter no formato:
        {"type": "file", "file": {"filename": "...", "file_data": "..."}}

        - Para URL pública: `file_data` recebe a URL
        - Para arquivo local: `file_data` recebe data URL base64
        """
        normalized = str(file_path or '').strip()
        if not normalized:
            raise ValueError('Caminho/URL de arquivo inválido')

        if normalized.startswith('http://') or normalized.startswith('https://'):
            filename = Path(urlparse(normalized).path).name or 'document.pdf'
            return {
                'type': 'file',
                'file': {
                    'filename': filename,
                    'file_data': normalized,
                }
            }

        local_path = normalized.replace('file://', '') if normalized.startswith('file://') else normalized
        path_obj = Path(local_path)
        if not path_obj.exists() or not path_obj.is_file():
            raise FileNotFoundError(f'Arquivo não encontrado: {local_path}')

        file_bytes = path_obj.read_bytes()
        mime_type = mimetypes.guess_type(path_obj.name)[0] or 'application/octet-stream'
        b64 = base64.b64encode(file_bytes).decode('utf-8')
        data_url = f'data:{mime_type};base64,{b64}'

        return {
            'type': 'file',
            'file': {
                'filename': path_obj.name,
                'file_data': data_url,
            }
        }

    def upload_file(self, file_path: str):
        """
        Faz upload de um arquivo para a OpenAI Files API (legado).
        
        Args:
            file_path: Pode ser uma URL (http/https) ou caminho local do arquivo
        """
        if self.is_openrouter:
            raise RuntimeError(
                'upload_file() não é compatível com OpenRouter. '
                'Use build_openrouter_file_part() e envie no content da mensagem.'
            )

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
