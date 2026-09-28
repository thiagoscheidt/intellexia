"""Base de Conhecimento do Painel de Processos — a tela que junta as duas bases
que a IA usa para montar a impugnação:

- **Jurisprudência** (`jurisprudence_*`): decisões judiciais; entram na peça
  como precedente citado.
- **Peças-modelo** (`ImpugnacaoReferenceModel`): impugnações do escritório;
  entram na peça como estrutura e estilo.

Fonte única da Visão geral (números, pendências, cobertura por tese) e da busca
nas duas bases. Não guarda nada: cada base continua dona dos próprios dados,
telas e motores de busca — aqui só se lê e se cruza.

A **cobertura por tese** é o que só existe com as duas juntas: para cada tese
do catálogo, se há peça-modelo para dar a estrutura e decisão favorável para
citar. É o mesmo aviso "sem peça-modelo" que a geração dá nas notas internas,
visto antes de gerar.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from app.models import (
    db,
    ImpugnacaoReferenceChunk,
    ImpugnacaoReferenceModel,
    JudicialLegalThesis,
    JurisprudenceDecision,
    JurisprudenceUpload,
)
from app.services import jurisprudence_normalizer as norm
from app.services import jurisprudence_service as jur

TRFS = ('TRF1', 'TRF2', 'TRF3', 'TRF4', 'TRF5', 'TRF6')

# "Maioria contra": a partir de quantas decisões a proporção de desfavoráveis
# passa a dizer algo. Com duas decisões, uma contra já seria "metade".
MIN_DECISOES_MAIORIA = 3

COBERTA = 'coberta'
SEM_PECA = 'sem_peca'
SEM_DECISAO = 'sem_decisao'
DESCOBERTA = 'descoberta'
MAIORIA_CONTRA = 'maioria_contra'

SITUACOES = {
    COBERTA: 'coberta',
    SEM_PECA: 'sem peça-modelo',
    SEM_DECISAO: 'sem decisão',
    DESCOBERTA: 'descoberta',
    MAIORIA_CONTRA: 'maioria contra',
}
# Ordem da tabela: o que pede ação primeiro.
_ORDEM = {DESCOBERTA: 0, MAIORIA_CONTRA: 1, SEM_PECA: 2, SEM_DECISAO: 3, COBERTA: 4}


def contagens(law_firm_id: int) -> dict:
    """Os dois números das abas — COUNTs baratos, chamados em toda tela do hub."""
    return {
        'decisoes': JurisprudenceDecision.query.filter_by(law_firm_id=law_firm_id).count(),
        'pecas': ImpugnacaoReferenceModel.query.filter_by(law_firm_id=law_firm_id, status='active').count(),
    }


def _pecas_ativas(law_firm_id: int) -> list[ImpugnacaoReferenceModel]:
    return ImpugnacaoReferenceModel.query.filter_by(law_firm_id=law_firm_id, status='active').all()


def resumo_jurisprudencia(law_firm_id: int) -> dict:
    totais = jur.totais(law_firm_id)
    por_resultado = dict(
        db.session.query(JurisprudenceDecision.resultado, db.func.count())
        .filter(JurisprudenceDecision.law_firm_id == law_firm_id)
        .group_by(JurisprudenceDecision.resultado).all()
    )
    com_resultado = sum(n for r, n in por_resultado.items() if r)
    exito = [
        {'resultado': r, 'rotulo': norm.RESULTADO_LABELS_CURTOS[r], 'n': por_resultado.get(r, 0),
         'pct': (100.0 * por_resultado.get(r, 0) / com_resultado) if com_resultado else 0}
        for r in (norm.RESULTADO_FAVORAVEL, norm.RESULTADO_PARCIAL, norm.RESULTADO_DESFAVORAVEL)
    ]
    a_favor = por_resultado.get(norm.RESULTADO_FAVORAVEL, 0) + por_resultado.get(norm.RESULTADO_PARCIAL, 0)
    return {
        **totais,
        'exito': exito,
        'pct_a_favor': round(100.0 * a_favor / com_resultado) if com_resultado else None,
    }


def resumo_pecas(law_firm_id: int, pecas: Optional[list] = None) -> dict:
    pecas = pecas if pecas is not None else _pecas_ativas(law_firm_id)
    por_trf = Counter(p.trf_region for p in pecas if p.trf_region)
    return {
        'pecas': len(pecas),
        'trechos': sum(p.chunks_count or 0 for p in pecas),
        'por_trf': [(trf, por_trf.get(trf, 0)) for trf in TRFS if por_trf.get(trf)],
        'trfs_sem_peca': [trf for trf in TRFS if not por_trf.get(trf)],
    }


def cobertura_por_tese(law_firm_id: int, pecas: Optional[list] = None) -> list[dict]:
    """Uma linha por tese ativa do catálogo, com peças, decisões e situação."""
    from app.services.jurisprudence_generation_service import decisoes_por_tese_do_catalogo

    catalogo = (JudicialLegalThesis.query.filter_by(law_firm_id=law_firm_id, is_active=True)
                .order_by(JudicialLegalThesis.name).all())
    if not catalogo:
        return []
    pecas = pecas if pecas is not None else _pecas_ativas(law_firm_id)
    pecas_por_chave = Counter(k for p in pecas for k in set(p.thesis_catalog_ids or []))
    decisoes = decisoes_por_tese_do_catalogo(law_firm_id, [t.id for t in catalogo])

    linhas = []
    for tese in catalogo:
        resultados = Counter(d.resultado for d in decisoes.get(tese.id, []) if d.resultado)
        total = sum(resultados.values())
        a_favor = resultados[norm.RESULTADO_FAVORAVEL] + resultados[norm.RESULTADO_PARCIAL]
        contra = resultados[norm.RESULTADO_DESFAVORAVEL]
        n_pecas = pecas_por_chave.get(tese.key, 0)
        if not n_pecas and not a_favor:
            situacao = DESCOBERTA
        elif total >= MIN_DECISOES_MAIORIA and contra * 2 > total:
            situacao = MAIORIA_CONTRA
        elif not n_pecas:
            situacao = SEM_PECA
        elif not a_favor:
            situacao = SEM_DECISAO
        else:
            situacao = COBERTA
        linhas.append({
            'tese': tese,
            'pecas': n_pecas,
            'decisoes': total,
            'resultados': {r: resultados[r] for r in (norm.RESULTADO_FAVORAVEL, norm.RESULTADO_PARCIAL,
                                                      norm.RESULTADO_DESFAVORAVEL)},
            'situacao': situacao,
            'rotulo': SITUACOES[situacao],
        })
    linhas.sort(key=lambda l: (_ORDEM[l['situacao']], -l['decisoes'], l['tese'].name))
    return linhas


def pendencias(law_firm_id: int, cobertura: list[dict], pecas: Optional[list] = None) -> list[dict]:
    """O que pede ação agora, das duas bases. Só entra o que é > 0."""
    pecas = pecas if pecas is not None else _pecas_ativas(law_firm_id)
    uploads = dict(
        db.session.query(JurisprudenceUpload.status, db.func.count())
        .filter(JurisprudenceUpload.law_firm_id == law_firm_id)
        .group_by(JurisprudenceUpload.status).all()
    )
    itens = [
        ('teses', jur.contar_teses_pendentes(law_firm_id), 'warning',
         'teses das decisões sem ligação com o catálogo', 'revisar'),
        ('sem_peca', sum(1 for l in cobertura if l['pecas'] == 0), 'warning',
         'teses do catálogo sem peça-modelo', 'ver quais'),
        ('pecas_falha', sum(1 for p in pecas if p.ingestion_status == 'failed'), 'danger',
         'peças-modelo com falha na indexação', 'abrir'),
        ('pecas_processando', sum(1 for p in pecas if p.ingestion_status == 'processing'), 'secondary',
         'peças-modelo ainda indexando', 'abrir'),
        ('pdf_falha', uploads.get(JurisprudenceUpload.STATUS_FAILED, 0), 'danger',
         'PDFs de decisão com falha na leitura', 'tentar de novo'),
        ('pdf_revisar', uploads.get(JurisprudenceUpload.STATUS_REVIEW, 0), 'warning',
         'decisões em "revisar" (possível duplicata)', 'decidir'),
    ]
    return [{'chave': k, 'n': n, 'cor': cor, 'texto': texto, 'acao': acao}
            for k, n, cor, texto, acao in itens if n]


def visao_geral(law_firm_id: int) -> dict:
    pecas = _pecas_ativas(law_firm_id)
    cobertura = cobertura_por_tese(law_firm_id, pecas)
    return {
        'jurisprudencia': resumo_jurisprudencia(law_firm_id),
        'pecas': resumo_pecas(law_firm_id, pecas),
        'cobertura': cobertura,
        'pendencias': pendencias(law_firm_id, cobertura, pecas),
    }


# ── Busca nas duas bases ──────────────────────────────────────────────

LIMITE_POR_BASE = 5


def buscar_pecas(law_firm_id: int, consulta: str, limite_pecas: int = LIMITE_POR_BASE) -> dict:
    """Trechos das peças-modelo, agrupados por peça.

    Meilisearch primeiro (a mesma busca da lista de peças); fora do ar, o mesmo
    `LIKE` nos trechos que a lista de peças já usa como reserva.
    """
    from app.services import impugnacao_reference_search

    indisponivel = False
    hits = impugnacao_reference_search.search_chunks(law_firm_id, consulta, status='active', limit=40)
    if hits is None:
        indisponivel = True
        hits = [
            {'reference_id': c.reference_id, 'section': c.secao_origem or '',
             'section_kind': c.section_kind, 'text': (c.preview_text or c.full_text or '')[:240]}
            for c in (ImpugnacaoReferenceChunk.query
                      .filter_by(law_firm_id=law_firm_id)
                      .filter(ImpugnacaoReferenceChunk.full_text.ilike(f'%{consulta}%'))
                      .limit(40).all())
        ]
    por_peca: dict[int, list[dict]] = {}
    for hit in hits:
        ref_id = hit.get('reference_id')
        if ref_id is not None:
            por_peca.setdefault(int(ref_id), []).append(hit)
    pecas = {p.id: p for p in ImpugnacaoReferenceModel.query.filter(
        ImpugnacaoReferenceModel.law_firm_id == law_firm_id,
        ImpugnacaoReferenceModel.status == 'active',
        ImpugnacaoReferenceModel.id.in_(list(por_peca) or [0])).all()}
    # Grifo e escape pelo mesmo caminho da jurisprudência: o trecho entra no
    # template com `| safe`, então o escape tem de vir antes do <mark>.
    from app.services.jurisprudence_search_service import trecho
    termos = norm.termos_da_consulta(consulta)

    def grifado(hit):
        texto = hit.get('text') or ''
        return trecho(texto, termos, janela=150) or trecho(texto, [], janela=150)

    grupos = [{'peca': pecas[i], 'n': len(por_peca[i]),
               'trechos': [{'secao': h.get('section') or '', 'html': grifado(h)} for h in por_peca[i][:2]]}
              for i in por_peca if i in pecas]
    return {
        'grupos': grupos[:limite_pecas],
        'total_pecas': len(grupos),
        'total_trechos': sum(g['n'] for g in grupos),
        'indisponivel': indisponivel,
    }


def buscar(law_firm_id: int, consulta: str, escopo: str = 'tudo') -> dict:
    from app.services import jurisprudence_search_service as busca

    consulta = (consulta or '').strip()[:300]
    saida = {'consulta': consulta, 'escopo': escopo, 'jurisprudencia': None, 'pecas': None}
    if not consulta:
        return saida
    if escopo in ('tudo', 'jurisprudencia'):
        r = busca.buscar(law_firm_id, busca.Filtros(q=consulta),
                         por_pagina=LIMITE_POR_BASE if escopo == 'tudo' else busca.POR_PAGINA)
        saida['jurisprudencia'] = r
    if escopo in ('tudo', 'pecas'):
        saida['pecas'] = buscar_pecas(law_firm_id, consulta,
                                      LIMITE_POR_BASE if escopo == 'tudo' else 30)
    return saida
