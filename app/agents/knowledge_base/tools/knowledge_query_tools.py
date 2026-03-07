from __future__ import annotations

import re
from typing import Callable

from langchain_core.tools import tool


@tool("normalizar_pergunta_sugerida")
def normalizar_pergunta_sugerida(texto: str) -> str:
    """Normaliza uma pergunta sugerida para envio direto à IA."""
    if not texto:
        return ""

    clean = " ".join(str(texto).split()).strip()
    clean = re.sub(
        r"^(próxima\s+pergunta:|proxima\s+pergunta:|próxima\s+ação:|proxima\s+acao:)",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    return clean


@tool("criar_sugestoes_proximo_passo")
def criar_sugestoes_proximo_passo(pergunta: str, resposta: str) -> list[str]:
    """Gera sugestões de perguntas/comandos para próximo passo do usuário."""
    if not resposta:
        return [
            "Faça um resumo objetivo do caso com os principais pontos e status atual.",
            "Liste os próximos passos práticos recomendados para este caso.",
            "Quais documentos ou informações faltam para avançar com segurança?",
        ]

    return [
        "Faça um resumo objetivo do caso com os principais pontos e status atual.",
        "Liste os próximos passos práticos recomendados para este caso.",
        "Quais documentos ou informações faltam para avançar com segurança?",
    ]


@tool("obter_capital_pais_ficticio")
def obter_capital_pais_ficticio(pais: str) -> str:
    """Retorna a capital de um país fictício para testes de tool calling."""
    capitais_ficticias = {
        "auroria": "Luminápolis",
        "drakonia": "Vulkar",
        "novaterra": "Porto Claro",
        "zelphar": "Névoa Alta",
        "kandora": "Solaris",
    }

    chave = (pais or "").strip().lower()
    if not chave:
        return "Informe o nome de um país fictício para consultar a capital."

    capital = capitais_ficticias.get(chave)
    if not capital:
        disponiveis = ", ".join(sorted(capitais_ficticias.keys()))
        return f"País fictício não encontrado. Opções disponíveis: {disponiveis}."

    return f"A capital de {pais.strip()} é {capital}."


class KnowledgeQueryTools:
    """Registro de tools para o KnowledgeQueryAgent.

    Adicione novos métodos com `@tool` e exponha via `get_tools`.
    """

    def __init__(
        self,
        should_use_context_resolver: Callable[[str, str], bool] | None = None,
        context_search_resolver: Callable[[str, str], str] | None = None,
    ) -> None:
        self._tools = [
            normalizar_pergunta_sugerida,
            criar_sugestoes_proximo_passo,
            obter_capital_pais_ficticio,
        ]

        if should_use_context_resolver is not None:
            @tool("decidir_uso_contexto")
            def decidir_uso_contexto(pergunta: str, historico: str = "") -> str:
                """Decide se deve buscar contexto na base vetorial antes de responder."""
                try:
                    should_use = bool(should_use_context_resolver(pergunta, historico))
                    return "usar_contexto" if should_use else "nao_usar_contexto"
                except Exception:
                    return "usar_contexto"

            self._tools.append(decidir_uso_contexto)

        if context_search_resolver is not None:
            @tool("buscar_contexto_base")
            def buscar_contexto_base(pergunta: str, historico: str = "") -> str:
                """Busca contexto na base vetorial e retorna trechos com índice de fonte."""
                try:
                    return context_search_resolver(pergunta, historico)
                except Exception as exc:
                    return f"Falha ao buscar contexto: {exc}"

            self._tools.append(buscar_contexto_base)

    def register_tool(self, tool_fn: Callable) -> None:
        self._tools.append(tool_fn)

    def get_tools(self) -> list:
        return list(self._tools)
