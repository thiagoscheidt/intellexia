"""
Busca no acervo do Diário Oficial (Meilisearch).

Índice dedicado, alimentado pela ingestão e reconstruível a partir do banco. O
MySQL é a fonte da verdade; este índice é descartável. Daí as duas regras que
valem em todo o arquivo: indexar nunca derruba a captura, buscar nunca derruba
a tela.

O ponto central é o tratamento de identificadores. O Meilisearch tokeniza
separando em '.', '/' e '-', então `19.630.496/0001-05` vira os tokens 19, 630,
496, 0001, 05 e quem digitasse `19630496000105` não acharia nada — em 31% do
acervo, que é a fatia que contém CNPJ. Por isso os identificadores são
extraídos, normalizados para só dígitos e guardados em campos próprios, e a
consulta é roteada para esses campos quando o termo é um número.
"""

from __future__ import annotations

import html
import logging
import os
import re

from dotenv import load_dotenv
from meilisearch_python_sdk import Client as MeilisearchClient
from meilisearch_python_sdk.models.settings import TypoTolerance

# Carregado aqui, e não só pelo main.py: os testes importam este módulo direto,
# e sem isso a chave do Meilisearch seria lida como None na importação. É o
# mesmo que impugnacao_reference_search faz.
load_dotenv()

logger = logging.getLogger(__name__)

MEILISEARCH_HOST = os.getenv('MEILISEARCH_HOST', 'http://localhost:7700')
MEILISEARCH_API_KEY = os.getenv('MEILISEARCH_API_KEY')
MEILI_INDEX = os.getenv('DOU_MEILI_INDEX', 'dou_articles')

# A ordem é a ordem de relevância: o Meilisearch pesa os primeiros mais alto.
_SEARCHABLE = ['identifica', 'ementa', 'titulo', 'orgao_hierarquia',
               'cnpjs', 'processos', 'texto']
_FILTERABLE = ['pub_name', 'pub_date_num', 'art_type', 'orgao_raiz', 'edicao']
_SORTABLE = ['pub_date_num']
_FACETAS = ['pub_name', 'orgao_raiz', 'art_type']

# Número aproximado é número errado: sem isso, 19630496000105 casaria com o
# CNPJ de outra empresa que difere por um dígito.
_SEM_TOLERANCIA = ['cnpjs', 'processos']

LOTE_PADRAO = 1000

# Teto de paginação do Meilisearch (padrão do próprio servidor). Além dele o
# `estimated_total_hits` satura e não há mais páginas para entregar.
MAX_TOTAL_HITS = 1000
TAM_TRECHO = 40

# O Meilisearch marca o trecho inserindo as tags que a gente pedir, e NÃO
# escapa o texto original. Como o texto do DOU chega com '<' e '&' literais
# (6 em 5.000 matérias têm '<', p.ex. "Site da SEAD <centraldecompras.pi.gov.br>"),
# mandar '<mark>' direto significaria injetar HTML do documento na página.
# Pedimos um marcador neutro, escapamos tudo, e só então trocamos o marcador
# pela tag de verdade.
#
# ASCII imprimível de propósito: a primeira versão usava STX/ETX (\x02/\x03) e
# caractere de controle atravessa JSON e proxies de forma imprevisível entre
# versões do servidor. O marcador abaixo não ocorre em texto do DOU e não
# depende de como a camada de transporte trata bytes de controle.
MARCA_INI = '@@DOUMARK@@'
MARCA_FIM = '@@/DOUMARK@@'
TAM_JANELA_IDENTIFICADOR = 240

# Formatos conferidos contra o acervo real:
#   CNPJ     19.630.496/0001-05     -> 14 dígitos
#   processo 15414.630210/2026-80   -> 17 dígitos
_RE_CNPJ = re.compile(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}')
_RE_CNPJ_DIGITOS = re.compile(r'(?<!\d)\d{14}(?!\d)')
_RE_PROCESSO = re.compile(r'\d{5}\.\d{6}/\d{4}-\d{2}')

TAM_CNPJ = 14
TAM_PROCESSO = 17

# Pontuação aceita num termo que ainda assim é "só um número"
_PONTUACAO_DE_NUMERO = re.compile(r'[\s.\-/]')


def so_digitos(valor: str | None) -> str:
    """'19.630.496/0001-05' → '19630496000105'."""
    return re.sub(r'\D', '', valor or '')


