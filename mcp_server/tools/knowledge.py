"""
Tools: Base de Conhecimento (RAG)
"""
from __future__ import annotations


def _attach_file_links(items: list[dict], law_firm_id: int, app_public_url: str,
                       file_id_key: str = "file_id") -> list[dict]:
    """Adiciona 'url_abrir' (rota /knowledge-base/<id>/view do sistema) aos itens.

    Só gera link para arquivos ativos do escritório do usuário — a própria rota
    também revalida login e tenant ao abrir.
    """
    from app.models import KnowledgeBase

    file_ids = {item.get(file_id_key) for item in items if item.get(file_id_key)}
    if not file_ids:
        return items

    allowed = {
        kb.id
        for kb in KnowledgeBase.query.filter(
            KnowledgeBase.id.in_(file_ids),
            KnowledgeBase.law_firm_id == law_firm_id,
            KnowledgeBase.is_active.is_(True),
        ).with_entities(KnowledgeBase.id).all()
    }
    base = app_public_url.rstrip("/")
    for item in items:
        file_id = item.get(file_id_key)
        if file_id in allowed:
            item["url_abrir"] = f"{base}/knowledge-base/{file_id}/view"
    return items


def query_knowledge_base_handler(question: str, law_firm_id: int, user_id: int | None = None,
                                 app_public_url: str = "") -> dict:
    """Invoca KnowledgeQueryAgent.ask_with_llm e retorna resposta formatada.

    O modo de busca (semântico vs. full-text) é decidido automaticamente pelo
    agente de roteamento a partir da pergunta. O user_id alimenta o rastreio
    de tokens/custo por usuário.
    """
    from app.agents.knowledge_base.knowledge_query_agent import KnowledgeQueryAgent

    agent = KnowledgeQueryAgent()
    result = agent.ask_with_llm(
        question=question,
        user_id=user_id,
        law_firm_id=law_firm_id,
    )

    fontes_detalhe = result.get("sources_detail", []) or []
    if app_public_url:
        fontes_detalhe = _attach_file_links(fontes_detalhe, law_firm_id, app_public_url)

    return {
        "resposta": result.get("answer", ""),
        "fontes": result.get("sources", []),
        "fontes_detalhe": fontes_detalhe,
        "perguntas_sugeridas": result.get("suggested_questions", []),
    }


