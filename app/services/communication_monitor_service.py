"""
Monitoramento de Comunicações (Comunica PJe / DJEN) — fonte única da tela,
do digest por e-mail e de futuras tools MCP.

Fluxo de sincronização (cron diário):

    para cada escritório → para cada advogado com OAB + UF:
        buscar comunicações desde (last_synced_date - margem)
        hash já existe → UPDATE dos campos mutáveis
        hash novo:
            resolver JudicialProcess pelo número CNJ
            não existe → criar flagado (origin='comunica_auto',
                         discovery_status='pending_review') e importar o
                         histórico completo do processo
        sucesso → marca d'água avança; falha → mantém e registra last_error
"""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import or_

from app.models import (
    db,
    CommunicationSyncState,
    JudicialProcess,
    LawFirm,
    Lawyer,
    ProcessCommunication,
    User,
)
from app.services.comunica_pje_client import ComunicaPjeClient, ComunicaPjeError, only_digits

logger = logging.getLogger(__name__)

# Margem de segurança da janela incremental: reprocessa os últimos dias já
# sincronizados (dedup por hash torna isso barato) para cobrir publicações tardias.
SYNC_OVERLAP_DAYS = 2

# Primeira sincronização de um advogado: quantos dias para trás buscar.
FIRST_SYNC_DAYS = 30

DIGEST_LIMIT = 20


# --------------------------------------------------------------------- helpers

def format_cnj(digits):
    """20 dígitos → máscara CNJ NNNNNNN-DD.AAAA.J.TR.OOOO (ou o valor original)."""
    d = only_digits(digits)
    if len(d) != 20:
        return digits or ''
    return f'{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}'


def monitored_lawyers(law_firm_id):
    """Advogados do escritório aptos ao radar (OAB + UF preenchidas)."""
    lawyers = Lawyer.query.filter_by(law_firm_id=law_firm_id).order_by(Lawyer.name).all()
    ready, skipped = [], []
    for lawyer in lawyers:
        if only_digits(lawyer.oab_number) and (lawyer.oab_uf or '').strip():
            ready.append(lawyer)
        else:
            skipped.append(lawyer)
    return ready, skipped


def _system_user_id(law_firm_id):
    """Usuário dono dos processos criados automaticamente (admin do escritório)."""
    user = (User.query.filter_by(law_firm_id=law_firm_id, role='admin')
            .order_by(User.id).first()
            or User.query.filter_by(law_firm_id=law_firm_id).order_by(User.id).first())
    return user.id if user else None


def _get_or_create_sync_state(law_firm_id, lawyer_id):
    state = CommunicationSyncState.query.filter_by(
        law_firm_id=law_firm_id, lawyer_id=lawyer_id
    ).first()
    if state is None:
        state = CommunicationSyncState(law_firm_id=law_firm_id, lawyer_id=lawyer_id)
        db.session.add(state)
        db.session.flush()
    return state


# --------------------------------------------------------------- persistência

def _resolve_process(law_firm_id, parsed, client, stats):
    """JudicialProcess do número CNJ da comunicação; cria flagado se não existir.

    Retorna o id do processo (ou None quando o número é inválido/ausente).
    """
    digits = parsed.get('numero_processo')
    if not digits or len(digits) != 20:
        return None

    mascara = parsed.get('numero_processo_mascara') or format_cnj(digits)
    process = JudicialProcess.query.filter(
        JudicialProcess.law_firm_id == law_firm_id,
        or_(
            JudicialProcess.process_number == digits,
            JudicialProcess.process_number == mascara,
        ),
    ).first()
    if process:
        return process.id

    user_id = _system_user_id(law_firm_id)
    if user_id is None:
        logger.warning('Escritório %s sem usuários — processo %s não criado.',
                       law_firm_id, mascara)
        return None

    process = JudicialProcess(
        law_firm_id=law_firm_id,
        user_id=user_id,
        process_number=mascara,
        title=parsed.get('nome_classe') or f'Processo {mascara}',
        tribunal=parsed.get('sigla_tribunal'),
        process_class=parsed.get('nome_classe'),
        origin='comunica_auto',
        discovery_status='pending_review',
        status='ativo',
    )
    db.session.add(process)
    db.session.flush()
    stats['processes_created'] += 1
    logger.info('Processo descoberto via DJEN: %s (id=%s)', mascara, process.id)

    # Importa o histórico completo de comunicações do processo recém-descoberto.
    try:
        history = client.get_comunicacoes_processo(digits)
    except ComunicaPjeError as exc:
        logger.warning('Histórico de %s indisponível agora: %s', mascara, exc)
        history = []
    for item in history:
        parsed_hist = client.parse_comunicacao(item)
        if not parsed_hist.get('hash'):
            continue
        _upsert_communication(law_firm_id, parsed_hist, item, stats,
                              matched_lawyer_id=None, known_process_id=process.id)

    return process.id


