import os

from langchain_openai import ChatOpenAI


class QueryEnhancerAgent:
    """Melhora perguntas para busca semântica na base vetorial."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("QUERY_ENHANCER_MODEL", "gpt-4o-mini")
        self.llm = ChatOpenAI(model=self.model_name, temperature=0)

    def enhance_question(self, question: str, history: list[dict] | None = None) -> str:
        cleaned_question = (question or "").strip()
        if not cleaned_question:
            return ""

        history = history or []
        limited_history = history[-10:] if len(history) > 10 else history
        history_lines: list[str] = []
        for item in limited_history:
            role = item.get("role", "")
            content = item.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(part) for part in content)
            content = str(content).strip()
            if role and content:
                history_lines.append(f"{role}: {content}")

        history_block = "\n".join(history_lines) if history_lines else "(sem histórico)"

        system_prompt = (
            "Você é um agente de reformulação de consultas para busca vetorial jurídica. "
            "Reescreva a pergunta para melhorar recall e precisão sem alterar a intenção original. "
            "Mantenha em português, seja objetivo e preserve nomes, números de processo, datas e termos legais relevantes. "
            "Retorne somente a pergunta reformulada, sem explicações."
        )

        user_prompt = (
            "Considere o histórico e reescreva APENAS a pergunta atual para consulta semântica em base jurídica.\n\n"
            f"Histórico recente:\n{history_block}\n\n"
            f"Pergunta atual:\n{cleaned_question}"
        )

        try:
            response = self.llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
            improved_question = (response.content or "").strip()
            return improved_question or cleaned_question
        except Exception as e:
            print(f"Erro ao melhorar pergunta para busca: {str(e)}")
            return cleaned_question