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
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.models import (db, Client, DouArticle, DouClientAlert,
                        DouClientAlertMatch)
from app.services import dou_search_service as busca_service

logger = logging.getLogger(__name__)

TAM_CNPJ = 14
TAM_RAIZ = 8

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
                alerta = DouClientAlert(law_firm_id=law_firm_id,
                                        article_id=article_id,
                                        status=DouClientAlert.STATUS_NEW)
                db.session.add(alerta)
                gerados += 1

            # Reprocessamento mantém a triagem: quem já leu o alerta não deve
            # vê-lo voltar por causa de uma republicação que não mudou nada.
            alerta.pub_date = pub_date
            alerta.pub_name = pub_name
            alerta.clients_count = len(por_cnpj)
            alerta.match_type = (DouClientAlert.MATCH_EXACT if tem_exato
                                 else DouClientAlert.MATCH_ROOT)

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
                        cnpj=cnpj, match_type=tipo))
                else:
                    existente.client_id = cliente.id
                    existente.match_type = tipo

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
    dados = {'nao_lidos': 0, 'exatos': 0, 'raiz': 0, 'total': 0}
    for status, tipo, qtd in linhas:
        dados['total'] += qtd
        if status == DouClientAlert.STATUS_NEW:
            dados['nao_lidos'] += qtd
        if tipo == DouClientAlert.MATCH_EXACT:
            dados['exatos'] += qtd
        else:
            dados['raiz'] += qtd
    return dados


def listar(law_firm_id: int, status=None, tipo=None, secao=None,
           client_id=None, page: int = 1, por_pagina: int = 30):
    """Página de alertas, do mais recente para o mais antigo.

    A ordenação termina no ``id`` porque a carga é em lote: dezenas de alertas
    dividem a mesma ``pub_date``, e empate no critério faz LIMIT/OFFSET pular e
    repetir linha sem avisar — a mesma regra da paginação das tools do MCP.
    """
    query = _base(law_firm_id).options(
        joinedload(DouClientAlert.article),
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
    return (query.order_by(DouClientAlert.pub_date.desc(),
                           DouClientAlert.id.desc())
            .paginate(page=page, per_page=por_pagina, error_out=False))


def clientes_com_alerta(law_firm_id: int):
    """``[(client_id, nome, qtd)]`` para o filtro — só quem tem alerta."""
    linhas = (db.session.query(DouClientAlertMatch.client_id, Client.name,
                               func.count(func.distinct(DouClientAlertMatch.alert_id)))
              .join(Client, Client.id == DouClientAlertMatch.client_id)
              .filter(DouClientAlertMatch.law_firm_id == law_firm_id)
              .group_by(DouClientAlertMatch.client_id, Client.name)
              .order_by(Client.name).all())
    return [(cid, nome, qtd) for cid, nome, qtd in linhas]


def cnpjs_invalidos(law_firm_id: int):
    """Clientes que ficam de fora da vigilância por CNPJ inválido.

    Aparece na tela de propósito: um cliente que não é vigiado por causa do
    cadastro é uma falha silenciosa, e falha silenciosa em alerta é pior que
    alerta nenhum — a pessoa confia numa cobertura que não existe.
    """
    return Carteira(law_firm_id).invalidos


# -------------------------------------------------------------------- trecho

# Acima disto os trechos passam a somar mais que o próprio texto e não vale
# recortar: é o caso do edital-tabela do CRPS, onde 103 CNPJs ficam lado a lado
# em 9 mil caracteres e as janelas se sobrepõem quase inteiras.
LIMIAR_TEXTO_INTEIRO = 0.8


def trechos_do_alerta(alerta, maximo: int = 40) -> dict:
    """O que o modal "ver trecho" mostra.

    Devolve ``{'modo', 'itens', 'restantes', 'inteiro'}``:

    * ``modo='trechos'`` — um recorte por CNPJ, em volta da citação. É o caso
      comum: a matéria fala do cliente numa frase, e a frase é o que interessa.
    * ``modo='inteiro'`` — o texto todo com as ocorrências marcadas, quando os
      recortes somariam quase o texto inteiro.

    O ``<mark>`` sai daqui já escapado por ``destacar``: o texto do DOU tem
    ``<`` de verdade, e inserir a tag antes de escapar deixaria o conteúdo
    virar elemento na página.
    """
    artigo = alerta.article
    texto = (artigo.texto or '') if artigo else ''
    if not texto:
        return {'modo': 'vazio', 'itens': [], 'restantes': 0, 'inteiro': None}

    itens = []
    for m in alerta.matches_ordenados:
        recorte = busca_service.trecho_do_identificador(texto, m.cnpj)
        if not recorte:
            continue
        itens.append({
            'cnpj': m.cnpj,
            'cnpj_formatado': m.cnpj_formatado,
            'cliente': m.client,
            'tipo': m.match_type,
            'html': busca_service.destacar(recorte),
        })

    soma = sum(len(i['html']) for i in itens)
    if not itens or soma >= len(texto) * LIMIAR_TEXTO_INTEIRO:
        marcado = busca_service.marcar_identificadores(
            texto, [m.cnpj for m in alerta.matches])
        return {'modo': 'inteiro', 'itens': [], 'restantes': 0,
                'inteiro': busca_service.destacar(marcado)}

    return {'modo': 'trechos', 'itens': itens[:maximo],
            'restantes': max(0, len(itens) - maximo), 'inteiro': None}


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
