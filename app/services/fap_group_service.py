"""
Grupos empresariais do FAP — fonte única de opções, filtro e cadastro.

Um grupo reúne várias empresas outorgantes: ADSERVI, por exemplo, tem ~15 CNPJs
raiz distintos. O mapeamento CNPJ raiz → grupo vive em ``FapCompanyGroup``,
alimentado por planilha do escritório ou pelo cadastro manual da tela de
Empresas Sincronizadas.

Antes disto, o filtro "Grupo Empresarial" do Disputes Center chamava de "grupo"
uma empresa outorgante só — era um segundo filtro de CNPJ raiz com outro rótulo.

As telas nunca montam esse filtro na mão: só este módulo sabe que o banco guarda
CNPJ em dois formatos (``cnpj_raiz`` com 8 dígitos limpos e ``employer_cnpj``
ora mascarado, ora só dígitos).
"""

import unicodedata

from sqlalchemy import String, cast, false, func, or_

from app.models import db, FapCompanyGroup

# Valor do filtro que recorta as empresas ainda não mapeadas. Sem essa opção,
# uma sincronização que traga empresas novas as tornaria invisíveis a qualquer
# recorte por grupo, e ninguém perceberia que falta cadastrá-las.
SEM_GRUPO = '__sem_grupo__'
SEM_GRUPO_LABEL = '— Sem grupo —'

ORIGEM_PLANILHA = 'planilha'
ORIGEM_MANUAL = 'manual'


def normalize_group_key(nome):
    """Texto do grupo → chave de comparação (maiúsculas, sem acento, sem espaço duplo).

    A coluna de grupo da planilha é texto digitado: sem normalizar, "ÁGUIA
    SISTEMAS" e "Águia Sistemas" viram dois grupos distintos.
    """
    texto = (nome or '').strip()
    if not texto:
        return ''
    sem_acento = ''.join(
        ch for ch in unicodedata.normalize('NFKD', texto)
        if not unicodedata.combining(ch)
    )
    return ' '.join(sem_acento.upper().split())


def cnpj_root(valor):
    """Qualquer forma de CNPJ → raiz de 8 dígitos ('60.659.463/' → '60659463')."""
    digitos = ''.join(ch for ch in str(valor or '') if ch.isdigit())
    return digitos[:8]


def _root_expression(coluna, coluna_e_raiz):
    """Expressão SQL que devolve a raiz de 8 dígitos da coluna de CNPJ.

    ``coluna_e_raiz=True`` para colunas que já guardam a raiz limpa
    (``FapWebContestacao.cnpj_raiz``); caso contrário a coluna é reduzida a
    dígitos e cortada em 8 — conferido: todas as colunas ``employer_cnpj`` do
    banco têm exatamente 14 dígitos, sem zero à esquerda, então o corte acerta
    a raiz.
    """
    if coluna_e_raiz:
        return coluna
    somente_digitos = func.replace(
        func.replace(
            func.replace(func.replace(cast(coluna, String), '.', ''), '/', ''),
            '-', '',
        ),
        ' ', '',
    )
    return func.substr(somente_digitos, 1, 8)


def group_options(law_firm_id):
    """Opções do select de grupo: [{'chave', 'nome', 'total_empresas'}].

    Ordenado por nome. A opção "sem grupo" não entra aqui — as telas a
    acrescentam no fim, para ela não se perder no meio da lista alfabética.
    """
    linhas = (
        db.session.query(
            FapCompanyGroup.grupo_chave,
            func.min(FapCompanyGroup.grupo_nome),
            func.count(FapCompanyGroup.id),
        )
        .filter(FapCompanyGroup.law_firm_id == law_firm_id)
        .group_by(FapCompanyGroup.grupo_chave)
        .all()
    )
    opcoes = [
        {'chave': chave, 'nome': nome or chave, 'total_empresas': int(total)}
        for chave, nome, total in linhas
    ]
    return sorted(opcoes, key=lambda o: o['nome'].lower())


def roots_for_group(law_firm_id, grupo_chave):
    """CNPJs raiz de um grupo. Lista vazia quando o grupo não existe."""
    chave = normalize_group_key(grupo_chave)
    if not chave:
        return []
    return [
        raiz for (raiz,) in
        db.session.query(FapCompanyGroup.cnpj_raiz)
        .filter(
            FapCompanyGroup.law_firm_id == law_firm_id,
            FapCompanyGroup.grupo_chave == chave,
        )
        .all()
    ]


