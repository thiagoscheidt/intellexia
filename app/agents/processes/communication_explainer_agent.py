"""
CommunicationExplainerAgent — explica uma comunicação processual em linguagem
clara: o que aconteceu, se há prazo, que ação é exigida e com qual urgência.

Apoio à triagem do Monitoramento de Processos. NÃO substitui a conferência
oficial de prazos — o disclaimer é exibido junto ao resultado na tela.
"""
from __future__ import annotations

import os
import time

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agents.config import DEFAULT_MODEL_MINI
from app.services.token_usage_service import TokenUsageService

MAX_TEOR_CHARS = 20000


class CommunicationDeadline(BaseModel):
    """Prazo identificado no teor (ou ausência dele)."""

    existe: bool = Field(description='True se o teor indica prazo para alguma providência')
    descricao: str | None = Field(default=None, description='Descrição do prazo em linguagem clara')
    dias: int | None = Field(default=None, description='Quantidade de dias do prazo, se numérico')
    tipo_contagem: str | None = Field(default=None, description="'uteis', 'corridos' ou null se não especificado")
    data_limite_estimada: str | None = Field(default=None, description='Data-limite estimada (YYYY-MM-DD), se calculável')
    base_calculo: str | None = Field(default=None, description='A partir de que evento o prazo conta')


class KeyDate(BaseModel):
    data: str = Field(description='Data no formato YYYY-MM-DD (ou texto literal se incompleta)')
    descricao: str = Field(description='O que acontece nessa data')


class GlossaryItem(BaseModel):
    termo: str
    significado: str = Field(description='Explicação curta e acessível')


class CommunicationExplanation(BaseModel):
    """Explicação estruturada de uma comunicação processual."""

    resumo: str = Field(description='2-3 frases claras: o que aconteceu e o que significa para o cliente')
    tipo_ato: str | None = Field(default=None, description=(
        "Tipo do ato comunicado, deduzido do teor: 'sentenca', 'decisao_interlocutoria', "
        "'despacho', 'acordao', 'ato_ordinatorio', 'edital', 'audiencia' ou 'outro'"))
    tipo_ato_detalhe: str | None = Field(default=None, description=(
        'Descrição curta do ato (ex.: "Sentença integrativa em embargos de declaração")'))
    acao_requerida: str = Field(description="'exige_acao', 'acao_facultativa' ou 'apenas_ciencia'")
    acao_descricao: str | None = Field(default=None, description='Qual providência tomar (ou considerar), se houver')
    prazo: CommunicationDeadline
    datas_chave: list[KeyDate] = Field(default_factory=list, description='Sessões, audiências, janelas — em ordem cronológica')
    papel_escritorio: str | None = Field(default=None, description='Posição do cliente/advogado do escritório no processo (ex.: advogado do apelado)')
    urgencia: str = Field(description="'alta', 'media' ou 'baixa'")
    urgencia_justificativa: str | None = Field(default=None, description='Uma linha justificando a urgência')
    glossario: list[GlossaryItem] = Field(default_factory=list, description='Só termos técnicos incomuns presentes no teor')


