"""
Tools: Revisor de Petições FAP — leitura do módulo.

Deixam o Claude **ler** as revisões que já existem no sistema (feitas pela tela ou
por ele mesmo), em vez de só criar novas. É o que permite "o que a revisão da
petição X apontou? me ajuda a corrigir" sem gastar outra rodada de IA.

Os rótulos e a leitura do resultado vêm de ``app/services/fap_review_service.py`` —
a mesma fonte da tela.
"""
from __future__ import annotations

import re
import unicodedata

from mcp_server.tools.pagination import (
    clamp_limit,
    clamp_offset,
    fetch_page,
    page_envelope,
)


def _iso(value):
    return value.isoformat() if value else None


def _status_label(status: str) -> str:
    from app.services.fap_review_service import PETITION_WORKFLOW_STATUSES
    return PETITION_WORKFLOW_STATUSES.get(status, status or '')


def _finding_dict(f: dict) -> dict:
    """Achado no vocabulário das tools (o result_json usa chaves em inglês)."""
    return {
        "categoria": f.get("category"),
        "gravidade": f.get("severity"),
        "descricao": f.get("description"),
        "localizacao": f.get("location"),
        "correcao_sugerida": f.get("correction"),
        "referencia_manual": f.get("manual_reference"),
        "padrao_novo": f.get("is_new_pattern", False),
    }


def _origem(execution) -> str:
    from app.services.fap_review_service import describe_review_origin
    return describe_review_origin(execution)


