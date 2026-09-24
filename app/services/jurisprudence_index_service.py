"""Índice de busca da Base de Jurisprudência — coleção Qdrant e índice
Meilisearch próprios, separados da base de conhecimento.

Separado de propósito: a jurisprudência não disputa espaço com os documentos
da base de conhecimento nas respostas do chat, e nasce com `law_firm_id` em
todo ponto — a coleção `knowledge_base` não guarda o escritório no payload e a
busca dela não filtra por tenant.

O banco é a fonte da verdade; o índice é derivado e descartável
(`scripts/reindex_jurisprudence.py` reconstrói). Indexar nunca derruba a
leitura, a importação nem a correção de uma decisão; buscar nunca derruba a
tela — falha vira `None` e a tela diz "indisponível".

Cada decisão vira:
- um trecho **ficha** (campos estruturados: resultado, teses, motivo, resumo,
  ementa, argumentos) — existe mesmo sem PDF, então a decisão importada da
  planilha já é encontrada;
- um trecho por **página** do inteiro teor, quando há PDF. O texto é extraído
  localmente (pdfplumber → Docling), sem IA, e guardado em
  `texto_integral` — reindexar não relê o PDF.

Os ids dos pontos são determinísticos (decisão + posição): assim a troca de
metadados (tese ligada ao catálogo, mesclada) atualiza o payload sem gerar
embedding de novo.
"""
from __future__ import annotations

import html
import logging
import os
import re
import threading
import uuid
from datetime import datetime
from typing import Callable, Iterable, Optional

from app.services import jurisprudence_normalizer as norm

logger = logging.getLogger(__name__)

COLECAO = os.getenv('JURISPRUDENCE_COLLECTION', 'jurisprudence')
INDICE_MEILI = os.getenv('JURISPRUDENCE_MEILI_INDEX', 'jurisprudence')
QDRANT_HOST = os.getenv('QDRANT_HOST', 'localhost')
QDRANT_PORT = int(os.getenv('QDRANT_PORT', '6333'))
MEILISEARCH_HOST = os.getenv('MEILISEARCH_HOST', 'http://localhost:7700')
MEILISEARCH_API_KEY = os.getenv('MEILISEARCH_API_KEY')
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL')
VECTOR_SIZE = int(os.getenv('VECTOR_SIZE', '0') or 0)

MAX_TRECHO = 4000           # caracteres por trecho de página (página maior é partida)
LOTE_EMBEDDING = 64
SEPARADOR_PAGINA = '\f'

_FILTRAVEIS = ['law_firm_id', 'decision_id', 'tribunal', 'resultado', 'tipo', 'uf',
               'catalogo_ids', 'processo_digits', 'kind']
_BUSCAVEIS = ['text', 'processo', 'parte_autora', 'orgao_julgador', 'relator', 'teses']
_INDICES_QDRANT = {
    'law_firm_id': 'integer', 'decision_id': 'integer', 'catalogo_ids': 'integer',
    'tribunal': 'keyword', 'resultado': 'keyword', 'tipo': 'keyword',
}
# Marcadores do grifo do Meilisearch; viram <mark> depois do escape — o texto
# da decisão tem "<" de verdade, então o escape vem antes do grifo.
_MARCA_INI, _MARCA_FIM = '\u0001', '\u0002'


class IndiceIndisponivel(RuntimeError):
    pass


# ── Clientes (injetáveis nos testes) ──────────────────────────────────

