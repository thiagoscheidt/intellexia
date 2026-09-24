"""Correspondência entre as teses das decisões e o catálogo do Painel.

Fonte única da tela "Correspondência de teses". A tese chega nas decisões em
texto livre (a planilha tem 219 chaves; "duplicidade" sozinha tem seis
grafias) e o catálogo do painel é mais fino ("ACIDENTE DE TRAJETO" ↔ Trajeto
B91, B92, B93 e B94). A ligação é N:N e curada: a IA sugere, a pessoa confirma.

Mesclar leva as decisões da variante para a canônica e deixa a variante
apontando para ela, para a próxima importação com aquela grafia cair no lugar
certo. Desfazer a mescla usa `teses_brutas_json` da decisão (a tese como veio),
então nada se perde.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta
from typing import Optional

from flask import current_app

from app.models import (
    db,
    JudicialLegalThesis,
    JurisprudenceDecision,
    JurisprudenceThesis,
    jurisprudence_decision_theses,
)
from app.services import jurisprudence_index_service as indice
from app.services import jurisprudence_normalizer as norm
from app.services import jurisprudence_service as svc

FILTROS = ('pendentes', 'sugeridas', 'ligadas', 'sem_equivalente', 'todas')
# Pedido de sugestão parado há mais que isso é thread morta (restart/deploy).
SUGESTAO_TRAVADA_MINUTOS = 20


def _contagem_de_decisoes(law_firm_id: int) -> dict[int, int]:
    return dict(
        db.session.query(jurisprudence_decision_theses.c.thesis_id, db.func.count())
        .join(JurisprudenceThesis, JurisprudenceThesis.id == jurisprudence_decision_theses.c.thesis_id)
        .filter(JurisprudenceThesis.law_firm_id == law_firm_id)
        .group_by(jurisprudence_decision_theses.c.thesis_id)
        .all()
    )


def listar(law_firm_id: int, filtro: str = 'pendentes', busca: str = '') -> dict:
    todas = JurisprudenceThesis.query.filter_by(law_firm_id=law_firm_id).all()
    contagem = _contagem_de_decisoes(law_firm_id)
    variantes: dict[int, list[JurisprudenceThesis]] = {}
    for tese in todas:
        if tese.merged_into_id:
            variantes.setdefault(tese.merged_into_id, []).append(tese)

    canonicas = [t for t in todas if not t.merged_into_id]
    # Tese sem decisão nenhuma (todas as decisões foram excluídas) não é
    # pendência de ninguém — fica só no filtro "todas".
    def conta(t):
        return contagem.get(t.id, 0)

    totais = {
        'pendentes': sum(1 for t in canonicas if t.status == t.STATUS_PENDENTE and conta(t)),
        'sugeridas': sum(1 for t in canonicas if t.status == t.STATUS_PENDENTE and t.suggestion_json and conta(t)),
        'ligadas': sum(1 for t in canonicas if t.status == t.STATUS_LIGADA),
        'sem_equivalente': sum(1 for t in canonicas if t.status == t.STATUS_SEM_EQUIVALENTE),
        'todas': len(canonicas),
    }

    if filtro == 'pendentes':
        linhas = [t for t in canonicas if t.status == t.STATUS_PENDENTE and conta(t)]
    elif filtro == 'sugeridas':
        linhas = [t for t in canonicas if t.status == t.STATUS_PENDENTE and t.suggestion_json and conta(t)]
    elif filtro == 'ligadas':
        linhas = [t for t in canonicas if t.status == t.STATUS_LIGADA]
    elif filtro == 'sem_equivalente':
        linhas = [t for t in canonicas if t.status == t.STATUS_SEM_EQUIVALENTE]
    else:
        linhas = canonicas

    alvo = norm.texto_de_busca(busca)
    if alvo:
        linhas = [t for t in linhas
                  if alvo in norm.texto_de_busca(' '.join([t.name, *(v.name for v in variantes.get(t.id, []))]))]

    linhas.sort(key=lambda t: (-conta(t), t.name))
    catalogo = (JudicialLegalThesis.query.filter_by(law_firm_id=law_firm_id, is_active=True)
                .order_by(JudicialLegalThesis.name).all())
    catalogo_por_id = {c.id: c for c in catalogo}
    nomes_teses = {t.id: t.name for t in canonicas}

    def sugestao(t):
        s = t.suggestion_json or {}
        if not s or t.status != t.STATUS_PENDENTE:
            return None
        return {
            'catalogo': [catalogo_por_id[i] for i in s.get('catalog_ids') or [] if i in catalogo_por_id],
            'mesclar_em': (s.get('merge_into_id'), nomes_teses.get(s.get('merge_into_id')))
            if s.get('merge_into_id') in nomes_teses else None,
            'sem_equivalente': bool(s.get('sem_equivalente')),
            'motivo': s.get('motivo') or '',
        }

    return {
        'linhas': [{
            'tese': t,
            'decisoes': conta(t),
            'variantes': sorted(variantes.get(t.id, []), key=lambda v: v.name),
            'sugestao': sugestao(t),
        } for t in linhas],
        'totais': totais,
        'catalogo': catalogo,
        'canonicas': sorted(canonicas, key=lambda t: t.name),
        'sugestao_em_andamento': sugestoes_em_andamento(law_firm_id),
    }


def _tese(law_firm_id: int, thesis_id: int) -> JurisprudenceThesis:
    tese = JurisprudenceThesis.query.filter_by(id=thesis_id, law_firm_id=law_firm_id).first()
    if tese is None:
        raise LookupError('Tese não encontrada.')
    return tese


def _reindexar_metadados(law_firm_id: int, *thesis_ids: int) -> None:
    """A tese ligada/mesclada muda o payload das decisões no índice (teses e
    catálogo) — sem gerar embedding de novo."""
    ids = [r[0] for r in db.session.query(jurisprudence_decision_theses.c.decision_id)
           .filter(jurisprudence_decision_theses.c.thesis_id.in_([t for t in thesis_ids if t])).all()]
    indice.agendar(law_firm_id, ids, somente_metadados=True)


def _catalogo(law_firm_id: int, ids) -> list[JudicialLegalThesis]:
    ids = {int(i) for i in ids or [] if str(i).isdigit()}
    if not ids:
        return []
    return JudicialLegalThesis.query.filter(JudicialLegalThesis.law_firm_id == law_firm_id,
                                            JudicialLegalThesis.id.in_(ids)).all()


def ligar(law_firm_id: int, thesis_id: int, catalog_ids) -> JurisprudenceThesis:
    tese = _tese(law_firm_id, thesis_id)
    tese.catalog_theses = _catalogo(law_firm_id, catalog_ids)
    tese.status = tese.STATUS_LIGADA if tese.catalog_theses else tese.STATUS_PENDENTE
    tese.suggestion_json = None
    db.session.commit()
    _reindexar_metadados(law_firm_id, tese.id)
    return tese


def marcar_sem_equivalente(law_firm_id: int, thesis_id: int) -> JurisprudenceThesis:
    tese = _tese(law_firm_id, thesis_id)
    tese.catalog_theses = []
    tese.status = tese.STATUS_SEM_EQUIVALENTE
    tese.suggestion_json = None
    db.session.commit()
    _reindexar_metadados(law_firm_id, tese.id)
    return tese


def reabrir(law_firm_id: int, thesis_id: int) -> JurisprudenceThesis:
    """Volta a tese para a fila (tira a ligação e o "sem equivalente")."""
    tese = _tese(law_firm_id, thesis_id)
    tese.catalog_theses = []
    tese.status = tese.STATUS_PENDENTE
    db.session.commit()
    _reindexar_metadados(law_firm_id, tese.id)
    return tese


def mesclar(law_firm_id: int, variante_id: int, canonica_id: int) -> JurisprudenceThesis:
    if variante_id == canonica_id:
        raise ValueError('Escolha outra tese para mesclar.')
    variante = _tese(law_firm_id, variante_id)
    canonica = _tese(law_firm_id, canonica_id)
    while canonica.merged_into_id:
        canonica = canonica.merged_into
    if canonica.id == variante.id:
        raise ValueError('Essa tese já está mesclada nesta.')

    # Decisões da variante passam para a canônica.
    decisoes = (JurisprudenceDecision.query
                .join(jurisprudence_decision_theses,
                      jurisprudence_decision_theses.c.decision_id == JurisprudenceDecision.id)
                .filter(jurisprudence_decision_theses.c.thesis_id == variante.id).all())
    for decisao in decisoes:
        teses = [t for t in decisao.theses if t.id != variante.id]
        if canonica not in teses:
            teses.append(canonica)
        decisao.theses = teses

    # A ligação ao catálogo não se perde: a canônica fica com a união.
    for do_catalogo in variante.catalog_theses:
        if do_catalogo not in canonica.catalog_theses:
            canonica.catalog_theses.append(do_catalogo)
    if canonica.catalog_theses:
        canonica.status = canonica.STATUS_LIGADA

    # Quem apontava para a variante passa a apontar para a canônica.
    for filha in JurisprudenceThesis.query.filter_by(law_firm_id=law_firm_id, merged_into_id=variante.id).all():
        filha.merged_into_id = canonica.id

    variante.merged_into_id = canonica.id
    variante.catalog_theses = []
    variante.suggestion_json = None
    variante.status = canonica.status
    db.session.flush()
    for decisao in decisoes:
        decisao.search_text = svc.montar_texto_de_busca(decisao)
    db.session.commit()
    _reindexar_metadados(law_firm_id, canonica.id)
    return canonica


def desfazer_mescla(law_firm_id: int, variante_id: int) -> JurisprudenceThesis:
    """Separa a variante de novo. As decisões voltam para ela pela tese bruta."""
    variante = _tese(law_firm_id, variante_id)
    canonica = variante.merged_into
    if canonica is None:
        raise ValueError('Essa tese não está mesclada.')

    # Grafias que continuam levando à canônica depois da separação.
    da_canonica = {canonica.key} | {
        t.key for t in JurisprudenceThesis.query.filter_by(
            law_firm_id=law_firm_id, merged_into_id=canonica.id).all()
        if t.id != variante.id
    }
    variante.merged_into_id = None
    variante.status = variante.STATUS_PENDENTE

    decisoes = (JurisprudenceDecision.query
                .join(jurisprudence_decision_theses,
                      jurisprudence_decision_theses.c.decision_id == JurisprudenceDecision.id)
                .filter(jurisprudence_decision_theses.c.thesis_id == canonica.id).all())
    for decisao in decisoes:
        chaves = {norm.chave(t) for t in decisao.teses_brutas_json or []}
        if variante.key not in chaves:
            continue
        teses = [t for t in decisao.theses if t.id != canonica.id or (chaves & da_canonica)]
        if variante not in teses:
            teses.append(variante)
        decisao.theses = teses
        decisao.search_text = svc.montar_texto_de_busca(decisao)
    db.session.commit()
    _reindexar_metadados(law_firm_id, variante.id, canonica.id)
    return variante


def aceitar_sugestao(law_firm_id: int, thesis_id: int) -> JurisprudenceThesis:
    tese = _tese(law_firm_id, thesis_id)
    s = tese.suggestion_json or {}
    if not s:
        raise ValueError('Essa tese não tem sugestão.')
    if s.get('merge_into_id'):
        return mesclar(law_firm_id, tese.id, int(s['merge_into_id']))
    if s.get('sem_equivalente'):
        return marcar_sem_equivalente(law_firm_id, tese.id)
    return ligar(law_firm_id, tese.id, s.get('catalog_ids') or [])


def descartar_sugestao(law_firm_id: int, thesis_id: int) -> None:
    tese = _tese(law_firm_id, thesis_id)
    tese.suggestion_json = None
    db.session.commit()


def _chave_de_catalogo(nome: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', norm.sem_acento(nome).lower()).strip('_')[:120] or 'tese'


def criar_no_catalogo(law_firm_id: int, thesis_id: int) -> JudicialLegalThesis:
    """Cria a tese no catálogo do painel com o nome da tese da base e liga as duas."""
    tese = _tese(law_firm_id, thesis_id)
    base = _chave_de_catalogo(tese.name)
    chave, n = base, 2
    while JudicialLegalThesis.query.filter_by(law_firm_id=law_firm_id, key=chave).first():
        chave, n = f'{base}_{n}', n + 1
    nova = JudicialLegalThesis(law_firm_id=law_firm_id, key=chave, name=tese.name, is_active=True)
    db.session.add(nova)
    tese.catalog_theses = [*tese.catalog_theses, nova]
    tese.status = tese.STATUS_LIGADA
    tese.suggestion_json = None
    db.session.commit()
    _reindexar_metadados(law_firm_id, tese.id)
    return nova


# ── Sugestões da IA ───────────────────────────────────────────────────

def sugestoes_em_andamento(law_firm_id: int) -> int:
    limite = datetime.now() - timedelta(minutes=SUGESTAO_TRAVADA_MINUTOS)
    return (JurisprudenceThesis.query
            .filter(JurisprudenceThesis.law_firm_id == law_firm_id,
                    JurisprudenceThesis.suggestion_requested_at.isnot(None),
                    JurisprudenceThesis.suggestion_requested_at > limite)
            .count())


def pedir_sugestoes(law_firm_id: int, user_id: Optional[int] = None) -> int:
    """Marca as pendentes sem sugestão e dispara a IA em segundo plano."""
    contagem = _contagem_de_decisoes(law_firm_id)
    alvo = [t for t in JurisprudenceThesis.query.filter_by(
                law_firm_id=law_firm_id, status=JurisprudenceThesis.STATUS_PENDENTE,
                merged_into_id=None).all()
            if not t.suggestion_json and contagem.get(t.id)]
    if not alvo:
        return 0
    agora = datetime.now()
    for tese in alvo:
        tese.suggestion_requested_at = agora
    db.session.commit()
    threading.Thread(
        target=_rodar_sugestoes,
        args=(current_app._get_current_object(), law_firm_id, [t.id for t in alvo], user_id),
        daemon=True,
        name=f'jurisprudence-thesis-suggest-{law_firm_id}',
    ).start()
    return len(alvo)


def _rodar_sugestoes(app_obj, law_firm_id: int, thesis_ids: list[int], user_id: Optional[int]) -> None:
    with app_obj.app_context():
        try:
            gerar_sugestoes(law_firm_id, thesis_ids, user_id=user_id)
        except Exception as erro:
            app_obj.logger.error(f'[JurisprudenceThesis] sugestões falharam: {erro}')
        finally:
            try:
                (JurisprudenceThesis.query
                 .filter(JurisprudenceThesis.id.in_(thesis_ids))
                 .update({'suggestion_requested_at': None}, synchronize_session=False))
                db.session.commit()
            except Exception:
                db.session.rollback()
            db.session.remove()


def gerar_sugestoes(law_firm_id: int, thesis_ids: list[int], *, user_id: Optional[int] = None,
                    agente=None, lote: int = 40) -> int:
    """Pede à IA a sugestão de cada tese e grava em suggestion_json. Síncrono."""
    from app.agents.jurisprudence.thesis_mapper_agent import JurisprudenceThesisMapperAgent
    from app.services import ai_model_settings_service

    agente = agente or JurisprudenceThesisMapperAgent(
        model_name=ai_model_settings_service.get_model(law_firm_id, 'jurisprudence_thesis_mapper'))
    contagem = _contagem_de_decisoes(law_firm_id)
    catalogo = JudicialLegalThesis.query.filter_by(law_firm_id=law_firm_id, is_active=True).all()
    if not catalogo:
        return 0
    canonicas = [t for t in JurisprudenceThesis.query.filter_by(law_firm_id=law_firm_id, merged_into_id=None).all()
                 if contagem.get(t.id)]
    referencia = sorted(canonicas, key=lambda t: -contagem.get(t.id, 0))[:150]
    alvo = [t for t in canonicas if t.id in set(thesis_ids)]
    gravadas = 0
    for i in range(0, len(alvo), lote):
        parte = alvo[i:i + lote]
        sugestoes = agente.sugerir(
            teses=[{'tese_id': t.id, 'nome': t.name, 'decisoes': contagem.get(t.id, 0)} for t in parte],
            catalogo=[{'catalogo_id': c.id, 'nome': c.name, 'descricao': c.description or ''} for c in catalogo],
            existentes=[{'tese_id': t.id, 'nome': t.name, 'decisoes': contagem.get(t.id, 0)} for t in referencia],
            law_firm_id=law_firm_id, user_id=user_id,
        )
        ids_catalogo = {c.id for c in catalogo}
        ids_teses = {t.id for t in canonicas}
        por_id = {t.id: t for t in parte}
        for s in sugestoes:
            tese = por_id.get(s.tese_id)
            if tese is None:
                continue
            merge = s.mesclar_em_tese_id if (s.mesclar_em_tese_id in ids_teses and s.mesclar_em_tese_id != tese.id) else None
            catalogo_ids = [c for c in s.catalogo_ids if c in ids_catalogo]
            if not merge and not catalogo_ids and not s.sem_equivalente:
                continue
            tese.suggestion_json = {
                'catalog_ids': catalogo_ids,
                'merge_into_id': merge,
                'sem_equivalente': bool(s.sem_equivalente) and not catalogo_ids and not merge,
                'motivo': (s.motivo or '')[:300],
            }
            tese.suggestion_requested_at = None
            gravadas += 1
        db.session.commit()
    return gravadas
