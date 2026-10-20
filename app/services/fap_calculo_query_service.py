"""Consulta dos benefícios e CATs do cálculo FAP (``fap_calculo_itens``).

Fonte única da tela do Painel FAP e das tools do MCP. "Contestado" = mesmo
número **e mesma vigência** na Central: o mesmo NB em outra vigência não conta.
"""
from sqlalchemy import Integer, and_, cast, exists, func, or_

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
        if digitos:
            q = q.filter(Item.cnpj == completar_zeros(digitos, 14))
    if identificador:
        digitos = apenas_digitos(identificador)
        if digitos:
            if len(digitos) <= 11:
                q = q.filter(or_(
                    Item.cpf == completar_zeros(digitos, 11),
                    Item.nit == digitos,
                    Item.identificador == digitos,
                ))
            else:
                q = q.filter(or_(Item.identificador == digitos, Item.nit == digitos))
    if tipos:
        q = q.filter(Item.tipo.in_([t.upper() for t in tipos]))
    if situacao in _ESTADO:
        q = q.filter(Item.estado_atual == _ESTADO[situacao])
    if contestado is not None:
        expr = contestado_expr(law_firm_id)
        q = q.filter(expr if contestado else ~expr)
    return q


def _firm_id(query):
    return query._execution_options.get('fap_law_firm_id')


def contadores(query):
    """Totais por GROUP BY, sem carregar linhas."""
    base = query.order_by(None)
    por_tipo = {t: 0 for t in TIPOS}
    total = excluidos = 0
    for tipo, estado, n in base.with_entities(
            Item.tipo, Item.estado_atual, func.count()).group_by(
            Item.tipo, Item.estado_atual).all():
        por_tipo[tipo] = por_tipo.get(tipo, 0) + n
        total += n
        if estado == 'EXCLUIDO':
            excluidos += n
    nao_contestados = base.filter(~contestado_expr(_firm_id(query))).count()
    return {'total': total, 'por_tipo': por_tipo, 'excluidos': excluidos,
            'nao_contestados': nao_contestados}


def pagina(query, page, per_page=50):
    firm_id = _firm_id(query)
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
