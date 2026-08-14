"""
Regras de palavra-chave do Diário Oficial — o motor de casamento.

Este módulo **não sabe o que é alerta**: recebe regras e matérias e devolve
``{article_id: [rule_id]}``. Quem grava alerta é o ``dou_alert_service``, que
continua sendo o dono único desse registro.

Por que motor próprio e não o Meilisearch, que já indexa o acervo: o índice
busca com tolerância a erro e trata o termo como prefixo. Medido em 7 dias de
acervo, ``FAP`` devolve **92** matérias pelo índice e **12** aqui — as 80 de
diferença são FAPED (82x), FAPEG (34x), FAPESP, FAPEMIG, FAPERJ, fundações de
amparo à pesquisa. Para uma caixa de busca isso é recall; para um alerta são 80
falsos positivos que fazem a pessoa desligar a regra e nunca mais voltar.

E ``Fator Acidentário de Prevenção`` devolve **748** pelo índice contra **7**
aqui, porque o modo OU casa "Fator" e "Prevenção" sozinhos — 107x as mesmas
palavras. **Por isso não existe modo OU aqui.** Quem quiser OU cria duas
regras, e aí vê o volume de cada uma separado.

De quebra o alerta deixa de depender do índice, o que já era invariante do
módulo: o índice serve à tela de busca; o alerta não pode depender dele.
"""

import logging
import re
import unicodedata
from types import SimpleNamespace

from app.services.dou_search_service import orgao_raiz

logger = logging.getLogger(__name__)

# Modos de casamento. Não existe OU — ver docstring do módulo.
MODO_FRASE = 'frase'        # a sequência inteira, na ordem
MODO_PALAVRAS = 'palavras'  # todas as palavras, em qualquer posição
MODOS = (MODO_FRASE, MODO_PALAVRAS)

MODO_LABELS = {
    MODO_FRASE: 'frase exata',
    MODO_PALAVRAS: 'todas as palavras',
}

# Sonda menor que isto não peneira nada — vale mais varrer tudo.
MIN_SONDA = 3

# Janela do teste e do backfill ao salvar: o que foi visto é o que chega.
DIAS_TESTE = 7

# Cortes do veredito, ancorados no volume real: a carteira inteira de clientes
# gera ~6 alertas/dia (41 em 7 dias). Uma regra que passa disso já merece
# atenção; acima de 20/dia ela sozinha supera tudo o que existe hoje.
ALERTAS_DIA_CARTEIRA = 6
CORTE_OK = 5
CORTE_ALTO = 20

NIVEL_VAZIO = 'vazio'
NIVEL_OK = 'ok'
NIVEL_ALTO = 'alto'
NIVEL_RUIDOSO = 'ruidoso'
NIVEL_SEM_ACERVO = 'sem_acervo'   # não há edição capturada para testar contra


def normalizar(valor: str | None) -> str:
    """Minúsculo e sem acento — a forma em que texto e termo se comparam."""
    texto = unicodedata.normalize('NFKD', valor or '')
    return ''.join(c for c in texto if not unicodedata.combining(c)).lower()


def sonda(termo: str | None) -> str | None:
    """A maior corrida de caracteres sem acento do termo, ou None.

    É a peneira do banco: ``licitação`` vira ``licita``, ``Fator Acidentário de
    Prevenção`` vira ``fator acident``. Esse pedaço está **literalmente** no
    texto publicado, então ``LIKE '%sonda%'`` é superconjunto seguro do
    casamento por fronteira de palavra — nunca muda a resposta, só evita
    carregar 34 MB de LONGTEXT para a memória.

    Sem acento de propósito: o MySQL ignoraria acento pela collation, o SQLite
    do ambiente de desenvolvimento não. A sonda remove a diferença em vez de
    depender de uma das duas.
    """
    baixo = (termo or '').lower()
    corridas, atual = [], ''
    for ch in baixo:
        if normalizar(ch) == ch:
            atual += ch
        else:
            corridas.append(atual)
            atual = ''
    corridas.append(atual)
    melhor = max(corridas, key=len, default='')
    return melhor if len(melhor.strip()) >= MIN_SONDA else None


def compilar(termo: str | None, modo: str = MODO_FRASE) -> list:
    r"""Padrões que **todos** precisam casar. Lista vazia = não filtra texto.

    Fronteira por ``(?<!\w)``/``(?!\w)`` e não por ``\b``: um termo que começa
    ou termina em pontuação — "art. 22" — faria o ``\b`` exigir uma transição
    que não existe, e a regra nunca casaria.
    """
    alvo = normalizar(termo).strip()
    if not alvo:
        return []
    pedacos = ([p for p in re.split(r'\s+', alvo) if p]
               if modo == MODO_PALAVRAS else [alvo])
    padroes = []
    for pedaco in pedacos:
        # Pedaço sem letra nem dígito (só pontuação) não delimita nada.
        if not re.search(r'\w', pedaco):
            continue
        padroes.append(re.compile(r'(?<!\w)' + re.escape(pedaco) + r'(?!\w)'))
    return padroes