def _unicos(valores) -> list[str]:
    """Preserva a ordem de aparição e remove repetidos."""
    vistos, saida = set(), []
    for v in valores:
        if v not in vistos:
            vistos.add(v)
            saida.append(v)
    return saida


def extrair_cnpjs(texto: str | None) -> list[str]:
    """Todos os CNPJs do texto, normalizados. Cobre as duas grafias."""
    if not texto:
        return []
    achados = [so_digitos(m) for m in _RE_CNPJ.findall(texto)]
    achados += _RE_CNPJ_DIGITOS.findall(texto)
    return _unicos(achados)


def extrair_processos(texto: str | None) -> list[str]:
    """Todos os números de processo administrativo, normalizados."""
    if not texto:
        return []
    return _unicos(so_digitos(m) for m in _RE_PROCESSO.findall(texto))


def formatar_identificador(tipo: str, digitos: str) -> str | None:
    """Dígitos → a grafia com pontuação, que é como o número sai impresso.

    Serve para procurar o número dentro do PDF: o índice guarda só dígitos, mas
    a página traz `19.630.496/0001-05`.
    """
    d = so_digitos(digitos)
    if tipo == 'cnpj' and len(d) == TAM_CNPJ:
        return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}'
    if tipo == 'processo' and len(d) == TAM_PROCESSO:
        return f'{d[:5]}.{d[5:11]}/{d[11:15]}-{d[15:]}'
    return None


def termos_para_pdf(consulta: str) -> list[str]:
    """O que procurar dentro da página do PDF, a partir do que foi digitado.

    Para texto livre devolve o próprio termo. Para identificador devolve as
    duas grafias — o usuário pode ter digitado só os dígitos, e no PDF o número
    aparece pontuado.
    """
    tipo, normalizado = classificar_consulta(consulta)
    if tipo == 'texto':
        return [normalizado] if normalizado else []

    formatado = formatar_identificador(tipo, normalizado)
    return [t for t in (formatado, normalizado) if t]


def termos_para_grifo(consulta: str) -> list[str]:
    """O que grifar no texto da matéria.

    Diferente de ``termos_para_pdf``: no PDF a busca é literal e a frase
    inteira é o alvo; no texto vale grifar também as palavras soltas, porque é
    assim que o Meilisearch casa — quem procurou "fator acidentário" achou a
    matéria por causa das duas palavras, e esperaria ver as duas marcadas.
    """
    tipo, normalizado = classificar_consulta(consulta)
    if tipo != 'texto':
        return termos_para_pdf(consulta)
    if not normalizado:
        return []

    palavras = [p.strip('"\'.,;:()[]') for p in normalizado.split()]
    return [normalizado] + [p for p in palavras if len(p) >= 3]


def orgao_raiz(hierarquia: str | None) -> str | None:
    """Primeiro nível de 'Ministério X/Autarquia Y/Diretoria Z'.

    A hierarquia completa tem centenas de valores distintos e não vira faceta
    usável; a raiz tem dezenas.
    """
    if not hierarquia:
        return None
    return (hierarquia.split('/')[0] or '').strip() or None


def classificar_consulta(termo: str) -> tuple[str, str]:
    """Decide por qual campo a consulta vai. Devolve (tipo, termo_normalizado).

    tipo é 'cnpj', 'processo' ou 'texto'.

    O identificador só é reconhecido quando o termo **inteiro** é o número —
    aceitando pontuação e espaço. Sem esse guarda, "portaria 19630496000105 de
    agosto" viraria busca de CNPJ e perderia o resto da frase.
    """
    termo = (termo or '').strip()
    if not termo:
        return ('texto', '')

    digitos = so_digitos(termo)
    if digitos and not _PONTUACAO_DE_NUMERO.sub('', termo).strip(digitos):
        if len(digitos) == TAM_CNPJ:
            return ('cnpj', digitos)
        if len(digitos) == TAM_PROCESSO:
            return ('processo', digitos)

    return ('texto', termo)


# ---------------------------------------------------------------- o índice

def _client() -> MeilisearchClient:
    return MeilisearchClient(MEILISEARCH_HOST, MEILISEARCH_API_KEY)


def is_available() -> bool:
    """O Meilisearch responde? Falha aqui nunca vira exceção para quem chama."""
    try:
        _client().health()
        return True
    except Exception as exc:  # noqa: BLE001 — indisponibilidade não é erro de programa
        logger.info('DOU busca: Meilisearch indisponível (%s)', exc)
        return False


