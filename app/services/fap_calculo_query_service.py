"""Consulta dos benefícios e CATs do cálculo FAP (``fap_calculo_itens``).

Fonte única da tela do Painel FAP e das tools do MCP. "Contestado" = mesmo
número **e mesma vigência** na Central: o mesmo NB em outra vigência não conta.
"""
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import Integer, and_, cast, exists, false, func, or_

from app.models import (
    Benefit, FapCalculoEstabelecimento as Estab, FapCalculoItem as Item, FapCompany, FapContestationCat,
    FapVigenciaCnpj, db,
)
from app.services import fap_group_service
from app.utils.cnpj import apenas_digitos, completar_zeros, link_consulta_cpf_receita

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


def _cat_central_id_expr(law_firm_id):
    return (
        db.select(func.min(FapContestationCat.id))
        .where(Item.tipo == 'CAT',
               FapContestationCat.law_firm_id == law_firm_id,
               FapContestationCat.cat_number == Item.identificador,
               _igual_ano(FapContestationCat.vigencia_year))
        .correlate(Item)
        .scalar_subquery()
    )


ROTULOS_CALCULO = {
    'CALCULO_ORIGINAL': 'Cálculo original',
    'RECALCULO_ELETRONICO_PRIMEIRA_INSTANCIA': 'Recálculo 1ª instância',
    'RECALCULO_ELETRONICO_SEGUNDA_INSTANCIA': 'Recálculo 2ª instância',
}


def rotulo_calculo(tipo):
    return ROTULOS_CALCULO.get(tipo, tipo)


def _data_br(valor):
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10]).strftime('%d/%m/%Y')
    except ValueError:
        return str(valor)


def _historico(texto):
    try:
        lista = json.loads(texto) if texto else []
    except ValueError:
        return []
    out = []
    for h in lista if isinstance(lista, list) else []:
        if isinstance(h, dict):
            out.append({'id': h.get('id'), 'tipo': h.get('tipo'),
                        'rotulo': rotulo_calculo(h.get('tipo')), 'data': _data_br(h.get('data'))})
    return out


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
        if not digitos:
            q = q.filter(false())
        elif len(digitos) <= 8:  # raiz (8 dígitos): todos os estabelecimentos dela
            q = q.filter(Item.cnpj_raiz == completar_zeros(digitos, 8))
        else:
            q = q.filter(Item.cnpj == completar_zeros(digitos, 14))
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
    ``total_pago`` (e o recorte dos não contestados e dos excluídos) soma o
    ``total_pago`` dos benefícios; CAT não tem valor e entra como zero.
    """
    firm_id = _firm_id(query, law_firm_id)
    cont = contestado_expr(firm_id).label('contestado')
    por_tipo = {t: 0 for t in TIPOS}
    cruzamento = {t: {s: {'contestado': 0, 'nao_contestado': 0} for s in SITUACOES}
                  for t in TIPOS}
    estado_para_situacao = {v: k for k, v in _ESTADO.items()}
    total = excluidos = nao_contestados = 0
    pago = pago_nao_contestado = pago_excluido = Decimal('0')
    # A expressão é por linha: calcula na subquery e agrupa por colunas simples
    # (GROUP BY direto na expressão quebra only_full_group_by no MySQL).
    sub = query.order_by(None).with_entities(
        Item.tipo.label('tipo'), Item.estado_atual.label('estado'), cont,
        Item.total_pago.label('total_pago')).subquery()
    linhas = (db.session.query(sub.c.tipo, sub.c.estado, sub.c.contestado, func.count(),
                               func.sum(sub.c.total_pago))
              .group_by(sub.c.tipo, sub.c.estado, sub.c.contestado).all())
    for tipo, estado, contestado, n, soma in linhas:
        soma = Decimal(str(soma or 0))
        por_tipo[tipo] = por_tipo.get(tipo, 0) + n
        total += n
        pago += soma
        if estado == 'EXCLUIDO':
            excluidos += n
            pago_excluido += soma
        if not contestado:
            nao_contestados += n
            pago_nao_contestado += soma
        situacao = estado_para_situacao.get(estado)
        if situacao and tipo in cruzamento:
            cruzamento[tipo][situacao]['contestado' if contestado else 'nao_contestado'] += n
    return {'total': total, 'por_tipo': por_tipo, 'excluidos': excluidos,
            'nao_contestados': nao_contestados, 'contestados': total - nao_contestados,
            'total_pago': pago, 'total_pago_nao_contestado': pago_nao_contestado,
            'total_pago_excluido': pago_excluido, 'cruzamento': cruzamento}


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
            _cat_central_id_expr(firm_id).label('cat_id'),
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

    estabs = {}
    if linhas:
        for e in Estab.query.filter(
                Estab.law_firm_id == firm_id,
                Estab.cnpj.in_({linha[0].cnpj for linha in linhas}),
                Estab.ano_vigencia.in_({linha[0].ano_vigencia for linha in linhas})).all():
            estabs[(e.ano_vigencia, e.cnpj)] = e

    itens = []
    for item, contestado, central_id, cat_id in linhas:
        d = {c.name: getattr(item, c.name) for c in Item.__table__.columns
             if c.name != 'raw_json'}
        d['empresa_nome'] = nomes.get(item.cnpj_raiz)
        d['consulta_cpf_receita'] = link_consulta_cpf_receita(item.cpf, item.data_nascimento)
        d['contestado'] = bool(contestado)
        d['beneficio_central_id'] = (
            central_id if contestado and item.tipo != 'CAT' else None)
        d['cat_central_id'] = cat_id if contestado and item.tipo == 'CAT' else None
        e = estabs.get((item.ano_vigencia, item.cnpj))
        d['calculo_tipo'] = rotulo_calculo(e.calculo_atual_tipo) if e and e.calculo_atual_tipo else None
        d['calculo_data'] = e.calculo_atual_data if e else None
        d['protocolo'] = e.protocolo if e else None
        d['historico'] = _historico(e.historico_json) if e else []
        d['ausente_no_calculo_atual'] = bool(
            e and e.calculo_atual_id and item.calculo_id
            and item.calculo_id != e.calculo_atual_id)
        itens.append(d)
    return itens, total
