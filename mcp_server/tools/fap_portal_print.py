"""
Tool: print da Consulta do FAP no portal (fap-mps.dataprev.gov.br), ao vivo.

Abre a tela com a sessão do portal desta instalação, tira o print e devolve o
link da imagem (``app.services.fap_portal_print_service``). Complementa
``prints_das_peticoes``, que acha os prints que o escritório já usou: esta tira
um novo. Módulo ``fap_panel``.
"""
from __future__ import annotations

from fastmcp.exceptions import ToolError


def _url(app_public_url: str, caminho: str) -> str | None:
    return f"{app_public_url.rstrip('/')}{caminho}" if app_public_url else None


def fap_portal_print_handler(
    law_firm_id: int,
    user_id: int | None,
    cnpj: str,
    vigencia: int,
    tela: str = "calculo",
    numero: str | None = None,
    calculo: str = "atual",
    app_public_url: str = "",
) -> dict:
    from app.services import fap_portal_print_service as svc
    from app.utils.cnpj import formatar_cnpj
    from app.utils.timezone import format_datetime_sp

    try:
        p = svc.capturar(law_firm_id, user_id, cnpj, vigencia, tela, numero, calculo)
    except svc.PrintFapIndisponivel as erro:
        raise ToolError(str(erro)) from erro

    resposta = {
        "cnpj": formatar_cnpj(p.cnpj),
        "empresa": p.empresa,
        "vigencia": p.vigencia,
        "tela": p.tela,
        "tela_descricao": svc.TELAS[p.tela],
        "numero": p.numero,
        "calculo": p.calculo_rotulo,
        "fap": p.fap,
        "linhas": p.linhas,
        "capturado_em": format_datetime_sp(p.capturado_em),
        "disponivel_ate": format_datetime_sp(svc.expira_em(p)),
        "imagens": [
            {"parte": i, "descricao": parte["descricao"],
             "url_imagem": _url(app_public_url, f"/fap-panel/print-portal/{parte['nome']}")}
            for i, parte in enumerate(p.partes, start=1)
        ],
    }
    avisos = []
    if len(p.partes) > 1:
        avisos.append("A tabela tem mais colunas do que cabem na tela: a parte 2 é a mesma linha com a "
                      "tabela rolada até o fim (DIB, DCB, CPF, NIT...).")
    if p.linhas_omitidas:
        avisos.append(f"A tabela tem mais de 100 linhas: {p.linhas_omitidas} ficaram fora do print. "
                      "Filtre por número para o benefício que interessa.")
    if p.sessao_parcial:
        avisos.append("A sessão do portal está parcial (perdeu as empresas vinculadas do gov.br): "
                      "algumas empresas podem não aparecer até um login novo.")
    if avisos:
        resposta["aviso"] = " ".join(avisos)
    return resposta
