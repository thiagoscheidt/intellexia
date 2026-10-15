"""
Tool: busca por número de processo em todas as bases do escritório.

Determinística, sem IA: o número é comparado só pelos dígitos
(`app.utils.cnj.filtro_numero_processo`), então "5001181-56.2023.4.03.6100",
"50011815620234036100" e "5001181562023" acham a mesma coisa — completo é
igualdade, parcial é "contém". O `pesquisar_base_conhecimento` continua sendo a
busca por texto/significado; nele, número de processo depende de a IA
reconhecer o número na pergunta.

Cada base entra só com o módulo que a tela exige (Base de Conhecimento →
`knowledge_base`; Jurisprudência, Peças-modelo e Painel de Processos →
`process_panel`) e sempre filtrada pelo escritório.
"""
from __future__ import annotations

from fastmcp.exceptions import ToolError

from mcp_server.tools.pagination import clamp_limit, clamp_offset, fetch_page, page_envelope

BASES = {
    "base_conhecimento": "knowledge_base",
    "jurisprudencia": "process_panel",
    "pecas_modelo": "process_panel",
    "processos": "process_panel",
}
_ROTULOS = {
    "base_conhecimento": "Base de Conhecimento",
    "jurisprudencia": "Base de Jurisprudência",
    "pecas_modelo": "Peças-modelo",
    "processos": "Painel de Processos",
}
_PROXIMO_PASSO = {
    "base_conhecimento": "ler_arquivo_base_conhecimento(arquivo_id=id) traz o arquivo inteiro.",
    "jurisprudencia": "detalhar_decisao(decisao_id=id) traz a decisão completa.",
    "pecas_modelo": "a peça-modelo abre pelo 'url'.",
    "processos": "detalhar_processo(processo_id=id) traz fases, benefícios e notas.",
}


def _iso(valor):
    return valor.isoformat() if valor else None


def _url(app_public_url, caminho):
    return f"{app_public_url.rstrip('/')}{caminho}" if app_public_url else None


def _base_conhecimento(law_firm_id, numero, app_public_url):
    from app.models import KnowledgeBase
    from app.utils.cnj import filtro_numero_processo

    query = KnowledgeBase.query.filter(
        KnowledgeBase.law_firm_id == law_firm_id,
        KnowledgeBase.is_active.is_(True),
        filtro_numero_processo(numero, coluna_mascara=KnowledgeBase.lawsuit_number, varios_numeros=True),
    )
    ordem = query.order_by(KnowledgeBase.uploaded_at.desc(), KnowledgeBase.id.desc())

    def item(k):
        return {
            "id": k.id,
            "numero_processo": k.lawsuit_number,
            "arquivo": k.original_filename,
            "categoria": k.category,
            "tags": [t for t in (k.tags or "").split(",") if t],
            "tipo": k.file_type,
            "situacao": k.processing_status,
            "enviado_em": _iso(k.uploaded_at),
            "url_abrir": _url(app_public_url, f"/knowledge-base/{k.id}/view"),
            **({"url_original": k.source_url} if k.source_url else {}),
        }
    return query, ordem, item


def _jurisprudencia(law_firm_id, numero, app_public_url):
    from app.models import JurisprudenceDecision
    from app.services import jurisprudence_normalizer as norm
    from app.utils.cnj import filtro_numero_processo

    query = JurisprudenceDecision.query.filter(
        JurisprudenceDecision.law_firm_id == law_firm_id,
        filtro_numero_processo(numero, coluna_digitos=JurisprudenceDecision.processo_digits),
    )
    ordem = query.order_by(JurisprudenceDecision.data_julgamento.desc(), JurisprudenceDecision.id.desc())

    def item(d):
        return {
            "id": d.id,
            "numero_processo": d.processo,
            "instancia": norm.TIPO_LABELS.get(d.tipo_documento or "", d.tipo_documento),
            "data_julgamento": _iso(d.data_julgamento),
            "tribunal": d.tribunal,
            "orgao_julgador": d.orgao_julgador,
            "resultado": norm.RESULTADO_LABELS.get(d.resultado or "", "não informado"),
            "parte_autora": d.parte_autora,
            "teses_originais": list(d.teses_brutas_json or []),
            "url": _url(app_public_url, f"/process-panel/jurisprudencia/decisao/{d.id}"),
            **({"url_original": d.drive_link} if d.drive_link else {}),
        }
    return query, ordem, item


