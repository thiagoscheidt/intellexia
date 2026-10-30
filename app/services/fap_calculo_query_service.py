"""Consulta dos benefícios e CATs do cálculo FAP (``fap_calculo_itens``).

Fonte única da tela do Painel FAP e das tools do MCP. "Contestado" = mesmo
número **e mesma vigência** na Central: o mesmo NB em outra vigência não conta.
"""
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import Integer, and_, cast, exists, false, func, or_
from sqlalchemy.orm import aliased

from app.models import (
    Benefit, FapCalculoEstabelecimento as Estab, FapCalculoItem as Item, FapCompany, FapContestationCat,
    FapVigenciaCnpj, db,
)
from app.services import fap_group_service
from app.utils.cnpj import apenas_digitos, completar_zeros, cpf_valido, link_consulta_cpf_receita

TIPOS = ('B91', 'B92', 'B93', 'B94', 'CAT')
SITUACOES = ('conta', 'excluido')
_ESTADO = {'conta': 'ORIGINAL', 'excluido': 'EXCLUIDO'}
_SITUACAO_DO_ESTADO = {v: k for k, v in _ESTADO.items()}


def _igual_ano(coluna_texto, item=Item):
    # vigencia_year é string na Central; ano_vigencia é inteiro aqui. Compara
    # como número: CAST(inteiro AS CHAR) no MySQL usa a collation da conexão e
    # estoura "Illegal mix of collations" contra colunas utf8mb4_unicode_ci.
    return cast(coluna_texto, Integer) == item.ano_vigencia


def _benefit_match(law_firm_id, item=Item):
    return and_(
        Benefit.law_firm_id == law_firm_id,
        Benefit.benefit_number == item.identificador,
        Benefit.fap_vigencia_cnpj_id == FapVigenciaCnpj.id,
        _igual_ano(FapVigenciaCnpj.vigencia_year, item),
    )


