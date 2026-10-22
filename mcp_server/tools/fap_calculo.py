"""Tools do MCP para os benefícios e CATs do cálculo FAP (``fap_calculo_itens``).

Lê pelo mesmo serviço da tela do Painel FAP (``fap_calculo_query_service``);
aqui só entram a resolução de empresa/grupo, a validação dos valores e o envelope.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from mcp_server.tools.pagination import clamp_limit, clamp_offset, page_envelope


def _tool_error(msg: str):
    from fastmcp.exceptions import ToolError
    return ToolError(msg)


def _validar(tipo, situacao):
    from app.services.fap_calculo_query_service import SITUACOES, TIPOS

    tipo_n = None
    if tipo:
        tipo_n = str(tipo).strip().upper()
        if tipo_n not in TIPOS:
            raise _tool_error(f"tipo '{tipo}' inválido. Valores aceitos: {', '.join(TIPOS)}.")
    sit_n = None
    if situacao:
        sit_n = str(situacao).strip().lower()
        if sit_n not in SITUACOES:
            raise _tool_error(
                f"situacao '{situacao}' inválida. Valores aceitos: {', '.join(SITUACOES)} "
                "(conta = entra no cálculo; excluido = o portal tirou do cálculo no recálculo)."
            )
    return tipo_n, sit_n


def _vigencia(vigencia):
    if vigencia in (None, ""):
        return None
    try:
        return int(str(vigencia).strip())
    except ValueError:
        raise _tool_error(f"vigencia '{vigencia}' inválida: informe o ano, por exemplo 2023.")


def _consulta(law_firm_id, *, vigencia, empresa, grupo, cnpj, cpf=None, nit=None,
              numero=None, tipo=None, situacao=None, contestado=None):
    from app.models import FapCompany
    from app.services import fap_calculo_query_service as svc
    from mcp_server.tools.fap import resolver_grupo

    tipo_n, sit_n = _validar(tipo, situacao)
    ano = _vigencia(vigencia)
    grupo_info = resolver_grupo(law_firm_id, grupo) if grupo else None

    raizes = None
    if empresa:
        rq = FapCompany.query.filter_by(law_firm_id=law_firm_id)
        for t in empresa.split():
            rq = rq.filter(FapCompany.nome.ilike(f"%{t}%"))
        raizes = [c.cnpj for c in rq.with_entities(FapCompany.cnpj).limit(50).all() if c.cnpj]
        if not raizes:
            raizes = ["__nenhuma__"]

    q = svc.filtrar(
        law_firm_id, vigencia=ano, raizes=raizes,
        grupo=grupo_info["chave"] if grupo_info else None,
        cnpj=cnpj, tipos=[tipo_n] if tipo_n else None, situacao=sit_n,
        contestado=contestado,
    )
    q = _por_segurado(q, cpf=cpf, nit=nit, numero=numero)
    return q


def _por_segurado(q, *, cpf=None, nit=None, numero=None):
    """CPF, NIT e número restringem juntos (E); valor sem dígitos filtra a vazio."""
    from sqlalchemy import false

    from app.services import fap_calculo_query_service as svc
    from app.utils.cnpj import apenas_digitos, completar_zeros

    for valor, coluna, tam in ((cpf, svc.Item.cpf, 11), (nit, svc.Item.nit, None),
                               (numero, svc.Item.identificador, None)):
        if not valor:
            continue
        d = apenas_digitos(valor)
        if not d:
            q = q.filter(false())
        else:
            q = q.filter(coluna == (completar_zeros(d, tam) if tam else d))
    return q


def _serializar(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, (date, datetime)):
            v = v.isoformat()
        elif isinstance(v, Decimal):
            v = float(v)
        out[k] = v
    return out


def listar_beneficios_calculo_fap_handler(
    law_firm_id: int,
    vigencia=None,
    empresa: str | None = None,
    grupo: str | None = None,
    cnpj: str | None = None,
    cpf: str | None = None,
    nit: str | None = None,
    numero: str | None = None,
    tipo: str | None = None,
    situacao: str | None = None,
    contestado: bool | None = None,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    from app.services import fap_calculo_query_service as svc

    q = _consulta(law_firm_id, vigencia=vigencia, empresa=empresa, grupo=grupo, cnpj=cnpj,
                  cpf=cpf, nit=nit, numero=numero, tipo=tipo, situacao=situacao,
                  contestado=contestado)
    limite = clamp_limit(limite, 50)
    deslocamento = clamp_offset(deslocamento)

    itens, total = svc.janela(q, deslocamento, limite, law_firm_id=law_firm_id)
    return page_envelope(total, deslocamento, [_serializar(i) for i in itens])


def resumo_beneficios_calculo_fap_handler(
    law_firm_id: int,
    vigencia=None,
    empresa: str | None = None,
    grupo: str | None = None,
    cnpj: str | None = None,
    tipo: str | None = None,
) -> dict:
    from app.services import fap_calculo_query_service as svc

    q = _consulta(law_firm_id, vigencia=vigencia, empresa=empresa, grupo=grupo, cnpj=cnpj,
                  tipo=tipo)
    return svc.contadores(q, law_firm_id=law_firm_id)


def itens_do_segurado(law_firm_id: int, cpf: str | None, nit: str | None, limite: int = 30) -> dict:
    """Itens do cálculo de um segurado (CPF e/ou NIT), para o buscar_por_segurado."""
    from app.services import fap_calculo_query_service as svc

    q = _por_segurado(svc.filtrar(law_firm_id), cpf=cpf, nit=nit)
    itens, total = svc.pagina(q, 1, limite, law_firm_id=law_firm_id)
    return {"total": total, "itens": [_serializar(i) for i in itens]}