def _pecas_modelo(law_firm_id, numero, app_public_url):
    from app.models import ImpugnacaoReferenceModel
    from app.utils.cnj import filtro_numero_processo

    query = ImpugnacaoReferenceModel.query.filter(
        ImpugnacaoReferenceModel.law_firm_id == law_firm_id,
        filtro_numero_processo(numero, coluna_mascara=ImpugnacaoReferenceModel.process_number,
                               varios_numeros=True),
    )
    ordem = query.order_by(ImpugnacaoReferenceModel.created_at.desc(), ImpugnacaoReferenceModel.id.desc())

    def item(p):
        return {
            "id": p.id,
            "numero_processo": p.process_number,
            "titulo": p.title,
            "tribunal": p.trf_region,
            "orgao_julgador": p.orgao_julgador,
            "situacao": p.status,
            "teses": list(p.source_theses_json or []),
            "url": _url(app_public_url, f"/referencias-impugnacao/{p.id}"),
            **({"url_original": f"https://drive.google.com/file/d/{p.source_drive_file_id}/view"}
               if p.source_drive_file_id else {}),
        }
    return query, ordem, item


def _processos(law_firm_id, numero, app_public_url):
    from app.models import JudicialProcess
    from app.utils.cnj import filtro_numero_processo

    query = JudicialProcess.query.filter(
        JudicialProcess.law_firm_id == law_firm_id,
        filtro_numero_processo(numero, coluna_mascara=JudicialProcess.process_number),
    )
    ordem = query.order_by(JudicialProcess.created_at.desc(), JudicialProcess.id.desc())

    def item(p):
        return {
            "id": p.id,
            "numero_processo": p.process_number,
            "titulo": p.title,
            "status": p.status,
            "tribunal": p.tribunal_name,
            "autor": p.plaintiff_client.name if p.plaintiff_client else None,
            "reu": p.defendant.name if p.defendant else None,
            "url": _url(app_public_url, f"/process-panel/{p.id}"),
        }
    return query, ordem, item


_CONSULTAS = {
    "base_conhecimento": _base_conhecimento,
    "jurisprudencia": _jurisprudencia,
    "pecas_modelo": _pecas_modelo,
    "processos": _processos,
}


def search_by_process_number_handler(law_firm_id: int, modulos: list[str], numero: str, *,
                                     bases: list[str] | None = None, limite: int = 20,
                                     deslocamento: int = 0, app_public_url: str | None = None) -> dict:
    """Procura o número em cada base pedida que o usuário pode ver."""
    from app.utils.cnj import MIN_DIGITOS_BUSCA, cnj_digits

    digitos = cnj_digits(numero)
    if len(digitos) < MIN_DIGITOS_BUSCA:
        raise ToolError(
            f"Informe ao menos {MIN_DIGITOS_BUSCA} dígitos do número do processo (com ou sem pontuação). "
            "Menos que isso casa metade da base — \"2023\" está em todo número do ano."
        )
    pedidas = list(dict.fromkeys(bases or BASES))
    desconhecidas = [b for b in pedidas if b not in BASES]
    if desconhecidas:
        raise ToolError(f"Base desconhecida: {', '.join(desconhecidas)}. Use: {', '.join(BASES)}.")
    liberadas = [b for b in pedidas if BASES[b] in (modulos or [])]
    if not liberadas:
        raise ToolError("Acesso negado: seu usuário não tem permissão para nenhuma das bases pedidas.")

    limite, deslocamento = clamp_limit(limite, 20), clamp_offset(deslocamento)
    resultado = {
        "numero_buscado": numero,
        "digitos": digitos,
        "comparacao": "número completo (igual)" if len(digitos) == 20 else "parte do número (contém)",
        "bases": {},
    }
    total_geral = 0
    for base in liberadas:
        query, ordem, item = _CONSULTAS[base](law_firm_id, numero, app_public_url)
        total = query.count()
        total_geral += total
        grupo = page_envelope(total, deslocamento, [item(r) for r in fetch_page(ordem, limite, deslocamento)])
        grupo["base"] = _ROTULOS[base]
        if total:
            grupo["proximo_passo"] = _PROXIMO_PASSO[base]
        if grupo.get("tem_mais"):
            grupo["dica"] = (f"Há mais nesta base: chame de novo com bases=['{base}'] e "
                             f"deslocamento={grupo.get('proximo_deslocamento')}.")
        resultado["bases"][base] = grupo
    resultado["total_encontrado"] = total_geral
    sem_permissao = [_ROTULOS[b] for b in pedidas if b not in liberadas]
    if sem_permissao:
        resultado["sem_permissao"] = sem_permissao
    if not total_geral:
        resultado["aviso"] = ("Nada com esse número nas bases consultadas. Confira os dígitos; na Base de "
                              "Conhecimento só entram arquivos com o número preenchido.")
    return resultado
