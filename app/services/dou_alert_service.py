"""
Alertas de cliente no Diário Oficial.

Cruza os CNPJs da carteira de clientes do escritório com o texto de cada
matéria capturada. Fonte única da tela ``/dou/alertas``, do gancho na ingestão
e do script de varredura retroativa.

O que a medição no acervo real (21.038 matérias, 7 dias, 538 clientes) definiu
neste arquivo:

* **A unidade do alerta é a matéria**, não o par (cliente, matéria). Um edital
  do CRPS cita 52 clientes de uma vez; por par o mesmo documento viraria 52
  linhas na tela e no e-mail. 41 alertas contra 1.333 — 32x.
* **CNPJ sem dígito verificador válido não vigia nada.** A HAVAN estava
  cadastrada com ``00000000000000``, cuja raiz casa com ``00.000.000/0001-91``
  — o Banco do Brasil, que está em todo convênio de folha de pagamento do país.
  Ela aparecia em acordos do TRE de Rondônia e da Polícia Rodoviária Federal.
  Exigir o DV derrubou o ruído de 54 para 41 alertas.
* **A varredura é em memória, sem Meilisearch.** ``extrair_cnpjs`` já existe e
  o acervo inteiro levou 8,4 s — cerca de 2 s por edição do dia. O índice serve
  à tela de busca; o alerta não pode depender dele.
"""

import logging
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.models import (db, Client, DouArticle, DouClientAlert,
                        DouClientAlertMatch, DouEdition)
from app.services import dou_search_service as busca_service
from app.services.dou_xml_parser import grifar_html, sanitizar_html

logger = logging.getLogger(__name__)

TAM_CNPJ = 14
TAM_RAIZ = 8

# Vocabulário de decisão do CRPS. Os três primeiros são os que aparecem no
# acervo — 1.070 "Indeferimento Total", 249 "Deferimento Parcial", 1
# "Deferimento Total". Os demais entram porque são desfechos padrão do Conselho
# e podem cair em qualquer edital; sem eles a coluna ficaria vazia justamente
# no caso raro, que é quando o alerta mais importa.
_RESULTADOS = (
    'deferimento total', 'deferimento parcial',
    'indeferimento total', 'indeferimento parcial',
    'recurso nao conhecido', 'nao conhecido', 'prejudicado',
    'diligencia', 'anulado', 'nulidade',
)

# Recortes do filtro de resultado. Além destes, o valor pode ser a decisão
# exata ("Indeferimento Total"), para quem já sabe o que procura.
FAP_QUALQUER = 'com'          # houve decisão, qualquer que seja
FAP_FAVORAVEL = 'deferimento'  # onde ganhamos
FAP_CONTRA = 'indeferimento'   # onde há prazo correndo

# Pesos do módulo 11, os dois dígitos verificadores do CNPJ
_PESOS_DV1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_PESOS_DV2 = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


# --------------------------------------------------------------- validação

def cnpj_valido(digitos: str | None) -> bool:
    """True quando os 14 dígitos passam no dígito verificador (módulo 11).

    Rejeita também os repetidos (``00000000000000``, ``11111111111111``): eles
    passariam no cálculo em alguns casos e são sempre preenchimento, não CNPJ.
    """
    d = digitos or ''
    if len(d) != TAM_CNPJ or not d.isdigit() or d == d[0] * TAM_CNPJ:
        return False
    for tam, pesos in ((12, _PESOS_DV1), (13, _PESOS_DV2)):
        resto = sum(int(d[i]) * pesos[i] for i in range(tam)) % 11
        if int(d[tam]) != (0 if resto < 2 else 11 - resto):
            return False
    return True


