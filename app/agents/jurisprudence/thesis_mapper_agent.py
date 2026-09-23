"""Sugestão de correspondência: tese das decisões → catálogo do Painel.

Só sugere; quem confirma é a pessoa, na tela de Correspondência de teses.
Três saídas possíveis por tese: ligar a uma ou mais teses do catálogo, mesclar
numa tese já existente da base (outra grafia da mesma ideia) ou "sem
equivalente" (tema processual, não tese de FAP).
"""
from __future__ import annotations

import json
import time
from typing import Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agents.config import DEFAULT_MODEL_ROBUST
from app.services.token_usage_service import TokenUsageService

_SISTEMA = """Você organiza a base de jurisprudência FAP de um escritório de advocacia.

As decisões judiciais trazem TESES em texto livre. O escritório tem um CATÁLOGO de teses, usado para montar as peças. Para cada tese pendente, sugira UMA destas saídas:

Os identificadores são de dois tipos e NUNCA se misturam: `catalogo_id` identifica uma tese do CATÁLOGO; `tese_id` identifica uma tese da BASE de decisões. O mesmo número pode existir nas duas listas e significar coisas diferentes.

1. catalogo_ids: os `catalogo_id` das teses do catálogo que correspondem a ela. Pode ser mais de uma: o catálogo é mais fino que a decisão. Exemplo: "ACIDENTE DE TRAJETO" corresponde a "TRAJETO - B91", "TRAJETO - B92", "TRAJETO - B93" e "TRAJETO - B94", porque o catálogo separa por espécie de benefício.
2. mesclar_em_tese_id: o `tese_id` de outra tese da base, quando a tese é só outra grafia de uma tese que JÁ EXISTE na base ("BENEFICIOS EM DUPLICIDADE" = "DUPLICIDADE DE BENEFICIO"). Mescle na que tem mais decisões. Mescle só quando for a mesma ideia jurídica, não apenas um tema parecido.
3. sem_equivalente: true quando for tema processual ou acessório, e não uma tese de FAP (honorários, custas, gratuidade…), e não houver tese do catálogo para ela.

NÃO FORCE a ligação. Ligue só quando a tese do catálogo tratar do MESMO fato ou vício — não de um tema vizinho. Erro no índice de frequência não é erro no índice de custo; "base estatística" não é "60 dias". Tese ampla ou genérica (erro metodológico, erro de cálculo em geral) que não tem tese específica no catálogo fica pendente. Na dúvida, devolva a tese com as listas vazias e sem_equivalente false: ela continua pendente para a pessoa decidir — uma sugestão errada custa mais que nenhuma. Nunca invente identificadores: use só os das listas recebidas, cada um no seu campo. Em "motivo", diga em uma frase curta por que sugeriu."""


class SugestaoDeTese(BaseModel):
    tese_id: int = Field(description='tese_id da tese pendente a que a sugestão se refere')
    catalogo_ids: list[int] = Field(default_factory=list, description='catalogo_id das teses do CATÁLOGO')
    mesclar_em_tese_id: Optional[int] = Field(default=None, description='tese_id de outra tese da BASE')
    sem_equivalente: bool = False
    motivo: str = ''


class SugestoesDeTeses(BaseModel):
    sugestoes: list[SugestaoDeTese] = Field(default_factory=list)


class JurisprudenceThesisMapperAgent:
    AGENT_NAME = 'JurisprudenceThesisMapperAgent'

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or DEFAULT_MODEL_ROBUST
        self.token_usage_service = TokenUsageService()

    def sugerir(self, *, teses: list[dict], catalogo: list[dict], existentes: list[dict],
                law_firm_id: Optional[int] = None, user_id: Optional[int] = None) -> list[SugestaoDeTese]:
        if not teses:
            return []
        llm = ChatOpenAI(model=self.model_name, temperature=0).with_structured_output(
            SugestoesDeTeses, include_raw=True)
        usuario = (
            'CATÁLOGO DO ESCRITÓRIO (catalogo_id, nome, descrição):\n'
            + json.dumps(catalogo, ensure_ascii=False)
            + '\n\nTESES JÁ EXISTENTES NA BASE (tese_id, nome, nº de decisões) — candidatas a mescla:\n'
            + json.dumps(existentes, ensure_ascii=False)
            + '\n\nTESES PENDENTES (sugira para cada uma):\n'
            + json.dumps(teses, ensure_ascii=False)
        )
        inicio = time.time()
        saida = llm.invoke([{'role': 'system', 'content': _SISTEMA}, {'role': 'user', 'content': usuario}])
        raw = saida.get('raw') if isinstance(saida, dict) else None
        parsed = saida.get('parsed') if isinstance(saida, dict) else saida
        if raw is not None:
            try:
                self.token_usage_service.capture_and_store(
                    {'messages': [raw]}, agent_name=self.AGENT_NAME, action_name='sugerir_correspondencia',
                    print_prefix='[JurisprudenceThesisMapper]', model_name=self.model_name,
                    model_provider='openai', user_id=user_id, law_firm_id=law_firm_id,
                    latency_ms=int((time.time() - inicio) * 1000),
                    metadata_payload={'teses': len(teses)},
                )
            except Exception as erro:
                print(f'[JurisprudenceThesisMapper] falha ao registrar tokens: {erro}')
        return list(parsed.sugestoes) if parsed else []
