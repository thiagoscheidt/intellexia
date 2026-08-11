"""
Filtro de vigência (ano do FAP) — fonte única das telas do Painel de Contestações.

A vigência é o recorte mais importante do FAP Web, então nas telas ela é uma
caixa própria em vez de ficar enterrada no filtro genérico de campos.

Duas regras que valem para todas as telas e que só existem aqui:

- **As opções são os anos que a tela realmente tem**, não um range fixo. Um
  select que oferece 2013 numa tela sem nada em 2013 só produz busca vazia.
- **O padrão é o ano mais recente com dados**, não ``datetime.now().year``.
  Fixar o ano do calendário faria a tela abrir vazia em janeiro, antes de a
  vigência nova ser sincronizada.

Cada entidade guarda o ano de um jeito diferente, e é isso que este módulo
esconde das telas:

- ``FapContestationCat`` e irmãs: coluna ``vigencia_year`` (String) na própria
  tabela, indexada. Filtrar por ela alcança inclusive as linhas em que
  ``vigencia_id`` ficou nulo.
- ``Benefit``: não tem coluna de ano. Tem ``fap_vigencia_cnpj_id`` (FK) e
  ``fap_vigencia_years`` (CSV legado). Vamos pela FK — nos dados reais ela está
  100% preenchida, enquanto o CSV exigiria ``LIKE`` com risco de falso
  positivo ("2021" casando dentro de "12021").
"""

from sqlalchemy import false

from app.models import db

# Valor do select que desliga o filtro. Espelha o "__all__" já usado no
# Painel FAP › Contestações, para os dois se comportarem igual.
TODAS = '__all__'


def normalize_year(valor):
    """Entrada do filtro → ano como string, ou '' quando não é um ano."""
    texto = str(valor or '').strip()
    if not texto or texto == TODAS:
        return ''
    digitos = ''.join(ch for ch in texto if ch.isdigit())
    return digitos if len(digitos) == 4 else ''


def available_years(law_firm_id, coluna, law_firm_column):
    """Anos distintos existentes na tabela, do mais recente para o mais antigo.

    ``coluna`` é a coluna de ano da entidade (String em todas as tabelas de
    contestação). A ordenação é numérica para não cair na ordem alfabética.
    """
    linhas = (
        db.session.query(coluna)
        .filter(law_firm_column == law_firm_id, coluna.isnot(None), coluna != '')
        .distinct()
        .all()
    )
    anos = {str(valor).strip() for (valor,) in linhas if str(valor or '').strip()}
    return sorted((a for a in anos if a.isdigit()), key=int, reverse=True)


def benefit_available_years(law_firm_id):
    """Anos de vigência dos benefícios, resolvidos pela FK (não pelo CSV legado)."""
    from app.models import Benefit, FapVigenciaCnpj

    linhas = (
        db.session.query(FapVigenciaCnpj.vigencia_year)
        .join(Benefit, Benefit.fap_vigencia_cnpj_id == FapVigenciaCnpj.id)
        .filter(Benefit.law_firm_id == law_firm_id)
        .distinct()
        .all()
    )
    anos = {str(valor).strip() for (valor,) in linhas if str(valor or '').strip()}
    return sorted((a for a in anos if a.isdigit()), key=int, reverse=True)


def default_year(anos_disponiveis):
    """Ano que a tela abre selecionado: o mais recente que existe.

    Devolve ``TODAS`` quando não há nenhum — sem dados, o certo é não esconder
    nada atrás de um filtro que a pessoa não escolheu.
    """
    return anos_disponiveis[0] if anos_disponiveis else TODAS


def resolve_selected(valor_recebido, anos_disponiveis, *, ausente=False):
    """Valor que o select deve mostrar.

    ``ausente=True`` (parâmetro não veio na URL) aplica o padrão. Se o usuário
    escolheu explicitamente, respeitamos — inclusive "Todas".
    """
    if ausente:
        return default_year(anos_disponiveis)
    texto = str(valor_recebido or '').strip()
    return texto or TODAS


def year_condition(ano, coluna, *, coluna_e_inteiro=False):
    """Condição SQLAlchemy do recorte por vigência, ou ``None`` para não filtrar.

    ``coluna_e_inteiro`` para ``FapWebContestacao.ano_vigencia``, o único ano
    guardado como Integer; nas demais tabelas o ano é String(10).
    """
    ano_limpo = normalize_year(ano)
    if not ano_limpo:
        return None
    if coluna_e_inteiro:
        return coluna == int(ano_limpo)
    return coluna == ano_limpo


def apply_year_filter(query, ano, coluna, *, coluna_e_inteiro=False):
    """Aplica o recorte por vigência numa query. Ver ``year_condition``."""
    condicao = year_condition(ano, coluna, coluna_e_inteiro=coluna_e_inteiro)
    if condicao is None:
        return query
    return query.filter(condicao)


def apply_benefit_year_filter(query, ano, law_firm_id):
    """Recorta benefícios por vigência, resolvendo pela FK.

    Sem coluna de ano em ``benefits``, o caminho é traduzir o ano para os ids
    de ``fap_vigencia_cnpjs`` e filtrar pela FK — indexada e exata. Ano sem
    nenhuma vigência correspondente filtra para vazio, em vez de ignorar o
    filtro e fazer a tela parecer que o ano tem todos os benefícios.
    """
    from app.models import Benefit, FapVigenciaCnpj

    ano_limpo = normalize_year(ano)
    if not ano_limpo:
        return query

    ids = [
        vid for (vid,) in
        db.session.query(FapVigenciaCnpj.id)
        .filter(
            FapVigenciaCnpj.law_firm_id == law_firm_id,
            FapVigenciaCnpj.vigencia_year == ano_limpo,
        )
        .all()
    ]
    if not ids:
        return query.filter(false())
    return query.filter(Benefit.fap_vigencia_cnpj_id.in_(ids))
