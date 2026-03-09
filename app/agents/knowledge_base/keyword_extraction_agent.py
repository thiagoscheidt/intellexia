import os
import logging
import time
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from app.services.token_usage_service import TokenUsageService


logger = logging.getLogger(__name__)


class KeywordExtractionSchema(BaseModel):
    search_keywords: list[str] = Field(
        description="Lista de termos-chave extraídos da pergunta (CPF, CNPJ, números de processo, benefício, etc.)"
    )
    extracted_type: str = Field(
        default="mixed",
        description="Tipo de busca identificado: 'cpf', 'cnpj', 'process_number', 'benefit_number', 'name', 'date', 'mixed' ou 'generic'"
    )


class KeywordExtractionAgent:
    """Extrai termos-chave (CPF, CNPJ, números, etc) de perguntas para busca full_text otimizada."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("KB_ROUTER_MODEL", "gpt-5-nano")
        self.llm = ChatOpenAI(model=self.model_name, temperature=0)
        self.token_usage_service = TokenUsageService()

    def extract_keywords(self, question: str) -> list[str]:
        """
        Extrai termos-chave da pergunta para busca full_text.
        
        Retorna ambos os formatos (original e normalizado) para CPF/CNPJ:
        - Exemplo: '88.611.835/0008-03' → ['88.611.835/0008-03', '88611835000803']
        - Exemplo: '098.545.439.-35' → ['098.545.439.-35', '09854543935']
        
        Args:
            question: Pergunta do usuário
            
        Returns:
            Lista de termos-chave extraídos, ou lista vazia se nenhum termo específico encontrado
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "Você é um extrator de termos-chave para busca em base de conhecimento jurídica.\n"
                    "Sua tarefa é identificar e extrair os termos mais importantes da pergunta do usuário:\n"
                    "- CPF ou CNPJ (RETORNE AMBOS: com formatação original E normalizado sem pontos/hífens)\n"
                    "- Números de processo judicial (CNJ format ou variações)\n"
                    "- Números de benefício (B91, B94, B31, etc.)\n"
                    "- Datas (no formato que aparecem)\n"
                    "- Nomes de pessoas ou empresas\n"
                    "- Qualquer número ou código específico\n\n"
                    "Retorne uma lista com os termos extraídos em ordem de relevância.\n"
                    "Se a pergunta for muito genérica e não tiver termos específicos, retorne lista vazia.\n"
                    "IMPORTANTE: Para CPF/CNPJ, inclua AMBAS as formas:\n"
                    "  - Exemplo: se encontrar '88.611.835/0008-03', retorne: ['88.611.835/0008-03', '88611835000803']\n"
                    "  - Exemplo: se encontrar '098.545.439.-35', retorne: ['098.545.439.-35', '09854543935']"
                ),
            },
            {
                "role": "user",
                "content": f"Extrai os termos-chave desta pergunta:\n\n{question}",
            },
        ]

        try:
            agent = create_agent(
                model=self.llm,
                response_format=ToolStrategy(KeywordExtractionSchema),
            )
            
            call_started_at = time.time()
            response_payload = agent.invoke({"messages": messages})
            latency_ms = int((time.time() - call_started_at) * 1000)
            
            # Capturar tokens
            self.token_usage_service.capture_and_store(
                response_payload,
                agent_name="KeywordExtractionAgent",
                action_name="extract_keywords",
                print_prefix="[KeywordExtractionAgent][tokens]",
                model_name=self.model_name,
                model_provider="openai",
                latency_ms=latency_ms,
                status="success",
                metadata_payload={"question_length": len(question)},
            )
            
            result = response_payload.get("structured_response")
            if not result:
                raise RuntimeError("Resposta estruturada não retornada pelo create_agent")
            
            logger.debug(
                "Extração de termos-chave concluída | "
                "extracted_type=%s | keywords_count=%d | keywords=%s",
                result.extracted_type,
                len(result.search_keywords),
                result.search_keywords,
            )
            return result.search_keywords
        except Exception as e:
            logger.error("Erro ao extrair termos-chave: %s", str(e))
            return []
