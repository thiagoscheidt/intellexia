"""
Configuração centralizada de modelos LLM para todos os agentes.

Configure via variáveis de ambiente no .env:

    DEFAULT_MODEL=gpt-4o            # tarefas pesadas: geração de documentos, petições
    DEFAULT_MODEL_MINI=gpt-4o-mini  # tarefas médias: análise, extração, classificação, queries
    DEFAULT_MODEL_NANO=gpt-4o-mini  # tarefas leves: roteamento, extração de keywords, metadados

Para uso com OpenRouter, defina também:
    OPENAI_BASE_URL=https://openrouter.ai/api/v1
    OPENAI_API_KEY=sk-or-...
E use nomes com prefixo de provedor (ex: openai/gpt-4o-mini).
"""

import os

# Tarefas pesadas: geração de textos jurídicos completos (petições, recursos, seções FAP)
DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")

# Tarefas médias: análise de documentos, extração estruturada, classificação, queries KB
DEFAULT_MODEL_MINI: str = os.getenv("DEFAULT_MODEL_MINI", "gpt-4o-mini")

# Tarefas leves: roteamento, extração de keywords, metadados simples
DEFAULT_MODEL_NANO: str = os.getenv("DEFAULT_MODEL_NANO", "gpt-4o-mini")
