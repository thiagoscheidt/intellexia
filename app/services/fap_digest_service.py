"""
Contestações FAP recentes — fonte única do widget do dashboard e do e-mail de resumo.

O dashboard (aba D.O.U. / Cadastradas / Atualizadas) e a notificação "Resumo FAP"
chamam as mesmas funções daqui, então tela e e-mail nunca divergem.

Cada builder aceita ``since`` opcional:

- ``since=None``  → as N mais recentes (comportamento do widget do dashboard);
- ``since=<dt>``  → apenas o que é novidade a partir daquele instante (janela do e-mail).
"""
import json
import logging

from app.models import db

logger = logging.getLogger(__name__)

# Rótulos amigáveis dos campos rastreados no histórico de mudanças
# (usado na aba/seção "Atualizadas" para mostrar o que mudou na última alteração).
FAP_CHANGE_FIELD_LABELS = {
    'situacao_codigo': 'Situação',
    'situacao_descricao': 'Situação',
    'instancia_codigo': 'Instância',
    'instancia_descricao': 'Instância',
    'protocolo': 'Protocolo',
    'data_transmissao': 'Transmissão',
    'data_dou_date': 'Publicação D.O.U.',
    'cnpj': 'CNPJ',
    'cnpj_raiz': 'CNPJ',
    'ano_vigencia': 'Vigência',
    'fap_company_id': 'Empresa',
}

DEFAULT_LIMIT = 10


def fmt_cnpj_digits(digits):
    s = (digits or '').zfill(14)
    if len(s) == 14:
        return f'{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}'
    return digits or ''


def fap_company_name_map(law_firm_id):
    """Mapa CNPJ → nome da empresa (para exibir junto às contestações)."""
    from app.models import FapCompany
    return {
        c.cnpj: c.nome
        for c in FapCompany.query.filter_by(law_firm_id=law_firm_id)
        .with_entities(FapCompany.cnpj, FapCompany.nome).all()
        if c.cnpj
    }


def changed_field_labels(changed_fields_json):
    """Converte o JSON de changed_fields em rótulos amigáveis, sem repetição."""
    if not changed_fields_json:
        return []
    try:
        fields = json.loads(changed_fields_json)
    except (ValueError, TypeError):
        return []
    labels = []
    for f in fields:
        lbl = FAP_CHANGE_FIELD_LABELS.get(f, f)
        if lbl not in labels:
            labels.append(lbl)
    return labels


def contestacao_item(r, company_map, data_str, extra=None):
    """Monta o dict de exibição de uma contestação (comum às três listas)."""
    nome = (
        company_map.get(r.cnpj)
        or company_map.get(r.cnpj_raiz)
        or company_map.get((r.cnpj or '')[:8])
        or ''
    )
    item = {
        'id': r.id,
        'contestacao_id': r.contestacao_id,
        'cnpj_raiz': r.cnpj_raiz,
        'cnpj_fmt': fmt_cnpj_digits(r.cnpj),
        'empresa': nome,
        'ano_vigencia': r.ano_vigencia,
        'protocolo': r.protocolo or '—',
        'situacao': r.situacao_descricao or '',
        'instancia': r.instancia_descricao or '',
        'data': data_str,
    }
    if extra:
        item.update(extra)
    return item


def build_latest_dou(law_firm_id, limit=DEFAULT_LIMIT, since=None):
    """Contestações publicadas no D.O.U. (por ``data_dou_date``), mais recentes primeiro."""
    from app.models import FapWebContestacao

    query = (
        FapWebContestacao.query
        .filter_by(law_firm_id=law_firm_id)
        .filter(FapWebContestacao.data_dou_date.isnot(None))
    )
    if since is not None:
        # data_dou_date é uma data (sem hora): compara pela data da janela.
        query = query.filter(FapWebContestacao.data_dou_date >= _as_date(since))

    rows = query.order_by(FapWebContestacao.data_dou_date.desc()).limit(limit).all()
    cmap = fap_company_name_map(law_firm_id)
    return [contestacao_item(r, cmap, r.data_dou_date.strftime('%d/%m/%Y')) for r in rows]