def contestado_expr(law_firm_id, item=Item):
    """EXISTS booleano: o item existe na Central, na mesma vigência.

    ``item`` aceita um ``aliased(Item)``, para perguntar de outro item do
    cálculo dentro da mesma consulta (o cruzamento entre vigências).
    """
    benef = and_(item.tipo != 'CAT', exists().where(_benefit_match(law_firm_id, item)))
    cat = and_(item.tipo == 'CAT', exists().where(and_(
        FapContestationCat.law_firm_id == law_firm_id,
        FapContestationCat.cat_number == item.identificador,
        _igual_ano(FapContestationCat.vigencia_year, item),
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


def ausente_expr(law_firm_id, item=Item):
    """EXISTS: o item veio de um cálculo que não é mais o atual do estabelecimento."""
    return exists().where(and_(
        Estab.law_firm_id == law_firm_id,
        Estab.ano_vigencia == item.ano_vigencia,
        Estab.cnpj == item.cnpj,
        Estab.calculo_atual_id.isnot(None),
        item.calculo_id.isnot(None),
        item.calculo_id != Estab.calculo_atual_id,
    ))


def cnpj_divergente_expr(item=Item):
    """O portal atribuiu o item a um CNPJ diferente do original (possível erro de estabelecimento)."""
    return and_(item.cnpj_original.isnot(None), item.cnpj_atribuido.isnot(None),
                item.cnpj_original != '', item.cnpj_atribuido != '',
                item.cnpj_original != item.cnpj_atribuido)


def filtrar(law_firm_id, *, vigencia=None, raizes=None, grupo=None, cnpj=None,
            identificador=None, tipos=None, situacao=None, contestado=None,
            cpfs=None, cnpj_divergente=None, ausente=None, inicio_de=None, inicio_ate=None,
            cessacao_de=None, cessacao_ate=None, com_obito=None):
    """Query de ``FapCalculoItem`` do escritório, com os filtros dados.

    ``vigencia`` tem de ser conversível em int (quem chama valida). Filtro com
    valor inutilizável (sem dígitos, tipo ou situação desconhecidos) filtra para
    vazio, em vez de ignorar e mostrar tudo — mesma convenção de
    ``fap_group_service.group_condition``. ``cpfs`` é lista: vazia filtra para
    vazio (a busca por nome não achou ninguém); ``None`` não filtra.
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
    if cpfs is not None:
        q = q.filter(Item.cpf.in_(list(cpfs))) if cpfs else q.filter(false())
    if cnpj_divergente is not None:
        expr = cnpj_divergente_expr()
        q = q.filter(expr if cnpj_divergente else ~expr)
    if ausente is not None:
        expr = ausente_expr(law_firm_id)
        q = q.filter(expr if ausente else ~expr)
    for valor, condicao in ((inicio_de, lambda v: Item.data_inicio >= v),
                            (inicio_ate, lambda v: Item.data_inicio <= v),
                            (cessacao_de, lambda v: Item.data_cessacao >= v),
                            (cessacao_ate, lambda v: Item.data_cessacao <= v)):
        if valor:
            q = q.filter(condicao(valor))
    if com_obito is not None:
        q = q.filter(Item.data_obito.isnot(None) if com_obito else Item.data_obito.is_(None))
    return q


def _firm_id(query, law_firm_id=None):
    firm_id = law_firm_id or query.get_execution_options().get('fap_law_firm_id')
    if firm_id is None:
        raise ValueError(
            'Consulta sem escritório: monte a query com filtrar() '
            'ou passe law_firm_id.')
    return firm_id


def _novo_acumulador():
    return {
        'total': 0, 'por_tipo': {t: 0 for t in TIPOS}, 'conta': 0, 'excluidos': 0,
        'nao_contestados': 0, 'conta_nao_contestados': 0,
        'total_pago': Decimal('0'), 'total_pago_nao_contestado': Decimal('0'),
        'total_pago_excluido': Decimal('0'), 'total_pago_conta_nao_contestado': Decimal('0'),
        'cruzamento': {t: {s: {'contestado': 0, 'nao_contestado': 0} for s in SITUACOES}
                       for t in TIPOS},
    }


def _acumular(acc, tipo, estado, contestado, n, soma):
    soma = Decimal(str(soma or 0))
    acc['por_tipo'][tipo] = acc['por_tipo'].get(tipo, 0) + n
    acc['total'] += n
    acc['total_pago'] += soma
    if estado == 'EXCLUIDO':
        acc['excluidos'] += n
        acc['total_pago_excluido'] += soma
    elif estado == 'ORIGINAL':
        acc['conta'] += n
    if not contestado:
        acc['nao_contestados'] += n
        acc['total_pago_nao_contestado'] += soma
        if estado == 'ORIGINAL':
            acc['conta_nao_contestados'] += n
            acc['total_pago_conta_nao_contestado'] += soma
    situacao = _SITUACAO_DO_ESTADO.get(estado)
    if situacao and tipo in acc['cruzamento']:
        acc['cruzamento'][tipo][situacao]['contestado' if contestado else 'nao_contestado'] += n


def _fechar(acc):
    acc['contestados'] = acc['total'] - acc['nao_contestados']
    return acc


def _agrupado(query, firm_id, *chaves):
    """Linhas (chaves..., tipo, estado, contestado, n, soma) por um GROUP BY só.

    A expressão de contestado é por linha: calcula na subquery e agrupa por
    colunas simples (GROUP BY direto na expressão quebra only_full_group_by no MySQL).
    """
    cont = contestado_expr(firm_id).label('contestado')
    sub = query.order_by(None).with_entities(
        *[c.label(f'k{i}') for i, c in enumerate(chaves)],
        Item.tipo.label('tipo'), Item.estado_atual.label('estado'), cont,
        Item.total_pago.label('total_pago')).subquery()
    colunas = [getattr(sub.c, f'k{i}') for i in range(len(chaves))]
    return (db.session.query(*colunas, sub.c.tipo, sub.c.estado, sub.c.contestado, func.count(),
                             func.sum(sub.c.total_pago))
            .group_by(*colunas, sub.c.tipo, sub.c.estado, sub.c.contestado).all())


def contadores(query, *, law_firm_id=None):
    """Totais por um GROUP BY só (tipo, situação, contestado), sem carregar linhas.

    ``cruzamento``: {tipo: {'conta'|'excluido': {'contestado': n, 'nao_contestado': n}}}.
    Situação fora de ORIGINAL/EXCLUIDO entra nos totais, não no cruzamento.
    ``total_pago`` (e o recorte dos não contestados e dos excluídos) soma o
    ``total_pago`` dos benefícios; CAT não tem valor e entra como zero.
    ``conta_nao_contestados`` é o que ainda pesa no cálculo e ninguém contestou.
    """
    firm_id = _firm_id(query, law_firm_id)
    acc = _novo_acumulador()
    for linha in _agrupado(query, firm_id):
        _acumular(acc, *linha)
    return _fechar(acc)


AGRUPAMENTOS = ('empresa', 'estabelecimento', 'vigencia', 'grupo')
METRICAS = ('total', 'conta', 'excluidos', 'contestados', 'nao_contestados', 'conta_nao_contestados',
            'total_pago', 'total_pago_nao_contestado', 'total_pago_excluido',
            'total_pago_conta_nao_contestado')


def ranking(query, agrupar_por, ordenar_por='total_pago_conta_nao_contestado', *, law_firm_id=None):
    """Os mesmos contadores de ``contadores``, um bloco por empresa, estabelecimento,
    vigência ou grupo, do maior para o menor em ``ordenar_por``.

    Devolve a lista inteira (quem pagina é quem chama): por grupo a soma só fecha
    depois de juntar as raízes, então não dá para cortar no SQL. Raiz sem grupo
    entra em "Sem grupo".
    """
    if agrupar_por not in AGRUPAMENTOS:
        raise ValueError(agrupar_por)
    if ordenar_por not in METRICAS:
        raise ValueError(ordenar_por)
    firm_id = _firm_id(query, law_firm_id)
    chaves = {
        'empresa': (Item.cnpj_raiz,),
        'estabelecimento': (Item.cnpj, Item.cnpj_raiz),
        'vigencia': (Item.ano_vigencia,),
        'grupo': (Item.cnpj_raiz,),
    }[agrupar_por]
    grupos = fap_group_service.groups_by_root(firm_id) if agrupar_por == 'grupo' else {}

    blocos = {}
    for linha in _agrupado(query, firm_id, *chaves):
        k, resto = linha[:len(chaves)], linha[len(chaves):]
        if agrupar_por == 'grupo':
            g = grupos.get(k[0])
            chave = (g['chave'], g['nome']) if g else (fap_group_service.SEM_GRUPO, 'Sem grupo')
        else:
            chave = k
        if chave not in blocos:
            blocos[chave] = _novo_acumulador()
        _acumular(blocos[chave], *resto)

    raizes = {c[0] if agrupar_por == 'empresa' else c[1]
              for c in blocos if agrupar_por in ('empresa', 'estabelecimento')}
    nomes = {}
    if raizes:
        nomes = dict(db.session.query(FapCompany.cnpj, FapCompany.nome).filter(
            FapCompany.law_firm_id == firm_id, FapCompany.cnpj.in_(raizes)).all())

    saida = []
    for chave, acc in blocos.items():
        d = _fechar(acc)
        if agrupar_por == 'empresa':
            d = {'cnpj_raiz': chave[0], 'empresa_nome': nomes.get(chave[0]), **d}
        elif agrupar_por == 'estabelecimento':
            d = {'cnpj': chave[0], 'cnpj_raiz': chave[1], 'empresa_nome': nomes.get(chave[1]), **d}
        elif agrupar_por == 'vigencia':
            d = {'ano_vigencia': chave[0], **d}
        else:
            d = {'grupo_chave': chave[0], 'grupo_nome': chave[1], **d}
        saida.append(d)
    # Desempate pela chave, para a paginação nunca pular nem repetir bloco.
    saida.sort(key=lambda d: str(d.get('cnpj') or d.get('cnpj_raiz') or d.get('grupo_chave')
                                 or d.get('ano_vigencia')))
    saida.sort(key=lambda d: d[ordenar_por], reverse=True)
    return saida


_ORDEM_PADRAO = (Item.ano_vigencia.desc(), Item.cnpj, Item.tipo, Item.identificador, Item.id)
# Do maior para o menor; o vazio fica no fim nos dois bancos (NULL é o menor
# valor no MySQL e no SQLite). Sempre termina no id: carga em lote empata muito.
ORDENS = {
    'padrao': _ORDEM_PADRAO,
    'total_pago': (Item.total_pago.desc(), Item.id),
    'valor_mensal': (Item.valor_mensal.desc(), Item.id),
    'meses_contabilizacao': (Item.meses_contabilizacao.desc(), Item.id),
    'data_inicio': (Item.data_inicio.desc(), Item.id),
    'data_cessacao': (Item.data_cessacao.desc(), Item.id),
}


def _linhas(query, firm_id, offset, limite, ordem=None):
    return (
        query.order_by(None)
        .with_entities(
            Item,
            contestado_expr(firm_id).label('contestado'),
            _beneficio_central_id_expr(firm_id).label('central_id'),
            _cat_central_id_expr(firm_id).label('cat_id'),
        )
        .order_by(*ORDENS[ordem or 'padrao'])
        .offset(offset).limit(limite).all()
    )


def pagina(query, page, per_page=50, *, law_firm_id=None):
    """Uma página de itens (dicts). ``per_page`` é limitado a 200."""
    firm_id = _firm_id(query, law_firm_id)
    per_page = max(1, min(int(per_page), 200))
    total = query.order_by(None).count()
    linhas = _linhas(query, firm_id, max(page - 1, 0) * per_page, per_page)
    return _montar(linhas, firm_id), total


def janela(query, deslocamento, limite, *, law_firm_id=None, ordem=None):
    """Itens de ``deslocamento`` a ``deslocamento + limite`` (dicts) e o total.

    Para o MCP e a API, que paginam por deslocamento. Sem o teto de 200 da
    ``pagina``: quem chama já limitou o tamanho — montar a janela com duas
    ``pagina`` cortadas em 200 devolvia, com limite maior, linhas de outra
    posição sem avisar.
    """
    firm_id = _firm_id(query, law_firm_id)
    total = query.order_by(None).count()
    linhas = _linhas(query, firm_id, max(int(deslocamento), 0), max(int(limite), 1), ordem)
    return _montar(linhas, firm_id), total


def todos(query, *, law_firm_id=None, lote=1000, ordem=None):
    """Todos os itens do filtro, na ordem da tela, em lotes — para a planilha.

    Mesma montagem da ``pagina`` (nome revelado, contestado, cálculo atual),
    então a planilha nunca diverge do que a tela mostra.
    """
    firm_id = _firm_id(query, law_firm_id)
    offset = 0
    while True:
        linhas = _linhas(query, firm_id, offset, lote, ordem)
        if not linhas:
            return
        yield from _montar(linhas, firm_id)
        if len(linhas) < lote:
            return
        offset += lote


def _montar(linhas, firm_id):
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

    from app.services import segurado_nome_service
    revelados = segurado_nome_service.nomes_conhecidos(firm_id, [linha[0].cpf for linha in linhas])

    itens = []
    for item, contestado, central_id, cat_id in linhas:
        d = {c.name: getattr(item, c.name) for c in Item.__table__.columns
             if c.name != 'raw_json'}
        d['empresa_nome'] = nomes.get(item.cnpj_raiz)
        d['consulta_cpf_receita'] = link_consulta_cpf_receita(item.cpf, item.data_nascimento)
        # O FAP não informa nome: só existe o que alguém revelou pela consulta de CPF.
        d['nome_revelado'] = revelados.get(item.cpf or '')
        d['segurado_nome'] = (d['nome_revelado'] or {}).get('nome')
        d['cpf_revelavel'] = cpf_valido(item.cpf)
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
    return itens


# ── Cruzamento entre vigências ───────────────────────────────────────────────
# O período-base de vigências vizinhas se sobrepõe, então o mesmo benefício
# entra em mais de um cálculo. Excluído numa vigência (contestação ganha) e
# ainda contando, sem contestação, em outra é o candidato mais forte a contestar.

CRITERIOS_CRUZAMENTO = ('excluido', 'contestado', 'qualquer')


def em_outra_vigencia_expr(law_firm_id, criterio='excluido'):
    """EXISTS: o mesmo número (e tipo) está excluído/contestado em outra vigência."""
    if criterio not in CRITERIOS_CRUZAMENTO:
        raise ValueError(criterio)
    outro = aliased(Item)
    excluido = outro.estado_atual == 'EXCLUIDO'
    contestado = contestado_expr(law_firm_id, outro)
    marca = {'excluido': excluido, 'contestado': contestado,
             'qualquer': or_(excluido, contestado)}[criterio]
    return exists().where(and_(
        outro.law_firm_id == law_firm_id,
        outro.tipo == Item.tipo,
        outro.identificador == Item.identificador,
        outro.ano_vigencia != Item.ano_vigencia,
        marca,
    ))


def vigencias_do_item(law_firm_id, itens):
    """{(tipo, identificador): [situação do mesmo número em cada vigência]}."""
    numeros = {i['identificador'] for i in itens if i.get('identificador')}
    if not numeros:
        return {}
    linhas = (Item.query.filter(Item.law_firm_id == law_firm_id, Item.identificador.in_(numeros))
              .with_entities(Item.tipo, Item.identificador, Item.ano_vigencia, Item.cnpj,
                             Item.estado_atual, contestado_expr(law_firm_id).label('contestado'))
              .order_by(Item.ano_vigencia.desc(), Item.id).all())
    saida = {}
    for tipo, numero, ano, cnpj, estado, contestado in linhas:
        saida.setdefault((tipo, numero), []).append({
            'ano_vigencia': ano, 'cnpj': cnpj, 'estado_atual': estado,
            'situacao': _SITUACAO_DO_ESTADO.get(estado), 'contestado': bool(contestado),
        })
    return saida


# ── Estabelecimento ──────────────────────────────────────────────────────────

_CAMPOS_RESUMIDOS = ('id', 'tipo', 'identificador', 'cpf', 'nit', 'segurado_nome', 'total_pago',
                     'data_inicio', 'data_cessacao', 'estado_original', 'estado_atual', 'calculo_id',
                     'contestado', 'beneficio_central_id', 'cat_central_id')


def _resumido(d):
    return {k: d.get(k) for k in _CAMPOS_RESUMIDOS}


def estabelecimento(law_firm_id, cnpj, vigencia=None, limite_itens=50):
    """Um estabelecimento numa vigência: cálculo atual e original, protocolo,
    histórico de recálculos, contadores e os itens excluídos e os que saíram
    do cálculo atual. Sem ``vigencia``, a mais recente. ``None`` se não houver.
    """
    cnpj = completar_zeros(apenas_digitos(cnpj), 14)
    registros = (Estab.query.filter_by(law_firm_id=law_firm_id, cnpj=cnpj)
                 .order_by(Estab.ano_vigencia.desc()).all())
    anos_itens = [a for (a,) in db.session.query(Item.ano_vigencia).filter(
        Item.law_firm_id == law_firm_id, Item.cnpj == cnpj).distinct()]
    anos = sorted({r.ano_vigencia for r in registros} | set(anos_itens), reverse=True)
    if not anos:
        return None
    ano = int(vigencia) if vigencia else anos[0]
    if ano not in anos:
        return {'cnpj': cnpj, 'ano_vigencia': ano, 'vigencias_disponiveis': anos, 'sem_vigencia': True}
    e = next((r for r in registros if r.ano_vigencia == ano), None)

    nome = (db.session.query(FapCompany.nome)
            .filter(FapCompany.law_firm_id == law_firm_id, FapCompany.cnpj == cnpj[:8]).scalar())
    base = filtrar(law_firm_id, vigencia=ano, cnpj=cnpj)

    def _bloco(query):
        itens, total = janela(query, 0, limite_itens, law_firm_id=law_firm_id, ordem='total_pago')
        return {'total': total, 'itens': [_resumido(i) for i in itens]}

    return {
        'cnpj': cnpj,
        'cnpj_raiz': cnpj[:8],
        'empresa_nome': nome,
        'ano_vigencia': ano,
        'vigencias_disponiveis': anos,
        'situacao': e.situacao if e else None,
        'lido_em': e.synced_at if e else None,
        'calculo_atual': ({'id': e.calculo_atual_id, 'tipo': e.calculo_atual_tipo,
                           'rotulo': rotulo_calculo(e.calculo_atual_tipo) if e.calculo_atual_tipo else None,
                           'data': _data_br(e.calculo_atual_data)}
                          if e and e.calculo_atual_id else None),
        'calculo_original_id': e.calculo_original_id if e else None,
        'recalculado': bool(e and e.calculo_atual_id and e.calculo_original_id
                            and e.calculo_atual_id != e.calculo_original_id),
        'protocolo': e.protocolo if e else None,
        'historico': _historico(e.historico_json) if e else [],
        'contadores': contadores(base, law_firm_id=law_firm_id),
        'excluidos': _bloco(filtrar(law_firm_id, vigencia=ano, cnpj=cnpj, situacao='excluido')),
        'ausentes_no_calculo_atual': _bloco(filtrar(law_firm_id, vigencia=ano, cnpj=cnpj, ausente=True)),
    }