def _upsert_communication(law_firm_id, parsed, raw_item, stats,
                          matched_lawyer_id=None, known_process_id=None, client=None):
    """Dedup por (law_firm_id, hash): existe → UPDATE; novo → INSERT.

    Retorna a ProcessCommunication persistida (ou None sem hash).
    """
    comm_hash = parsed.get('hash')
    if not comm_hash:
        stats['skipped_no_hash'] += 1
        return None

    existing = ProcessCommunication.query.filter_by(
        law_firm_id=law_firm_id, hash=comm_hash
    ).first()

    if existing:
        # Campos que podem mudar na origem (status/link); o resto é imutável.
        existing.link = parsed.get('link') or existing.link
        existing.raw_json = raw_item
        if matched_lawyer_id and not existing.matched_lawyer_id:
            existing.matched_lawyer_id = matched_lawyer_id
        stats['updated'] += 1
        return existing

    process_id = known_process_id
    if process_id is None and client is not None:
        process_id = _resolve_process(law_firm_id, parsed, client, stats)
        # A importação do histórico do processo recém-descoberto pode já ter
        # inserido esta mesma comunicação — re-checa antes de inserir de novo.
        existing = ProcessCommunication.query.filter_by(
            law_firm_id=law_firm_id, hash=comm_hash
        ).first()
        if existing:
            if matched_lawyer_id and not existing.matched_lawyer_id:
                existing.matched_lawyer_id = matched_lawyer_id
            return existing

    comm = ProcessCommunication(
        law_firm_id=law_firm_id,
        judicial_process_id=process_id,
        matched_lawyer_id=matched_lawyer_id,
        raw_json=raw_item,
        **{k: parsed.get(k) for k in (
            'comunica_id', 'hash', 'sigla_tribunal', 'tipo_comunicacao',
            'tipo_documento', 'nome_orgao', 'nome_classe', 'codigo_classe',
            'meio', 'data_disponibilizacao', 'numero_processo',
            'numero_processo_mascara', 'texto', 'link',
            'destinatarios_json', 'advogados_json',
        )},
    )
    db.session.add(comm)
    stats['created'] += 1
    return comm


# ------------------------------------------------------------------ sincronia

def sync_lawyer(law_firm_id, lawyer, client=None, dry_run=False):
    """Sincroniza as comunicações de um advogado. Retorna dict de estatísticas."""
    client = client or ComunicaPjeClient()
    stats = {'lawyer_id': lawyer.id, 'lawyer_name': lawyer.name,
             'created': 0, 'updated': 0, 'processes_created': 0,
             'skipped_no_hash': 0, 'status': 'ok', 'error': None}

    state = _get_or_create_sync_state(law_firm_id, lawyer.id)
    today = date.today()
    if state.last_synced_date:
        data_inicio = state.last_synced_date - timedelta(days=SYNC_OVERLAP_DAYS)
    else:
        data_inicio = today - timedelta(days=FIRST_SYNC_DAYS)

    try:
        for item in client.iter_comunicacoes(
            numero_oab=lawyer.oab_number,
            uf_oab=lawyer.oab_uf,
            data_inicio=data_inicio,
            data_fim=today,
        ):
            parsed = client.parse_comunicacao(item)
            _upsert_communication(law_firm_id, parsed, item, stats,
                                  matched_lawyer_id=lawyer.id, client=client)

        if dry_run:
            db.session.rollback()
            stats['status'] = 'dry_run'
            return stats

        # Sucesso: avança a marca d'água.
        state.last_synced_date = today
        state.last_run_at = datetime.now()
        state.last_error = None
        db.session.commit()
    except ComunicaPjeError as exc:
        db.session.rollback()
        # Falha não avança a marca d'água; registra o erro para diagnóstico.
        state = _get_or_create_sync_state(law_firm_id, lawyer.id)
        state.last_run_at = datetime.now()
        state.last_error = str(exc)[:2000]
        db.session.commit()
        stats['status'] = 'failed'
        stats['error'] = str(exc)
        logger.error('Sincronização falhou para %s (OAB %s/%s): %s',
                     lawyer.name, lawyer.oab_number, lawyer.oab_uf, exc)

    return stats


def sync_law_firm(law_firm_id, client=None, dry_run=False):
    """Sincroniza todos os advogados monitoráveis de um escritório."""
    client = client or ComunicaPjeClient()
    ready, skipped = monitored_lawyers(law_firm_id)
    results = []
    for lawyer in skipped:
        logger.info('Advogado %s pulado (OAB/UF incompleta).', lawyer.name)
    for lawyer in ready:
        results.append(sync_lawyer(law_firm_id, lawyer, client=client, dry_run=dry_run))
    return {
        'law_firm_id': law_firm_id,
        'lawyers_synced': len(ready),
        'lawyers_skipped': [l.name for l in skipped],
        'results': results,
    }


def sync_all(law_firm_id=None, dry_run=False):
    """Sincroniza todos os escritórios (ou um específico). Usado pelo cron."""
    client = ComunicaPjeClient()
    query = LawFirm.query.order_by(LawFirm.id)
    if law_firm_id:
        query = query.filter_by(id=law_firm_id)
    summaries = []
    for firm in query.all():
        try:
            summaries.append(sync_law_firm(firm.id, client=client, dry_run=dry_run))
        except Exception:
            db.session.rollback()
            logger.exception('Erro inesperado sincronizando escritório %s', firm.id)
    return summaries


