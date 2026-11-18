"""Anexos das contestações do FAP: índice, busca e consultas (FB-08).

Fonte única da tela (Central e cálculo FAP), do MCP e da API.

- **Índice próprio no Meilisearch** (``FAP_ANEXOS_MEILI_INDEX``, padrão
  ``fap_anexos``; teste ``fap_anexos_test``), com ``law_firm_id`` em todo
  documento e em todo filtro. O banco é a fonte da verdade: o índice se
  reconstrói de ``fap_contestacao_anexos.texto`` sem reler PDF.
- **Número não é texto** (a lição do DOU): 10 dígitos = NB, 14 = CNPJ,
  8 = raiz — viram filtro exato.
- **Indexar nunca derruba o registro e buscar nunca derruba a tela**: índice
  fora do ar cai para ``LIKE`` no banco, com ``fonte='banco'``.
- O HISMED tem dado de saúde (CID): quem chama confere o módulo
  ``disputes_center`` — a busca não é porta lateral.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
from collections import Counter
from typing import Iterable, Optional

from app.models import db, Benefit, FapContestacaoAnexo
from app.services.fap_anexos_conteudo import TIPOS
from app.utils.cnpj import apenas_digitos

logger = logging.getLogger(__name__)

INDICE_MEILI = os.getenv('FAP_ANEXOS_MEILI_INDEX', 'fap_anexos')
MEILISEARCH_HOST = os.getenv('MEILISEARCH_HOST', 'http://localhost:7700')
MEILISEARCH_API_KEY = os.getenv('MEILISEARCH_API_KEY')

_FILTRAVEIS = ['law_firm_id', 'ano_vigencia', 'cnpj', 'cnpj_raiz', 'nb', 'instancia', 'elemento',
               'tipo_documento', 'cids', 'cat_tipo', 'especie', 'benefit_id']
_BUSCAVEIS = ['texto', 'nome']
_MAX_TEXTO_INDICE = 60_000
_LOTE = 500
_MARCA_INI, _MARCA_FIM = '\x02', '\x03'

_estado = {'cliente': None, 'pronto': False, 'indice': INDICE_MEILI, 'esperar': False}


def configurar(indice: Optional[str] = None, esperar: bool = False) -> None:
    """Troca o nome do índice (testes) e reinicia a configuração."""
    _estado.update(indice=indice or INDICE_MEILI, pronto=False, esperar=esperar)


def _cliente():
    if _estado['cliente'] is None:
        from meilisearch_python_sdk import Client
        _estado['cliente'] = Client(MEILISEARCH_HOST, MEILISEARCH_API_KEY)
    return _estado['cliente']


def _indice():
    cliente = _cliente()
    if not _estado['pronto']:
        indice = cliente.get_or_create_index(uid=_estado['indice'], primary_key='id')
        if set(indice.get_filterable_attributes() or []) != set(_FILTRAVEIS):
            cliente.wait_for_task(indice.update_filterable_attributes(_FILTRAVEIS).task_uid, timeout_in_ms=20000)
        if list(indice.get_searchable_attributes() or []) != _BUSCAVEIS:
            cliente.wait_for_task(indice.update_searchable_attributes(_BUSCAVEIS).task_uid, timeout_in_ms=20000)
        _estado['pronto'] = True
    return cliente.index(_estado['indice'])


def campos(anexo: FapContestacaoAnexo) -> dict:
    try:
        return json.loads(anexo.campos_json) if anexo.campos_json else {}
    except ValueError:
        return {}


def _documento(a: FapContestacaoAnexo) -> dict:
    c = campos(a)
    return {
        'id': a.id, 'law_firm_id': a.law_firm_id, 'anexo_id': a.anexo_id,
        'ano_vigencia': a.ano_vigencia, 'cnpj': a.cnpj, 'cnpj_raiz': a.cnpj_raiz,
        'nb': a.nb or '', 'benefit_id': a.benefit_id, 'instancia': a.instancia,
        'elemento': a.elemento or '', 'tipo_documento': a.tipo_documento or '',
        'cids': c.get('cids') or [], 'cat_tipo': c.get('cat_tipo') or '', 'especie': c.get('especie') or '',
        'nome': a.nome or '', 'texto': (a.texto or '')[:_MAX_TEXTO_INDICE],
    }


def indexar_pendentes(law_firm_id: Optional[int] = None, *, refazer: bool = False,
                      log=lambda m: None) -> dict:
    """Manda ao índice os anexos com texto lido e ainda não indexados."""
    q = FapContestacaoAnexo.query.filter(FapContestacaoAnexo.texto_status == FapContestacaoAnexo.TEXTO_OK)
    if law_firm_id:
        q = q.filter(FapContestacaoAnexo.law_firm_id == law_firm_id)
    if not refazer:
        q = q.filter(db.or_(FapContestacaoAnexo.index_status.is_(None),
                            FapContestacaoAnexo.index_status != 'ok'))
    ids = [i for (i,) in q.with_entities(FapContestacaoAnexo.id).order_by(FapContestacaoAnexo.id)]
    rel = {'indexados': 0, 'erros': 0, 'erro': None}
    for inicio in range(0, len(ids), _LOTE):
        lote = FapContestacaoAnexo.query.filter(FapContestacaoAnexo.id.in_(ids[inicio:inicio + _LOTE])).all()
        try:
            tarefa = _indice().add_documents([_documento(a) for a in lote])
            if _estado['esperar']:
                _cliente().wait_for_task(tarefa.task_uid, timeout_in_ms=60000)
            status = 'ok'
            rel['indexados'] += len(lote)
        except Exception as erro:
            logger.info('anexos FAP: indexação indisponível: %s', erro)
            status = 'erro'
            rel['erros'] += len(lote)
            rel['erro'] = str(erro)[:200]
        for a in lote:
            a.index_status = status
        db.session.commit()
        if status == 'erro':
            break  # índice fora do ar: o resto fica para a próxima rodada
        if (inicio // _LOTE) % 20 == 19:
            log(f'  {rel["indexados"]}/{len(ids)} indexados')
    return rel


# ---------------------------------------------------------------- consultas

def _item(a: FapContestacaoAnexo, trecho: Optional[str] = None) -> dict:
    c = campos(a)
    return {
        'id': a.id, 'anexo_id': a.anexo_id, 'vigencia': a.ano_vigencia, 'cnpj': a.cnpj, 'nb': a.nb,
        'benefit_id': a.benefit_id, 'instancia': a.instancia, 'elemento': a.elemento,
        'tipo_documento': a.tipo_documento, 'tipo_documento_label': TIPOS.get(a.tipo_documento or '', a.tipo_documento),
        'nome': a.nome, 'data_envio': a.data_envio.isoformat() if a.data_envio else None,
        'tamanho': a.tamanho, 'cids': c.get('cids') or [], 'cat_tipo': c.get('cat_tipo'),
        'especie': c.get('especie'), 'tem_arquivo': bool(a.arquivo), 'trecho': trecho,
    }


def anexos_do_beneficio(law_firm_id: int, *, benefit_id: Optional[int] = None,
                        ano: Optional[int] = None, cnpj: Optional[str] = None,
                        nb: Optional[str] = None) -> list[dict]:
    """Documentos enviados de um benefício: pelo ``benefit_id`` da Central ou
    por vigência + CNPJ + NB (tela do cálculo FAP)."""
    q = FapContestacaoAnexo.query.filter(FapContestacaoAnexo.law_firm_id == law_firm_id)
    if benefit_id:
        q = q.filter(FapContestacaoAnexo.benefit_id == benefit_id)
    elif ano and cnpj and nb:
        q = q.filter(FapContestacaoAnexo.ano_vigencia == int(ano),
                     FapContestacaoAnexo.cnpj == apenas_digitos(cnpj).zfill(14),
                     FapContestacaoAnexo.nb == apenas_digitos(nb))
    else:
        return []
    anexos = q.order_by(FapContestacaoAnexo.instancia, FapContestacaoAnexo.data_envio,
                        FapContestacaoAnexo.id).all()
    return [_item(a) for a in anexos]


def anexos_das_chaves(law_firm_id: int, chaves: Iterable[tuple]) -> dict[tuple, list[dict]]:
    """{(ano, cnpj, nb): [documentos]} numa consulta só — a página do cálculo FAP."""
    chaves = {(int(a), apenas_digitos(str(c)).zfill(14), apenas_digitos(str(n))) for a, c, n in chaves if a and c and n}
    if not chaves:
        return {}
    saida: dict[tuple, list[dict]] = {}
    anexos = (FapContestacaoAnexo.query
              .filter(FapContestacaoAnexo.law_firm_id == law_firm_id,
                      FapContestacaoAnexo.nb.in_({n for _, _, n in chaves}))
              .order_by(FapContestacaoAnexo.instancia, FapContestacaoAnexo.data_envio, FapContestacaoAnexo.id))
    for a in anexos:
        chave = (a.ano_vigencia, a.cnpj, a.nb)
        if chave in chaves:
            saida.setdefault(chave, []).append(_item(a))
    return saida


def beneficios_com_documento(law_firm_id: int, instancia: Optional[int] = None):
    """Subconsulta com os ``benefit_id`` que têm documento (na instância, se dada)."""
    q = (db.session.query(FapContestacaoAnexo.benefit_id)
         .filter(FapContestacaoAnexo.law_firm_id == law_firm_id, FapContestacaoAnexo.benefit_id.isnot(None)))
    if instancia:
        q = q.filter(FapContestacaoAnexo.instancia == int(instancia))
    return q.distinct()


def documentacao_por_resultado(law_firm_id: int, base_query=None) -> dict:
    """Contestado com e sem documento × resultado, por instância.

    ``base_query`` é a consulta de benefícios já filtrada da tela (a mesma do
    resto dos cartões); sem ela, todos os benefícios do escritório.
    """
    base = base_query if base_query is not None else Benefit.query.filter(Benefit.law_firm_id == law_firm_id)
    saida = {}
    for instancia, coluna in ((1, Benefit.first_instance_status), (2, Benefit.second_instance_status)):
        # Agregado no banco (a Central tem dezenas de milhares de benefícios);
        # o vínculo é inteiro (benefit_id), sem comparar texto entre tabelas.
        # Duas contagens agrupadas (todos e só os com documento): agrupar por
        # um CASE com subconsulta quebra no only_full_group_by do MySQL.
        decididos = base.order_by(None).filter(coluna.isnot(None), coluna != '')

        def por_status(q):
            contagem = Counter()
            for status, n in q.with_entities(coluna, db.func.count(Benefit.id)).group_by(coluna):
                contagem[_resultado(status)] += int(n)
            return contagem

        todos = por_status(decididos)
        com = por_status(decididos.filter(Benefit.id.in_(beneficios_com_documento(law_firm_id, instancia))))
        grupos = {'com': com, 'sem': todos - com}
        saida[instancia] = {k: _placar(v) for k, v in grupos.items()}
    return saida


def _resultado(status: Optional[str]) -> str:
    s = (status or '').lower()
    if s in ('approved', 'deferido', 'partially_approved', 'deferido_parcial') or s.startswith('defer'):
        return 'deferido'
    if s in ('rejected', 'indeferido') or s.startswith('indefer'):
        return 'indeferido'
    return 'outro'


def _placar(contagem: Counter) -> dict:
    decididos = contagem['deferido'] + contagem['indeferido']
    return {'deferido': contagem['deferido'], 'indeferido': contagem['indeferido'],
            'outro': contagem['outro'], 'decididos': decididos,
            'taxa_deferimento': round(100 * contagem['deferido'] / decididos, 1) if decididos else None}


# ---------------------------------------------------------------- busca

def _filtro_texto(valores) -> list[str]:
    return [str(v) for v in (valores if isinstance(valores, (list, tuple, set)) else [valores])
            if v not in (None, '') and re.match(r'^[\w.\-]+$', str(v))]


def _grifar(texto: str) -> str:
    """Trecho do Meilisearch → HTML seguro com <mark> (escapa antes de marcar)."""
    return (html.escape(texto or '').replace(_MARCA_INI, '<mark>').replace(_MARCA_FIM, '</mark>'))


def _trecho_do_banco(texto: str, termo: str, largura: int = 160) -> str:
    if not texto:
        return ''
    pos = texto.lower().find(termo.lower()) if termo else -1
    if pos < 0:
        return html.escape(texto[:largura * 2])
    ini = max(0, pos - largura)
    pedaco = texto[ini:pos + len(termo) + largura]
    i = pos - ini
    return (html.escape(pedaco[:i]) + '<mark>' + html.escape(pedaco[i:i + len(termo)]) + '</mark>'
            + html.escape(pedaco[i + len(termo):]))


def pesquisar(law_firm_id: int, termo: Optional[str] = None, *, nb=None, cnpj=None, vigencia=None,
              tipo_documento=None, cid=None, instancia=None, cat_tipo=None,
              limite: int = 20, deslocamento: int = 0) -> dict:
    """Busca nos anexos do escritório. ``total_e_minimo`` quando o índice só
    estima (o Meilisearch satura em 1.000)."""
    termo = (termo or '').strip()
    digitos = apenas_digitos(termo) if termo else ''
    raiz = None
    if termo and digitos == re.sub(r'[\s./-]', '', termo):  # o termo inteiro é número
        if len(digitos) == 10:
            nb, termo = digitos, ''
        elif len(digitos) == 14:
            cnpj, termo = digitos, ''
        elif len(digitos) == 8:
            raiz, termo = digitos, ''
    nb = apenas_digitos(nb) if nb else None
    cnpj = apenas_digitos(cnpj).zfill(14) if cnpj else None
    tipos = [t.upper() for t in _filtro_texto(tipo_documento)]
    cids = [c.upper() for c in _filtro_texto(cid)]

    if termo:
        filtros = [f'law_firm_id = {int(law_firm_id)}']
        for campo, valor in (('nb', nb), ('cnpj', cnpj), ('cnpj_raiz', raiz)):
            if valor:
                filtros.append(f'{campo} = "{valor}"')
        if vigencia:
            filtros.append(f'ano_vigencia = {int(vigencia)}')
        if instancia:
            filtros.append(f'instancia = {int(instancia)}')
        if tipos:
            filtros.append('tipo_documento IN [' + ', '.join(f'"{t}"' for t in tipos) + ']')
        if cids:
            filtros.append('cids IN [' + ', '.join(f'"{c}"' for c in cids) + ']')
        if cat_tipo:
            filtros.append(f'cat_tipo = "{_filtro_texto(cat_tipo.upper())[0]}"' if _filtro_texto(cat_tipo) else 'id = -1')
        try:
            r = _indice().search(
                termo, filter=' AND '.join(filtros), limit=limite, offset=deslocamento,
                matching_strategy='all', attributes_to_retrieve=['id'],
                attributes_to_crop=['texto'], crop_length=40, attributes_to_highlight=['texto'],
                highlight_pre_tag=_MARCA_INI, highlight_post_tag=_MARCA_FIM,
            )
            ids = [int(h['id']) for h in r.hits or []]
            trechos = {int(h['id']): _grifar((h.get('_formatted') or {}).get('texto') or '') for h in r.hits or []}
            por_id = {a.id: a for a in FapContestacaoAnexo.query.filter(
                FapContestacaoAnexo.law_firm_id == law_firm_id, FapContestacaoAnexo.id.in_(ids or [-1]))}
            total = int(r.estimated_total_hits or 0)
            return {'total': total, 'total_e_minimo': total >= 1000, 'fonte': 'indice',
                    'itens': [_item(por_id[i], trechos.get(i)) for i in ids if i in por_id]}
        except Exception as erro:
            logger.info('anexos FAP: busca no índice indisponível, usando o banco: %s', erro)

    q = FapContestacaoAnexo.query.filter(FapContestacaoAnexo.law_firm_id == law_firm_id)
    if nb:
        q = q.filter(FapContestacaoAnexo.nb == nb)
    if cnpj:
        q = q.filter(FapContestacaoAnexo.cnpj == cnpj)
    if raiz:
        q = q.filter(FapContestacaoAnexo.cnpj_raiz == raiz)
    if vigencia:
        q = q.filter(FapContestacaoAnexo.ano_vigencia == int(vigencia))
    if instancia:
        q = q.filter(FapContestacaoAnexo.instancia == int(instancia))
    if tipos:
        q = q.filter(FapContestacaoAnexo.tipo_documento.in_(tipos))
    for c in cids:
        q = q.filter(FapContestacaoAnexo.campos_json.like(f'%"{c}"%'))
    if cat_tipo:
        q = q.filter(FapContestacaoAnexo.campos_json.like(f'%"cat_tipo": "{cat_tipo.upper()}"%'))
    for palavra in termo.split():
        q = q.filter(FapContestacaoAnexo.texto.ilike(f'%{palavra}%'))
    total = q.count()
    anexos = (q.order_by(FapContestacaoAnexo.ano_vigencia.desc(), FapContestacaoAnexo.data_envio.desc(),
                         FapContestacaoAnexo.id.desc())
              .offset(deslocamento).limit(limite).all())
    return {'total': total, 'total_e_minimo': False, 'fonte': 'banco' if termo else 'filtros',
            'itens': [_item(a, _trecho_do_banco(a.texto or '', termo.split()[0]) if termo else None)
                      for a in anexos]}


def ler(law_firm_id: int, anexo_id: int) -> Optional[dict]:
    """Um anexo com o texto inteiro (``anexo_id`` = id da linha)."""
    a = FapContestacaoAnexo.query.filter_by(id=anexo_id, law_firm_id=law_firm_id).first()
    if a is None:
        return None
    return {**_item(a), 'texto': a.texto or '', 'texto_status': a.texto_status}
