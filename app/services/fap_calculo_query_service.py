"""Consulta dos benefícios e CATs do cálculo FAP (``fap_calculo_itens``).

Fonte única da tela do Painel FAP e das tools do MCP. "Contestado" = mesmo
número **e mesma vigência** na Central: o mesmo NB em outra vigência não conta.
"""
from sqlalchemy import Integer, and_, cast, exists, false, func, or_

from app.models import (
    Benefit, FapCalculoItem as Item, FapCompany, FapContestationCat,
    FapVigenciaCnpj, db,
)
from app.services import fap_group_service
from app.utils.cnpj import apenas_digitos, completar_zeros

TIPOS = ('B91', 'B92', 'B93', 'B94', 'CAT')
SITUACOES = ('conta', 'excluido')
_ESTADO = {'conta': 'ORIGINAL', 'excluido': 'EXCLUIDO'}


def _igual_ano(coluna_texto):
    # vigencia_year é string na Central; ano_vigencia é inteiro aqui. Compara
    # como número: CAST(inteiro AS CHAR) no MySQL usa a collation da conexão e
    # estoura "Illegal mix of collations" contra colunas utf8mb4_unicode_ci.
    return cast(coluna_texto, Integer) == Item.ano_vigencia


def _benefit_match(law_firm_id):
    return and_(
        Benefit.law_firm_id == law_firm_id,
        Benefit.benefit_number == Item.identificador,
        Benefit.fap_vigencia_cnpj_id == FapVigenciaCnpj.id,
        _igual_ano(FapVigenciaCnpj.vigencia_year),
    )


def contestado_expr(law_firm_id):
    """EXISTS booleano: o item existe na Central, na mesma vigência."""
    benef = and_(Item.tipo != 'CAT', exists().where(_benefit_match(law_firm_id)))
    cat = and_(Item.tipo == 'CAT', exists().where(and_(
        FapContestationCat.law_firm_id == law_firm_id,
        FapContestationCat.cat_number == Item.identificador,
        _igual_ano(FapContestationCat.vigencia_year),
    )))
    return or_(benef, cat)


def _beneficio_central_id_expr(law_firm_id):
    return (
        db.select(func.min(Benefit.id))
        .where(Item.tipo != 'CAT', _benefit_match(law_firm_id))
        .correlate(Item)
        .scalar_subquery()
    )


def filtrar(law_firm_id, *, vigencia=None, raizes=None, grupo=None, cnpj=None,
            identificador=None, tipos=None, situacao=None, contestado=None):
    """Query de ``FapCalculoItem`` do escritório, com os filtros dados.

    ``vigencia`` tem de ser conversível em int (quem chama valida). Filtro com
    valor inutilizável (sem dígitos, tipo ou situação desconhecidos) filtra para
    vazio, em vez de ignorar e mostrar tudo — mesma convenção de
    ``fap_group_service.group_condition``.
    """
    # O escritório vai junto na query (execution option) para contadores/pagina.
    q = Item.query.filter(Item.law_firm_id == law_firm_id).execution_options(
        fap_law_firm_id=law_firm_id)
    if vigencia:
        q = q.filter(Item.ano_vigencia == int(vigencia))
    if raizes:
        q = q.filter(Item.cnpj_raiz.in_([completar_zeros(r, 8) for r in raizes]))
    if grupo:
        q = fap_group_service.apply_group_filter(
            q, law_firm_id, grupo, Item.cnpj_raiz, coluna_e_raiz=True)
    if cnpj:
        digitos = apenas_digitos(cnpj)
        q = q.filter(Item.cnpj == completar_zeros(digitos, 14)) if digitos else q.filter(false())
    if identificador:
        digitos = apenas_digitos(identificador)
        if not digitos:
            q = q.filter(false())
        elif len(digitos) <= 11:
            q = q.filter(or_(
                Item.cpf == completar_zeros(digitos, 11),
                Item.nit == digitos,
                Item.identificador == digitos,
            ))
        else:
            q = q.filter(or_(Item.identificador == digitos, Item.nit == digitos))
    if tipos:
        validos = [t.upper() for t in tipos if t and t.upper() in TIPOS]
        q = q.filter(Item.tipo.in_(validos)) if validos else q.filter(false())
    if situacao:
        if situacao in _ESTADO:
            q = q.filter(Item.estado_atual == _ESTADO[situacao])
        else:
            q = q.filter(false())
    if contestado is not None:
        expr = contestado_expr(law_firm_id)
        q = q.filter(expr if contestado else ~expr)
    return q