def kb_search_handler(
    question: str,
    law_firm_id: int,
    search_mode: str | None = None,
    limit: int = 20,
    app_public_url: str = "",
) -> dict:
    """Pesquisa Inteligente da base de conhecimento (mesmo pipeline da tela).

    Sem modo explícito, o roteador LLM decide entre busca semântica e textual;
    o enriquecimento da pergunta (semântica) e a extração de termos-chave
    (textual) acontecem dentro de ask_knowledge_base. A pontuação/corte usa as
    mesmas funções compartilhadas da tela (search_helpers). Retorna apenas
    trechos de arquivos do escritório do usuário.
    """
    from app.agents.knowledge_base.knowledge_query_agent import KnowledgeQueryAgent
    from app.models import KnowledgeBase
    from app.services.knowledge_base.search_helpers import adjust_search_score, passes_score_cutoff

    agent = KnowledgeQueryAgent()

    mode = (search_mode or "").strip().lower() or None
    if mode in {"full-text", "literal", "textual"}:
        mode = "full_text"
    if mode in {"semantic", "full_text"}:
        decidido_por = "usuario"
    else:
        decision = agent.context_retrieval_routing.decide_retrieval_and_mode(question)
        mode = decision.search_mode if decision.search_mode in ("semantic", "full_text") else "semantic"
        decidido_por = "roteador_llm"

    import re as _re
    from types import SimpleNamespace

    def _raw_full_text_points(term: str):
        raw = agent.meilisearch.index(agent.collection).search(
            term, limit=50, show_ranking_score=True,
        )
        return [
            SimpleNamespace(payload=hit, score=hit.get("_rankingScore"))
            for hit in (raw.hits or [])
        ]

    aviso = None
    # Identificadores (NB, NIT, CPF, CNPJ, nº de processo): busca textual direta,
    # determinística — sem depender da extração de termos-chave por LLM.
    if mode == "full_text" and _re.search(r"\d{6,}", question.replace(".", "").replace("-", "").replace("/", "")):
        points = _raw_full_text_points(question)
        data = {"improved_question": question}
    else:
        try:
            data = agent.ask_knowledge_base(question, limit=50, search_mode=mode)
        except Exception:
            if mode != "full_text":
                mode = "full_text"
                aviso = "Busca semântica indisponível no momento; foi usada a busca textual."
                data = agent.ask_knowledge_base(question, limit=50, search_mode=mode)
            else:
                raise
        points = data["results"].points if data.get("results") else []

    def _process(points_list, current_mode):
        # Isolamento de tenant: só trechos de arquivos do escritório do usuário
        file_ids = {p.payload.get("file_id") for p in points_list if (p.payload or {}).get("file_id")}
        allowed: dict = {}
        if file_ids:
            rows = KnowledgeBase.query.filter(
                KnowledgeBase.id.in_(file_ids),
                KnowledgeBase.law_firm_id == law_firm_id,
                KnowledgeBase.is_active.is_(True),
            ).all()
            allowed = {kb.id: kb for kb in rows}

        collected = []
        for idx, point in enumerate(points_list):
            payload = point.payload or {}
            file_id = payload.get("file_id")
            if file_id not in allowed:
                continue

            base_score = getattr(point, "score", None)
            if base_score is None:
                base_score = payload.get("_rankingScore")
            if base_score is None and current_mode == "full_text":
                base_score = max(0.35, 1.0 - (idx * 0.02))

            text = payload.get("text", "") or ""
            candidate_text = f"{text} {payload.get('source', '') or ''} {payload.get('description', '') or ''}"
            adjusted_score, literal = adjust_search_score(question, current_mode, float(base_score or 0), candidate_text)
            if not passes_score_cutoff(adjusted_score, current_mode):
                continue

            kb = allowed[file_id]
            collected.append({
                "trecho": text[:1200] + ("…" if len(text) > 1200 else ""),
                "fonte": payload.get("source") or kb.original_filename or "Documento sem nome",
                "pagina": payload.get("page"),
                "categoria": payload.get("category") or None,
                "tags": [t for t in (payload.get("tags") or "").split(",") if t],
                "numero_processo": payload.get("lawsuit_number") or None,
                "relevancia_percentual": round(adjusted_score * 100, 2),
                "match_literal": literal,
                "arquivo": {
                    "id": kb.id,
                    "nome": kb.original_filename,
                    "descricao": kb.description,
                    "tipo": kb.file_type,
                },
                **({"url_abrir": f"{app_public_url.rstrip('/')}/knowledge-base/{kb.id}/view"}
                   if app_public_url else {}),
            })

        collected.sort(key=lambda r: r["relevancia_percentual"], reverse=True)
        return collected[:limit]

    resultados = _process(points, mode)

    # Rede de segurança: se nada passou (ex.: a extração de termos-chave do LLM
    # descartou um número exato, ou o score da query reescrita ficou baixo),
    # refaz a busca textual DIRETA com o termo original, sem LLM.
    if not resultados:
        retried = _process(_raw_full_text_points(question), "full_text")
        if retried:
            mode = "full_text"
            resultados = retried
            aviso = "Resultados obtidos por busca textual direta com o termo original."

    out = {
        "modo_busca": mode,
        "modo_decidido_por": decidido_por,
        "pergunta_melhorada": data.get("improved_question"),
        "total_resultados": len(resultados),
        "resultados": resultados,
    }
    if aviso:
        out["aviso"] = aviso
    return out