def get_index(nome: str | None = None):
    """Índice pronto para uso, com os atributos aplicados de forma idempotente."""
    client = _client()
    indice = client.get_or_create_index(uid=nome or MEILI_INDEX, primary_key='id')

    if list(indice.get_searchable_attributes() or []) != _SEARCHABLE:
        client.wait_for_task(
            indice.update_searchable_attributes(_SEARCHABLE).task_uid,
            timeout_in_ms=20000)

    if set(indice.get_filterable_attributes() or []) != set(_FILTERABLE):
        client.wait_for_task(
            indice.update_filterable_attributes(_FILTERABLE).task_uid,
            timeout_in_ms=20000)

    if set(indice.get_sortable_attributes() or []) != set(_SORTABLE):
        client.wait_for_task(
            indice.update_sortable_attributes(_SORTABLE).task_uid,
            timeout_in_ms=20000)

    # Comparar antes de gravar, como nos três acima. Sem a comparação, TODA
    # busca enfileirava uma tarefa de settings e ficava esperando por ela: com
    # o Meilisearch ocupado (uma captura ou reindexação em curso), a espera
    # estourava o timeout e a tela mostrava "A busca falhou".
    tolerancia = indice.get_typo_tolerance()
    if (not tolerancia.enabled
            or list(tolerancia.disable_on_attributes or []) != _SEM_TOLERANCIA):
        client.wait_for_task(
            indice.update_typo_tolerance(
                TypoTolerance(enabled=True, disable_on_attributes=_SEM_TOLERANCIA)
            ).task_uid, timeout_in_ms=20000)

    return indice


def drop_index(nome: str) -> None:
    """Remove um índice. Existe para o teste limpar o índice dele."""
    try:
        _client().delete_index_if_exists(nome)
    except Exception as exc:  # noqa: BLE001
        logger.warning('DOU busca: falha ao remover o índice %s: %s', nome, exc)


def aguardar_indexacao(indice=None, timeout_ms: int = 600000) -> None:
    """Espera a fila do Meilisearch esvaziar para este índice.

    ``add_documents`` é assíncrono: devolve na hora e o documento só fica
    buscável depois. Quem indexa e consulta em seguida — o teste, a
    reindexação — precisa esperar, senão consulta um índice ainda vazio.

    Recebe o **nome** do índice, nunca chama ``get_index``: aquela função
    reconfigura os atributos e o `wait_for_task` dela ficaria na fila atrás dos
    documentos que estamos justamente esperando, estourando o timeout.
    """
    uid = indice.uid if hasattr(indice, 'uid') else (indice or MEILI_INDEX)
    try:
        client = _client()
        for tarefa in client.get_tasks(index_ids=[uid]).results:
            if tarefa.status in ('enqueued', 'processing'):
                client.wait_for_task(tarefa.uid, timeout_in_ms=timeout_ms)
    except Exception as exc:  # noqa: BLE001
        logger.warning('DOU busca: falha ao aguardar a indexação: %s', exc)


# ------------------------------------------------------------- indexação

def montar_documento(artigo) -> dict:
    """DouArticle → documento do índice."""
    texto = artigo.texto or ''
    return {
        'id': artigo.id,
        'edition_id': artigo.edition_id,
        'identifica': artigo.identifica or '',
        'ementa': artigo.ementa or '',
        'titulo': artigo.titulo or '',
        'texto': texto,
        'orgao_hierarquia': artigo.orgao_hierarquia or '',
        'orgao_raiz': orgao_raiz(artigo.orgao_hierarquia) or '—',
        'art_type': artigo.art_type or '—',
        'pub_name': artigo.pub_name or '—',
        'edicao': artigo.edicao or '',
        'pagina': artigo.pagina or '',
        'pagina_num': artigo.pagina_num,
        'pdf_page': artigo.pdf_page or '',
        # AAAAMMDD inteiro, não timestamp: timestamp depende de fuso e erra o
        # dia no filtro por data.
        'pub_date_num': int(artigo.pub_date.strftime('%Y%m%d')) if artigo.pub_date else 0,
        'data_br': artigo.pub_date.strftime('%d/%m/%Y') if artigo.pub_date else '',
        'cnpjs': extrair_cnpjs(texto),
        'processos': extrair_processos(texto),
    }


