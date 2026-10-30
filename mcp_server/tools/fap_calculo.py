"""Tools do MCP para os benefícios e CATs do cálculo FAP (``fap_calculo_itens``).

Lê pelo mesmo serviço da tela do Painel FAP (``fap_calculo_query_service``);
aqui só entram a resolução de empresa/grupo/nome, a validação dos valores e o envelope.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from mcp_server.tools.pagination import clamp_limit, clamp_offset, page_envelope


def _tool_error(msg: str):
    from fastmcp.exceptions import ToolError
    return ToolError(msg)


def _tipos(tipo):
    """``tipo`` em texto ("B91" ou "B91,B94") ou lista; ``None`` = todos."""
    from app.services.fap_calculo_query_service import TIPOS

    if not tipo:
        return None
    brutos = tipo if isinstance(tipo, (list, tuple)) else str(tipo).split(',')
    tipos = [str(t).strip().upper() for t in brutos if str(t).strip()]
    invalidos = [t for t in tipos if t not in TIPOS]
    if invalidos:
        raise _tool_error(f"tipo '{', '.join(invalidos)}' inválido. Valores aceitos: {', '.join(TIPOS)}.")
    return tipos or None


def _situacao(situacao):
    from app.services.fap_calculo_query_service import SITUACOES

    if not situacao:
        return None
    sit_n = str(situacao).strip().lower()
    if sit_n not in SITUACOES:
        raise _tool_error(
            f"situacao '{situacao}' inválida. Valores aceitos: {', '.join(SITUACOES)} "
            "(conta = entra no cálculo; excluido = o portal tirou do cálculo no recálculo)."
        )
    return sit_n


def _escolha(valor, aceitos, nome, padrao=None):
    if valor in (None, ""):
        return padrao
    v = str(valor).strip().lower()
    if v not in aceitos:
        raise _tool_error(f"{nome} '{valor}' inválido. Valores aceitos: {', '.join(aceitos)}.")
    return v


def _vigencia(vigencia):
    if vigencia in (None, ""):
        return None
    try:
        return int(str(vigencia).strip())
    except ValueError:
        raise _tool_error(f"vigencia '{vigencia}' inválida: informe o ano, por exemplo 2023.")


def _data(valor, nome):
    """AAAA-MM-DD ou DD/MM/AAAA."""
    if valor in (None, ""):
        return None
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            pass
    raise _tool_error(f"{nome} '{valor}' inválida: use AAAA-MM-DD (ex.: 2024-01-31).")


def _consulta(law_firm_id, *, vigencia=None, empresa=None, grupo=None, cnpj=None, cpf=None, nit=None,
              numero=None, tipo=None, situacao=None, contestado=None, nome=None,
              cnpj_divergente=None, ausente_no_calculo_atual=None, inicio_de=None, inicio_ate=None,
              cessacao_de=None, cessacao_ate=None, com_obito=None):
    from app.models import FapCompany
    from app.services import fap_calculo_query_service as svc
    from app.services import segurado_nome_service
    from mcp_server.tools.fap import resolver_grupo

    tipos = _tipos(tipo)
    sit_n = _situacao(situacao)
    ano = _vigencia(vigencia)
    datas = {k: _data(v, k) for k, v in (("inicio_de", inicio_de), ("inicio_ate", inicio_ate),
                                          ("cessacao_de", cessacao_de), ("cessacao_ate", cessacao_ate))}
    grupo_info = resolver_grupo(law_firm_id, grupo) if grupo else None

    raizes = None
    if empresa:
        rq = FapCompany.query.filter_by(law_firm_id=law_firm_id)
        for t in empresa.split():
            rq = rq.filter(FapCompany.nome.ilike(f"%{t}%"))
        raizes = [c.cnpj for c in rq.with_entities(FapCompany.cnpj).limit(50).all() if c.cnpj]
        if not raizes:
            raizes = ["__nenhuma__"]

    # O FAP não informa nome: só casa quem já teve o nome revelado.
    cpfs = segurado_nome_service.cpfs_por_nome(law_firm_id, nome, limite=500) if nome else None

    q = svc.filtrar(
        law_firm_id, vigencia=ano, raizes=raizes,
        grupo=grupo_info["chave"] if grupo_info else None,
        cnpj=cnpj, tipos=tipos, situacao=sit_n, contestado=contestado, cpfs=cpfs,
        cnpj_divergente=cnpj_divergente, ausente=ausente_no_calculo_atual,
        com_obito=com_obito, **datas,
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


_DINHEIRO = ("total_pago", "total_pago_nao_contestado", "total_pago_excluido",
             "total_pago_conta_nao_contestado")


def _contadores_json(c: dict) -> dict:
    """Somas em reais como texto decimal ("1234.56"), como no resumo."""
    return {k: (str(v) if k in _DINHEIRO and v is not None else v) for k, v in c.items()}


def _ordem(ordem):
    from app.services.fap_calculo_query_service import ORDENS
    return _escolha(ordem, tuple(ORDENS), "ordem")


def listar_beneficios_calculo_fap_handler(
    law_firm_id: int,
    vigencia=None,
    empresa: str | None = None,
    grupo: str | None = None,
    cnpj: str | None = None,
    cpf: str | None = None,
    nit: str | None = None,
    numero: str | None = None,
    tipo=None,
    situacao: str | None = None,
    contestado: bool | None = None,
    limite: int = 50,
    deslocamento: int = 0,
    *,
    nome: str | None = None,
    cnpj_divergente: bool | None = None,
    ausente_no_calculo_atual: bool | None = None,
    inicio_de=None,
    inicio_ate=None,
    cessacao_de=None,
    cessacao_ate=None,
    com_obito: bool | None = None,
    ordem: str | None = None,
) -> dict:
    from app.services import fap_calculo_query_service as svc

    ordem = _ordem(ordem)
    q = _consulta(law_firm_id, vigencia=vigencia, empresa=empresa, grupo=grupo, cnpj=cnpj,
                  cpf=cpf, nit=nit, numero=numero, tipo=tipo, situacao=situacao,
                  contestado=contestado, nome=nome, cnpj_divergente=cnpj_divergente,
                  ausente_no_calculo_atual=ausente_no_calculo_atual, inicio_de=inicio_de,
                  inicio_ate=inicio_ate, cessacao_de=cessacao_de, cessacao_ate=cessacao_ate,
                  com_obito=com_obito)
    limite = clamp_limit(limite, 50)
    deslocamento = clamp_offset(deslocamento)

    itens, total = svc.janela(q, deslocamento, limite, law_firm_id=law_firm_id, ordem=ordem)
    return page_envelope(total, deslocamento, [_serializar(i) for i in itens])


def resumo_beneficios_calculo_fap_handler(
    law_firm_id: int,
    vigencia=None,
    empresa: str | None = None,
    grupo: str | None = None,
    cnpj: str | None = None,
    tipo=None,
    *,
    situacao: str | None = None,
    contestado: bool | None = None,
    cpf: str | None = None,
    nit: str | None = None,
    numero: str | None = None,
    nome: str | None = None,
    cnpj_divergente: bool | None = None,
    ausente_no_calculo_atual: bool | None = None,
    inicio_de=None,
    inicio_ate=None,
    cessacao_de=None,
    cessacao_ate=None,
    com_obito: bool | None = None,
) -> dict:
    from app.services import fap_calculo_query_service as svc

    q = _consulta(law_firm_id, vigencia=vigencia, empresa=empresa, grupo=grupo, cnpj=cnpj,
                  cpf=cpf, nit=nit, numero=numero, tipo=tipo, situacao=situacao,
                  contestado=contestado, nome=nome, cnpj_divergente=cnpj_divergente,
                  ausente_no_calculo_atual=ausente_no_calculo_atual, inicio_de=inicio_de,
                  inicio_ate=inicio_ate, cessacao_de=cessacao_de, cessacao_ate=cessacao_ate,
                  com_obito=com_obito)
    return svc.contadores(q, law_firm_id=law_firm_id)


def ranking_calculo_fap_handler(
    law_firm_id: int,
    agrupar_por: str = "empresa",
    ordenar_por: str | None = None,
    vigencia=None,
    empresa: str | None = None,
    grupo: str | None = None,
    cnpj: str | None = None,
    tipo=None,
    situacao: str | None = None,
    contestado: bool | None = None,
    cnpj_divergente: bool | None = None,
    limite: int = 20,
    deslocamento: int = 0,
) -> dict:
    from app.services import fap_calculo_query_service as svc

    agrupar_por = _escolha(agrupar_por, svc.AGRUPAMENTOS, "agrupar_por", "empresa")
    ordenar_por = _escolha(ordenar_por, svc.METRICAS, "ordenar_por", "total_pago_conta_nao_contestado")
    q = _consulta(law_firm_id, vigencia=vigencia, empresa=empresa, grupo=grupo, cnpj=cnpj,
                  tipo=tipo, situacao=situacao, contestado=contestado,
                  cnpj_divergente=cnpj_divergente)
    blocos = svc.ranking(q, agrupar_por, ordenar_por, law_firm_id=law_firm_id)
    limite = clamp_limit(limite, 20)
    deslocamento = clamp_offset(deslocamento)
    pagina = [_contadores_json(b) for b in blocos[deslocamento:deslocamento + limite]]
    r = page_envelope(len(blocos), deslocamento, pagina)
    r["agrupado_por"] = agrupar_por
    r["ordenado_por"] = ordenar_por
    return r


def cruzamento_vigencias_calculo_fap_handler(
    law_firm_id: int,
    vigencia=None,
    empresa: str | None = None,
    grupo: str | None = None,
    cnpj: str | None = None,
    tipo=None,
    criterio: str | None = None,
    ordem: str | None = None,
    limite: int = 50,
    deslocamento: int = 0,
) -> dict:
    from app.services import fap_calculo_query_service as svc

    criterio = _escolha(criterio, svc.CRITERIOS_CRUZAMENTO, "criterio", "excluido")
    ordem = _ordem(ordem) or "total_pago"
    # O alvo é o que ainda conta e ninguém contestou nesta vigência.
    q = _consulta(law_firm_id, vigencia=vigencia, empresa=empresa, grupo=grupo, cnpj=cnpj,
                  tipo=tipo, situacao="conta", contestado=False)
    q = q.filter(svc.em_outra_vigencia_expr(law_firm_id, criterio))
    limite = clamp_limit(limite, 50)
    deslocamento = clamp_offset(deslocamento)

    resumo = svc.contadores(q, law_firm_id=law_firm_id)
    itens, total = svc.janela(q, deslocamento, limite, law_firm_id=law_firm_id, ordem=ordem)
    vigencias = svc.vigencias_do_item(law_firm_id, itens)
    saida = []
    for i in itens:
        d = _serializar(i)
        d["outras_vigencias"] = [v for v in vigencias.get((i["tipo"], i["identificador"]), [])
                                 if v["ano_vigencia"] != i["ano_vigencia"]]
        saida.append(d)
    r = page_envelope(total, deslocamento, saida)
    r["criterio"] = criterio
    r["total_pago"] = str(resumo["total_pago"])
    r["por_tipo"] = resumo["por_tipo"]
    return r


def detalhar_estabelecimento_calculo_fap_handler(law_firm_id: int, cnpj: str, vigencia=None) -> dict:
    from app.services import fap_calculo_query_service as svc
    from app.utils.cnpj import apenas_digitos

    digitos = apenas_digitos(cnpj or "")
    if len(digitos) < 9 or len(digitos) > 14:
        raise _tool_error(
            "Informe o CNPJ do estabelecimento (14 dígitos, com ou sem pontuação). Para a "
            "empresa inteira use ranking_calculo_fap com agrupar_por='estabelecimento'.")
    ano = _vigencia(vigencia)
    d = svc.estabelecimento(law_firm_id, digitos, ano)
    if d is None:
        return {"erro": f"Estabelecimento {cnpj} não encontrado no cálculo FAP sincronizado."}
    if d.get("sem_vigencia"):
        return {"erro": (f"Estabelecimento {cnpj} não encontrado no cálculo FAP de {ano}. "
                         f"Vigências com cálculo: {', '.join(map(str, d['vigencias_disponiveis']))}.")}
    d["contadores"] = _contadores_json(d["contadores"])
    for bloco in ("excluidos", "ausentes_no_calculo_atual"):
        d[bloco]["itens"] = [_serializar(i) for i in d[bloco]["itens"]]
    if isinstance(d.get("lido_em"), datetime):
        d["lido_em"] = d["lido_em"].isoformat()
    d["dica"] = ("Para todos os itens deste estabelecimento use listar_beneficios_calculo_fap "
                 f"com cnpj='{d['cnpj']}' e vigencia={d['ano_vigencia']}.")
    return d


def itens_do_segurado(law_firm_id: int, cpf: str | None, nit: str | None, limite: int = 30) -> dict:
    """Itens do cálculo de um segurado (CPF e/ou NIT), para o buscar_por_segurado."""
    from app.services import fap_calculo_query_service as svc

    q = _por_segurado(svc.filtrar(law_firm_id), cpf=cpf, nit=nit)
    itens, total = svc.pagina(q, 1, limite, law_firm_id=law_firm_id)
    return {"total": total, "itens": [_serializar(i) for i in itens]}
