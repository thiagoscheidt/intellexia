from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional, List

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI

from app.agents.config import DEFAULT_MODEL
from app.agents.core.file_agent import FileAgent
from app.services.agent_execution_history_service import AgentExecutionHistoryService
from app.services.token_usage_service import TokenUsageService


load_dotenv()


class UnionArgumentsByThesis(BaseModel):
    """Argumentos da União para uma tese/tema (documentos de contestação).

    Modelo fechado (extra='forbid'): o modo estrito de saída estruturada exige
    additionalProperties=false em todos os objetos do schema — um dict aberto
    é rejeitado pelo provedor (invalid_json_schema).
    """
    model_config = ConfigDict(extra='forbid')

    thesis: str = Field(description='Nome da tese/tema')
    status: str = Field(
        description="'procedente', 'improcedente', 'parcial' ou 'nao identificado'")
    arguments: List[str] = Field(
        default_factory=list, description='Fundamentos objetivos da União')


class JudicialDocumentSummarySchema(BaseModel):
    summary: str = Field(description="Resumo geral do documento")
    summary_short: str = Field(default="", description="Resumo executivo: 2-4 frases objetivas com panorama, risco principal e próximo passo")
    summary_long: str = Field(default="", description="Resumo completo: 4-7 parágrafos detalhados, com contexto fático, fundamentos, pedidos, provas e impactos processuais")
    key_points: List[str] = Field(default_factory=list, description="Pontos-chave do documento")
    requests: List[str] = Field(default_factory=list, description="Pedidos identificados no documento")
    union_arguments_by_thesis: List['UnionArgumentsByThesis'] = Field(
        default_factory=list,
        description='Argumentos da União por tese para documentos de contestação.',
    )
    document_type: str = Field(default="", description="Tipo do documento judicial")
    file_type: str = Field(default="", description="Tipo de arquivo (PDF, DOCX, etc.)")
    notes: str = Field(default="", description="Observacoes adicionais")

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)


_SYSTEM_PROMPT = (
    "Voce e um assistente juridico especializado em resumir documentos processuais trabalhistas e previdenciarios. "
    "Gere um resumo tecnico, objetivo e estruturado, com foco nos pontos que advogados analisam para decidir estrategia."
)