class Indice:
    """Clientes do Qdrant, do Meilisearch e do embedding.

    Nos testes: `Indice(qdrant=QdrantClient(':memory:'), embedder=falso,
    colecao='jurisprudence_test', indice_meili='jurisprudence_test')`.
    """

    def __init__(self, *, qdrant=None, meili=None, embedder: Optional[Callable] = None,
                 colecao: str = COLECAO, indice_meili: str = INDICE_MEILI, esperar_meili: bool = False):
        self._qdrant = qdrant
        self._meili = meili
        self._embedder = embedder
        self.colecao = colecao
        self.indice_meili = indice_meili
        self.esperar_meili = esperar_meili
        self._colecao_pronta = False
        self._meili_pronto = False

    @property
    def qdrant(self):
        if self._qdrant is None:
            from qdrant_client import QdrantClient
            self._qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60)
        return self._qdrant

    @property
    def meili(self):
        if self._meili is None:
            from meilisearch_python_sdk import Client
            self._meili = Client(MEILISEARCH_HOST, MEILISEARCH_API_KEY)
        return self._meili

    def embed(self, textos: list[str]) -> list[list[float]]:
        if self._embedder is not None:
            return self._embedder(textos)
        if not EMBEDDING_MODEL or VECTOR_SIZE <= 0:
            raise IndiceIndisponivel('EMBEDDING_MODEL/VECTOR_SIZE não configurados no .env')
        from openai import OpenAI
        resposta = OpenAI().embeddings.create(input=textos, model=EMBEDDING_MODEL)
        return [item.embedding for item in resposta.data]

    def garantir_colecao(self, tamanho: int) -> None:
        if self._colecao_pronta:
            return
        from qdrant_client.http import models as rest
        if not self.qdrant.collection_exists(self.colecao):
            self.qdrant.create_collection(
                collection_name=self.colecao,
                vectors_config=rest.VectorParams(size=tamanho, distance=rest.Distance.COSINE),
            )
            for campo, tipo in _INDICES_QDRANT.items():
                try:
                    self.qdrant.create_payload_index(self.colecao, campo, field_schema=tipo)
                except Exception as erro:  # modo em memória não indexa payload
                    logger.debug('índice de payload %s: %s', campo, erro)
        self._colecao_pronta = True

    def indice(self):
        """Índice do Meilisearch; configurações só quando mudam (lição do DOU:
        gravar settings a cada chamada enfileira tarefa e trava a busca)."""
        cliente = self.meili
        if not self._meili_pronto:
            indice = cliente.get_or_create_index(uid=self.indice_meili, primary_key='id')
            if set(indice.get_filterable_attributes() or []) != set(_FILTRAVEIS):
                cliente.wait_for_task(indice.update_filterable_attributes(_FILTRAVEIS).task_uid,
                                      timeout_in_ms=20000)
            if list(indice.get_searchable_attributes() or []) != _BUSCAVEIS:
                cliente.wait_for_task(indice.update_searchable_attributes(_BUSCAVEIS).task_uid,
                                      timeout_in_ms=20000)
            self._meili_pronto = True
        return cliente.index(self.indice_meili)

    def _meili_tarefa(self, tarefa) -> None:
        if self.esperar_meili:
            self.meili.wait_for_task(tarefa.task_uid, timeout_in_ms=30000)


_INDICE_PADRAO: Optional[Indice] = None


def indice_padrao() -> Indice:
    global _INDICE_PADRAO
    if _INDICE_PADRAO is None:
        _INDICE_PADRAO = Indice()
    return _INDICE_PADRAO


def configurar(indice: Optional[Indice]) -> None:
    """Troca o índice padrão (testes)."""
    global _INDICE_PADRAO
    _INDICE_PADRAO = indice


# ── Texto integral ────────────────────────────────────────────────────

def extrair_paginas(pdf_path: str) -> list[str]:
    """Texto de cada página do PDF, sem IA (pdfplumber; Docling se escaneado)."""
    from app.services.document_processor_service import DocumentProcessorService
    resultado = DocumentProcessorService().process_document(pdf_path, annotate_images=False)
    por_pagina: dict[int, list[str]] = {}
    for trecho in resultado.chunks_with_pages or []:
        texto = str((trecho or {}).get('text') or '').strip()
        if texto:
            por_pagina.setdefault(int(trecho.get('page') or 1), []).append(texto)
    if por_pagina:
        return ['\n'.join(por_pagina[p]) for p in sorted(por_pagina)]
    texto = (resultado.full_text or '').strip()
    return [texto] if texto else []