def _utcnow() -> datetime:
    """Agora em UTC, naive — a base de ``created_at`` e da janela do e-mail.

    O ``main.py`` define ``TZ=America/Sao_Paulo``, então ``datetime.now()``
    devolve hora local, três horas atrás do UTC. A janela do digest é o
    ``NotificationSetting.last_sent_at``, que é UTC: gravar ``created_at`` em
    hora local faria o alerta das últimas três horas parecer mais velho que a
    marca d'água e ser **pulado em silêncio**. Mesma regra do
    ``fap_procuracoes_service``.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sem_acento(valor: str | None) -> str:
    return (unicodedata.normalize('NFKD', (valor or '').strip().lower())
            .encode('ascii', 'ignore').decode())


def eh_resultado(valor: str | None) -> bool:
    """A célula é uma decisão de recurso FAP?

    Compara a célula **inteira**, não por substring: "Indeferimento Total" é
    uma coluna própria da tabela do CRPS, e procurar o termo dentro de um texto
    qualquer marcaria a ementa de qualquer matéria que mencione a palavra.
    """
    return _sem_acento(valor) in _RESULTADOS


def resultado_do_bloco(bloco) -> str | None:
    """A decisão na mesma linha em que o CNPJ apareceu, ou None.

    O edital do CRPS é uma tabela com uma linha por estabelecimento —
    sequência, processo, ano, CNPJ, instância e resultado. A decisão daquele
    CNPJ é a célula de decisão da linha dele, não a primeira do documento.
    """
    if getattr(bloco, 'name', None) != 'tr':
        return None
    for celula in bloco.find_all('td'):
        texto = celula.get_text(' ', strip=True)
        if eh_resultado(texto):
            return texto
    return None


def formatar_cnpj(digitos: str | None) -> str:
    """'19630496000105' → '19.630.496/0001-05'. Devolve como veio se não der."""
    d = digitos or ''
    if len(d) != TAM_CNPJ:
        return d
    return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}'


# ----------------------------------------------------------------- carteira

class Carteira:
    """Os CNPJs vigiados de um escritório, prontos para casar em memória."""

    def __init__(self, law_firm_id: int):
        self.law_firm_id = law_firm_id
        self.por_cnpj: dict[str, Client] = {}
        self.por_raiz: dict[str, Client] = {}
        self.invalidos: list[Client] = []

        for cliente in Client.query.filter_by(law_firm_id=law_firm_id).all():
            digitos = busca_service.so_digitos(cliente.cnpj)
            if not cnpj_valido(digitos):
                self.invalidos.append(cliente)
                continue
            self.por_cnpj[digitos] = cliente
            # Primeira filial cadastrada representa o grupo. Basta para dar
            # nome ao alerta; o CNPJ que apareceu no DOU vai na linha.
            self.por_raiz.setdefault(digitos[:TAM_RAIZ], cliente)

    def __bool__(self):
        return bool(self.por_cnpj)

    def casar(self, texto: str | None) -> list[tuple[str, Client, str]]:
        """``[(cnpj_no_dou, cliente, tipo)]`` para o texto de uma matéria.

        Um CNPJ que é exatamente o do cadastro nunca vira casamento por raiz —
        senão o mesmo cliente entraria duas vezes na mesma matéria.
        """
        achados = []
        for digitos in busca_service.extrair_cnpjs(texto):
            # O número mal extraído do texto também tem de passar no DV: é o que
            # impede protocolo e valor de virarem CNPJ de cliente.
            if not cnpj_valido(digitos):
                continue
            cliente = self.por_cnpj.get(digitos)
            if cliente is not None:
                achados.append((digitos, cliente, DouClientAlert.MATCH_EXACT))
                continue
            cliente = self.por_raiz.get(digitos[:TAM_RAIZ])
            if cliente is not None:
                achados.append((digitos, cliente, DouClientAlert.MATCH_ROOT))
        return achados


def carteiras_ativas() -> dict[int, Carteira]:
    """Uma carteira por escritório que tenha ao menos um CNPJ válido."""
    ids = [linha[0] for linha in
           db.session.query(Client.law_firm_id).distinct().all()]
    carteiras = {}
    for law_firm_id in ids:
        carteira = Carteira(law_firm_id)
        if carteira:
            carteiras[law_firm_id] = carteira
    return carteiras


# ------------------------------------------------------------------ geração

def gerar_para_edicao(edition, carteiras=None) -> int:
    """Gera/atualiza os alertas das matérias de uma edição. Devolve quantos.

    Não comita: quem chama decide. Nunca levanta — o alerta é derivado, e uma
    falha aqui não pode derrubar a captura, mesma regra do índice de busca.
    """
    try:
        materias = (db.session.query(DouArticle.id, DouArticle.texto,
                                     DouArticle.pub_date, DouArticle.pub_name)
                    .filter(DouArticle.edition_id == edition.id).all())
        if not materias:
            return 0
        return _gerar_para_materias(materias, carteiras)
    except Exception:  # noqa: BLE001 — alerta não derruba a captura
        logger.exception('DOU: falha ao gerar alertas da edição %s', edition.id)
        return 0


def gerar_para_datas(datas, carteiras=None) -> int:
    """Varredura retroativa: gera alertas das matérias de uma lista de datas."""
    materias = (db.session.query(DouArticle.id, DouArticle.texto,
                                 DouArticle.pub_date, DouArticle.pub_name)
                .filter(DouArticle.pub_date.in_(list(datas))).all())
    return _gerar_para_materias(materias, carteiras)


def _decisoes_por_cnpj(article_id: int, cnpjs) -> dict:
    """``{cnpj: decisão}`` lido da tabela da matéria. ``{}`` quando não é edital.

    O ``texto_html`` é LONGTEXT e só é buscado para matéria que já casou — são
    ~8 por dia, contra as milhares de uma edição. O teste por ``<table`` evita
    até esse custo na matéria em prosa: decisão de recurso mora em tabela.
    """
    if not cnpjs:
        return {}
    linha = (db.session.query(DouArticle.texto_html)
             .filter(DouArticle.id == article_id).first())
    bruto = (linha[0] if linha else '') or ''
    if '<table' not in bruto:
        return {}

    alvos = set(cnpjs)
    decisoes = {}
    try:
        sopa = BeautifulSoup(sanitizar_html(bruto), 'html.parser')
        for bloco in _blocos_com_cnpj(sopa, alvos):
            decisao = resultado_do_bloco(bloco)
            if not decisao:
                continue
            for digitos in busca_service.extrair_cnpjs(bloco.get_text(' ')):
                if digitos in alvos:
                    decisoes[digitos] = decisao
    except Exception:  # noqa: BLE001 — sem decisão o alerta continua valendo
        logger.exception('DOU: falha ao ler decisões da matéria %s', article_id)
    return decisoes


def _gerar_para_materias(materias, carteiras=None) -> int:
    """O laço de casamento. ``materias`` é a tupla enxuta, não o modelo inteiro.

    Carregar o ORM completo aqui traria ``raw_xml`` e ``texto_html`` junto — três
    campos LONGTEXT por linha que ninguém usa no casamento.
    """
    if carteiras is None:
        carteiras = carteiras_ativas()
    if not carteiras:
        return 0

    gerados = 0
    for law_firm_id, carteira in carteiras.items():
        # Os alertas já existentes desta leva, para o upsert não duplicar
        ids = [m[0] for m in materias]
        existentes = {}
        for pedaco in range(0, len(ids), 500):
            for alerta in (DouClientAlert.query
                           .filter(DouClientAlert.law_firm_id == law_firm_id,
                                   DouClientAlert.article_id.in_(ids[pedaco:pedaco + 500]))
                           .all()):
                existentes[alerta.article_id] = alerta

        for article_id, texto, pub_date, pub_name in materias:
            casados = carteira.casar(texto)
            alerta = existentes.get(article_id)

            if not casados:
                # A matéria pode ter sido republicada sem o CNPJ; o alerta
                # antigo deixa de valer.
                if alerta is not None:
                    db.session.delete(alerta)
                continue

            # Um cliente citado por dois estabelecimentos aparece uma vez por
            # CNPJ — é o CNPJ que identifica o estabelecimento no DOU.
            por_cnpj = {cnpj: (cliente, tipo) for cnpj, cliente, tipo in casados}
            tem_exato = any(t == DouClientAlert.MATCH_EXACT
                            for _, t in por_cnpj.values())

            if alerta is None:
                # created_at em UTC, não no default local do modelo: é ele que
                # a janela do e-mail compara com last_sent_at.
                alerta = DouClientAlert(law_firm_id=law_firm_id,
                                        article_id=article_id,
                                        status=DouClientAlert.STATUS_NEW,
                                        created_at=_utcnow())
                db.session.add(alerta)
                gerados += 1

            decisoes = _decisoes_por_cnpj(article_id, set(por_cnpj))

            # Reprocessamento mantém a triagem: quem já leu o alerta não deve
            # vê-lo voltar por causa de uma republicação que não mudou nada.
            alerta.pub_date = pub_date
            alerta.pub_name = pub_name
            alerta.clients_count = len(por_cnpj)
            alerta.match_type = (DouClientAlert.MATCH_EXACT if tem_exato
                                 else DouClientAlert.MATCH_ROOT)
            alerta.tem_resultado = bool(decisoes)

            # Casa CNPJ a CNPJ em vez de limpar e reinserir. Um `clear()`
            # seguido de append emitia os INSERT antes dos DELETE no mesmo
            # flush e estourava a chave única (alert_id, cnpj) — e ainda
            # reescreveria as 103 linhas de um edital de lista a cada
            # reprocessamento, para nada.
            atuais = {m.cnpj: m for m in alerta.matches}
            for cnpj in list(atuais):
                if cnpj not in por_cnpj:
                    alerta.matches.remove(atuais.pop(cnpj))
            for cnpj, (cliente, tipo) in sorted(por_cnpj.items()):
                existente = atuais.get(cnpj)
                if existente is None:
                    alerta.matches.append(DouClientAlertMatch(
                        law_firm_id=law_firm_id, client_id=cliente.id,
                        cnpj=cnpj, match_type=tipo,
                        resultado=decisoes.get(cnpj)))
                else:
                    existente.client_id = cliente.id
                    existente.match_type = tipo
                    existente.resultado = decisoes.get(cnpj)

    return gerados


# ------------------------------------------------------------------ consulta

def _base(law_firm_id: int):
    return DouClientAlert.query.filter(DouClientAlert.law_firm_id == law_firm_id)


def contar_nao_lidos(law_firm_id: int) -> int:
    """Um COUNT no índice (law_firm_id, status, pub_date). Para o chip."""
    return _base(law_firm_id).filter(
        DouClientAlert.status == DouClientAlert.STATUS_NEW).count()


def resumo(law_firm_id: int) -> dict:
    """Os números do topo da tela, em uma varredura do índice."""
    linhas = (db.session.query(DouClientAlert.status, DouClientAlert.match_type,
                               func.count())
              .filter(DouClientAlert.law_firm_id == law_firm_id)
              .group_by(DouClientAlert.status, DouClientAlert.match_type).all())
    dados = {'nao_lidos': 0, 'exatos': 0, 'raiz': 0, 'total': 0, 'com_resultado': 0}
    for status, tipo, qtd in linhas:
        dados['total'] += qtd
        if status == DouClientAlert.STATUS_NEW:
            dados['nao_lidos'] += qtd
        if tipo == DouClientAlert.MATCH_EXACT:
            dados['exatos'] += qtd
        else:
            dados['raiz'] += qtd
    dados['com_resultado'] = _base(law_firm_id).filter(
        DouClientAlert.tem_resultado.is_(True)).count()
    return dados


def listar(law_firm_id: int, status=None, tipo=None, secao=None,
           client_id=None, fap=None, page: int = 1, por_pagina: int = 30):
    """Página de alertas, do mais recente para o mais antigo.

    Dentro do dia, **quem traz decisão de recurso vem primeiro**: é desfecho,
    não notícia, e num dia de 32 alertas a ordem por id o empurraria para o fim
    da lista.

    A ordenação termina no ``id`` porque a carga é em lote: dezenas de alertas
    dividem a mesma ``pub_date``, e empate no critério faz LIMIT/OFFSET pular e
    repetir linha sem avisar — a mesma regra da paginação das tools do MCP.
    """
    # A edição vem junto porque cada linha decide o destino de "Ver no Diário"
    # pelo `pdf_disponivel` dela; sem isto seriam 30 consultas por página.
    query = _base(law_firm_id).options(
        joinedload(DouClientAlert.article).joinedload(DouArticle.edition),
        joinedload(DouClientAlert.matches).joinedload(DouClientAlertMatch.client),
    )
    if status:
        query = query.filter(DouClientAlert.status == status)
    if tipo:
        query = query.filter(DouClientAlert.match_type == tipo)
    if secao:
        query = query.filter(DouClientAlert.pub_name == secao)
    if client_id:
        query = query.filter(DouClientAlert.id.in_(
            db.session.query(DouClientAlertMatch.alert_id)
            .filter(DouClientAlertMatch.law_firm_id == law_firm_id,
                    DouClientAlertMatch.client_id == client_id)))
    if fap:
        # Os três recortes que o advogado pede: "houve decisão", "onde ganhamos"
        # e "onde há prazo correndo" — mais a decisão exata, quando ele já sabe
        # o que procura. Tudo pelo mesmo caminho, a tabela de casamentos.
        sub = (db.session.query(DouClientAlertMatch.alert_id)
               .filter(DouClientAlertMatch.law_firm_id == law_firm_id,
                       DouClientAlertMatch.resultado.isnot(None)))
        if fap == FAP_FAVORAVEL:
            sub = sub.filter(DouClientAlertMatch.resultado.ilike('deferimento%'))
        elif fap == FAP_CONTRA:
            # `not ilike('deferimento%')` e não `ilike('indeferimento%')`:
            # diligência e prejudicado também não são ganho de causa.
            sub = sub.filter(~DouClientAlertMatch.resultado.ilike('deferimento%'))
        elif fap != FAP_QUALQUER:
            sub = sub.filter(DouClientAlertMatch.resultado == fap)
        query = query.filter(DouClientAlert.id.in_(sub))
    return (query.order_by(DouClientAlert.pub_date.desc(),
                           DouClientAlert.tem_resultado.desc(),
                           DouClientAlert.id.desc())
            .paginate(page=page, per_page=por_pagina, error_out=False))


def resultados_disponiveis(law_firm_id: int):
    """``[(decisão, quantos alertas)]`` para o filtro — só o que existe.

    Como no filtro de cliente: oferecer opção que não devolve nada é convidar
    para uma tela vazia. O vocabulário do CRPS é curto, mas varia por edital.
    """
    linhas = (db.session.query(DouClientAlertMatch.resultado,
                               func.count(func.distinct(DouClientAlertMatch.alert_id)))
              .filter(DouClientAlertMatch.law_firm_id == law_firm_id,
                      DouClientAlertMatch.resultado.isnot(None))
              .group_by(DouClientAlertMatch.resultado).all())
    # Deferimento primeiro: é o desfecho que se procura de propósito.
    return sorted(linhas, key=lambda t: (not _sem_acento(t[0]).startswith('deferimento'),
                                         -t[1], t[0]))


def clientes_com_alerta(law_firm_id: int):
    """``[(client_id, nome, cnpj_formatado, qtd)]`` — só quem tem alerta.

    O CNPJ vai junto e não é enfeite: a carteira tem um cadastro por
    estabelecimento, e "BANCO SANTANDER (BRASIL) S.A." aparece dezenas de vezes
    na lista. Sem o número, as opções ficam indistinguíveis — e é por ele que
    o matcher do select2 deixa procurar, com ou sem pontuação.
    """
    linhas = (db.session.query(DouClientAlertMatch.client_id, Client.name,
                               Client.cnpj,
                               func.count(func.distinct(DouClientAlertMatch.alert_id)))
              .join(Client, Client.id == DouClientAlertMatch.client_id)
              .filter(DouClientAlertMatch.law_firm_id == law_firm_id)
              .group_by(DouClientAlertMatch.client_id, Client.name, Client.cnpj)
              .order_by(Client.name, Client.cnpj).all())
    return [(cid, nome, formatar_cnpj(busca_service.so_digitos(cnpj)) or cnpj, qtd)
            for cid, nome, cnpj, qtd in linhas]


def cnpjs_invalidos(law_firm_id: int):
    """Clientes que ficam de fora da vigilância por CNPJ inválido.

    Aparece na tela de propósito: um cliente que não é vigiado por causa do
    cadastro é uma falha silenciosa, e falha silenciosa em alerta é pior que
    alerta nenhum — a pessoa confia numa cobertura que não existe.
    """
    return Carteira(law_firm_id).invalidos


# -------------------------------------------------------------------- trecho

# Elementos que valem como bloco ao recortar o HTML. `tr` na frente porque num
# edital-tabela o CNPJ está dentro de <td><p>, e parar no <p> devolveria só a
# célula do número — sem processo, instância nem resultado, que é o que o
# advogado veio ver.
_BLOCOS_HTML = ('tr', 'li', 'p')


def _bloco_do_no(no):
    """Sobe do nó de texto até o bloco que dá contexto ao número."""
    linha, menor = None, None
    for pai in no.parents:
        nome = getattr(pai, 'name', None)
        if nome == 'tr':
            linha = pai                       # a linha inteira vence a célula
        elif nome in ('li', 'p') and menor is None:
            menor = pai
    return linha or menor


def _blocos_com_cnpj(sopa, cnpjs):
    """Blocos do HTML que citam algum dos CNPJs, em ordem de documento."""
    alvos = set(cnpjs)
    marcados = set()
    for no in sopa.find_all(string=True):
        achados = busca_service.extrair_cnpjs(str(no))
        if achados and not alvos.isdisjoint(achados):
            bloco = _bloco_do_no(no)
            if bloco is not None:
                marcados.add(id(bloco))
    if not marcados:
        return []
    # find_all devolve em ordem de documento e não repete o <p> aninhado num
    # <tr> já marcado: só o id do bloco escolhido está no conjunto.
    return [el for el in sopa.find_all(_BLOCOS_HTML) if id(el) in marcados]


def _montar_html(blocos) -> str:
    """Junta os blocos num HTML renderizável, preservando a ordem.

    ``<tr>`` solto não vira tabela: sem o ``<table>`` em volta o navegador
    descarta a marcação e a linha sai como texto corrido. Corridas de linhas
    consecutivas viram uma tabela só, para o edital não sair fatiado em uma
    tabela por linha.
    """
    partes, linhas = [], []
    for bloco in blocos:
        if getattr(bloco, 'name', None) == 'tr':
            # A célula de decisão ganha classe própria: numa linha de seis
            # colunas de números, é ela que responde o que aconteceu. A classe
            # é nossa, posta depois da faxina — não vem do documento.
            for celula in bloco.find_all('td'):
                valor = celula.get_text(' ', strip=True)
                if eh_resultado(valor):
                    celula['class'] = [
                        'dou-decisao',
                        'dou-decisao--favoravel' if _sem_acento(valor).startswith('deferimento')
                        else 'dou-decisao--contra',
                    ]
            linhas.append(str(bloco))
            continue
        if linhas:
            partes.append('<table>' + ''.join(linhas) + '</table>')
            linhas = []
        partes.append(str(bloco))
    if linhas:
        partes.append('<table>' + ''.join(linhas) + '</table>')
    return ''.join(partes)


def _termos_de_grifo(cnpjs):
    """O CNPJ nas duas grafias: o DOU escreve pontuado, o banco guarda cru."""
    termos = []
    for digitos in cnpjs:
        termos.append(formatar_cnpj(digitos))
        termos.append(digitos)
    return termos


def trechos_do_alerta(alerta, maximo: int = 200) -> dict:
    """O que o modal "ver trecho" mostra.

    Devolve ``{'modo', 'html', 'blocos', 'restantes', 'itens'}``:

    * ``modo='html'`` — os blocos do inteiro teor que citam o cliente, com a
      formatação original. É o caminho normal: 28 das 41 matérias com alerta
      têm tabela, e a linha do edital do CRPS traz processo, ano, CNPJ,
      instância e o resultado ("Indeferimento Total") — em texto corrido isso
      vira um paredão ilegível.
    * ``modo='trechos'`` — recorte de texto puro em volta de cada citação.
      Reserva para matéria capturada sem ``texto_html``.

    ``maximo`` é teto de blocos, não meta: o maior edital medido tem 103 linhas
    e cabe inteiro (~34 KB numa busca sob demanda). Cortar em 60 escondia a
    decisão de 43 estabelecimentos do cliente, que é justamente o que ele veio
    ler.

    Sanitizar antes de marcar, sempre: o conteúdo vem do documento publicado,
    e ``grifar_html`` marca, não protege.
    """
    artigo = alerta.article
    cnpjs = [m.cnpj for m in alerta.matches]

    bruto = (artigo.texto_html or '') if artigo else ''
    if bruto.strip():
        sopa = BeautifulSoup(sanitizar_html(bruto), 'html.parser')
        blocos = _blocos_com_cnpj(sopa, cnpjs)
        if blocos:
            escolhidos = blocos[:maximo]
            return {
                'modo': 'html',
                'html': grifar_html(_montar_html(escolhidos),
                                    _termos_de_grifo(cnpjs)),
                'blocos': len(escolhidos),
                'restantes': max(0, len(blocos) - len(escolhidos)),
                'itens': [],
            }

    # Sem HTML — ou com HTML onde o número não caiu em bloco nenhum — vale o
    # recorte de texto puro, que é o que sempre existe.
    texto = (artigo.texto or '') if artigo else ''
    if not texto:
        return {'modo': 'vazio', 'html': None, 'blocos': 0, 'restantes': 0,
                'itens': []}

    itens = []
    for m in alerta.matches_ordenados:
        recorte = busca_service.trecho_do_identificador(texto, m.cnpj)
        if recorte:
            itens.append({
                'cnpj': m.cnpj,
                'cnpj_formatado': m.cnpj_formatado,
                'cliente': m.client,
                'tipo': m.match_type,
                'html': busca_service.destacar(recorte),
            })

    if not itens:
        return {'modo': 'inteiro', 'html': None, 'blocos': 0, 'restantes': 0,
                'itens': [],
                'inteiro': busca_service.destacar(
                    busca_service.marcar_identificadores(texto, cnpjs))}

    return {'modo': 'trechos', 'html': None, 'blocos': 0,
            'itens': itens[:maximo], 'restantes': max(0, len(itens) - maximo)}


# -------------------------------------------------------------------- digest

DIGEST_EDICOES = 3     # janela do e-mail: os últimos N diários publicados
DIGEST_EXEMPLOS = 3    # matérias citadas por empresa, antes do "+N"


def datas_do_digest(quantas: int = DIGEST_EDICOES):
    """As últimas ``quantas`` datas com edição publicada, da mais recente.

    Sai de ``dou_editions`` e não dos alertas: "os últimos 3 diários" inclui o
    dia em que nada casou — e é isso que diferencia "não saiu nada para os
    clientes" de "a captura não rodou".
    """
    linhas = (db.session.query(DouEdition.data_publicacao)
              .filter(DouEdition.status == DouEdition.STATUS_PARSED,
                      DouEdition.qtd_materias > 0)
              .distinct()
              .order_by(DouEdition.data_publicacao.desc())
              .limit(max(quantas, 1)).all())
    return [d for (d,) in linhas]


def build_digest(law_firm_id: int, since=None, quantas_edicoes: int = DIGEST_EDICOES):
    """O conteúdo do e-mail diário de alertas do DOU.

    A janela é **fixa nos últimos N diários**, então o mesmo alerta aparece em
    mais de um e-mail. Por isso cada empresa e o total carregam ``novos`` — o
    que entrou depois de ``since`` (o ``last_sent_at``): sem essa marca, o
    leitor não distingue o que chegou hoje do que já leu ontem, e um digest que
    se repete inteiro ensina a ser ignorado.

    Agrupado por **nome** de empresa, não por ``client_id``: a carteira tem um
    cadastro por estabelecimento, e um edital do CRPS que julga 786 CNPJs do
    Itaú tem de virar uma linha, não 786.
    """
    datas = datas_do_digest(quantas_edicoes)
    vazio = {'datas': datas, 'total': 0, 'novos': 0, 'materias': 0,
             'deferimentos': 0, 'indeferimentos': 0, 'empresas': [],
             'com_fap': 0, 'has_novidades': False}
    if not datas:
        return vazio

    alertas = (DouClientAlert.query
               .options(joinedload(DouClientAlert.article),
                        joinedload(DouClientAlert.matches)
                        .joinedload(DouClientAlertMatch.client))
               .filter(DouClientAlert.law_firm_id == law_firm_id,
                       DouClientAlert.pub_date.in_(datas))
               .order_by(DouClientAlert.pub_date.desc(),
                         DouClientAlert.clients_count.desc()).all())
    if not alertas:
        return vazio

    empresas = {}
    for alerta in alertas:
        novo = bool(since and alerta.created_at and alerta.created_at > since)
        decisoes_do_alerta = defaultdict(Counter)
        for m in alerta.matches:
            if m.resultado and m.client:
                decisoes_do_alerta[m.client.name][m.resultado] += 1

        for cliente, tipo, estabelecimentos in alerta.clientes_citados:
            nome = cliente.name if cliente else '—'
            dados = empresas.setdefault(nome, {
                'nome': nome, 'client_id': cliente.id if cliente else None,
                'materias': 0, 'cnpjs': 0, 'novos': 0,
                'decisoes': Counter(), 'exemplos': [],
            })
            dados['materias'] += 1
            dados['cnpjs'] += estabelecimentos
            dados['novos'] += 1 if novo else 0
            dados['decisoes'].update(decisoes_do_alerta.get(nome, Counter()))
            identifica = (alerta.article.identifica if alerta.article else None) or ''
            dados['exemplos'].append({
                'article_id': alerta.article_id,
                'identifica': identifica.strip() or 'Matéria sem identificação',
                'identificada': bool(identifica.strip()),
                'pub_name': alerta.pub_name,
                'pagina': alerta.article.pagina if alerta.article else None,
                'pub_date': alerta.pub_date,
                'tem_resultado': alerta.tem_resultado,
                'estabelecimentos': estabelecimentos,
                'novo': novo,
            })

    lista = []
    for dados in empresas.values():
        decisoes = [
            (decisao, qtd, _sem_acento(decisao).startswith('deferimento'))
            for decisao, qtd in dados['decisoes'].most_common()
        ]
        # Deferimento primeiro: é a notícia boa, e é o que se procura na lista.
        decisoes.sort(key=lambda t: (not t[2], -t[1], t[0]))
        dados['decisoes'] = decisoes
        dados['deferimentos'] = sum(q for _, q, fav in decisoes if fav)
        dados['indeferimentos'] = sum(q for _, q, fav in decisoes if not fav)
        dados['tem_fap'] = bool(decisoes)
        # Exemplo bom é o que o leitor reconhece: identificação na frente de
        # tudo. Sete das dezesseis matérias do CRPS vêm sem `identifica` no
        # XML, e três linhas "Matéria sem identificação" não ajudam ninguém.
        # Depois vem o que tem decisão, e então o que cita mais
        # estabelecimentos — nessa ordem porque é a ordem do que se procura.
        dados['exemplos'].sort(key=lambda e: (not e['identificada'],
                                              not e['tem_resultado'],
                                              -e['estabelecimentos'],
                                              -(e['pub_date'].toordinal()
                                                if e['pub_date'] else 0)))
        dados['restantes'] = max(0, len(dados['exemplos']) - DIGEST_EXEMPLOS)
        dados['exemplos'] = dados['exemplos'][:DIGEST_EXEMPLOS]
        lista.append(dados)

    # Quem teve recurso julgado primeiro; depois, quem foi mais citado.
    lista.sort(key=lambda d: (not d['tem_fap'], -d['cnpjs'], d['nome']))

    novos = sum(1 for a in alertas
                if since and a.created_at and a.created_at > since)
    return {
        'datas': datas,
        'total': len(alertas),
        'novos': novos if since else len(alertas),
        'materias': len(alertas),
        'com_fap': sum(1 for a in alertas if a.tem_resultado),
        # Cada linha do edital é um processo de um estabelecimento — medido:
        # 1.320 linhas, 1.320 números de processo distintos, nenhum CNPJ
        # repetido na mesma matéria. Por isso a unidade é "recurso", não
        # "deferimento": o leitor precisa saber de que se está contando.
        'deferimentos': sum(d['deferimentos'] for d in lista),
        'indeferimentos': sum(d['indeferimentos'] for d in lista),
        # O número que abre o bloco é este, não os milhares: quantos clientes
        # tiveram recurso julgado e quantos ganharam alguma coisa. É pequeno,
        # cabe na cabeça e é sobre ele que se age.
        'clientes_com_fap': sum(1 for d in lista if d['tem_fap']),
        'clientes_com_deferimento': sum(1 for d in lista if d['deferimentos']),
        'empresas': lista,
        # Sem alerta novo não sai e-mail: com janela fixa de 3 diários, o
        # conteúdo se repetiria todo dia até a edição sair da janela.
        'has_novidades': (novos > 0) if since else bool(alertas),
    }


# -------------------------------------------------------------------- ações

def marcar(alerta, usuario, lido: bool = True) -> None:
    """Marca um alerta como lido (ou devolve para não lido). Não comita."""
    alerta.status = (DouClientAlert.STATUS_READ if lido
                     else DouClientAlert.STATUS_NEW)
    alerta.read_at = datetime.now() if lido else None
    alerta.read_by_id = usuario.id if (lido and usuario) else None


def marcar_todos(law_firm_id: int, usuario) -> int:
    """Marca como lidos todos os não lidos do escritório. Devolve quantos."""
    return _base(law_firm_id).filter(
        DouClientAlert.status == DouClientAlert.STATUS_NEW
    ).update({'status': DouClientAlert.STATUS_READ,
              'read_at': datetime.now(),
              'read_by_id': usuario.id if usuario else None},
             synchronize_session=False)