def build_latest_cadastro(law_firm_id, limit=DEFAULT_LIMIT, since=None):
    """Contestações trazidas mais recentemente (por ``created_at``)."""
    from app.models import FapWebContestacao

    query = FapWebContestacao.query.filter_by(law_firm_id=law_firm_id)
    if since is not None:
        query = query.filter(FapWebContestacao.created_at >= since)

    rows = (
        query.order_by(FapWebContestacao.created_at.desc(), FapWebContestacao.id.desc())
        .limit(limit)
        .all()
    )
    cmap = fap_company_name_map(law_firm_id)
    return [
        contestacao_item(r, cmap, r.created_at.strftime('%d/%m/%Y') if r.created_at else '—')
        for r in rows
    ]


def build_latest_atualizacao(law_firm_id, limit=DEFAULT_LIMIT, since=None):
    """Contestações com mudança real de conteúdo mais recente.

    Usa ``FapWebContestacaoChangeHistory`` (change_type='updated'): a data
    exibida é a da última mudança e os rótulos indicam o que mudou nela.
    """
    from sqlalchemy import func
    from app.models import FapWebContestacao, FapWebContestacaoChangeHistory

    # Última mudança real por contestação → top N por essa data.
    subq_filters = [
        FapWebContestacaoChangeHistory.law_firm_id == law_firm_id,
        FapWebContestacaoChangeHistory.change_type == 'updated',
    ]
    if since is not None:
        subq_filters.append(FapWebContestacaoChangeHistory.synced_at >= since)

    subq = (
        db.session.query(
            FapWebContestacaoChangeHistory.contestacao_db_id.label('cid'),
            func.max(FapWebContestacaoChangeHistory.synced_at).label('last_change'),
        )
        .filter(*subq_filters)
        .group_by(FapWebContestacaoChangeHistory.contestacao_db_id)
        .subquery()
    )
    rows = (
        db.session.query(FapWebContestacao, subq.c.last_change)
        .join(subq, FapWebContestacao.id == subq.c.cid)
        .order_by(subq.c.last_change.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return []

    cmap = fap_company_name_map(law_firm_id)
    items = []
    for r, last_change in rows:
        # Entrada específica da última mudança (para saber o que mudou).
        entry_query = (
            FapWebContestacaoChangeHistory.query
            .filter_by(law_firm_id=law_firm_id, contestacao_db_id=r.id, change_type='updated')
        )
        if since is not None:
            entry_query = entry_query.filter(FapWebContestacaoChangeHistory.synced_at >= since)
        last_entry = entry_query.order_by(
            FapWebContestacaoChangeHistory.synced_at.desc(),
            FapWebContestacaoChangeHistory.id.desc(),
        ).first()

        items.append(contestacao_item(
            r, cmap,
            last_change.strftime('%d/%m/%Y') if last_change else '—',
            extra={'changed': changed_field_labels(last_entry.changed_fields if last_entry else None)},
        ))
    return items


def _as_date(value):
    """Datetime → date (``data_dou_date`` é coluna de data, sem hora)."""
    return value.date() if hasattr(value, 'date') else value


def build_fap_digest(law_firm_id, since, limit=DEFAULT_LIMIT):
    """Dados do e-mail de Resumo FAP: novidades da janela + panorama recente.

    ``novidades`` responde "o que mudou desde o último envio" e ``recentes``
    espelha o widget do dashboard (as N mais recentes de cada lista).
    """
    novidades = {
        'dou': build_latest_dou(law_firm_id, limit=limit, since=since),
        'cadastro': build_latest_cadastro(law_firm_id, limit=limit, since=since),
        'atualizacao': build_latest_atualizacao(law_firm_id, limit=limit, since=since),
    }
    recentes = {
        'dou': build_latest_dou(law_firm_id, limit=limit),
        'cadastro': build_latest_cadastro(law_firm_id, limit=limit),
        'atualizacao': build_latest_atualizacao(law_firm_id, limit=limit),
    }
    totais = {key: len(items) for key, items in novidades.items()}
    totais['total'] = sum(totais.values())

    return {
        'novidades': novidades,
        'recentes': recentes,
        'totais': totais,
        'periodo': {'inicio': since},
        'has_novidades': totais['total'] > 0,
    }