# ------------------------------------------------------------------- consultas

def communications_query(law_firm_id, sigla_tribunal=None, tipo_comunicacao=None,
                         lawyer_id=None, numero_processo=None, only_unread=False,
                         date_from=None, date_to=None):
    """Query base da tela, com filtros. Sempre filtra o tenant."""
    query = ProcessCommunication.query.filter_by(law_firm_id=law_firm_id)
    if sigla_tribunal:
        query = query.filter(ProcessCommunication.sigla_tribunal == sigla_tribunal)
    if tipo_comunicacao:
        query = query.filter(ProcessCommunication.tipo_comunicacao == tipo_comunicacao)
    if lawyer_id:
        query = query.filter(ProcessCommunication.matched_lawyer_id == lawyer_id)
    if numero_processo:
        digits = only_digits(numero_processo)
        query = query.filter(or_(
            ProcessCommunication.numero_processo == digits,
            ProcessCommunication.numero_processo_mascara.ilike(f'%{numero_processo}%'),
        ))
    if only_unread:
        query = query.filter(ProcessCommunication.read_at.is_(None))
    if date_from:
        query = query.filter(ProcessCommunication.data_disponibilizacao >= date_from)
    if date_to:
        query = query.filter(ProcessCommunication.data_disponibilizacao <= date_to)
    return query.order_by(ProcessCommunication.data_disponibilizacao.desc(),
                          ProcessCommunication.id.desc())


def unread_count(law_firm_id):
    return ProcessCommunication.query.filter_by(law_firm_id=law_firm_id) \
        .filter(ProcessCommunication.read_at.is_(None)).count()


def filter_options(law_firm_id):
    """Valores distintos para os selects de filtro da tela."""
    base = ProcessCommunication.query.filter_by(law_firm_id=law_firm_id)
    tribunais = [row[0] for row in base.with_entities(ProcessCommunication.sigla_tribunal)
                 .filter(ProcessCommunication.sigla_tribunal.isnot(None))
                 .distinct().order_by(ProcessCommunication.sigla_tribunal).all()]
    tipos = [row[0] for row in base.with_entities(ProcessCommunication.tipo_comunicacao)
             .filter(ProcessCommunication.tipo_comunicacao.isnot(None))
             .distinct().order_by(ProcessCommunication.tipo_comunicacao).all()]
    return {'tribunais': tribunais, 'tipos': tipos}


def mark_read(law_firm_id, communication_id, user_id):
    comm = ProcessCommunication.query.filter_by(
        id=communication_id, law_firm_id=law_firm_id
    ).first()
    if comm and comm.read_at is None:
        comm.read_at = datetime.now()
        comm.read_by_user_id = user_id
        db.session.commit()
    return comm


# --------------------------------------------------------------------- digest

def build_communications_digest(law_firm_id, since, limit=DIGEST_LIMIT):
    """Dados do e-mail de resumo: comunicações novas da janela, agrupadas por processo.

    ``since`` é datetime UTC (janela desde o último envio) — compara com
    ``created_at`` (quando o sistema tomou conhecimento), não com a data de
    disponibilização, para nada escapar entre janelas.
    """
    rows = (ProcessCommunication.query
            .filter_by(law_firm_id=law_firm_id)
            .filter(ProcessCommunication.created_at >= since)
            .order_by(ProcessCommunication.data_disponibilizacao.desc(),
                      ProcessCommunication.id.desc())
            .limit(limit * 5)  # margem para agrupar; o corte final é por processo
            .all())

    grupos = {}
    for comm in rows:
        key = comm.numero_processo or f'_sem_numero_{comm.id}'
        grupo = grupos.setdefault(key, {
            'numero_mascara': comm.numero_processo_mascara or format_cnj(comm.numero_processo),
            'process_id': comm.judicial_process_id,
            'sigla_tribunal': comm.sigla_tribunal,
            'nome_classe': comm.nome_classe,
            'comunicacoes': [],
        })
        grupo['comunicacoes'].append({
            'id': comm.id,
            'tipo': comm.tipo_comunicacao or 'Comunicação',
            'tipo_documento': comm.tipo_documento,
            'orgao': comm.nome_orgao,
            'data': comm.data_disponibilizacao.strftime('%d/%m/%Y') if comm.data_disponibilizacao else '—',
            'link': comm.link,
        })

    processos = list(grupos.values())[:limit]
    total = sum(len(g['comunicacoes']) for g in processos)
    novos_processos = (JudicialProcess.query
                       .filter_by(law_firm_id=law_firm_id, origin='comunica_auto')
                       .filter(JudicialProcess.created_at >= since).count())

    return {
        'processos': processos,
        'totais': {'total': total, 'processos': len(processos),
                   'novos_processos': novos_processos},
        'periodo': {'inicio': since},
        'has_novidades': total > 0 or novos_processos > 0,
    }
