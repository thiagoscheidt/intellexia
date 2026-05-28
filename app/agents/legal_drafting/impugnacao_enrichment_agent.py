"""Agente de enriquecimento jurisprudencial de impugnações geradas.

Recebe o texto do documento já gerado pelo AgentGeneratedDocument e:
1. Substitui referências genéricas à jurisprudência por citações reais do banco
2. Insere blocos de citação onde o argumento se beneficiaria de precedente
3. Nunca inventa jurisprudência — usa apenas o que está no banco Qdrant

Atua sobre o documento completo (mérito, preliminares, introdução, pedidos).
"""

from __future__ import annotations

import os
import time
from typing import Optional

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from app.agents.config import DEFAULT_MODEL_ROBUST
from app.agents.legal_drafting.impugnacao_reference_retriever import ImpugnacaoReferenceRetriever
from app.services.token_usage_service import TokenUsageService


class DocumentoEnriquecido(BaseModel):
    texto_enriquecido: str = Field(
        description=(
            "Documento COMPLETO após enriquecimento. "
            "Preservar toda a estrutura, numeração e formatação original. "
            "Retornar o documento inteiro — não resumir nem cortar."
        )
    )
    citacoes_inseridas: int = Field(
        default=0,
        description="Número de citações reais inseridas ou substituídas no documento.",
    )


_SYSTEM_PROMPT = """Você é um especialista em enriquecimento de peças jurídicas com jurisprudência.

Recebe:
1. Um documento de impugnação à contestação já redigido
2. Um banco de jurisprudências reais extraídas das peças-modelo do escritório

Sua tarefa:
- Identificar trechos que fazem referência genérica à jurisprudência (ex: "conforme entendimento do TRF", "a jurisprudência reconhece", "precedentes favoráveis") sem citar processo específico
- Substituir essas referências genéricas por citações reais do banco, quando houver jurisprudência adequada ao tema do trecho
- Onde o argumento for forte mas não tiver citação, inserir bloco de jurisprudência relevante do banco imediatamente após o parágrafo
- Preservar INTEGRALMENTE a estrutura, numeração (1., 2., 3.1, etc.), formatação e todos os argumentos originais
- Retornar o documento COMPLETO — nunca resumir, nunca cortar seções

Formato de citação a usar (quando inserir bloco novo):
  [Tribunal, tipo nº processo, Turma, Rel. Nome do Relator, julgado em data]:
  "trecho relevante da ementa ou ratio decidendi"

PROIBIDO:
- Inventar jurisprudência que não consta no banco fornecido
- Remover ou alterar argumentos existentes
- Alterar a estrutura ou numeração do documento
- Resumir ou omitir qualquer seção
""".strip()