def guardar_texto(decisao, paginas: list[str]) -> None:
    paginas = [p.replace(SEPARADOR_PAGINA, ' ') for p in paginas]
    decisao.texto_integral = SEPARADOR_PAGINA.join(paginas) if paginas else None
    decisao.texto_paginas = len(paginas) or None


def paginas_da_decisao(decisao) -> list[str]:
    return (decisao.texto_integral or '').split(SEPARADOR_PAGINA) if decisao.texto_integral else []


# ── Montagem dos pontos ───────────────────────────────────────────────

def ficha(decisao) -> str:
    """Os campos estruturados em texto corrido — o trecho que existe sempre."""
    def lista(titulo, valores):
        return f'{titulo}: ' + '; '.join(valores) if valores else ''

    linhas = [
        f'{norm.TIPO_LABELS.get(decisao.tipo_documento or "", "Decisão")} · '
        f'{" · ".join(p for p in (decisao.tribunal, decisao.orgao_julgador) if p)}',
        f'Processo {decisao.processo}' if decisao.processo else '',
        f'Resultado para a empresa: {norm.RESULTADO_LABELS.get(decisao.resultado or "", "não informado")}',
        f'Julgado em {decisao.data_julgamento.strftime("%d/%m/%Y")}' if decisao.data_julgamento else '',
        f'Parte autora: {decisao.parte_autora}' if decisao.parte_autora else '',
        f'Vigência FAP: {decisao.vigencia_texto}' if decisao.vigencia_texto else '',
        lista('Teses', [t.name for t in decisao.theses] or (decisao.teses_brutas_json or [])),
        f'Por que esse resultado: {decisao.motivo_resultado}' if decisao.motivo_resultado else '',
        f'Resumo: {decisao.resumo_executivo}' if decisao.resumo_executivo else '',
        lista('Argumentos acolhidos', decisao.argumentos_acolhidos_json or []),
        lista('Argumentos rejeitados', decisao.argumentos_rejeitados_json or []),
        lista('Fundamentos', decisao.fundamentos_json or []),
        f'Ementa: {decisao.ementa}' if decisao.ementa else '',
    ]
    return '\n'.join(l for l in linhas if l)[:12000]


def _partir(texto: str, limite: int = MAX_TRECHO) -> list[str]:
    texto = texto.strip()
    if len(texto) <= limite:
        return [texto] if texto else []
    partes, atual = [], ''
    for paragrafo in re.split(r'\n{1,}', texto):
        if len(atual) + len(paragrafo) + 1 > limite and atual:
            partes.append(atual.strip())
            atual = ''
        while len(paragrafo) > limite:
            partes.append(paragrafo[:limite])
            paragrafo = paragrafo[limite:]
        atual += paragrafo + '\n'
    if atual.strip():
        partes.append(atual.strip())
    return partes


def trechos(decisao) -> list[dict]:
    saida = [{'kind': 'ficha', 'page': None, 'text': ficha(decisao)}]
    for numero, pagina in enumerate(paginas_da_decisao(decisao), start=1):
        for parte in _partir(pagina):
            saida.append({'kind': 'pagina', 'page': numero, 'text': parte})
    return saida


def metadados(decisao) -> dict:
    catalogo = {c.id for tese in decisao.theses for c in tese.catalog_theses}
    return {
        'law_firm_id': int(decisao.law_firm_id),
        'decision_id': int(decisao.id),
        'processo': decisao.processo or '',
        'processo_digits': decisao.processo_digits or '',
        'tribunal': decisao.tribunal or '',
        'orgao_julgador': decisao.orgao_julgador or '',
        'relator': decisao.relator or '',
        'uf': decisao.uf or '',
        'tipo': decisao.tipo_documento or '',
        'resultado': decisao.resultado or '',
        'data_julgamento': decisao.data_julgamento.isoformat() if decisao.data_julgamento else None,
        'parte_autora': decisao.parte_autora or '',
        'teses': [t.name for t in decisao.theses],
        'catalogo_ids': sorted(catalogo),
    }


def id_do_ponto(decision_id: int, posicao: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'intellexia:jurisprudencia:{int(decision_id)}:{int(posicao)}'))


