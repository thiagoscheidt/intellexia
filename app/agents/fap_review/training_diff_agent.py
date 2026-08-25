"""
Agrupador das diferenças de uma revisão FAP.

Recebe a lista de mudanças que ``fap_training_diff_service`` extraiu com
``difflib`` e a transforma em padrões. É a ponte entre o que mudou e o que se
aprende: nas petições reais do escritório o diff traz ~240 pares "de → para",
e a maioria é ruído isolado (uma vírgula, ``1196,`` virando ``1.196,``).
Agrupados, viram meia dúzia de padrões — "preposição antes de FAP: 8
ocorrências" — que é a forma em que uma regra de manual pode ser escrita.

O prompt deste agente é embutido: agrupar diferenças é tarefa mecânica, sem
política do escritório. O que é configurável por escritório fica no agente
seguinte, o que propõe as mudanças no manual.
"""

import json
import os
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class ChangePattern(BaseModel):
    """Um padrão de correção e QUAIS mudanças o compõem.

    O modelo devolve só o rótulo e os índices. Contagem, exemplos e relevância
    saem do código, em ``fap_training_diff_service.reconcile_patterns`` — o
    modelo errava os três: somava ocorrências além das mudanças existentes,
    ilustrava "correção de placeholder" com a inserção de uma preposição, e
    marcava como "caso isolado" um padrão de 15 ocorrências ausente do manual.
    """

    pattern: str = Field(..., description="O padrão de correção, em uma frase")
    change_indices: list[int] = Field(
        default_factory=list,
        description="Os números (#N) das mudanças que formam este padrão",
    )


class ChangeGrouping(BaseModel):
    """Os padrões encontrados numa revisão."""

    summary: str = Field(..., description="O que a revisão fez, em um parágrafo")
    patterns: list[ChangePattern] = Field(default_factory=list)


class FapTrainingDiffGrouperAgent:
    """Agrupa as diferenças literais de uma revisão em padrões."""

    _SYSTEM_PROMPT = (
        "Você analisa a revisão de uma petição inicial de Ação Revisional do FAP.\n\n"
        "Você recebe a lista LITERAL e COMPLETA das diferenças entre a versão que o "
        "advogado entregou e a versão que o revisor sênior devolveu. Cada diferença "
        "vem numerada (#0, #1, #2...). A lista foi extraída mecanicamente: é o texto "
        "exato que mudou, não um resumo.\n\n"
        "Sua tarefa é agrupar as diferenças em PADRÕES de correção. Para cada padrão, "
        "devolva a frase que o descreve e a LISTA DOS NÚMEROS das diferenças que o "
        "compõem.\n\n"
        "Regras:\n"
        "1. Cada diferença pertence a UM padrão só. Não repita o mesmo número em "
        "padrões diferentes.\n"
        "2. Classifique TODAS as diferenças que puder. O que sobrar sem padrão será "
        "contado e mostrado ao usuário.\n"
        "3. Agrupe correções equivalentes. Quinze trocas de \"índice FAP\" por "
        "\"índice do FAP\" são UM padrão com quinze números, nunca quinze padrões.\n"
        "4. Não crie dois padrões para a mesma coisa. \"Ajuste de preposição antes de "
        "FAP\" e \"correção de regência com FAP\" são o mesmo padrão.\n"
        "5. Mas não vá ao extremo oposto: devolva entre 8 e 15 padrões. Um padrão de "
        "cem ocorrências chamado \"padronização de nomes, siglas e grafia\" não ensina "
        "nada a ninguém — ele junta coisas que se corrigem de formas diferentes.\n"
        "6. O teste do rótulo: um revisor deve conseguir APLICAR o padrão lendo só a "
        "frase. \"Escrever 'índice do FAP', nunca 'índice FAP'\" passa no teste. "
        "\"Ajustes diversos de forma\" não passa. Se você precisou de três \"e\" para "
        "descrever o grupo, ele está largo demais — separe.\n"
        "7. Todas as diferenças de um mesmo padrão têm de compartilhar um traço "
        "LITERAL, visível no texto. Separar milhar (\"1196\" para \"1.196\") e "
        "capitalizar um cargo não compartilham traço nenhum.\n"
        "8. O rótulo será exibido junto dos trechos literais: rótulo que não bate "
        "com o trecho fica evidente na tela.\n"
        "9. Não invente número que não está na lista."
    )

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
    ):
        api_key = openai_api_key or os.environ.get("OPENAI_API_KEY")
        self.llm = ChatOpenAI(api_key=api_key, model=model, temperature=temperature)

    async def group_changes(self, changes_text: str, changes_summary: dict | None = None) -> ChangeGrouping:
        """Agrupa as diferenças literais em padrões de correção."""
        counts = changes_summary or {}
        contagem = (
            f"A revisão tem {counts.get('total', 0)} mudanças: "
            f"{counts.get('changes', 0)} trechos alterados, "
            f"{counts.get('additions', 0)} parágrafos acrescentados e "
            f"{counts.get('removals', 0)} removidos.\n\n"
        ) if counts else ""

        user_prompt = (
            f"{contagem}"
            "Retorne SOMENTE JSON com:\n"
            "summary (string — o que esta revisão fez, em um parágrafo),\n"
            "patterns (array de objetos com pattern e change_indices).\n\n"
            "DIFERENÇAS LITERAIS (numeradas):\n"
            f"{changes_text}"
        )

        # Erro de contexto, credencial ou rede sobe para quem chamou marcar a
        # execução como falha; engolir aqui devolveria um agrupamento vazio com
        # cara de resultado.
        response = self.llm.invoke(
            [SystemMessage(content=self._SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
        )

        parsed = self._parse_json(response.content)
        try:
            return ChangeGrouping(**parsed)
        except Exception:
            return ChangeGrouping(
                summary="O modelo respondeu fora do formato esperado ao agrupar as diferenças.",
                patterns=[],
            )

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        """Extrai o primeiro objeto JSON válido do texto."""
        if not content:
            return {}

        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}

        try:
            return json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            return {}