class CommunicationExplainerAgent:
    """Explica comunicações do DJEN com saída estruturada e temperatura 0."""

    SYSTEM_PROMPT = (
        'Você é um assistente jurídico de um escritório brasileiro (direito trabalhista e '
        'previdenciário). Sua tarefa é explicar comunicações processuais do DJEN para '
        'apoiar a triagem diária.\n\n'
        'Regras:\n'
        '- Escreva em português claro e direto, para leitura rápida.\n'
        '- tipo_ato: classifique o ato comunicado pelo TEOR (o campo "Tipo" da comunicação quase '
        'sempre é "Intimação" e não diz qual ato foi publicado): decisão que resolve o mérito ou '
        'encerra a fase → "sentenca"; decisão no curso do processo → "decisao_interlocutoria"; '
        'mero impulso processual → "despacho" ou "ato_ordinatorio"; decisão colegiada de tribunal '
        '→ "acordao"; designação ou realização de audiência → "audiencia"; edital → "edital"; '
        'não identificável → "outro". Em tipo_ato_detalhe, uma linha curta e específica '
        '(ex.: "Sentença integrativa em embargos de declaração").\n'
        '- Prazos: extraia exatamente o que o teor diz; calcule a data-limite apenas quando as '
        'datas necessárias estiverem no texto. Nunca invente prazo — se não houver, existe=false.\n'
        '- acao_requerida: "exige_acao" só quando o teor determina providência com consequência; '
        '"acao_facultativa" quando a manifestação é opcional; "apenas_ciencia" para atos sem providência.\n'
        '- urgencia "alta" apenas com prazo curto ou consequência grave; a maioria dos atos de '
        'ciência é "baixa".\n'
        '- Glossário: no máximo 3 termos, apenas os realmente incomuns para um assistente iniciante.\n'
        '- Use SOMENTE informações presentes no texto fornecido.'
    )

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv('COMMUNICATION_EXPLAINER_MODEL', DEFAULT_MODEL_MINI)
        self.token_usage_service = TokenUsageService()

    def explain(self, payload: dict, user_id: int | None = None,
                law_firm_id: int | None = None) -> CommunicationExplanation:
        """Gera a explicação. ``payload`` traz metadados + teor + contexto do processo."""
        teor = (payload.get('teor') or '')[:MAX_TEOR_CHARS]
        contexto_processo = payload.get('contexto_processo') or 'Processo ainda não cadastrado no painel.'
        advogados_escritorio = payload.get('advogados_escritorio') or 'não informado'

        user_prompt = (
            f"COMUNICAÇÃO PROCESSUAL\n"
            f"- Data de disponibilização no diário: {payload.get('data_disponibilizacao') or 'não informada'}\n"
            f"- Tribunal: {payload.get('sigla_tribunal') or 'não informado'}\n"
            f"- Tipo: {payload.get('tipo_comunicacao') or 'não informado'}\n"
            f"- Tipo de documento: {payload.get('tipo_documento') or 'não informado'}\n"
            f"- Órgão: {payload.get('nome_orgao') or 'não informado'}\n"
            f"- Classe: {payload.get('nome_classe') or 'não informada'}\n"
            f"- Processo: {payload.get('numero_processo') or 'não informado'}\n"
            f"- Advogado(s) do escritório intimado(s): {advogados_escritorio}\n\n"
            f"CONTEXTO DO PROCESSO NO PAINEL\n{contexto_processo}\n\n"
            f"TEOR DA COMUNICAÇÃO\n{teor}"
        )

        llm = ChatOpenAI(model=self.model_name, temperature=0).with_structured_output(
            CommunicationExplanation, include_raw=True
        )

        call_started_at = time.time()
        result = llm.invoke([
            {'role': 'system', 'content': self.SYSTEM_PROMPT},
            {'role': 'user', 'content': user_prompt},
        ])
        latency_ms = int((time.time() - call_started_at) * 1000)

        raw_message = result.get('raw') if isinstance(result, dict) else None
        parsed: CommunicationExplanation | None = result.get('parsed') if isinstance(result, dict) else None

        try:
            self.token_usage_service.capture_and_store(
                {'messages': [raw_message]} if raw_message is not None else None,
                agent_name='CommunicationExplainerAgent',
                action_name='explain',
                print_prefix='[CommunicationExplainerAgent][tokens]',
                model_name=self.model_name,
                model_provider='openai',
                user_id=user_id,
                law_firm_id=law_firm_id,
                chat_session_id=None,
                latency_ms=latency_ms,
                status='success' if parsed is not None else 'error',
            )
        except Exception:
            pass  # rastreio de custo nunca derruba a explicação

        if parsed is None:
            raise ValueError('O modelo não retornou uma explicação estruturada válida')
        return parsed
