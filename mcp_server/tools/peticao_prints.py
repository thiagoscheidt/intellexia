"""
Tool: prints das petições protocoladas (CONBAS, INFBEN, laudo, CAT, tela do FAP...).

O escritório já recortou esses prints dos autos e colou nas petições, com uma
legenda padronizada. Esta ferramenta acha o print pelas legendas do .md da Base
de Conhecimento e devolve o link da imagem, que é tirada do PDF original no
Drive quando a pessoa abre o link (``app.services.peticao_prints_service``).

Só acha o que o escritório **já protocolou**: print novo continua saindo dos
autos. Módulo ``knowledge_base``, sempre filtrado pelo escritório.
"""
from __future__ import annotations

from fastmcp.exceptions import ToolError

from mcp_server.tools.pagination import clamp_limit, clamp_offset, page_envelope


def _url(app_public_url: str, caminho: str) -> str | None:
    return f"{app_public_url.rstrip('/')}{caminho}" if app_public_url else None


def petition_prints_handler(
    law_firm_id: int,
    numero_processo: str | None = None,
    numero: str | None = None,
    sistema: str | None = None,
    termo: str | None = None,
    limite: int = 20,
    deslocamento: int = 0,
    app_public_url: str = "",
) -> dict:
    from app.services import peticao_prints_service as svc

    if not any((numero_processo, numero, termo)):
        raise ToolError(
            'Informe ao menos um filtro: "numero_processo", "numero" (NB, CAT) ou "termo" '
            '(ex.: o nome do segurado). "sistema" sozinho traria os prints de todas as petições.')
    limite = clamp_limit(limite, 20)
    deslocamento = clamp_offset(deslocamento)
    try:
        achados = svc.localizar(law_firm_id, numero_processo=numero_processo, numero=numero,
                                sistema=sistema, termo=termo)
    except ValueError as erro:
        raise ToolError(str(erro)) from erro

    pagina = achados[deslocamento:deslocamento + limite]
    acesso = svc.pdfs_acessiveis(law_firm_id, {svc.drive_id(kb.source_url) for kb, _p in pagina} - {None})
    itens = []
    for kb, p in pagina:
        fid = svc.drive_id(kb.source_url)
        disponivel = False if fid is None else acesso.get(fid)
        nome = (kb.original_filename or "").removesuffix(".md")
        itens.append({
            "arquivo_id": kb.id,
            "ordem": p.ordem,
            "peticao": nome,
            "data_peticao": svc.data_da_peticao(nome),
            "numero_processo": kb.lawsuit_number,
            "sistema": p.sistema,
            "legenda": p.legenda,
            "referencia": p.referencia,
            "numeros": p.numeros,
            "partes": p.partes,
            "texto_na_imagem": p.texto_imagem[:400],
            "pdf_disponivel": disponivel,
            "url_imagem": _url(app_public_url, f"/knowledge-base/{kb.id}/print/{p.ordem}"),
            "url_peticao": _url(app_public_url, f"/knowledge-base/{kb.id}/view"),
            "url_original": kb.source_url,
        })

    resposta = page_envelope(len(achados), deslocamento, itens)
    if not achados:
        resposta["dica"] = (
            "Nenhum print com esses filtros nas petições protocoladas da Base de Conhecimento. "
            "A busca só acha print que o escritório já usou numa petição; o número procurado "
            "precisa estar na legenda (NB, CAT ou processo).")
    elif any(i["pdf_disponivel"] is False for i in itens):
        resposta["dica"] = (
            'Itens com "pdf_disponivel": false têm o print citado, mas o PDF da petição não está '
            "compartilhado com o IntellexIA no Google Drive: o url_imagem não vai abrir. Mostre o "
            '"url_original" para a pessoa pegar o print no próprio PDF.')
    return resposta