def _filtro_qdrant(law_firm_id: int, decision_id: Optional[int] = None, excluir: Optional[int] = None):
    from qdrant_client.http import models as rest
    must = [rest.FieldCondition(key='law_firm_id', match=rest.MatchValue(value=int(law_firm_id)))]
    if decision_id is not None:
        must.append(rest.FieldCondition(key='decision_id', match=rest.MatchValue(value=int(decision_id))))
    must_not = ([rest.FieldCondition(key='decision_id', match=rest.MatchValue(value=int(excluir)))]
                if excluir is not None else None)
    return rest.Filter(must=must, must_not=must_not)


# ── Escrita ───────────────────────────────────────────────────────────

def indexar(decisao, indice: Optional[Indice] = None) -> int:
    """(Re)indexa a decisão inteira. Grava o status na decisão; quem chama faz o commit."""
    from qdrant_client.http import models as rest
    indice = indice or indice_padrao()
    partes = trechos(decisao)
    meta = metadados(decisao)
    vetores = []
    for inicio in range(0, len(partes), LOTE_EMBEDDING):
        vetores.extend(indice.embed([p['text'] for p in partes[inicio:inicio + LOTE_EMBEDDING]]))
    indice.garantir_colecao(len(vetores[0]))

    anteriores = int(decisao.index_chunks or 0)
    indice.qdrant.delete(collection_name=indice.colecao,
                         points_selector=rest.FilterSelector(filter=_filtro_qdrant(decisao.law_firm_id, decisao.id)),
                         wait=True)
    pontos = [
        rest.PointStruct(id=id_do_ponto(decisao.id, n), vector=vetor,
                         payload={**meta, 'kind': p['kind'], 'page': p['page'], 'text': p['text']})
        for n, (p, vetor) in enumerate(zip(partes, vetores))
    ]
    indice.qdrant.upsert(collection_name=indice.colecao, points=pontos, wait=True)

    try:
        docs = [{'id': id_do_ponto(decisao.id, n).replace('-', ''), **meta, 'kind': p['kind'],
                 'page': p['page'], 'text': p['text']} for n, p in enumerate(partes)]
        meili = indice.indice()
        if anteriores > len(partes):
            indice._meili_tarefa(meili.delete_documents_by_filter(f'decision_id = {int(decisao.id)}'))
        indice._meili_tarefa(meili.add_documents(docs))
    except Exception as erro:
        # Meilisearch fora não desfaz o Qdrant: a busca por texto fica sem esta
        # decisão até a próxima reindexação, e o status registra o motivo.
        decisao.index_status = decisao.INDEX_ERRO
        decisao.index_error = f'Meilisearch: {erro}'[:2000]
        decisao.index_chunks = len(partes)
        return len(partes)

    decisao.index_status = decisao.INDEX_INDEXADA
    decisao.index_error = None
    decisao.index_chunks = len(partes)
    decisao.indexed_at = datetime.now()
    return len(partes)


def atualizar_metadados(decisoes: Iterable, indice: Optional[Indice] = None) -> int:
    """Troca só o payload (teses, catálogo, resultado corrigido) — sem embedding."""
    indice = indice or indice_padrao()
    n = 0
    for decisao in decisoes:
        if decisao.index_status != decisao.INDEX_INDEXADA or not decisao.index_chunks:
            continue
        meta = metadados(decisao)
        indice.qdrant.set_payload(collection_name=indice.colecao, payload=meta,
                                  points=[id_do_ponto(decisao.id, i) for i in range(decisao.index_chunks)],
                                  wait=True)
        indice._meili_tarefa(indice.indice().update_documents(
            [{'id': id_do_ponto(decisao.id, i).replace('-', ''), **meta} for i in range(decisao.index_chunks)]))
        n += 1
    return n