def mapped_roots(law_firm_id):
    """Todos os CNPJs raiz que já têm grupo (usado pelo recorte "sem grupo")."""
    return [
        raiz for (raiz,) in
        db.session.query(FapCompanyGroup.cnpj_raiz)
        .filter(FapCompanyGroup.law_firm_id == law_firm_id)
        .all()
    ]


def group_condition(law_firm_id, grupo, coluna, *, coluna_e_raiz=False):
    """Condição SQLAlchemy do recorte por grupo, ou ``None`` quando não há filtro.

    Existe separada de ``apply_group_filter`` porque algumas telas montam uma
    lista de condições em vez de encadear ``.filter()`` — as duas formas saem
    daqui, para não haver duas versões da mesma regra.

    ``grupo`` vazio devolve None (não filtrar). ``grupo`` inexistente devolve
    ``false()``: filtra para vazio, em vez de ignorar o filtro em silêncio e
    fazer a tela mostrar tudo, parecendo que o grupo tem todos os registros.

    ``SEM_GRUPO`` devolve o complemento: registros cuja raiz não está mapeada,
    mais os que não têm CNPJ nenhum — os dois casos são "empresa que ainda não
    foi classificada".
    """
    valor = (grupo or '').strip()
    if not valor:
        return None

    expressao = _root_expression(coluna, coluna_e_raiz)

    if valor == SEM_GRUPO:
        conhecidas = mapped_roots(law_firm_id)
        if not conhecidas:
            return None  # ninguém mapeado ainda: "sem grupo" é o conjunto todo
        sem_cnpj = or_(coluna.is_(None), cast(coluna, String) == '')
        return or_(sem_cnpj, expressao.notin_(conhecidas))

    raizes = roots_for_group(law_firm_id, valor)
    if not raizes:
        return false()
    return expressao.in_(raizes)


def apply_group_filter(query, law_firm_id, grupo, coluna, *, coluna_e_raiz=False):
    """Recorta a query pelo grupo empresarial. Ver ``group_condition``."""
    condicao = group_condition(law_firm_id, grupo, coluna, coluna_e_raiz=coluna_e_raiz)
    if condicao is None:
        return query
    return query.filter(condicao)


def groups_by_root(law_firm_id):
    """Mapa {cnpj_raiz: {'nome', 'chave', 'origem'}} para exibir nas listagens."""
    return {
        registro.cnpj_raiz: {
            'nome': registro.grupo_nome,
            'chave': registro.grupo_chave,
            'origem': registro.origem,
        }
        for registro in FapCompanyGroup.query.filter_by(law_firm_id=law_firm_id).all()
    }


def assign_group(law_firm_id, raiz, grupo_nome, origem=ORIGEM_MANUAL,
                 razao_social_origem=None):
    """Cria ou atualiza o grupo de um CNPJ raiz. Não faz commit.

    Devolve ('criado' | 'alterado' | 'inalterado', registro).
    """
    raiz_limpa = cnpj_root(raiz)
    nome = (grupo_nome or '').strip()
    chave = normalize_group_key(nome)
    if not raiz_limpa or len(raiz_limpa) < 8:
        raise ValueError(f'CNPJ raiz inválido: {raiz!r}')
    if not chave:
        raise ValueError('O nome do grupo não pode ficar em branco.')

    registro = FapCompanyGroup.query.filter_by(
        law_firm_id=law_firm_id, cnpj_raiz=raiz_limpa,
    ).first()

    if registro is None:
        registro = FapCompanyGroup(
            law_firm_id=law_firm_id,
            cnpj_raiz=raiz_limpa,
            grupo_nome=nome,
            grupo_chave=chave,
            origem=origem,
            razao_social_origem=razao_social_origem,
        )
        db.session.add(registro)
        return 'criado', registro

    if registro.grupo_chave == chave and registro.grupo_nome == nome:
        # Mesma grafia: nada muda, nem a origem (não "promove" manual a planilha
        # sem necessidade, para o de-para da próxima importação não mentir).
        return 'inalterado', registro

    registro.grupo_nome = nome
    registro.grupo_chave = chave
    registro.origem = origem
    if razao_social_origem:
        registro.razao_social_origem = razao_social_origem
    return 'alterado', registro


def remove_group(law_firm_id, raiz):
    """Desvincula um CNPJ raiz do grupo. Não faz commit. Devolve True se removeu."""
    registro = FapCompanyGroup.query.filter_by(
        law_firm_id=law_firm_id, cnpj_raiz=cnpj_root(raiz),
    ).first()
    if registro is None:
        return False
    db.session.delete(registro)
    return True