def _firm_id(query, law_firm_id=None):
    firm_id = law_firm_id or query.get_execution_options().get('fap_law_firm_id')
    if firm_id is None:
        raise ValueError(
            'Consulta sem escritório: monte a query com filtrar() '
            'ou passe law_firm_id.')
    return firm_id


def contadores(query, *, law_firm_id=None):
    """Totais por um GROUP BY só (tipo, situação, contestado), sem carregar linhas.

    ``cruzamento``: {tipo: {'conta'|'excluido': {'contestado': n, 'nao_contestado': n}}}.
    Situação fora de ORIGINAL/EXCLUIDO entra nos totais, não no cruzamento.
    """
    firm_id = _firm_id(query, law_firm_id)
    cont = contestado_expr(firm_id).label('contestado')
    por_tipo = {t: 0 for t in TIPOS}
    cruzamento = {t: {s: {'contestado': 0, 'nao_contestado': 0} for s in SITUACOES}
                  for t in TIPOS}
    estado_para_situacao = {v: k for k, v in _ESTADO.items()}
    total = excluidos = nao_contestados = 0
    # A expressão é por linha: calcula na subquery e agrupa por colunas simples
    # (GROUP BY direto na expressão quebra only_full_group_by no MySQL).
    sub = query.order_by(None).with_entities(
        Item.tipo.label('tipo'), Item.estado_atual.label('estado'), cont).subquery()
    linhas = (db.session.query(sub.c.tipo, sub.c.estado, sub.c.contestado, func.count())
              .group_by(sub.c.tipo, sub.c.estado, sub.c.contestado).all())
    for tipo, estado, contestado, n in linhas:
        por_tipo[tipo] = por_tipo.get(tipo, 0) + n
        total += n
        if estado == 'EXCLUIDO':
            excluidos += n
        if not contestado:
            nao_contestados += n
        situacao = estado_para_situacao.get(estado)
        if situacao and tipo in cruzamento:
            cruzamento[tipo][situacao]['contestado' if contestado else 'nao_contestado'] += n
    return {'total': total, 'por_tipo': por_tipo, 'excluidos': excluidos,
            'nao_contestados': nao_contestados, 'cruzamento': cruzamento}


def pagina(query, page, per_page=50, *, law_firm_id=None):
    """Uma página de itens (dicts). ``per_page`` é limitado a 200."""
    firm_id = _firm_id(query, law_firm_id)
    per_page = max(1, min(int(per_page), 200))
    total = query.order_by(None).count()
    linhas = (
        query.order_by(None)
        .with_entities(
            Item,
            contestado_expr(firm_id).label('contestado'),
            _beneficio_central_id_expr(firm_id).label('central_id'),
        )
        .order_by(Item.ano_vigencia.desc(), Item.cnpj, Item.tipo,
                  Item.identificador, Item.id)
        .offset(max(page - 1, 0) * per_page).limit(per_page).all()
    )

    raizes = {linha[0].cnpj_raiz for linha in linhas}
    nomes = {}
    if raizes:
        nomes = dict(
            db.session.query(FapCompany.cnpj, FapCompany.nome).filter(
                FapCompany.law_firm_id == firm_id, FapCompany.cnpj.in_(raizes)).all())

    itens = []
    for item, contestado, central_id in linhas:
        d = {c.name: getattr(item, c.name) for c in Item.__table__.columns
             if c.name != 'raw_json'}
        d['empresa_nome'] = nomes.get(item.cnpj_raiz)
        d['contestado'] = bool(contestado)
        d['beneficio_central_id'] = (
            central_id if contestado and item.tipo != 'CAT' else None)
        itens.append(d)
    return itens, total