def index_articles(artigos, indice=None) -> int:
    """Indexa uma coleção de DouArticle. Devolve quantos foram enviados.

    Falha aqui **nunca** derruba a captura: a fase 1 não pode passar a depender
    da fase 2. Erro é registrado e a matéria entra no índice na próxima
    reindexação.
    """
    artigos = list(artigos or [])
    if not artigos:
        return 0

    try:
        indice = indice or get_index()
        documentos = [montar_documento(a) for a in artigos]
        for inicio in range(0, len(documentos), LOTE_PADRAO):
            indice.add_documents(documentos[inicio:inicio + LOTE_PADRAO])
        return len(documentos)
    except Exception as exc:  # noqa: BLE001 — indexar não derruba a captura
        logger.error('DOU busca: falha ao indexar %d matéria(s): %s', len(artigos), exc)
        return 0


def remove_articles(ids, indice=None) -> int:
    """Tira do índice as matérias que saíram do banco. Devolve quantas.

    Apagar matéria do MySQL não a tira do Meilisearch: o índice guardaria um
    resultado que leva a um 404. Todo caminho que exclui matéria precisa passar
    por aqui — foi assim que o teste de ingestão deixou 36 documentos órfãos no
    índice de produção, e eles apareciam em primeiro lugar na busca.
    """
    ids = [int(i) for i in (ids or [])]
    if not ids:
        return 0
    try:
        indice = indice or get_index()
        indice.delete_documents([str(i) for i in ids])
        return len(ids)
    except Exception as exc:  # noqa: BLE001 — limpeza de índice não derruba nada
        logger.error('DOU busca: falha ao remover %d documento(s): %s', len(ids), exc)
        return 0


def reindex_all(desde=None, lote: int = LOTE_PADRAO, indice=None) -> int:
    """Reconstrói o índice a partir do banco. Devolve o total indexado.

    Percorre por id crescente em blocos, para não carregar centenas de milhares
    de matérias na memória de uma vez.
    """
    from app.models import DouArticle  # import tardio: evita ciclo com models

    indice = indice or get_index()
    query_base = DouArticle.query
    if desde is not None:
        query_base = query_base.filter(DouArticle.pub_date >= desde)

    total = 0
    ultimo_id = 0
    while True:
        bloco = (query_base.filter(DouArticle.id > ultimo_id)
                 .order_by(DouArticle.id).limit(lote).all())
        if not bloco:
            break
        indice.add_documents([montar_documento(a) for a in bloco])
        total += len(bloco)
        ultimo_id = bloco[-1].id
        logger.info('DOU busca: %d matéria(s) indexada(s)', total)

    return total


# ---------------------------------------------------------------- consulta

def search(termo: str, filtros: dict | None = None, ordem: str = 'relevancia',
           pagina: int = 1, por_pagina: int = 20, indice=None) -> dict:
    """Busca no acervo. Devolve sempre um dicionário, mesmo em falha.

    Chaves: hits, total, ms, facetas, tipo_consulta, indisponivel.
    """
    vazio = {'hits': [], 'total': 0, 'total_navegavel': 0, 'ms': 0, 'facetas': {},
             'tipo_consulta': 'texto', 'indisponivel': False}

    tipo, normalizado = classificar_consulta(termo)
    if not normalizado:
        return vazio

    try:
        indice = indice or get_index()
        resultado = indice.search(
            normalizado,
            offset=(max(pagina, 1) - 1) * por_pagina,
            limit=por_pagina,
            filter=montar_filtro(filtros),
            facets=_FACETAS,
            attributes_to_highlight=['identifica', 'ementa', 'texto'],
            highlight_pre_tag=MARCA_INI,
            highlight_post_tag=MARCA_FIM,
            attributes_to_crop=['texto'],
            crop_length=TAM_TRECHO,
            sort=['pub_date_num:desc'] if ordem == 'data' else None,
        )
    except Exception as exc:  # noqa: BLE001 — buscar não derruba a tela
        logger.error('DOU busca: falha na consulta %r: %s', termo, exc)
        return {**vazio, 'indisponivel': True}

    facetas = resultado.facet_distribution or {}
    estimado = resultado.estimated_total_hits or 0

    # `estimated_total_hits` para no teto de paginação do Meilisearch (padrão
    # 1.000), então termos comuns reportariam sempre "1.000". As contagens de
    # faceta NÃO têm esse teto: "licitação" informa 1.000 no estimado e 5.139
    # somando as facetas. Como `pub_name` está sempre presente no documento, a
    # soma da distribuição dele é o total exato — usar isso evita subnotificar
    # em 5x nos termos mais buscados.
    por_secao = facetas.get('pub_name') or {}
    total = max(estimado, sum(por_secao.values())) if por_secao else estimado

    return {
        'hits': [_formatar_hit(h, tipo, normalizado) for h in resultado.hits],
        'total': total,
        # Quantos a paginação consegue alcançar: além do teto, o Meilisearch
        # não entrega mais páginas, e a tela precisa disso para não oferecer
        # uma página que voltaria vazia.
        'total_navegavel': min(total, MAX_TOTAL_HITS),
        'ms': resultado.processing_time_ms or 0,
        'facetas': facetas,
        'tipo_consulta': tipo,
        'indisponivel': False,
    }


