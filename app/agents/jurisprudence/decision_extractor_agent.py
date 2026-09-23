"""Leitura de uma decisão judicial FAP em PDF → registro estruturado.

O prompt é o da ferramenta que o escritório usava (Banco Mestre FAP), com o
que a planilha provou faltar: resultado e instância como valores fechados
(pedir "use FAVORAVEL" no texto rendeu FAVORÁVEL e FAVORAVEL misturados),
tribunal e órgão em campos separados (155 grafias de tribunal) e instrução
própria para argumentos acolhidos/rejeitados, que antes o modelo adivinhava
pelo nome do campo.

Saída estruturada em vez de "responda só com JSON": 57% das falhas da
ferramenta anterior eram JSON malformado ou cortado.

Resposta cortada no limite de saída (`finish_reason=length`) ou que não valida
ganha UMA nova tentativa, sem raciocínio estendido e com a ementa resumida em
vez de transcrita — o raciocínio sai do mesmo orçamento que a resposta (ver
FapPetitionReviewerAgent), e a ementa literal é o campo mais longo. A ementa
que vem dessa tentativa é marcada como resumo, para ninguém citar paráfrase
como transcrição. Os tokens das duas tentativas são contabilizados.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agents.config import DEFAULT_MODEL_ROBUST
from app.agents.core.file_agent import FileAgent
from app.services.token_usage_service import TokenUsageService

_PROMPT = (Path(__file__).resolve().parents[2] / 'prompts' / 'jurisprudence_extraction.md').read_text(encoding='utf-8')

_EMENTA_LITERAL = (
    'SOMENTE em ACÓRDÃO. Transcreva a ementa fielmente, incluindo o cabeçalho em CAIXA ALTA '
    '("TRIBUTÁRIO. PROCESSO CIVIL. FAP...") e os itens numerados, sem parafrasear. Limite a cerca '
    'de 2.500 palavras: se for maior, transcreva o cabeçalho e os itens até esse limite e termine com '
    '"[...]". Não inclua a palavra "Ementa:" no início. Em sentença ou embargos, devolva "".'
)
_EMENTA_RESUMO = (
    'SOMENTE em ACÓRDÃO. NÃO transcreva a ementa. Faça um RESUMO objetivo do conteúdo dela, com '
    'suas próprias palavras: a matéria, as teses fixadas e o dispositivo, em 3 a 8 frases. Não inclua '
    'a palavra "Ementa:" no início. Em sentença ou embargos, devolva "".'
)

TIPOS = Literal['SENTENCA', 'ACORDAO', 'EMBARGOS DE DECLARACAO', 'OUTRA']
RESULTADOS = Literal['FAVORAVEL', 'PARCIALMENTE FAVORAVEL', 'DESFAVORAVEL']


class DecisaoExtraida(BaseModel):
    processo: str = Field(default='', description='Número do processo como consta.')
    tribunal: str = Field(default='', description='Somente a sigla: TRF4, TRF3, STJ, STF…')
    orgao_julgador: str = Field(default='', description='Turma (acórdão) ou vara (sentença).')
    uf: str = Field(default='', description='UF da vara de origem, se identificável.')
    relator: str = Field(default='', description='Relator ou juiz.')
    data_julgamento: str = Field(default='', description='DD/MM/AAAA.')
    tipo_documento: TIPOS = Field(description='Instância da decisão.')
    classe_processual: str = Field(default='', description='Classe por extenso.')
    resultado: RESULTADOS = Field(description='Resultado para a EMPRESA.')
    motivo_resultado: str = Field(default='', description='Por que o resultado foi esse.')
    parte_autora: str = Field(default='', description='Empresa autora.')
    vigencia_fap: str = Field(default='', description='"AAAA a AAAA" ou "AAAA".')
    teses: list[str] = Field(default_factory=list, description='Todas as teses, CAIXA ALTA.')
    ementa: str = Field(default='', description='Ver regra da ementa no prompt.')
    fundamentos: list[str] = Field(default_factory=list)
    precedentes: list[str] = Field(default_factory=list)
    argumentos_acolhidos: list[str] = Field(default_factory=list)
    argumentos_rejeitados: list[str] = Field(default_factory=list)
    resumo_executivo: str = Field(default='')
    palavras_chave: list[str] = Field(default_factory=list)


class ExtracaoFalhou(Exception):
    """Falha com mensagem para a pessoa (vai para a linha da fila)."""


class JurisprudenceDecisionExtractorAgent:
    AGENT_NAME = 'JurisprudenceDecisionExtractorAgent'
    MAX_TOKENS = 16000

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
        ).with_structured_output(DecisaoExtraida, include_raw=True)

    @staticmethod
    def montar_prompt(teses_referencia: list[str], resumir_ementa: bool) -> str:
        if teses_referencia:
            lista = ' | '.join(teses_referencia)
            referencia = (
                '  Use PREFERENCIALMENTE os nomes já usados pelo escritório, exatamente como estão, '
                f'quando se aplicarem: {lista}. Se a decisão tratar de tese específica que não esteja '
                'bem representada por eles, crie um nome curto e padronizado em CAIXA ALTA — sempre o '
                'mesmo nome para o mesmo conceito.'
            )
        else:
            referencia = '  Use nomes curtos, consagrados e sempre iguais para o mesmo conceito.'
        return (_PROMPT
                .replace('{teses_referencia}', referencia)
                .replace('{ementa_regra}', _EMENTA_RESUMO if resumir_ementa else _EMENTA_LITERAL))

    @staticmethod
    def _cortada(raw) -> bool:
        metadata = getattr(raw, 'response_metadata', None) or {}
        return str(metadata.get('finish_reason') or '').strip().lower() in ('length', 'content_filter')

    def _registrar(self, raw, *, acao: str, law_firm_id, user_id, latency_ms, arquivo, extra=None):
        if raw is None:
            return
        try:
            self.token_usage_service.capture_and_store(
                {'messages': [raw]},
                agent_name=self.AGENT_NAME,
                action_name=acao,
                print_prefix='[JurisprudenceExtractor]',
                model_name=self.model_name,
                model_provider='openai',
                user_id=user_id,
                law_firm_id=law_firm_id,
                latency_ms=latency_ms,
                metadata_payload={'arquivo': arquivo, **(extra or {})},
            )
        except Exception as erro:
            # Contabilidade não derruba a leitura que deu certo.
            print(f'[JurisprudenceExtractor] falha ao registrar tokens: {erro}')

    def extrair(self, file_path: str, *, teses_referencia: Optional[list[str]] = None,
                law_firm_id: Optional[int] = None, user_id: Optional[int] = None) -> dict:
        """Lê o PDF e devolve o registro bruto (chaves do Banco Mestre) +
        `ementa_modo` ('literal' | 'resumo' | None)."""
        try:
            file_part = FileAgent().build_openrouter_file_part(file_path)
        except FileNotFoundError as erro:
            raise ExtracaoFalhou('O arquivo não está mais no servidor. Envie de novo.') from erro

        arquivo = Path(file_path).name
        ultimo_erro = ''
        for tentativa, resumir in enumerate((False, True), start=1):
            mensagens = [
                {'role': 'system', 'content': self.montar_prompt(teses_referencia or [], resumir)},
                {'role': 'user', 'content': [
                    {'type': 'text', 'text': 'Extraia os dados desta decisão.'},
                    file_part,
                ]},
            ]
            inicio = time.time()
            try:
                saida = self._llm_factory(tentativa == 1).invoke(mensagens)
            except Exception as erro:
                texto = str(erro)
                if '429' in texto or 'rate' in texto.lower():
                    raise ExtracaoFalhou('O provedor de IA recusou por limite de uso. Tente de novo em alguns minutos.') from erro
                ultimo_erro = texto
                if tentativa == 1:
                    continue
                raise ExtracaoFalhou(f'A IA não conseguiu ler o documento: {texto[:300]}') from erro
            latencia = int((time.time() - inicio) * 1000)
            raw = saida.get('raw') if isinstance(saida, dict) else None
            parsed = saida.get('parsed') if isinstance(saida, dict) else saida
            cortada = self._cortada(raw)

            if parsed is None or cortada:
                self._registrar(raw, acao='extrair_decisao_descartada', law_firm_id=law_firm_id,
                                user_id=user_id, latency_ms=latencia, arquivo=arquivo,
                                extra={'descartada': True, 'cortada': cortada, 'tentativa': tentativa})
                ultimo_erro = ('resposta cortada no limite de saída' if cortada
                               else f'resposta fora do formato: {str(saida.get("parsing_error") if isinstance(saida, dict) else "")[:200]}')
                continue

            self._registrar(raw, acao='extrair_decisao', law_firm_id=law_firm_id, user_id=user_id,
                            latency_ms=latencia, arquivo=arquivo,
                            extra={'tentativa': tentativa, 'ementa_resumida': resumir})
            dados = parsed.model_dump() if hasattr(parsed, 'model_dump') else dict(parsed)
            if not (dados.get('processo') or '').strip() and not (dados.get('resumo_executivo') or '').strip():
                raise ExtracaoFalhou(
                    'A leitura não achou número de processo nem conteúdo da decisão. '
                    'O PDF pode ser imagem sem texto ou não ser uma decisão judicial.')
            dados['ementa_modo'] = ('resumo' if resumir else 'literal') if (dados.get('ementa') or '').strip() else None
            return dados

        raise ExtracaoFalhou(f'A IA não devolveu uma leitura válida nas duas tentativas ({ultimo_erro}).')