def remover(law_firm_id: int, decision_id: int, indice: Optional[Indice] = None) -> None:
    from qdrant_client.http import models as rest
    indice = indice or indice_padrao()
    try:
        if indice.qdrant.collection_exists(indice.colecao):
            indice.qdrant.delete(collection_name=indice.colecao,
                                 points_selector=rest.FilterSelector(filter=_filtro_qdrant(law_firm_id, decision_id)),
                                 wait=True)
    except Exception as erro:
        logger.warning('jurisprudência: falha ao remover %s do Qdrant: %s', decision_id, erro)
    try:
        indice._meili_tarefa(indice.indice().delete_documents_by_filter(
            f'decision_id = {int(decision_id)} AND law_firm_id = {int(law_firm_id)}'))
    except Exception as erro:
        logger.warning('jurisprudência: falha ao remover %s do Meilisearch: %s', decision_id, erro)


# ── Em segundo plano ──────────────────────────────────────────────────

# Testes ligam para rodar na mesma thread.
SINCRONO = False


def preparar_e_indexar(decisao, *, extrair: bool = True, indice: Optional[Indice] = None) -> None:
    """Extrai o texto do PDF (se ainda não extraído) e indexa. Nunca levanta:
    falha vira `index_status='erro'` com o motivo."""
    aviso = None
    if extrair and decisao.pdf_path and not decisao.texto_integral and os.path.exists(decisao.pdf_path):
        try:
            guardar_texto(decisao, extrair_paginas(decisao.pdf_path))
        except Exception as erro:
            # PDF sem texto aproveitável não tira a decisão do índice: ela
            # entra pela ficha, e o motivo fica registrado.
            aviso = f'Inteiro teor não extraído do PDF: {erro}'[:2000]
    try:
        indexar(decisao, indice)
        if aviso and decisao.index_status == decisao.INDEX_INDEXADA:
            decisao.index_error = aviso
    except Exception as erro:
        logger.warning('jurisprudência: falha ao indexar %s: %s', getattr(decisao, 'id', '?'), erro)
        decisao.index_status = decisao.INDEX_ERRO
        decisao.index_error = str(erro)[:2000]


def agendar(law_firm_id: int, decision_ids: Iterable[int], *, somente_metadados: bool = False) -> None:
    """Indexa (ou só atualiza metadados de) decisões fora da requisição."""
    ids = [int(i) for i in dict.fromkeys(decision_ids) if i]
    if not ids:
        return
    if SINCRONO:
        _rodar(None, law_firm_id, ids, somente_metadados)
        return
    from flask import current_app
    threading.Thread(target=_rodar, args=(current_app._get_current_object(), law_firm_id, ids, somente_metadados),
                     daemon=True, name=f'jurisprudence-index-{ids[0]}').start()


def _rodar(app_obj, law_firm_id: int, ids: list[int], somente_metadados: bool) -> None:
    from contextlib import nullcontext
    from app.models import db, JurisprudenceDecision
    with (app_obj.app_context() if app_obj is not None else nullcontext()):
        try:
            for inicio in range(0, len(ids), 50):
                lote = JurisprudenceDecision.query.filter(
                    JurisprudenceDecision.law_firm_id == law_firm_id,
                    JurisprudenceDecision.id.in_(ids[inicio:inicio + 50])).all()
                if somente_metadados:
                    try:
                        atualizar_metadados(lote)
                    except Exception as erro:
                        logger.warning('jurisprudência: falha ao atualizar metadados: %s', erro)
                else:
                    for decisao in lote:
                        preparar_e_indexar(decisao)
                        db.session.commit()
        finally:
            if app_obj is not None:
                db.session.remove()


# ── Busca ─────────────────────────────────────────────────────────────

def _grifar(texto: str) -> str:
    return (html.escape(texto or '')
            .replace(_MARCA_INI, '<mark>').replace(_MARCA_FIM, '</mark>'))


