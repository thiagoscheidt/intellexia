from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agents.config import DEFAULT_MODEL_ROBUST
from app.agents.core.file_agent import FileAgent
from app.services.agent_execution_history_service import AgentExecutionHistoryService
from app.services.token_usage_service import TokenUsageService


load_dotenv()


class ContestationTechnicalResult(BaseModel):
    recalcula_fap: bool = Field(default=False)
    mantem_no_fap: bool = Field(default=False)
    depende_inss: bool = Field(default=False)
    depende_decisao_judicial: bool = Field(default=False)


class ContestationBenefitAnalysisItem(BaseModel):
    beneficio: str = Field(default='', description='Numero do beneficio (NB).')
    tese: str = Field(default='', description='Tese juridica ja associada ao beneficio.')
    status: str = Field(default='nao_analisado', description='Status tecnico-processual padronizado.')
    status_label: str = Field(default='', description='Rotulo humano do status.')
    fundamento_uniao: str = Field(default='', description='Fundamentacao literal da Uniao para o beneficio.')
    efeito_fap: str = Field(default='', description='Efeito pratico sobre o FAP.')
    trecho_detectado: str = Field(default='', description='Trecho objetivo identificado na contestacao.')
    trecho_completo_contestacao: str = Field(default='', description='Trecho completo de contexto da contestacao.')
    resultado_tecnico: ContestationTechnicalResult = Field(default_factory=ContestationTechnicalResult)


class JudicialContestationAnalysisSchema(BaseModel):
    analises: list[ContestationBenefitAnalysisItem] = Field(
        default_factory=list,
        description='Analise individual da resposta da Uniao para cada beneficio informado.',
    )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)


_SYSTEM_PROMPT = (
    'Voce e um analista juridico especializado em contestacao da Uniao em acoes revisionais de FAP. '
    'Analise integralmente a contestacao e responda de forma individual por beneficio informado. '
    'Nao resuma genericamente o documento. '
    'Nunca invente fundamento. '
    'Sempre priorize texto literal da contestacao e retorne trecho identificado. '
    'Se nao localizar o beneficio, retorne status nao_localizado. '
    'Se nao houver base suficiente para concluir, retorne nao_analisado. '
    'Saida obrigatoriamente estruturada e previsivel em JSON.'
)