def _severity_counts(findings: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for f in findings:
        key = (f.get("severity") or "SEM GRAVIDADE").upper()
        counts[key] = counts.get(key, 0) + 1
    return counts


def list_review_petitions_handler(
    law_firm_id: int,
    status: str | None = None,
    identificador: str | None = None,
    titulo: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Petições do Revisor com status do fluxo, nº de revisões e última revisão."""
    from app.models import FapReviewPetition

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)

    query = FapReviewPetition.query.filter_by(law_firm_id=law_firm_id)
    if status:
        query = query.filter(FapReviewPetition.workflow_status == status)
    if identificador:
        query = query.filter(
            FapReviewPetition.office_document_identifier.ilike(f"%{identificador}%")
        )
    if titulo:
        for token in titulo.split():
            query = query.filter(FapReviewPetition.title.ilike(f"%{token}%"))

    total = query.count()
    rows = fetch_page(
        query.order_by(FapReviewPetition.updated_at.desc(), FapReviewPetition.id.desc()),
        limit, offset,
    )

    itens = [
        {
            "peticao_id": p.id,
            "identificador": p.office_document_identifier,
            "titulo": p.title,
            "status": p.workflow_status,
            "status_descricao": _status_label(p.workflow_status),
            "revisoes": p.revision_count or 0,
            "ultima_revisao_em": _iso(p.last_reviewed_at),
            "ultima_revisao_id": p.latest_revision_id,
            "criada_em": _iso(p.created_at),
        }
        for p in rows
    ]
    return page_envelope(total, offset, itens)


def get_review_detail_handler(law_firm_id: int, revisao_id: int) -> dict:
    """Achados completos de uma revisão já feita, validando o escritório."""
    from datetime import datetime

    from app.models import FapReviewExecution
    from app.services.fap_review_service import fail_if_stuck, load_execution_result_payload

    execution = FapReviewExecution.query.filter_by(
        id=revisao_id, law_firm_id=law_firm_id
    ).first()
    if not execution:
        return {"erro": f"Revisão {revisao_id} não encontrada para este escritório."}

    payload = load_execution_result_payload(execution)
    findings = payload.get("findings") or []
    petition = execution.petition

    # Revisão presa (servidor reiniciou no meio) vira falha, como na tela.
    fail_if_stuck(execution)

    if execution.status == "processing":
        iniciada = execution.updated_at or execution.created_at
        minutos = int((datetime.now() - iniciada).total_seconds() // 60) if iniciada else None
        return {
            "revisao_id": execution.id,
            "peticao_id": execution.petition_id,
            "numero_revisao": execution.revision_number,
            "status": "processando",
            "origem": _origem(execution),
            "processando_ha_minutos": minutos,
            "aviso": (
                "A revisão (enviada pela tela do Revisor) ainda está processando — costuma "
                "levar alguns minutos. Não abra outra revisão."
            ),
        }
    if execution.status != "completed":
        return {
            "revisao_id": execution.id,
            "peticao_id": execution.petition_id,
            "numero_revisao": execution.revision_number,
            "status": "falhou" if execution.status == "failed" else execution.status,
            "origem": _origem(execution),
            "erro_execucao": execution.error_message,
            "aviso": "A revisão não foi concluída — não há achados para mostrar. "
                     "Pela tela do Revisor dá para reprocessá-la.",
        }

    resumo = payload.get("executive_summary") or {}
    return {
        "revisao_id": execution.id,
        "peticao_id": execution.petition_id,
        "identificador": execution.law_firm_document_identifier,
        "titulo_peticao": petition.title if petition else None,
        "status_peticao": petition.workflow_status if petition else None,
        "status_peticao_descricao": _status_label(petition.workflow_status) if petition else None,
        "numero_revisao": execution.revision_number,
        "origem": _origem(execution),
        "modelo": execution.model_name,
        "tipo_analise": payload.get("analysis_type"),
        "revisao_focada": payload.get("focused_review", False),
        "documento": execution.main_document_filename,
        "concluida_em": _iso(execution.completed_at),
        "total_achados": len(findings),
        "achados_por_gravidade": _severity_counts(findings),
        "achados": [_finding_dict(f) for f in findings],
        "documentos_faltantes": [
            {
                "tipo_documento": d.get("document_type"),
                "tese": d.get("thesis"),
                "referencia_manual": d.get("manual_reference"),
            }
            for d in (payload.get("missing_documents") or [])
        ],
        "teses": [
            {
                "tese": t.get("thesis"),
                "numero_beneficio": t.get("benefit_number"),
                "enquadramento": t.get("classification"),
            }
            for t in (payload.get("theses") or [])
        ],
        "mudancas_comparativas": payload.get("comparative_changes") or [],
        "resumo_executivo": resumo,
        "tokens_usados": execution.tokens_used,
        "custo_usd": float(execution.cost_usd) if execution.cost_usd is not None else None,
    }


# ── Mesmo achado entre revisões ─────────────────────────────────────
# A revisão seguinte reescreve o mesmo apontamento com outras palavras
# ("arts. 370/371", "destacamos/compartilhamos" — relato da Protege, 28/10/2026).
# Comparar a descrição idêntica marcava o mesmo achado como resolvido E novo.

# Medido nas revisões seguidas do banco local (28/10/2026): o mesmo achado
# reescrito fica entre 0,56 e 0,80 de sobreposição; achados diferentes da mesma
# categoria, até 0,36. O Jaccard dava 0,37–0,42 para reescritas óbvias ("há
# repetição e sobreposição" x "ainda há sobreposição") porque a descrição longa
# dilui as palavras em comum.
LIMIAR_MESMO_ACHADO = 0.55
# Mesma localização na petição ("Pedidos", "Item 3"): basta menos texto em comum.
LIMIAR_MESMO_LOCAL = 0.4
# Abaixo disso a sobreposição engana ("Falta o NTEP" estaria contido em qualquer
# achado longo que cite o NTEP): compara pelo Jaccard.
_MINIMO_PALAVRAS_SOBREPOSICAO = 5
_PALAVRA = re.compile(r"[0-9a-z]+")
# Palavras que aparecem em quase todo achado ou que só dizem "de novo" na
# revisão seguinte ("ainda", "permanece"): não distinguem um achado de outro.
_GENERICAS = frozenset("""
    que para com uma umas uns nao mais ainda dos das pelo pela pelos pelas por como seu sua seus
    suas este esta estes estas esse essa esses essas isso isto nos nas aos entre sem sobre tambem
    foi ser sao ter tem deve devem pode podem documento texto peticao trecho manual padrao forma
    uso usa usado usada permanece permanecem persiste persistem continua continuam mantem
    """.split())


def _normalizar(texto) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def _palavras(texto) -> set[str]:
    # Palavras de até 2 letras ("de", "do", "no") não distinguem achado; número
    # distingue ("370", "371"), seja qual for o tamanho.
    return {p for p in _PALAVRA.findall(_normalizar(texto))
            if (p.isdigit() or len(p) > 2) and p not in _GENERICAS}


def _nota_mesmo_achado(anterior: dict, atual: dict) -> float:
    trecho = _normalizar(anterior.get("location_excerpt"))
    if trecho and trecho == _normalizar(atual.get("location_excerpt")):
        return 1.0
    a, b = _palavras(anterior.get("description")), _palavras(atual.get("description"))
    if not a or not b:
        return 0.0
    if min(len(a), len(b)) >= _MINIMO_PALAVRAS_SOBREPOSICAO:
        return len(a & b) / min(len(a), len(b))
    return len(a & b) / len(a | b)


def _limiar(anterior: dict, atual: dict) -> float:
    local = _normalizar(anterior.get("location"))
    if local and local == _normalizar(atual.get("location")):
        return LIMIAR_MESMO_LOCAL
    return LIMIAR_MESMO_ACHADO


def casar_achados(anteriores: list[dict], atuais: list[dict]) -> list[tuple[int, int]]:
    """Pares (índice na revisão anterior, índice na atual) que são o mesmo achado.

    Um para um, só dentro da mesma categoria, maior semelhança primeiro: trecho
    da petição igual vale 1; senão, a sobreposição das palavras da descrição
    (sem acento, caixa nem palavras genéricas; Jaccard quando uma das duas é
    curta). Casa a partir de ``LIMIAR_MESMO_ACHADO``, ou de
    ``LIMIAR_MESMO_LOCAL`` quando a localização é a mesma.
    """
    candidatos = []
    for i, anterior in enumerate(anteriores):
        for j, atual in enumerate(atuais):
            if _normalizar(anterior.get("category")) != _normalizar(atual.get("category")):
                continue
            nota = _nota_mesmo_achado(anterior, atual)
            if nota >= _limiar(anterior, atual):
                candidatos.append((-nota, i, j))
    usados_antes: set[int] = set()
    usados_agora: set[int] = set()
    pares = []
    for _, i, j in sorted(candidatos):
        if i in usados_antes or j in usados_agora:
            continue
        usados_antes.add(i)
        usados_agora.add(j)
        pares.append((i, j))
    return pares


def _descricao(finding: dict) -> str:
    return " ".join(str(finding.get("description") or "").split())


def petition_review_history_handler(
    law_firm_id: int,
    peticao_id: int | None = None,
    identificador: str | None = None,
) -> dict:
    """Evolução das revisões de uma petição: o que saiu e o que reincidiu.

    Aceita o id da petição ou o identificador do escritório.
    """
    from app.models import FapReviewExecution, FapReviewPetition
    from app.services.fap_review_service import load_execution_result_payload

    query = FapReviewPetition.query.filter_by(law_firm_id=law_firm_id)
    if peticao_id:
        petition = query.filter_by(id=peticao_id).first()
    elif identificador:
        petition = query.filter_by(office_document_identifier=identificador.strip()).first()
    else:
        return {"erro": "Informe 'peticao_id' ou 'identificador' da petição."}

    if not petition:
        return {"erro": "Petição não encontrada para este escritório."}

    executions = (
        FapReviewExecution.query
        .filter_by(law_firm_id=law_firm_id, petition_id=petition.id, execution_type='revision')
        .order_by(FapReviewExecution.revision_number.asc(), FapReviewExecution.id.asc())
        .all()
    )

    revisoes = []
    anteriores: list[dict] = []
    for e in executions:
        payload = load_execution_result_payload(e)
        findings = payload.get("findings") or []
        atuais = [f for f in findings if isinstance(f, dict) and f.get("description")]
        casados = casar_achados(anteriores, atuais)
        casados_antes = {i for i, _ in casados}
        casados_agora = {j for _, j in casados}
        revisoes.append({
            "revisao_id": e.id,
            "numero_revisao": e.revision_number,
            "status": e.status,
            "origem": _origem(e),
            "concluida_em": _iso(e.completed_at),
            "total_achados": len(findings),
            "achados_por_gravidade": _severity_counts(findings),
            "reincidentes": [_descricao(atuais[j]) for _, j in sorted(casados, key=lambda par: par[1])],
            "resolvidos_desde_a_anterior": [
                _descricao(f) for i, f in enumerate(anteriores) if i not in casados_antes
            ],
            "novos": [_descricao(f) for j, f in enumerate(atuais) if j not in casados_agora],
        })
        anteriores = atuais

    return {
        "peticao_id": petition.id,
        "identificador": petition.office_document_identifier,
        "titulo": petition.title,
        "status": petition.workflow_status,
        "status_descricao": _status_label(petition.workflow_status),
        "total_revisoes": len(revisoes),
        "revisoes": revisoes,
    }


# ── Referências: o manual FAP e os casos que o revisor usa como régua ─────────

REFERENCE_TYPES = {
    "manual_fap": "Manual FAP (a régua das revisões)",
    "casos_referencia": "Casos de referência",
    "project_instructions": "Instruções do projeto",
}

# Acima disso, devolver o documento inteiro afogaria o contexto do agente —
# melhor obrigar a filtrar por seção/termo.
MAX_REFERENCE_CHARS = 40_000


def _split_sections(content: str) -> list[dict]:
    """Quebra o markdown por títulos, para permitir ler só uma seção."""
    import re

    sections: list[dict] = []
    current = {"titulo": "(início)", "nivel": 0, "conteudo": []}
    for line in (content or "").splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if current["conteudo"] or sections:
                sections.append(current)
            current = {"titulo": m.group(2).strip(), "nivel": len(m.group(1)), "conteudo": []}
        else:
            current["conteudo"].append(line)
    sections.append(current)
    return [
        {"titulo": s["titulo"], "nivel": s["nivel"], "conteudo": "\n".join(s["conteudo"]).strip()}
        for s in sections
        if s["titulo"] != "(início)" or "\n".join(s["conteudo"]).strip()
    ]


def read_reviewer_manual_handler(
    law_firm_id: int,
    tipo: str = "manual_fap",
    secao: str | None = None,
    termo: str | None = None,
) -> dict:
    """Lê a referência ativa do revisor (manual FAP por padrão).

    É o que permite ao agente explicar um achado citando a seção real do manual —
    os achados trazem 'referencia_manual' e sem isto não há como abrir.
    """
    from app.models import FapReviewReferenceVersion

    if tipo not in REFERENCE_TYPES:
        return {
            "erro": f"Tipo inválido: {tipo}.",
            "tipos_validos": REFERENCE_TYPES,
        }

    ref = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id, reference_type=tipo, is_active=True
    ).first()

    if not ref or not (ref.content or "").strip():
        return {
            "tipo": tipo,
            "tipo_descricao": REFERENCE_TYPES[tipo],
            "configurado": False,
            "aviso": (
                f"O escritório não tem '{REFERENCE_TYPES[tipo]}' cadastrado no módulo "
                "Revisor de Petições. As revisões rodam sem essa régua — avise um "
                "administrador (Revisor → Configurações → Referências)."
            ),
        }

    content = ref.content
    secoes = _split_sections(content)
    base = {
        "tipo": tipo,
        "tipo_descricao": REFERENCE_TYPES[tipo],
        "configurado": True,
        "versao": ref.version_number,
        "atualizado_em": _iso(ref.updated_at or ref.created_at),
        "total_secoes": len(secoes),
    }

    if secao or termo:
        alvo = (secao or termo or "").lower()
        achadas = [
            s for s in secoes
            if alvo in s["titulo"].lower() or (termo and alvo in s["conteudo"].lower())
        ]
        if not achadas:
            return {
                **base,
                "encontrado": False,
                "secoes_disponiveis": [s["titulo"] for s in secoes],
                "aviso": f"Nada encontrado para {secao or termo!r}. Veja as seções disponíveis.",
            }
        return {**base, "encontrado": True, "secoes": achadas}

    if len(content) > MAX_REFERENCE_CHARS:
        return {
            **base,
            "conteudo_completo": False,
            "aviso": (
                f"O documento tem {len(content)} caracteres — grande demais para devolver "
                "inteiro. Peça uma seção ('secao') ou busque por um termo ('termo')."
            ),
            "secoes_disponiveis": [s["titulo"] for s in secoes],
        }

    return {**base, "conteudo_completo": True, "conteudo": content}


def reference_versions_handler(law_firm_id: int, tipo: str | None = None) -> dict:
    """Histórico de versões das referências do revisor.

    O treinamento pode reescrever o manual e ativar uma versão nova; este é o
    caminho para auditar o que mudou, quando e por quem.
    """
    from app.models import FapReviewReferenceVersion, User

    query = FapReviewReferenceVersion.query.filter_by(law_firm_id=law_firm_id)
    if tipo:
        if tipo not in REFERENCE_TYPES:
            return {"erro": f"Tipo inválido: {tipo}.", "tipos_validos": REFERENCE_TYPES}
        query = query.filter_by(reference_type=tipo)

    rows = query.order_by(
        FapReviewReferenceVersion.reference_type,
        FapReviewReferenceVersion.version_number.desc(),
    ).all()

    if not rows:
        return {
            "total": 0,
            "versoes": [],
            "aviso": "O escritório não tem referências cadastradas no módulo Revisor.",
        }

    autores = {
        u.id: u.name
        for u in User.query.filter(
            User.id.in_([r.created_by_id for r in rows if r.created_by_id])
        ).all()
    } if any(r.created_by_id for r in rows) else {}

    return {
        "total": len(rows),
        "versoes": [
            {
                "tipo": r.reference_type,
                "tipo_descricao": REFERENCE_TYPES.get(r.reference_type, r.reference_type),
                "versao": r.version_number,
                "ativa": r.is_active,
                "tamanho_caracteres": len(r.content or ""),
                "criada_por": autores.get(r.created_by_id),
                "criada_em": _iso(r.created_at),
            }
            for r in rows
        ],
    }


# ── Auditoria ────────────────────────────────────────────────────────────────


def review_audit_log_handler(
    law_firm_id: int,
    peticao_id: int | None = None,
    acao: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Trilha de auditoria do módulo Revisor: quem fez o quê e quando."""
    from app.models import FapReviewAuditLog, User

    limit = clamp_limit(limit, 50)
    offset = clamp_offset(offset)

    query = FapReviewAuditLog.query.filter_by(law_firm_id=law_firm_id)
    if peticao_id:
        query = query.filter(
            FapReviewAuditLog.entity_type == 'petition',
            FapReviewAuditLog.entity_id == peticao_id,
        )
    if acao:
        query = query.filter(FapReviewAuditLog.action.ilike(f"%{acao}%"))

    total = query.count()
    rows = fetch_page(
        query.order_by(FapReviewAuditLog.created_at.desc(), FapReviewAuditLog.id.desc()),
        limit, offset,
    )

    autores = {
        u.id: u.name
        for u in User.query.filter(User.id.in_([r.user_id for r in rows if r.user_id])).all()
    } if rows else {}

    itens = [
        {
            "id": r.id,
            "acao": r.action,
            "entidade": r.entity_type,
            "entidade_id": r.entity_id,
            "descricao": r.change_description,
            "valor_anterior": r.old_value or None,
            "valor_novo": r.new_value or None,
            "usuario": autores.get(r.user_id),
            "quando": _iso(r.created_at),
        }
        for r in rows
    ]
    return page_envelope(total, offset, itens)


# ── Estatísticas por advogado (admin) ────────────────────────────────────────


def lawyer_statistics_handler(law_firm_id: int) -> dict:
    """Score, retrabalho e reincidência por advogado — os mesmos números da tela."""
    from app.services.fap_review_service import build_lawyer_statistics

    stats = build_lawyer_statistics(law_firm_id)
    overview = stats.get("overview") or {}
    lawyers = stats.get("lawyers") or []

    if not lawyers:
        return {
            "panorama": overview,
            "advogados": [],
            "aviso": "Ainda não há revisões concluídas para calcular estatísticas.",
        }

    return {
        "panorama": {
            "advogados": overview.get("total_lawyers"),
            "revisoes": overview.get("total_revisions"),
            "achados": overview.get("total_findings"),
            "achados_reincidentes": overview.get("repeated_findings"),
            "taxa_reincidencia": overview.get("recurrence_rate"),
        },
        "advogados": [
            {
                "usuario_id": l.get("user_id"),
                "nome": l.get("name"),
                "papel": l.get("role"),
                "score": l.get("score"),
                "revisoes": l.get("total_revisions"),
                "peticoes": l.get("petitions_count"),
                "achados": l.get("total_findings"),
                "achados_criticos": l.get("critical_findings"),
                "achados_moderados": l.get("moderate_findings"),
                "achados_formais": l.get("formal_findings"),
                "media_achados_por_revisao": l.get("avg_findings_per_revision"),
                "peticoes_com_retrabalho": l.get("rework_petitions"),
                "taxa_retrabalho": l.get("rework_ratio"),
                "achados_reincidentes": l.get("repeated_findings"),
                "taxa_reincidencia": l.get("recurrence_rate"),
                "categorias_mais_frequentes": l.get("top_categories"),
            }
            for l in lawyers
        ],
        "nota": (
            "Score é heurístico (100 menos penalidades por média de achados, retrabalho e "
            "reincidência) — serve para orientar melhoria, não para ranquear pessoas."
        ),
    }