def destacar(valor: str | None) -> str:
    """Escapa o HTML do texto e só então converte a marca em ``<mark>``.

    A ordem importa: escapar depois de inserir a tag apagaria o destaque;
    inserir a tag antes de escapar deixaria o '<' do próprio texto do DOU
    virar elemento na página.
    """
    if not valor:
        return ''
    return (html.escape(valor, quote=False)
            .replace(MARCA_INI, '<mark>')
            .replace(MARCA_FIM, '</mark>'))


def trecho_do_identificador(texto: str | None, digitos: str,
                            janela: int = TAM_JANELA_IDENTIFICADOR) -> str | None:
    """Recorta o texto em volta da ocorrência do número, já com a marca.

    Buscar por CNPJ casa no campo ``cnpjs``, que guarda só os dígitos — mas o
    texto traz o número formatado, então o Meilisearch não tem o que destacar
    em ``texto`` e devolve o começo da matéria. Num edital de 10 mil caracteres
    com o CNPJ na posição 9.700, o trecho mostrado não tinha nada a ver com a
    busca. Aqui a gente acha a ocorrência e recorta em volta dela.
    """
    if not texto or not digitos:
        return None

    for regex in (_RE_CNPJ, _RE_PROCESSO, _RE_CNPJ_DIGITOS):
        for achado in regex.finditer(texto):
            if so_digitos(achado.group()) != digitos:
                continue
            inicio = max(0, achado.start() - janela // 2)
            fim = min(len(texto), achado.end() + janela // 2)
            return (texto[inicio:achado.start()]
                    + MARCA_INI + achado.group() + MARCA_FIM
                    + texto[achado.end():fim])
    return None


def _formatar_hit(hit: dict, tipo: str = 'texto', normalizado: str = '') -> dict:
    """Achata o resultado do Meilisearch no que a tela precisa."""
    destacado = hit.get('_formatted') or {}

    if tipo in ('cnpj', 'processo'):
        trecho_bruto = trecho_do_identificador(hit.get('texto'), normalizado)
    else:
        trecho_bruto = destacado.get('texto')

    return {
        'id': hit.get('id'),
        'identifica': (destacar(destacado.get('identifica') or hit.get('identifica'))
                       or '(sem identificação)'),
        'ementa': destacar(destacado.get('ementa') or hit.get('ementa')),
        'trecho': destacar(trecho_bruto),
        'orgao_hierarquia': hit.get('orgao_hierarquia') or '',
        'orgao_raiz': hit.get('orgao_raiz') or '',
        'art_type': hit.get('art_type') or '',
        'pub_name': hit.get('pub_name') or '',
        'data_br': hit.get('data_br') or '',
        'pagina': hit.get('pagina') or '',
    }


def montar_filtro(filtros: dict | None) -> str | None:
    """Dicionário de filtros → expressão de filtro do Meilisearch.

    Valores do mesmo campo combinam com OR (marcar duas seções mostra as
    duas); campos diferentes combinam com AND (seção E órgão).
    """
    if not filtros:
        return None

    partes = []

    for campo in _FACETAS:
        valores = [v for v in (filtros.get(campo) or []) if v]
        if valores:
            ors = ' OR '.join(f'{campo} = "{_escapar(v)}"' for v in valores)
            partes.append(f'({ors})')

    de, ate = filtros.get('de'), filtros.get('ate')
    if de:
        partes.append(f"pub_date_num >= {int(de.strftime('%Y%m%d'))}")
    if ate:
        partes.append(f"pub_date_num <= {int(ate.strftime('%Y%m%d'))}")

    return ' AND '.join(partes) if partes else None


def _escapar(valor: str) -> str:
    """O filtro do Meilisearch delimita valores por aspas duplas."""
    return str(valor).replace('\\', '\\\\').replace('"', '\\"')