class JudicialContestationAnalysisAgent:
    """Analisa contestacao da Uniao por beneficio em processos revisionais de FAP."""

    def __init__(self, model_name: str | None = None):
        self.model_name = (
            model_name
            or os.getenv('JUDICIAL_CONTESTATION_ANALYSIS_MODEL')
            or DEFAULT_MODEL_ROBUST
        )
        self.model_provider = os.getenv('JUDICIAL_CONTESTATION_ANALYSIS_MODEL_PROVIDER', 'openai')
        self.chat_model = ChatOpenAI(model=self.model_name, temperature=0.0)
        self.token_usage_service = TokenUsageService()

    _ALLOWED_STATUS = {
        'deferido',
        'deferido_parcial',
        'indeferido',
        'ilegitimidade_passiva',
        'depende_decisao_judicial',
        'recalculo_realizado',
        'nao_localizado',
        'nao_analisado',
    }

    @staticmethod
    def _normalize_benefits_input(benefits: list[dict[str, Any]] | None) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for item in benefits or []:
            if not isinstance(item, dict):
                continue

            benefit_number = str(item.get('benefit_number', '') or '').strip()
            if not benefit_number:
                continue

            thesis = str(item.get('thesis', '') or '').strip()
            normalized.append(
                {
                    'benefit_number': benefit_number,
                    'thesis': thesis,
                }
            )

        return normalized

    @staticmethod
    def _build_messages_for_history(user_prompt: str, file_part: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {'role': 'system', 'content': _SYSTEM_PROMPT},
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': user_prompt},
                    file_part,
                ],
            },
        ]

    def _build_user_prompt(self, benefits: list[dict[str, str]]) -> str:
        statuses = (
            'deferido, deferido_parcial, indeferido, ilegitimidade_passiva, '
            'depende_decisao_judicial, recalculo_realizado, nao_localizado, nao_analisado'
        )

        lines = [
            'Analise a contestacao da Uniao com foco em cada beneficio informado.',
            'A tese ja esta informada e NAO deve ser reclassificada.',
            'Para cada beneficio, retornar: o que a Uniao respondeu, entendimento adotado, ',
            'aceitacao ou rejeicao da tese, efeito pratico no FAP e status tecnico/processual.',
            '',
            'REGRAS OBRIGATORIAS:',
            '- Nunca inventar fundamentacao.',
            '- Nunca inferir sem trecho correspondente.',
            '- Sempre priorizar texto literal da contestacao.',
            '- Sempre retornar trecho_detectado e trecho_completo_contestacao quando houver localizacao.',
            '- Se beneficio nao for localizado, usar status nao_localizado com trechos vazios.',
            '- Se houver mais de uma resposta para o mesmo beneficio, consolidar as respostas.',
            '- Resultado deve ser individual por beneficio, sem resumo generico do documento.',
            '',
            'MAPEAMENTO DE STATUS DISPONIVEIS:',
            f'- {statuses}',
            '',
            'PADROES COMUNS A IDENTIFICAR (quando houver evidencia textual):',
            '- improcedencia por ausencia de duplicidade',
            '- competencia exclusiva do INSS',
            '- necessidade de decisao judicial',
            '- exclusao aceita para recalculo',
            '- manutencao do beneficio no calculo',
            '- beneficio convertido para previdenciario',
            '- acidente de trajeto reconhecido',
            '- beneficio concedido judicialmente',
            '- ausencia de alteracao no SIBE',
            '- inexistencia de CAT de trajeto',
            '- recalculo ja realizado',
            '',
            'BENEFICIOS PARA ANALISAR:',
        ]

        for item in benefits:
            lines.append(
                f"- NB: {item.get('benefit_number', '')} | Tese: {item.get('thesis', '') or '(nao informada)'}"
            )

        lines.extend(
            [
                '',
                'Cada item de resposta deve usar o numero exato do beneficio informado em beneficio.',
                'Em resultado_tecnico, preencher booleans coerentes com a resposta da Uniao.',
            ]
        )

        return '\n'.join(lines)

    def _persist_execution_history(
        self,
        *,
        agent_token_usage_id: int | None,
        user_prompt: str,
        result_payload: dict[str, Any] | None,
        status: str,
        error_message: str | None,
        user_id: int | None,
        law_firm_id: int | None,
        history_messages: list[dict[str, Any]],
    ) -> None:
        model_response = ''
        if isinstance(result_payload, dict):
            analyses = result_payload.get('analises')
            if isinstance(analyses, list):
                model_response = f'analises={len(analyses)}'

        AgentExecutionHistoryService.save_execution_history(
            agent_name='JudicialContestationAnalysisAgent',
            action_name='analyze_contestation',
            agent_type='judicial_contestation_analysis',
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model_response=model_response,
            full_messages_history=history_messages,
            result_data=result_payload or {},
            model_name=self.model_name,
            model_provider=self.model_provider,
            status=status,
            error_message=error_message,
            user_id=user_id,
            law_firm_id=law_firm_id,
            agent_token_usage_id=agent_token_usage_id,
        )

    @staticmethod
    def _normalize_result_per_benefit(
        requested_benefits: list[dict[str, str]],
        result_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        analyses_raw = []
        if isinstance(result_payload, dict):
            maybe = result_payload.get('analises')
            if isinstance(maybe, list):
                analyses_raw = maybe

        by_number: dict[str, dict[str, Any]] = {}
        for item in analyses_raw:
            if not isinstance(item, dict):
                continue
            number = str(item.get('beneficio', '') or '').strip()
            if not number:
                continue
            by_number[number] = item

        normalized_items: list[dict[str, Any]] = []
        for requested in requested_benefits:
            number = requested.get('benefit_number', '')
            thesis = requested.get('thesis', '')
            base_item = by_number.get(number, {})
            status = str(base_item.get('status', '') or 'nao_localizado').strip()
            if status not in JudicialContestationAnalysisAgent._ALLOWED_STATUS:
                status = 'nao_analisado'

            normalized_items.append(
                {
                    'beneficio': number,
                    'tese': str(base_item.get('tese', '') or thesis).strip(),
                    'status': status,
                    'status_label': str(base_item.get('status_label', '') or '').strip(),
                    'fundamento_uniao': str(base_item.get('fundamento_uniao', '') or '').strip(),
                    'efeito_fap': str(base_item.get('efeito_fap', '') or '').strip(),
                    'trecho_detectado': str(base_item.get('trecho_detectado', '') or '').strip(),
                    'trecho_completo_contestacao': str(
                        base_item.get('trecho_completo_contestacao', '') or ''
                    ).strip(),
                    'resultado_tecnico': {
                        'recalcula_fap': bool((base_item.get('resultado_tecnico') or {}).get('recalcula_fap', False)),
                        'mantem_no_fap': bool((base_item.get('resultado_tecnico') or {}).get('mantem_no_fap', False)),
                        'depende_inss': bool((base_item.get('resultado_tecnico') or {}).get('depende_inss', False)),
                        'depende_decisao_judicial': bool(
                            (base_item.get('resultado_tecnico') or {}).get('depende_decisao_judicial', False)
                        ),
                    },
                }
            )

        return {'analises': normalized_items}

    def analyze_contestation(
        self,
        *,
        file_path: str,
        benefits: list[dict[str, Any]],
        user_id: Optional[int] = None,
        law_firm_id: Optional[int] = None,
    ) -> dict[str, Any]:
        if not file_path:
            raise ValueError('file_path e obrigatorio para analise da contestacao')

        normalized_path = str(file_path).strip()
        if not normalized_path:
            raise ValueError('file_path invalido')

        requested_benefits = self._normalize_benefits_input(benefits)
        if not requested_benefits:
            return {'analises': []}

        if normalized_path.startswith('http://') or normalized_path.startswith('https://'):
            file_part = FileAgent().build_openrouter_file_part(normalized_path)
        else:
            path_obj = Path(normalized_path)
            if not path_obj.exists():
                raise FileNotFoundError(f'Arquivo nao encontrado: {normalized_path}')
            file_part = FileAgent().build_openrouter_file_part(str(path_obj))

        user_prompt = self._build_user_prompt(requested_benefits)
        history_messages = self._build_messages_for_history(user_prompt, file_part)

        agent = create_agent(
            model=self.chat_model,
            tools=[],
            system_prompt=_SYSTEM_PROMPT,
            response_format=ToolStrategy(JudicialContestationAnalysisSchema),
        )

        call_started_at = time.time()
        response_payload = None
        metadata_payload = {
            'file_name': Path(normalized_path).name if normalized_path else '',
            'benefits_count': len(requested_benefits),
            'benefits': requested_benefits,
        }

        try:
            response_payload = agent.invoke({'messages': history_messages})
            latency_ms = int((time.time() - call_started_at) * 1000)

            _, token_rows = self.token_usage_service.capture_and_store(
                response_payload,
                agent_name='JudicialContestationAnalysisAgent',
                action_name='analyze_contestation.create_agent',
                print_prefix='[JudicialContestationAnalysisAgent][tokens]',
                model_name=self.model_name,
                model_provider=self.model_provider,
                user_id=user_id,
                law_firm_id=law_firm_id,
                latency_ms=latency_ms,
                status='success',
                metadata_payload=metadata_payload,
                return_rows=True,
            )

            structured_response = response_payload.get('structured_response')
            if not structured_response:
                raise RuntimeError('Resposta estruturada nao retornada pelo agente de contestacao')

            result_payload = structured_response.to_dict()
            normalized_result = self._normalize_result_per_benefit(requested_benefits, result_payload)
            token_usage_id = token_rows[0].id if token_rows else None

            self._persist_execution_history(
                agent_token_usage_id=token_usage_id,
                user_prompt=user_prompt,
                result_payload=normalized_result,
                status='success',
                error_message=None,
                user_id=user_id,
                law_firm_id=law_firm_id,
                history_messages=history_messages,
            )
            return normalized_result
        except Exception as exc:
            latency_ms = int((time.time() - call_started_at) * 1000)
            _, _ = self.token_usage_service.capture_and_store(
                response_payload,
                agent_name='JudicialContestationAnalysisAgent',
                action_name='analyze_contestation.create_agent',
                print_prefix='[JudicialContestationAnalysisAgent][tokens]',
                model_name=self.model_name,
                model_provider=self.model_provider,
                user_id=user_id,
                law_firm_id=law_firm_id,
                latency_ms=latency_ms,
                status='error',
                error_message=str(exc),
                metadata_payload=metadata_payload,
                return_rows=True,
            )

            fallback = self.chat_model.with_structured_output(JudicialContestationAnalysisSchema)
            fallback_payload = fallback.invoke(
                [
                    {'role': 'system', 'content': _SYSTEM_PROMPT},
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': user_prompt},
                            file_part,
                        ],
                    },
                ]
            )

            _, fallback_rows = self.token_usage_service.capture_and_store(
                {'messages': [fallback_payload]},
                agent_name='JudicialContestationAnalysisAgent',
                action_name='analyze_contestation.fallback',
                print_prefix='[JudicialContestationAnalysisAgent][tokens]',
                model_name=self.model_name,
                model_provider=self.model_provider,
                user_id=user_id,
                law_firm_id=law_firm_id,
                latency_ms=latency_ms,
                status='success',
                metadata_payload=metadata_payload,
                return_rows=True,
            )

            fallback_result = None
            if hasattr(fallback_payload, 'to_dict'):
                fallback_result = fallback_payload.to_dict()
            if hasattr(fallback_payload, 'model_dump'):
                fallback_result = fallback_payload.model_dump(by_alias=True)

            if fallback_result is None:
                raise RuntimeError('Fallback nao retornou resposta estruturada valida para contestacao')

            normalized_fallback = self._normalize_result_per_benefit(requested_benefits, fallback_result)
            fallback_token_usage_id = fallback_rows[0].id if fallback_rows else None
            self._persist_execution_history(
                agent_token_usage_id=fallback_token_usage_id,
                user_prompt=user_prompt,
                result_payload=normalized_fallback,
                status='success',
                error_message=None,
                user_id=user_id,
                law_firm_id=law_firm_id,
                history_messages=history_messages,
            )
            return normalized_fallback
