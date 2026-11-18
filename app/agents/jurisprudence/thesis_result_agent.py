"""Placar de teses de uma decisão que já está na base (PRC-24 e PRC-25).

A leitura completa (`JurisprudenceDecisionExtractorAgent`) já devolve o tipo de
julgamento e o resultado de cada tese para as decisões novas. As que já estão
na base — as 509 da planilha e as lidas antes do placar — não podem ser relidas
do zero: a releitura trocaria teses, resultado e ementa que o escritório já usa
e ligou ao catálogo. Este agente lê o texto e devolve SÓ os dois campos novos,
para as teses que a decisão já tem, escritas como estão.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agents.config import DEFAULT_MODEL_ROBUST
from app.agents.jurisprudence.decision_extractor_agent import JULGAMENTOS, ResultadoDaTese
from app.services.token_usage_service import TokenUsageService

# Acórdão longo passa de 100 mil caracteres; o dispositivo fica no fim, então o
# corte guarda começo e fim.
MAX_CARACTERES = 160_000

_SISTEMA = """Você é um assistente jurídico especializado em FAP (Fator Acidentário de Prevenção). Leia a decisão judicial e responda só o que foi pedido, usando EXCLUSIVAMENTE o que está no texto.

1. tipo_julgamento: o que a decisão julgou de fato.
   - MERITO: o julgador decidiu o pedido da empresa (acolheu ou rejeitou, no todo ou em parte).
   - HOMOLOGACAO DO RECONHECIMENTO: a União (ou o INSS) reconheceu a procedência do pedido e o juízo só homologou esse reconhecimento, sem decidir a tese.
   - SEM RESOLUCAO DE MERITO: extinção sem julgamento do mérito (ilegitimidade, perda do objeto, desistência, coisa julgada, litispendência, inadequação da via etc.).
   Se a decisão homologa o reconhecimento de parte dos pedidos e julga o restante, é MERITO, e as teses reconhecidas pela União vão como NAO JULGADA.

2. resultado_por_tese: UMA linha para CADA tese da lista recebida, com o nome escrito EXATAMENTE como veio (não traduza, não corrija, não crie tese nova). Resultado daquela tese **para a empresa**:
   - FAVORAVEL: o pedido ligado à tese foi acolhido.
   - DESFAVORAVEL: o pedido ligado à tese foi rejeitado.
   - PARCIALMENTE FAVORAVEL: acolhido só em parte (por exemplo, alguns benefícios excluídos e outros não).
   - NAO JULGADA: a decisão não decidiu aquela tese (prejudicada, não conhecida, homologada pelo reconhecimento da União, ou só mencionada).
   O resultado da decisão inteira NÃO vale para cada tese: uma sentença parcialmente favorável pode ter ganhado uma tese e perdido outra. Em embargos de declaração, a tese só tem resultado se os embargos a decidiram; senão, NAO JULGADA."""


class PlacarDaDecisao(BaseModel):
    tipo_julgamento: JULGAMENTOS = Field(description='O que a decisão julgou.')
    resultado_por_tese: list[ResultadoDaTese] = Field(default_factory=list)


class LeituraFalhou(Exception):
    """Falha com mensagem curta (vai para o relatório do script)."""


def recortar(texto: str, limite: int = MAX_CARACTERES) -> str:
    if len(texto) <= limite:
        return texto
    metade = limite // 2
    return texto[:metade] + '\n\n[… trecho do meio omitido …]\n\n' + texto[-metade:]


class JurisprudenceThesisResultAgent:
    AGENT_NAME = 'JurisprudenceThesisResultAgent'
    MAX_TOKENS = 4000

    def __init__(self, model_name: Optional[str] = None,
                 llm_factory: Optional[Callable[[], Any]] = None):
        """`llm_factory()` devolve o runnable já com saída estruturada —
        injetável para teste sem rede."""
        self.model_name = model_name or DEFAULT_MODEL_ROBUST
        self._llm_factory = llm_factory or self._llm_padrao
        self.token_usage_service = TokenUsageService()

    def _llm_padrao(self):
        return ChatOpenAI(model=self.model_name, temperature=0, max_tokens=self.MAX_TOKENS
                          ).with_structured_output(PlacarDaDecisao, include_raw=True)

    def _conteudo(self, *, texto: Optional[str], arquivo: Optional[str]) -> dict:
        if texto and texto.strip():
            return {'type': 'text', 'text': 'Texto da decisão:\n\n' + recortar(texto)}
        if arquivo:
            from app.agents.jurisprudence.decision_extractor_agent import JurisprudenceDecisionExtractorAgent
            try:
                parte = JurisprudenceDecisionExtractorAgent._parte_do_arquivo(arquivo)
            except FileNotFoundError as erro:
                raise LeituraFalhou('arquivo não está no servidor') from erro
            if parte.get('type') == 'text':
                parte = {**parte, 'text': recortar(parte['text'])}
            return parte
        raise LeituraFalhou('sem texto nem arquivo')

    def ler(self, *, teses: list[str], texto: Optional[str] = None, arquivo: Optional[str] = None,
            law_firm_id: Optional[int] = None, decision_id: Optional[int] = None) -> dict:
        """{'tipo_julgamento': 'MERITO'…, 'resultado_por_tese': [{'tese', 'resultado'}]}"""
        conteudo = self._conteudo(texto=texto, arquivo=arquivo)
        lista = '\n'.join(f'- {t}' for t in teses) or '(a decisão não tem teses cadastradas: devolva a lista vazia)'
        mensagens = [
            {'role': 'system', 'content': _SISTEMA},
            {'role': 'user', 'content': [{'type': 'text', 'text': f'TESES DESTA DECISÃO:\n{lista}'}, conteudo]},
        ]
        inicio = time.time()
        try:
            saida = self._llm_factory().invoke(mensagens)
        except Exception as erro:
            raise LeituraFalhou(f'IA: {str(erro)[:200]}') from erro
        raw = saida.get('raw') if isinstance(saida, dict) else None
        parsed = saida.get('parsed') if isinstance(saida, dict) else saida
        if raw is not None:
            try:
                self.token_usage_service.capture_and_store(
                    {'messages': [raw]}, agent_name=self.AGENT_NAME, action_name='placar_da_decisao',
                    print_prefix='[JurisprudenceThesisResult]', model_name=self.model_name,
                    model_provider='openai', law_firm_id=law_firm_id,
                    latency_ms=int((time.time() - inicio) * 1000),
                    metadata_payload={'decision_id': decision_id, 'arquivo': Path(arquivo).name if arquivo else None},
                )
            except Exception as erro:
                print(f'[JurisprudenceThesisResult] falha ao registrar tokens: {erro}')
        if parsed is None:
            raise LeituraFalhou('resposta fora do formato')
        dados = parsed.model_dump() if hasattr(parsed, 'model_dump') else dict(parsed)
        # Só as teses que a decisão tem, na grafia dela: a IA às vezes "corrige" o nome.
        from app.services import jurisprudence_normalizer as norm
        por_chave = {norm.chave(t): t for t in teses}
        dados['resultado_por_tese'] = [
            {'tese': por_chave[norm.chave(item['tese'])], 'resultado': item['resultado']}
            for item in dados.get('resultado_por_tese') or []
            if norm.chave(item.get('tese')) in por_chave
        ]
        return dados
