"""
A edição do dia do DOU — sumário por órgão e cobertura da captura.

Fonte única da tela da edição (``/dou/edicao/<data>`` e o leitor) e das tools
``ultimas_edicoes_dou`` / ``sumario_edicao_dou`` do MCP: o sumário que a IA
descreve é o mesmo que a pessoa vê na tela.

Órgão é sempre recortado na **raiz** da hierarquia (``orgao_raiz``): a
hierarquia completa tem ~104 valores por seção contra ~27 raízes.
"""
from sqlalchemy import func

from app.models import DouArticle, DouEdition, db
from app.services.dou_search_service import orgao_raiz

SECAO_LABELS = {
    'DO1': 'Seção 1', 'DO2': 'Seção 2', 'DO3': 'Seção 3',
    'DO1E': 'Seção 1 — Extra', 'DO2E': 'Seção 2 — Extra', 'DO3E': 'Seção 3 — Extra',
}


def orgaos_da_secao(edition_id):
    """Órgãos-raiz da seção com a contagem de matérias, do maior para o menor.

    A agregação é em Python porque cortar na barra dentro do SQL não é
    portável entre SQLite e MySQL — e são ~100 linhas, não uma varredura.
    """
    linhas = (db.session.query(DouArticle.orgao_hierarquia, func.count())
              .filter(DouArticle.edition_id == edition_id)
              .group_by(DouArticle.orgao_hierarquia).all())
    totais = {}
    for hierarquia, qtd in linhas:
        raiz = orgao_raiz(hierarquia)
        if raiz:
            totais[raiz] = totais.get(raiz, 0) + qtd
    return sorted(totais.items(), key=lambda item: (-item[1], item[0]))


def sumario_da_edicao(edition_id):
    """``[(órgão-raiz, primeira página)]`` da seção, na ordem das páginas.

    É o "Sumário da Edição" do portal da Imprensa Nacional, reconstruído do
    nosso acervo. Conferido contra o deles na Seção 1 de 10/08/2026: as mesmas
    23 raízes, nas mesmas páginas (Agricultura 1, Comunicações 4, Cultura 7,
    Defesa 14, Fazenda 23...).
    """
    linhas = (db.session.query(DouArticle.orgao_hierarquia,
                               func.min(DouArticle.pagina_num))
              .filter(DouArticle.edition_id == edition_id,
                      DouArticle.pagina_num.isnot(None))
              .group_by(DouArticle.orgao_hierarquia).all())
    primeira = {}
    for hierarquia, pagina in linhas:
        raiz = orgao_raiz(hierarquia)
        if raiz:
            primeira[raiz] = min(primeira.get(raiz, pagina), pagina)
    return sorted(primeira.items(), key=lambda item: (item[1], item[0]))


def sumario_com_contagem(edition_id):
    """Sumário e contagem juntos: ``[{orgao, primeira_pagina, materias}]``.

    Na ordem das páginas, como o sumário; órgão sem página conhecida (seções
    extras às vezes vêm sem) vai para o fim, ordenado pelo volume.
    """
    paginas = dict(sumario_da_edicao(edition_id))
    itens = [{'orgao': orgao, 'primeira_pagina': paginas.get(orgao), 'materias': qtd}
             for orgao, qtd in orgaos_da_secao(edition_id)]
    return sorted(itens, key=lambda i: (i['primeira_pagina'] is None,
                                        i['primeira_pagina'] or 0, -i['materias'], i['orgao']))


def tipos_da_secao(edition_id, limite=10):
    """``[(tipo de ato, qtd)]`` da seção, do mais frequente."""
    return (db.session.query(DouArticle.art_type, func.count())
            .filter(DouArticle.edition_id == edition_id, DouArticle.art_type.isnot(None))
            .group_by(DouArticle.art_type)
            .order_by(func.count().desc(), DouArticle.art_type)
            .limit(limite).all())


def ultimas_datas(quantas=5):
    """As últimas ``quantas`` datas com alguma seção processada, da mais recente."""
    linhas = (db.session.query(DouEdition.data_publicacao)
              .filter(DouEdition.status == DouEdition.STATUS_PARSED)
              .distinct()
              .order_by(DouEdition.data_publicacao.desc())
              .limit(max(quantas, 1)).all())
    return [d for (d,) in linhas]


def periodo_do_acervo():
    """``(primeira, última)`` data com edição processada, ou ``(None, None)``."""
    linha = (db.session.query(func.min(DouEdition.data_publicacao),
                              func.max(DouEdition.data_publicacao))
             .filter(DouEdition.status == DouEdition.STATUS_PARSED).first())
    return (linha[0], linha[1]) if linha else (None, None)
