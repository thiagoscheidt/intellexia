import json
import os
from datetime import datetime

from dotenv import load_dotenv
from markitdown import MarkItDown
from openai import OpenAI

load_dotenv()


class AgentDocumentSummary:
    client = None
    model_name = None

    def __init__(self, model_name: str = "gpt-4o"):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model_name = model_name

    def summarizeDocument(self, file_path: str | None = None, text_content: str | None = None) -> dict:
        """
        Gera um resumo estruturado em JSON para um documento.

        Args:
            file_path: Caminho do arquivo a ser convertido (PDF/DOCX/etc).
            text_content: Texto já extraído do documento.

        Returns:
            dict: Payload JSON pronto para persistência.
        """
        if not file_path and not text_content:
            raise ValueError("É necessário fornecer file_path ou text_content")

        extracted_text = ""
        if text_content:
            extracted_text = text_content if isinstance(text_content, str) else str(text_content)
        else:
            md = MarkItDown()
            result = md.convert(file_path)
            extracted_text = result.text_content or ""

        max_chars = int(os.getenv("SUMMARY_MAX_CHARS", "24000"))
        truncated = False
        if len(extracted_text) > max_chars:
            extracted_text = extracted_text[:max_chars]
            truncated = True

        system_prompt = (
            "Você é um assistente jurídico. Gere um resumo técnico, objetivo e estruturado. "
            "Responda SOMENTE com um JSON válido seguindo este schema: "
            "{"
            "\"summary\": string,"
            "\"summary_short\": string,"
            "\"summary_long\": string,"
            "\"key_points\": [string],"
            "\"entities\": {\"people\": [string], \"organizations\": [string], \"locations\": [string]},"
            "\"dates\": [string],"
            "\"lawsuit_numbers\": [string],"
            "\"language\": string,"
            "\"notes\": string"
            "}"
        )

        user_prompt = (
            "Resuma o documento abaixo. Preserve informações jurídicas relevantes. "
            "Regras de tamanho: summary_short com 2-4 frases objetivas; summary_long com 2-4 parágrafos, "
            "mais completo e detalhado que o resumo curto. "
            "Se não houver dado para algum campo, use lista vazia ou string vazia.\n\n"
            f"DOCUMENTO:\n{extracted_text}"
        )

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        content = response.choices[0].message.content or "{}"
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            payload = {
                "summary": content.strip(),
                "key_points": [],
                "entities": {"people": [], "organizations": [], "locations": []},
                "dates": [],
                "lawsuit_numbers": [],
                "language": "pt-BR",
                "notes": "Resposta não estava em JSON. Conteúdo armazenado em summary.",
            }

        payload.setdefault("summary", "")
        payload.setdefault("summary_short", "")
        payload.setdefault("summary_long", "")
        payload.setdefault("key_points", [])
        payload.setdefault("entities", {"people": [], "organizations": [], "locations": []})
        payload.setdefault("dates", [])
        payload.setdefault("lawsuit_numbers", [])
        payload.setdefault("language", "pt-BR")
        payload.setdefault("notes", "")

        payload["meta"] = {
            "model": self.model_name,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "source": {
                "file_path": file_path,
                "text_length": len(extracted_text),
                "truncated": truncated,
            },
        }

        return payload