def casa_texto(texto_normalizado: str, padroes: list) -> bool:
    """Todos os padrões presentes. Sem padrão, casa (o recorte é órgão/seção)."""
    if not padroes:
        return True
    return all(p.search(texto_normalizado) for p in padroes)


# ------------------------------------------------------------------ colheita

def regras_ativas() -> dict:
    """``{law_firm_id: [DouAlertRule]}`` — só as ligadas, para a colheita."""
    from app.models import DouAlertRule

    por_firma = {}
    for regra in DouAlertRule.query.filter(DouAlertRule.ativo.is_(True)).all():
        por_firma.setdefault(regra.law_firm_id, []).append(regra)
    return por_firma


def corpus(materia) -> str:
    """O texto em que a regra procura: identifica + ementa + texto.

    Não existe a opção "procurar só no título" porque não existe título: medido
    no acervo, ``titulo`` está vazio em **100%** das matérias e ``ementa`` em
    **98%**. O DOU põe o cabeçalho ("PORTARIA Nº 1.234, DE ...") em
    ``identifica`` e todo o resto em ``texto``.
    """
    return ' '.join(filter(None, (getattr(materia, 'identifica', None),
                                  getattr(materia, 'ementa', None),
                                  getattr(materia, 'texto', None))))


def _preparar(regras):
    """[(regra, padroes, secoes, orgao_normalizado)] — compila uma vez só."""
    return [(regra,
             compilar(regra.termo, regra.modo),
             set(regra.lista_secoes),
             normalizar(regra.orgao_raiz) if regra.orgao_raiz else None)
            for regra in regras]


def casar(regras, materias, cache=None) -> dict:
    """``{article_id: [rule_id]}``. Não toca o banco nem grava nada.

    O corpus normalizado é memorizado por matéria: sem isso, dez regras
    normalizariam os mesmos 34 MB dez vezes. O ``cache`` pode vir de fora para
    dois escritórios com regras diferentes dividirem o mesmo trabalho.

    Recorte barato antes do caro: seção e órgão descartam a matéria antes de
    qualquer normalização de texto.
    """
    if not regras or not materias:
        return {}
    cache = {} if cache is None else cache
    preparadas = _preparar(regras)

    achados = {}
    for materia in materias:
        for regra, padroes, secoes, orgao in preparadas:
            if secoes and (materia.pub_name or '').upper() not in secoes:
                continue
            if orgao and normalizar(orgao_raiz(materia.orgao_hierarquia)) != orgao:
                continue
            if padroes:
                corpo = cache.get(materia.id)
                if corpo is None:
                    corpo = cache[materia.id] = normalizar(corpus(materia))
                if not casa_texto(corpo, padroes):
                    continue
            achados.setdefault(materia.id, []).append(regra.id)
    return achados


# --------------------------------------------------------- testar uma regra

def datas_do_teste(quantas: int = DIAS_TESTE):
    """As últimas ``quantas`` datas **com edição capturada**, da mais nova.

    A janela é de edições publicadas, não de dias de calendário — e a diferença
    não é cosmética. Medido: com o acervo indo de 03/08 a 11/08 e "hoje" em
    14/08, a janela de 7 dias corridos pegava só duas datas, uma delas com 356
    matérias em vez das ~3.000 de sempre. O termo "licitação" achava 768
    matérias, dividia por 7 e anunciava **110 por dia** quando o real é **660**.
    Seis vezes menos, em silêncio, justamente no número que decide se a pessoa
    salva a regra. Fim de semana e feriado produzem o mesmo buraco toda semana.
    """
    from app.models import DouEdition, db

    linhas = (db.session.query(DouEdition.data_publicacao)
              .distinct()
              .order_by(DouEdition.data_publicacao.desc())
              .limit(max(1, int(quantas or DIAS_TESTE))).all())
    return [linha[0] for linha in linhas]


