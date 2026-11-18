"""
Tools: documentos anexados às contestações do FAP (FB-08).

O que o escritório juntou a cada contestação no portal FAP — CONBAS, INFBEN,
HISMED (perícias médicas, com CID), CAT, CNIS, insumos do eSocial — baixado do
"Visualizar Anexos" de cada recálculo, com o texto lido do PDF. Fonte única:
``app.services.fap_anexos_busca_service`` (a mesma da Central e da API).

Módulo ``disputes_center``: o HISMED tem dado de saúde. Sempre filtrado pelo
escritório.
"""
from __future__ import annotations

from fastmcp.exceptions import ToolError

from mcp_server.tools.pagination import clamp_limit, clamp_offset, page_envelope

LIMITE_TEXTO = 30_000


def _url(app_public_url: str, caminho: str) -> str | None:
    return f"{app_public_url.rstrip('/')}{caminho}" if app_public_url else None


def _limpo(item: dict, app_public_url: str) -> dict:
    """Item da busca no formato do MCP: ``documento_id`` (o que ``ler_documento_contestacao``
    recebe), trecho em texto com o achado entre « », link do arquivo."""
    import html

    saida = {"documento_id": item.pop("id"), **item}
    trecho = saida.pop("trecho", None)
    if trecho:
        saida["trecho"] = html.unescape(trecho.replace("<mark>", "«").replace("</mark>", "»"))
    tem_arquivo = saida.pop("tem_arquivo", False)
    saida["url_arquivo"] = (_url(app_public_url, f"/disputes-center/anexos/{saida['documento_id']}/arquivo")
                            if tem_arquivo else None)
    saida["anexo_id_portal"] = saida.pop("anexo_id", None)
    return saida


def search_fap_attachments_handler(
    law_firm_id: int,
    termo: str | None = None,
    nb: str | None = None,
    cnpj: str | None = None,
    vigencia: int | None = None,
    tipo_documento: str | None = None,
    cid: str | None = None,
    instancia: int | None = None,
    cat_tipo: str | None = None,
    limite: int = 20,
    deslocamento: int = 0,
    app_public_url: str = "",
) -> dict:
    from app.services import fap_anexos_busca_service as busca
    from app.services.fap_anexos_conteudo import TIPOS

    if not any((termo, nb, cnpj, vigencia, tipo_documento, cid, instancia, cat_tipo)):
        raise ToolError(
            'Informe ao menos um filtro: "termo", "nb", "cnpj", "vigencia", "tipo_documento", "cid", '
            '"instancia" ou "cat_tipo".')
    if tipo_documento and tipo_documento.upper() not in TIPOS:
        raise ToolError(f'tipo_documento "{tipo_documento}" não existe. Use um de: {", ".join(TIPOS)}.')
    if instancia not in (None, 1, 2):
        raise ToolError('instancia é 1 ou 2.')
    if cat_tipo and cat_tipo.upper() not in ("TRAJETO", "TIPICO", "DOENCA"):
        raise ToolError('cat_tipo é TRAJETO, TIPICO ou DOENCA.')
    limite = clamp_limit(limite, 20)
    deslocamento = clamp_offset(deslocamento)
    r = busca.pesquisar(law_firm_id, termo, nb=nb, cnpj=cnpj, vigencia=vigencia,
                        tipo_documento=tipo_documento, cid=cid, instancia=instancia, cat_tipo=cat_tipo,
                        limite=limite, deslocamento=deslocamento)
    itens = [_limpo(i, app_public_url) for i in r["itens"]]
    resposta = page_envelope(r["total"], deslocamento, itens)
    resposta["total_e_minimo"] = r["total_e_minimo"]
    if r["fonte"] == "banco":
        resposta["aviso"] = ("O índice de busca está fora do ar: a pesquisa foi feita direto no banco, "
                             "palavra por palavra, sem tolerância a erro de digitação.")
    if not itens:
        resposta["dica"] = (
            "Nenhum documento com esses filtros. Os anexos só ficam visíveis depois que o portal publica o "
            "recálculo da contestação — contestação ainda em análise não aparece aqui. Para frase exata, "
            "ponha entre aspas.")
    return resposta


def read_fap_attachment_handler(law_firm_id: int, documento_id: int, deslocamento: int = 0,
                                app_public_url: str = "") -> dict:
    from app.services import fap_anexos_busca_service as busca

    doc = busca.ler(law_firm_id, int(documento_id))
    if doc is None:
        raise ToolError(f"Documento {documento_id} não encontrado neste escritório.")
    texto = doc.pop("texto") or ""
    deslocamento = clamp_offset(deslocamento)
    pedaco = texto[deslocamento:deslocamento + LIMITE_TEXTO]
    doc = _limpo(doc, app_public_url)
    doc["texto"] = pedaco
    doc["tamanho_texto"] = len(texto)
    proximo = deslocamento + len(pedaco)
    doc["tem_mais"] = proximo < len(texto)
    doc["proximo_deslocamento"] = proximo if doc["tem_mais"] else None
    if not texto:
        doc["dica"] = ("Este documento não tem texto (PDF de imagem ou arquivo ainda não lido). "
                       "Mostre o url_arquivo para a pessoa abrir.")
    return doc