class JudicialDocumentSummaryAgent:
    """Agente para gerar resumo de documentos judiciais durante o processamento."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("JUDICIAL_DOCUMENT_SUMMARY_MODEL") or DEFAULT_MODEL
        self.model_provider = os.getenv("JUDICIAL_DOCUMENT_SUMMARY_MODEL_PROVIDER", "openai")
        self.chat_model = ChatOpenAI(model=self.model_name, temperature=0.2)
        self.token_usage_service = TokenUsageService()

    def _build_user_prompt(
        self,
        document_type_name: str,
        document_type_key: str,
        file_type: str,
        sections_overview: List[str] | None,
        pedidos_excerpt: str | None,
        document_event_identifier: str | None,
    ) -> str:
        safe_doc_type = (document_type_name or document_type_key or "documento judicial").strip()
        safe_file_type = (file_type or "").strip()
        safe_sections = sections_overview or []
        safe_pedidos_excerpt = (pedidos_excerpt or "").strip()
        safe_event_identifier = (document_event_identifier or "").strip()

        sections_block = "\n".join(f"- {section}" for section in safe_sections) if safe_sections else "(nao identificado)"
        pedidos_block = safe_pedidos_excerpt if safe_pedidos_excerpt else "(nao identificado)"

        return (
            "Resuma o documento judicial abaixo com foco pratico para advogado. Preserve informacoes juridicas relevantes "
            "e explique o contexto com base no tipo de documento informado. "
            "Regras de tamanho: summary_short com 2-4 frases objetivas; summary_long com 4-7 paragrafos detalhados. "
            "summary_short e summary_long DEVEM ser diferentes entre si. "
            "Liste pontos-chave em key_points e extraia os pedidos em requests. Se nao houver dado para algum campo, use lista vazia ou string vazia.\n\n"
            f"TIPO DE DOCUMENTO: {safe_doc_type}\n"
            f"CHAVE DO TIPO: {document_type_key or ''}\n"
            f"TIPO DE ARQUIVO: {safe_file_type}\n\n"
            f"ID DO EVENTO PROCESSUAL (se identificado): {safe_event_identifier or '(nao identificado)'}\n\n"
            f"SECOES IDENTIFICADAS NO DOCUMENTO:\n{sections_block}\n\n"
            f"TRECHO DOS PEDIDOS (SE HOUVER):\n{pedidos_block}\n\n"
            "DIFERENCIACAO OBRIGATORIA:\n"
            "- summary_short: apenas visao executiva para tomada de decisao rapida (sem repetir texto longo).\n"
            "- summary_long: analise completa e aprofundada, com detalhes factuais e juridicos.\n"
            "ORIENTACAO: deixe claro o papel do documento (ex.: peticao inicial, contestacao, sentenca, despacho).\n"
            "EXTRAIA o que for aplicavel entre: pedidos e valores; partes e qualificacao; fatos relevantes; fundamentos "
            "juridicos; provas/documentos citados; datas-chave; decisao/dispositivo e efeitos; pontos controversos; "
            "riscos/fragilidades; oportunidades processuais; prazos e proximos passos.\n"
            "Se houver dados quantificaveis (valores, prazos, indices), inclua no resumo.\n"
            "Se o trecho de pedidos existir, priorize-o para detalhar o que foi requerido ao juizo.\n"
            "Se o ID DO EVENTO PROCESSUAL estiver identificado, cite esse id explicitamente no summary_short e no summary_long.\n"
            "Em requests, retorne cada pedido de forma clara e separada, mantendo a redação juridica quando ela for importante.\n"
            "Se for documento de contestacao, preencha union_arguments_by_thesis com os argumentos da Uniao por tese/tema.\n"
            "Formato de union_arguments_by_thesis: lista de objetos com thesis (nome da tese/tema), status (procedente, improcedente, parcial ou nao identificado) e arguments (lista de fundamentos objetivos da Uniao).\n"
            "Evite argumentos genericos: cada item deve refletir o conteudo efetivamente identificado na contestacao.\n"
        )

    @staticmethod
    def _build_messages_for_history(
        user_prompt: str,
        file_part: dict,
    ) -> list[dict]:
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    file_part,
                ],
            },
        ]

    def _persist_execution_history(
        self,
        *,
        agent_token_usage_id: int | None,
        user_prompt: str,
        response_payload: dict | None,
        result_payload: dict | None,
        status: str,
        error_message: str | None,
        user_id: int | None,
        law_firm_id: int | None,
        history_messages: list[dict],
    ) -> None:
        model_response = ""
        if isinstance(result_payload, dict):
            model_response = result_payload.get("summary_long") or result_payload.get("summary") or ""

        AgentExecutionHistoryService.save_execution_history(
            agent_name="JudicialDocumentSummaryAgent",
            action_name="summarize_document",
            agent_type="judicial_document_summary",
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

    def summarize_document(
        self,
        file_path: str,
        document_type_name: str = "",
        document_type_key: str = "",
        file_type: str = "",
        sections_overview: List[str] | None = None,
        pedidos_excerpt: str | None = None,
        document_event_identifier: str = "",
        user_id: Optional[int] = None,
        law_firm_id: Optional[int] = None,
    ) -> dict:
        if not file_path:
            raise ValueError("file_path e obrigatorio para gerar resumo")

        normalized_path = str(file_path).strip()
        if not normalized_path:
            raise ValueError("file_path invalido")

        if normalized_path.startswith("http://") or normalized_path.startswith("https://"):
            file_part = FileAgent().build_openrouter_file_part(normalized_path)
        else:
            path_obj = Path(normalized_path)
            if not path_obj.exists():
                raise FileNotFoundError(f"Arquivo nao encontrado: {normalized_path}")
            file_part = FileAgent().build_openrouter_file_part(str(path_obj))

        user_prompt = self._build_user_prompt(
            document_type_name,
            document_type_key,
            file_type,
            sections_overview,
            pedidos_excerpt,
            document_event_identifier,
        )

        agent = create_agent(
            model=self.chat_model,
            tools=[],
            system_prompt=_SYSTEM_PROMPT,
            response_format=ToolStrategy(JudicialDocumentSummarySchema),
        )

        call_started_at = time.time()
        response_payload = None
        metadata_payload = {
            "document_type": document_type_name or document_type_key,
            "file_type": file_type,
            "file_name": Path(normalized_path).name if normalized_path else "",
            "document_event_identifier": document_event_identifier,
        }
        history_messages = self._build_messages_for_history(user_prompt, file_part)

        try:
            response_payload = agent.invoke(
                {"messages": history_messages}
            )
            latency_ms = int((time.time() - call_started_at) * 1000)

            _, token_rows = self.token_usage_service.capture_and_store(
                response_payload,
                agent_name="JudicialDocumentSummaryAgent",
                action_name="summarize_document.create_agent",
                print_prefix="[JudicialDocumentSummaryAgent][tokens]",
                model_name=self.model_name,
                model_provider=self.model_provider,
                user_id=user_id,
                law_firm_id=law_firm_id,
                latency_ms=latency_ms,
                status="success",
                metadata_payload=metadata_payload,
                return_rows=True,
            )

            structured_response = response_payload.get("structured_response")
            if not structured_response:
                raise RuntimeError("Resposta estruturada nao retornada pelo agente")

            result_payload = structured_response.to_dict()
            token_usage_id = token_rows[0].id if token_rows else None
            self._persist_execution_history(
                agent_token_usage_id=token_usage_id,
                user_prompt=user_prompt,
                response_payload=response_payload,
                result_payload=result_payload,
                status="success",
                error_message=None,
                user_id=user_id,
                law_firm_id=law_firm_id,
                history_messages=history_messages,
            )
            return result_payload
        except Exception as exc:
            latency_ms = int((time.time() - call_started_at) * 1000)
            _, token_rows = self.token_usage_service.capture_and_store(
                response_payload,
                agent_name="JudicialDocumentSummaryAgent",
                action_name="summarize_document.create_agent",
                print_prefix="[JudicialDocumentSummaryAgent][tokens]",
                model_name=self.model_name,
                model_provider=self.model_provider,
                user_id=user_id,
                law_firm_id=law_firm_id,
                latency_ms=latency_ms,
                status="error",
                error_message=str(exc),
                metadata_payload=metadata_payload,
                return_rows=True,
            )

            fallback = self.chat_model.with_structured_output(JudicialDocumentSummarySchema)
            fallback_payload = fallback.invoke(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            file_part,
                        ],
                    },
                ]
            )

            _, fallback_rows = self.token_usage_service.capture_and_store(
                {
                    "messages": [fallback_payload],
                },
                agent_name="JudicialDocumentSummaryAgent",
                action_name="summarize_document.fallback",
                print_prefix="[JudicialDocumentSummaryAgent][tokens]",
                model_name=self.model_name,
                model_provider=self.model_provider,
                user_id=user_id,
                law_firm_id=law_firm_id,
                latency_ms=latency_ms,
                status="success",
                metadata_payload=metadata_payload,
                return_rows=True,
            )

            fallback_result = None
            if hasattr(fallback_payload, "to_dict"):
                fallback_result = fallback_payload.to_dict()
            if hasattr(fallback_payload, "model_dump"):
                fallback_result = fallback_payload.model_dump(by_alias=True)

            if fallback_result is None:
                raise RuntimeError("Fallback nao retornou resposta estruturada valida")

            fallback_token_usage_id = fallback_rows[0].id if fallback_rows else None
            self._persist_execution_history(
                agent_token_usage_id=fallback_token_usage_id,
                user_prompt=user_prompt,
                response_payload={"messages": [fallback_payload] if fallback_payload else []},
                result_payload=fallback_result,
                status="success",
                error_message=None,
                user_id=user_id,
                law_firm_id=law_firm_id,
                history_messages=history_messages,
            )
            return fallback_result