def filtrar_candidatas(termo, secoes, orgao, datas=None):
    """A query das matérias que **podem** casar — a peneira, não a resposta.

    Varrer 7 dias em Python custa 9,1 s de carga mais 3,0 s de normalização.
    Inaceitável num botão que a pessoa aperta várias vezes ajustando a regra.
    A peneira derruba isso para 0,5–1,9 s.

    O ``LIKE`` cobre os **três** campos do corpus. Peneirar só ``texto``
    perderia a matéria cujo termo está no cabeçalho ("PORTARIA CRPS Nº 9"), e
    aí o teste mostraria menos do que vai chegar — que é exatamente o defeito
    que este recurso existe para evitar.

    O recorte de órgão vai como prefixo da hierarquia, superconjunto da raiz:
    quem decide continua sendo ``orgao_raiz`` em Python, um caminho só.
    """
    from app.models import DouArticle, db

    query = db.session.query(
        DouArticle.id, DouArticle.identifica, DouArticle.ementa,
        DouArticle.texto, DouArticle.pub_date, DouArticle.pub_name,
        DouArticle.pagina_num, DouArticle.orgao_hierarquia)
    if datas is not None:
        query = query.filter(DouArticle.pub_date.in_(list(datas)))
    if secoes:
        query = query.filter(DouArticle.pub_name.in_(list(secoes)))
    if orgao:
        query = query.filter(DouArticle.orgao_hierarquia.ilike(f'{orgao}%'))
    probe = sonda(termo)
    if probe:
        alvo = f'%{probe}%'
        query = query.filter(db.or_(DouArticle.texto.ilike(alvo),
                                    DouArticle.identifica.ilike(alvo),
                                    DouArticle.ementa.ilike(alvo)))
    return query


def nivel(por_dia: float) -> str:
    """O veredito do volume. Ver CORTE_OK/CORTE_ALTO para a âncora."""
    if por_dia <= 0:
        return NIVEL_VAZIO
    if por_dia <= CORTE_OK:
        return NIVEL_OK
    if por_dia <= CORTE_ALTO:
        return NIVEL_ALTO
    return NIVEL_RUIDOSO


def validar(nome, termo, modo, secoes, orgao) -> list:
    """Mensagens de erro; lista vazia quer dizer regra válida."""
    erros = []
    if not (nome or '').strip():
        erros.append('Dê um nome à regra — é ele que aparece no alerta.')
    if modo not in MODOS:
        erros.append('Modo de casamento inválido.')
    tem_termo = bool(compilar(termo, modo if modo in MODOS else MODO_FRASE))
    if (termo or '').strip() and not tem_termo:
        erros.append('A palavra-chave não tem nenhuma letra ou número.')
    elif not tem_termo and not (orgao or '').strip():
        erros.append('Informe uma palavra-chave ou um órgão — sem nenhum dos '
                     'dois a regra casaria a edição inteira, cerca de 3.000 '
                     'matérias por dia.')
    return erros


def testar(termo, modo=MODO_FRASE, secoes=None, orgao=None,
           dias: int = DIAS_TESTE, exemplos: int = 8) -> dict:
    """Quanto esta regra teria gerado nos últimos ``dias``, e alguns exemplos.

    Usa o **mesmo** ``casar`` da colheita diária, de propósito: se o teste e a
    colheita tivessem implementações separadas, elas divergiriam e o número
    mostrado antes de salvar viraria mentira — destruindo justamente a peça que
    resolve o problema de volume.
    """
    secoes = [s.strip().upper() for s in (secoes or []) if s and s.strip()]
    orgao = (orgao or '').strip() or None

    datas = datas_do_teste(dias)
    if not datas:
        # Sem edição capturada não há o que testar. Devolver "0 alertas" aqui
        # acusaria o termo por um problema que é do acervo.
        return {'total': 0, 'dias': 0, 'por_dia': 0.0, 'nivel': NIVEL_SEM_ACERVO,
                'vezes_carteira': 0, 'exemplos': []}

    candidatas = filtrar_candidatas(termo, secoes, orgao, datas).all()

    # Regra ainda não salva: um objeto solto com a mesma superfície que `casar`
    # consome. Assim o teste passa pelo caminho da colheita, não por um paralelo.
    provisoria = SimpleNamespace(id=0, termo=termo, modo=modo,
                                 lista_secoes=secoes, orgao_raiz=orgao)

    achados = casar([provisoria], candidatas)
    casadas = [m for m in candidatas if m.id in achados]
    casadas.sort(key=lambda m: (m.pub_date or datas[-1], m.id), reverse=True)

    total = len(casadas)
    por_dia = round(total / len(datas), 1)
    return {
        'total': total,
        'dias': len(datas),
        'por_dia': por_dia,
        'nivel': nivel(por_dia),
        # Quantas vezes o volume da carteira inteira de clientes. É a frase que
        # dói: "essa regra sozinha traria 100x o que já existe".
        'vezes_carteira': (int(por_dia / ALERTAS_DIA_CARTEIRA)
                           if por_dia > 2 * ALERTAS_DIA_CARTEIRA else 0),
        'exemplos': [{
            'id': m.id,
            'pub_date': m.pub_date.strftime('%d/%m') if m.pub_date else '',
            'pub_name': m.pub_name or '',
            'pagina': m.pagina_num,
            'identifica': m.identifica or '(sem identificação)',
            'orgao': orgao_raiz(m.orgao_hierarquia) or '',
        } for m in casadas[:exemplos]],
    }