class ImpugnacaoEnrichmentAgent:
    """Enriquece o texto de impugnação gerado com jurisprudências reais do banco Qdrant."""

    MAX_JURIS_CONTEXT_CHARS = 30_000
    MAX_JURIS_PER_THESIS = 15

    def __init__(self, model_name: Optional[str] = None, temperature: float = 0.1):
        self.model_name = model_name or os.getenv(
            "IMPUGNACAO_ENRICHMENT_MODEL",
            DEFAULT_MODEL_ROBUST,
        )
        self.temperature = temperature
        self.retriever = ImpugnacaoReferenceRetriever()

    # ── Recuperação ────────────────────────────────────────────────────

    def _build_jurisprudence_context(
        self,
        selections: list[dict],
        law_firm_id: int,
        trf_region: Optional[str],
    ) -> str:
        all_juris: list[dict] = []
        seen_texts: set[str] = set()

        def _add_chunks(chunks: list[dict]) -> None:
            for chunk in chunks:
                text = (chunk.get("text") or "").strip()
                key = text[:120].lower()
                if not text or key in seen_texts:
                    continue
                seen_texts.add(key)
                all_juris.append(chunk)

        # Por tese
        seen_thesis_keys: set[str] = set()
        for sel in selections or []:
            thesis = sel.get("thesis")
            thesis_key = getattr(thesis, "key", None) if thesis else None
            thesis_name = (
                getattr(thesis, "title", None) or getattr(thesis, "name", None)
                if thesis else None
            )
            if thesis_key and thesis_key in seen_thesis_keys:
                continue
            if thesis_key:
                seen_thesis_keys.add(thesis_key)

            query = f"jurisprudência sobre {thesis_name or 'FAP impugnação contestação'}"
            chunks = self.retriever.fetch_style_references(
                law_firm_id=law_firm_id,
                query_text=query,
                trf_region=trf_region,
                thesis_catalog_id=thesis_key,
                kind_plan=[("jurisprudence", self.MAX_JURIS_PER_THESIS)],
                max_chunks=self.MAX_JURIS_PER_THESIS,
            )
            _add_chunks(chunks)

        # Busca geral (sem filtro de tese) para cobrir preliminares e pedidos
        general_chunks = self.retriever.fetch_style_references(
            law_firm_id=law_firm_id,
            query_text="jurisprudência FAP impugnação contestação preliminar prescrição",
            trf_region=trf_region,
            kind_plan=[("jurisprudence", 20)],
            max_chunks=20,
        )
        _add_chunks(general_chunks)

        if not all_juris:
            return ""

        lines = ["=== BANCO DE JURISPRUDÊNCIAS DISPONÍVEIS ==="]
        total_chars = 0

        for i, chunk in enumerate(all_juris):
            meta_parts = []
            if chunk.get("tribunal"):
                meta_parts.append(f"Tribunal: {chunk['tribunal']}")
            if chunk.get("case_number") or chunk.get("processo"):
                meta_parts.append(f"Processo: {chunk.get('case_number') or chunk.get('processo')}")
            if chunk.get("relator"):
                meta_parts.append(f"Rel.: {chunk['relator']}")
            if chunk.get("orgao_julgador"):
                meta_parts.append(f"Órgão: {chunk['orgao_julgador']}")
            if chunk.get("data_julgamento"):
                meta_parts.append(f"Julgado: {chunk['data_julgamento']}")
            if chunk.get("secao_origem") and chunk["secao_origem"] != "general":
                meta_parts.append(f"Seção: {chunk['secao_origem']}")
            if chunk.get("fundamento_principal"):
                meta_parts.append(f"Fundamento: {chunk['fundamento_principal']}")

            meta_str = " | ".join(meta_parts) if meta_parts else "sem metadados"
            text = chunk.get("text", "")[:1500]

            entry = f"\n[JURIS {i + 1} | {meta_str}]\n{text}"
            if total_chars + len(entry) > self.MAX_JURIS_CONTEXT_CHARS:
                break
            lines.append(entry)
            total_chars += len(entry)

        return "\n".join(lines)

    # ── Enriquecimento ─────────────────────────────────────────────────

    def enrich(
        self,
        *,
        document_text: str,
        selections: list[dict],
        law_firm_id: int,
        trf_region: Optional[str] = None,
    ) -> str:
        """Enriquece o documento com jurisprudências reais do banco.

        Retorna o texto enriquecido ou o texto original em caso de falha.
        """
        if not document_text or not law_firm_id:
            return document_text

        try:
            juris_context = self._build_jurisprudence_context(selections, law_firm_id, trf_region)
        except Exception as error:
            print(f"[EnrichmentAgent] Falha ao recuperar jurisprudências: {error}")
            return document_text

        if not juris_context:
            print("[EnrichmentAgent] Banco de jurisprudências vazio — nenhum enriquecimento.")
            return document_text

        user_prompt = (
            f"{juris_context}\n\n"
            "=== DOCUMENTO A ENRIQUECER ===\n"
            f"{document_text}\n\n"
            "Enriqueça o documento acima com as jurisprudências do banco. "
            "Retorne o documento COMPLETO com as citações inseridas."
        )

        llm = ChatOpenAI(
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=16_000,
        ).with_structured_output(DocumentoEnriquecido, include_raw=True)

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        started_at = time.perf_counter()
        raw_message = None

        try:
            output = llm.invoke(messages)
            raw_message = output.get("raw")
            result: DocumentoEnriquecido = output.get("parsed")

            if result is None:
                print("[EnrichmentAgent] Parsing falhou — mantendo original.")
                return document_text

            enriched = (result.texto_enriquecido or "").strip()
            if not enriched:
                print("[EnrichmentAgent] Resposta vazia — mantendo original.")
                return document_text

            print(
                f"[EnrichmentAgent] Enriquecimento concluído: "
                f"{result.citacoes_inseridas} citação(ões) inserida(s)."
            )
            return enriched
        except Exception as error:
            print(f"[EnrichmentAgent] Falha no enriquecimento: {error} — mantendo original.")
            return document_text
        finally:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            try:
                TokenUsageService().capture_and_store(
                    response_payload={"messages": [raw_message]} if raw_message is not None else None,
                    agent_name="ImpugnacaoEnrichmentAgent",
                    action_name="enrich_impugnacao",
                    print_prefix="[EnrichmentAgent][TokenUsage]",
                    model_name=self.model_name,
                    model_provider="openai",
                    law_firm_id=law_firm_id,
                    latency_ms=elapsed_ms,
                    status="success" if raw_message is not None else "error",
                )
            except Exception as tu_error:
                print(f"[EnrichmentAgent] Falha ao registrar token usage: {tu_error}")
