"""Petição protocolada que chega pelo Google Drive → ficha do índice do escritório.

O Drive entrega só o PDF: sem caminho de pasta (compartilhado arquivo por
arquivo, `parents` vem vazio) e sem número de processo no nome. O que a peça
é, de quem e o que sustenta sai do nome do arquivo e do texto. A ficha tem
**os mesmos campos da linha do índice do lote .md** (autora, tribunal, órgão
julgador, peça, protocolo, teses), para a petição vinda do Drive entrar na
Base de Conhecimento igual à que veio pelo lote.

O número do processo **não** é pedido à IA como fonte: quem o lê é
`lote_md_import_service.processo_do_texto`, a regra já medida no lote (o número
rotulado logo após o endereçamento, nunca um precedente citado). A IA só o
sugere quando a regra não acha nenhum, e mesmo assim ele só vale se estiver
no texto.

Recebe o texto já extraído (pdfplumber), não o PDF: as petições do Drive têm
texto pesquisável, e mandar texto custa uma fração de mandar o arquivo.
Resposta cortada no limite de saída ganha UMA nova tentativa sem raciocínio
(ver FapPetitionReviewerAgent); os tokens das duas são contabilizados.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agents.config import DEFAULT_MODEL_ROBUST
from app.services.token_usage_service import TokenUsageService

_PROMPT = (Path(__file__).resolve().parents[2] / 'prompts' / 'drive_peticao_protocolada.md').read_text(encoding='utf-8')

# Texto demais não melhora a ficha e encarece: 120 mil caracteres cobrem a
# petição mais longa do lote com folga (as teses estão no corpo, não nos anexos).
MAX_CARACTERES = 120_000


class PeticaoExtraida(BaseModel):
    eh_peticao: bool = Field(description='Peça processual do escritório?')
    peca: str = Field(default='', description='Tipo da peça, CAIXA ALTA, vocabulário do índice.')
    autora: str = Field(default='', description='EMPRESA (VIGÊNCIAS), CAIXA ALTA.')
    tribunal: str = Field(default='', description='TRF-1..TRF-6, STJ ou STF.')
    orgao_julgador: str = Field(default='', description='Vara ou turma do endereçamento.')
    data_protocolo: str = Field(default='', description='DD/MM/AAAA ou vazio.')
    processo: str = Field(default='', description='Número do processo desta ação, como consta.')
    teses: str = Field(default='', description='TÍTULO. OBS.: síntese; … (CAIXA ALTA).')
    observacao: str = Field(default='')


class ExtracaoFalhou(Exception):
    """Falha com mensagem para a pessoa (vai para a linha da tela do Drive)."""


class SemTexto(ExtracaoFalhou):
    """PDF sem texto pesquisável — não adianta tentar de novo na próxima rodada."""


class PeticaoProtocoladaAgent:
    AGENT_NAME = 'PeticaoProtocoladaAgent'
    MAX_TOKENS = 12000

    def __init__(self, model_name: Optional[str] = None,
                 llm_factory: Optional[Callable[[bool], Any]] = None):
        """`llm_factory(com_raciocinio)` devolve o runnable já com saída
        estruturada — injetável para teste sem rede."""
        self.model_name = model_name or DEFAULT_MODEL_ROBUST
        self._llm_factory = llm_factory or self._llm_padrao
        self.token_usage_service = TokenUsageService()

    def _llm_padrao(self, com_raciocinio: bool):
        extra = {} if com_raciocinio else {'extra_body': {'reasoning': {'enabled': False}}}
        return ChatOpenAI(
            model=self.model_name, temperature=0, max_tokens=self.MAX_TOKENS, **extra,
        ).with_structured_output(PeticaoExtraida, include_raw=True)

    @staticmethod
    def montar_prompt(pecas_referencia: list[str]) -> str:
        lista = '\n'.join(f'  - {p}' for p in pecas_referencia) or '  (sem lista: use nomes curtos e consagrados)'
        return _PROMPT.replace('{pecas_referencia}', lista)

    @staticmethod
    def _cortada(raw) -> bool:
        metadata = getattr(raw, 'response_metadata', None) or {}
        return str(metadata.get('finish_reason') or '').strip().lower() in ('length', 'content_filter')

    def _registrar(self, raw, *, acao, law_firm_id, user_id, latency_ms, arquivo, extra=None):
        if raw is None:
            return
        try:
            self.token_usage_service.capture_and_store(
                {'messages': [raw]},
                agent_name=self.AGENT_NAME,
                action_name=acao,
                print_prefix='[PeticaoProtocolada]',
                model_name=self.model_name,
                model_provider='openai',
                user_id=user_id,
                law_firm_id=law_firm_id,
                latency_ms=latency_ms,
                metadata_payload={'arquivo': arquivo, **(extra or {})},
            )
        except Exception as erro:
            # Contabilidade não derruba a leitura que deu certo.
            print(f'[PeticaoProtocolada] falha ao registrar tokens: {erro}')

    def extrair(self, texto: str, nome_arquivo: str, *, pecas_referencia: Optional[list[str]] = None,
                law_firm_id: Optional[int] = None, user_id: Optional[int] = None) -> dict:
        """Ficha da petição a partir do texto. Levanta ``ExtracaoFalhou``."""
        texto = (texto or '').strip()
        if len(texto) < 200:
            raise SemTexto('O PDF não tem texto pesquisável (provavelmente escaneado).')
        mensagens = [
            {'role': 'system', 'content': self.montar_prompt(pecas_referencia or [])},
            {'role': 'user', 'content': (
                f'Nome do arquivo no Drive: {nome_arquivo}\n\n'
                f'Texto da peça:\n\n{texto[:MAX_CARACTERES]}'
            )},
        ]
        ultimo_erro = ''
        for tentativa in (1, 2):
            inicio = time.time()
            try:
                saida = self._llm_factory(tentativa == 1).invoke(mensagens)
            except Exception as erro:
                texto_erro = str(erro)
                if '429' in texto_erro or 'rate' in texto_erro.lower():
                    raise ExtracaoFalhou('O provedor de IA recusou por limite de uso. Tenta de novo na próxima rodada.') from erro
                ultimo_erro = texto_erro
                continue
            latencia = int((time.time() - inicio) * 1000)
            raw = saida.get('raw') if isinstance(saida, dict) else None
            parsed = saida.get('parsed') if isinstance(saida, dict) else saida
            cortada = self._cortada(raw)
            if parsed is None or cortada:
                self._registrar(raw, acao='extrair_peticao_descartada', law_firm_id=law_firm_id,
                                user_id=user_id, latency_ms=latencia, arquivo=nome_arquivo,
                                extra={'cortada': cortada, 'tentativa': tentativa})
                ultimo_erro = 'resposta cortada no limite de saída' if cortada else 'resposta fora do formato'
                continue
            self._registrar(raw, acao='extrair_peticao', law_firm_id=law_firm_id, user_id=user_id,
                            latency_ms=latencia, arquivo=nome_arquivo, extra={'tentativa': tentativa})
            return parsed.model_dump() if hasattr(parsed, 'model_dump') else dict(parsed)
        raise ExtracaoFalhou(f'A IA não conseguiu ler a petição: {ultimo_erro[:300]}')