def buscar_inteiro_teor(law_firm_id: int, consulta: str, *, tribunais=(), resultados=(), tipos=(),
                        limite: int = 40, indice: Optional[Indice] = None) -> Optional[list[dict]]:
    """Uma entrada por decisão (a página que melhor casou), com o trecho grifado.

    Número de processo vira filtro exato em `processo_digits`, nunca texto: o
    tokenizador quebra o número na pontuação (a mesma lição da busca do DOU).
    `None` = índice indisponível.
    """
    indice = indice or indice_padrao()
    filtros = [f'law_firm_id = {int(law_firm_id)}']

    def em(campo, valores):
        valores = [v for v in valores if v and re.match(r'^[\w-]+$', str(v))]
        if valores:
            filtros.append(f'{campo} IN [{", ".join(repr(str(v)) for v in valores)}]'.replace("'", '"'))
    em('tribunal', tribunais)
    em('resultado', resultados)
    em('tipo', tipos)

    termo = (consulta or '').strip()
    if norm.parece_numero_de_processo(termo):
        filtros.append(f'processo_digits = "{norm.digitos(termo)}"')
        termo = ''
    try:
        resposta = indice.indice().search(
            termo or None,
            filter=' AND '.join(filtros),
            limit=limite,
            distinct='decision_id',
            matching_strategy='all',
            attributes_to_retrieve=['decision_id', 'kind', 'page'],
            attributes_to_crop=['text'],
            crop_length=45,
            attributes_to_highlight=['text'],
            highlight_pre_tag=_MARCA_INI,
            highlight_post_tag=_MARCA_FIM,
        )
    except Exception as erro:
        logger.info('jurisprudência: busca no inteiro teor indisponível: %s', erro)
        return None
    saida = []
    for hit in resposta.hits or []:
        formatado = hit.get('_formatted') or {}
        saida.append({
            'decision_id': int(hit.get('decision_id')),
            'kind': hit.get('kind'),
            'page': hit.get('page'),
            'trecho': _grifar(formatado.get('text') or ''),
        })
    return saida


def parecidas(decisao, limite: int = 6, indice: Optional[Indice] = None) -> Optional[list[dict]]:
    """Decisões semanticamente próximas (pelo vetor da ficha). `None` = indisponível."""
    if decisao.index_status != decisao.INDEX_INDEXADA:
        return None
    indice = indice or indice_padrao()
    try:
        pontos = indice.qdrant.retrieve(collection_name=indice.colecao,
                                        ids=[id_do_ponto(decisao.id, 0)], with_vectors=True)
        if not pontos:
            return None
        resposta = indice.qdrant.query_points(
            collection_name=indice.colecao, query=pontos[0].vector,
            query_filter=_filtro_qdrant(decisao.law_firm_id, excluir=decisao.id),
            limit=limite * 6, with_payload=['decision_id', 'kind', 'page'],
        )
    except Exception as erro:
        logger.info('jurisprudência: decisões parecidas indisponíveis: %s', erro)
        return None
    melhores: dict[int, dict] = {}
    for ponto in resposta.points or []:
        d_id = int((ponto.payload or {}).get('decision_id'))
        if d_id not in melhores:
            melhores[d_id] = {'decision_id': d_id, 'score': float(ponto.score or 0),
                              'page': (ponto.payload or {}).get('page')}
        if len(melhores) >= limite:
            break
    return list(melhores.values())


def remover_escritorio(law_firm_id: int, indice: Optional[Indice] = None) -> list[str]:
    """Apaga todos os pontos do escritório nos dois índices (reset da base).
    Devolve o que falhou — vazio quando limpou tudo."""
    from qdrant_client.http import models as rest
    indice = indice or indice_padrao()
    falhas = []
    try:
        if indice.qdrant.collection_exists(indice.colecao):
            indice.qdrant.delete(collection_name=indice.colecao,
                                 points_selector=rest.FilterSelector(filter=_filtro_qdrant(law_firm_id)),
                                 wait=True)
    except Exception as erro:
        logger.warning('jurisprudência: reset do Qdrant falhou (%s): %s', law_firm_id, erro)
        falhas.append('vetores do Qdrant')
    try:
        indice._meili_tarefa(indice.indice().delete_documents_by_filter(f'law_firm_id = {int(law_firm_id)}'))
    except Exception as erro:
        logger.warning('jurisprudência: reset do Meilisearch falhou (%s): %s', law_firm_id, erro)
        falhas.append('índice de busca')
    return falhas
