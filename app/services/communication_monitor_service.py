"""
Monitoramento de Processos (Comunica PJe / DJEN) — fonte única da tela,
do digest por e-mail e de futuras tools MCP.

Fluxo de sincronização (cron diário):

    para cada escritório → para cada advogado com OAB + UF:
        FASE DE REDE (sem transação de banco aberta):
            buscar comunicações desde (last_synced_date - margem)
            identificar processos ainda não cadastrados e baixar o
            histórico completo de cada um
        FASE DE ESCRITA (uma transação curta, sem chamadas HTTP):
            criar processos flagados (origin='comunica_auto',
            discovery_status='pending_review')
            upsert das comunicações por hash (existe → UPDATE; novo → INSERT)
        sucesso → marca d'água avança; falha → mantém e registra last_error

    A separação rede/escrita é obrigatória: transação aberta durante a
    paginação da API segura locks (inclusive na linha do admin em `users`,
    via FK de judicial_processes) e já congelou a aplicação em produção.
"""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import or_, cast, String

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

# Sincronização FULL: início padrão do histórico (o DJEN opera desde 2023).
FULL_SYNC_START = date(2023, 1, 1)

# Janela de busca por lote (dias): mantém cada consulta bem abaixo do limite
# de 10.000 resultados da API e limita a memória por lote na sincronização FULL.
SYNC_WINDOW_DAYS = 90

DIGEST_LIMIT = 20

# Teto de explicações IA automáticas por escritório por execução do sync —
# protege o custo contra rajadas (ex.: primeira rodada após dias parado);
# o excedente fica para o botão "Explicar com IA" da tela.
AUTO_EXPLAIN_LIMIT = 100


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

def _existing_process_ids(law_firm_id, wanted):
    """Dígitos CNJ → id dos JudicialProcess já cadastrados (uma consulta só).

    ``wanted``: dict dígitos → parsed. Casa tanto o número só com dígitos
    quanto a máscara CNJ (formatos coexistem em ``process_number``).
    """
    if not wanted:
        return {}
    forms = set()
    for digits, parsed in wanted.items():
        forms.add(digits)
        forms.add(parsed.get('numero_processo_mascara') or format_cnj(digits))
    rows = JudicialProcess.query.filter(
        JudicialProcess.law_firm_id == law_firm_id,
        JudicialProcess.process_number.in_(forms),
    ).all()
    return {only_digits(p.process_number): p.id for p in rows}


def _create_discovered_process(law_firm_id, parsed, stats):
    """Cria o JudicialProcess flagado para triagem. Retorna o id (ou None)."""
    digits = parsed.get('numero_processo')
    mascara = parsed.get('numero_processo_mascara') or format_cnj(digits)

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
    return process.id


def _ingest_batch(law_firm_id, entries, client, stats,
                  source=ProcessCommunication.SOURCE_COMUNICA_PJE):
    """Persiste um lote de comunicações em duas fases: rede e escrita.

    ``entries``: lista de (parsed, raw_item, matched_lawyer_id).

    Fase de rede (sem transação aberta): identifica os processos ainda não
    cadastrados e baixa o histórico completo de cada um. Fase de escrita:
    processos + comunicações de uma vez, sem nenhuma chamada HTTP no meio.
    NUNCA intercale rede e escrita — o INSERT de JudicialProcess segura lock
    compartilhado na linha do admin em ``users`` (FK) até o commit, e o
    middleware atualiza essa mesma linha a cada request: segurar o lock
    durante a paginação da API já congelou a aplicação inteira em produção.

    O commit (ou rollback, no dry-run) é responsabilidade do chamador.
    """
    wanted = {}
    for parsed, _raw, _lawyer_id in entries:
        digits = parsed.get('numero_processo')
        if digits and len(digits) == 20 and digits not in wanted:
            wanted[digits] = parsed

    process_ids = _existing_process_ids(law_firm_id, wanted)

    # --- fase de rede: históricos dos processos novos, sem transação aberta
    db.session.rollback()
    histories = {}
    for digits, parsed in wanted.items():
        if digits in process_ids or client is None:
            continue
        try:
            histories[digits] = client.get_comunicacoes_processo(digits)
        except ComunicaPjeError as exc:
            logger.warning('Histórico de %s indisponível agora: %s',
                           parsed.get('numero_processo_mascara') or digits, exc)
            histories[digits] = []

    # --- fase de escrita: uma transação curta, nenhuma chamada HTTP
    for digits, parsed in wanted.items():
        if digits in process_ids:
            continue
        process_id = _create_discovered_process(law_firm_id, parsed, stats)
        if process_id is None:
            continue
        process_ids[digits] = process_id
        for item in histories.get(digits) or []:
            parsed_hist = client.parse_comunicacao(item)
            _upsert_communication(law_firm_id, parsed_hist, item, stats,
                                  known_process_id=process_id, source=source)

    for parsed, raw_item, lawyer_id in entries:
        _upsert_communication(law_firm_id, parsed, raw_item, stats,
                              matched_lawyer_id=lawyer_id,
                              known_process_id=process_ids.get(parsed.get('numero_processo')),
                              source=source)


def _upsert_communication(law_firm_id, parsed, raw_item, stats,
                          matched_lawyer_id=None, known_process_id=None,
                          source=ProcessCommunication.SOURCE_COMUNICA_PJE):
    """Dedup por (law_firm_id, hash): existe → UPDATE; novo → INSERT.

    ``source`` identifica a fonte da informação (hoje só Comunica PJe; novas
    fontes passam a sua constante SOURCE_*). Retorna a ProcessCommunication
    persistida (ou None sem hash). A resolução/descoberta de processo acontece
    antes, em ``_ingest_batch`` — aqui não há nenhuma chamada de rede.
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

    comm = ProcessCommunication(
        law_firm_id=law_firm_id,
        judicial_process_id=known_process_id,
        matched_lawyer_id=matched_lawyer_id,
        source=source,
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

def sync_process(law_firm_id, process, client=None):
    """Sincroniza sob demanda as comunicações de UM processo (botão da tela).

    Consulta o histórico por numeroProcesso no Comunica PJe e aplica o mesmo
    upsert por hash da sincronização geral — rodar junto com o cron não
    duplica. Retorna (stats, erro): stats tem 'created'/'updated'; erro é
    None em sucesso.
    """
    digits = only_digits(process.process_number or '')
    if len(digits) != 20:
        return None, 'Processo sem número CNJ completo — não é possível consultar o DJEN.'

    client = client or ComunicaPjeClient()
    stats = {'created': 0, 'updated': 0, 'skipped_no_hash': 0}

    # fase de rede (sem transação aberta) — mesma disciplina de _ingest_batch
    db.session.rollback()
    try:
        items = client.get_comunicacoes_processo(digits)
    except ComunicaPjeError as exc:
        return None, str(exc)

    # fase de escrita: transação curta, nenhuma chamada HTTP
    for item in items:
        parsed = client.parse_comunicacao(item)
        _upsert_communication(law_firm_id, parsed, item, stats,
                              known_process_id=process.id)
    db.session.commit()
    return stats, None


def sync_lawyer(law_firm_id, lawyer, client=None, dry_run=False, full_from=None):
    """Sincroniza as comunicações de um advogado. Retorna dict de estatísticas.

    ``full_from``: modo FULL — ignora a marca d'água e busca desde essa data
    (backfill do histórico). Sem ele, incremental pela marca d'água (diário).
    O período é percorrido em janelas de SYNC_WINDOW_DAYS, cada uma com sua
    própria fase de rede + transação curta de escrita; o progresso é commitado
    por janela (o dedup por hash torna reprocessamentos idempotentes).
    """
    client = client or ComunicaPjeClient()
    stats = {'lawyer_id': lawyer.id, 'lawyer_name': lawyer.name,
             'created': 0, 'updated': 0, 'processes_created': 0,
             'skipped_no_hash': 0, 'status': 'ok', 'error': None}

    state = _get_or_create_sync_state(law_firm_id, lawyer.id)
    today = date.today()
    if full_from is not None:
        data_inicio = full_from
    elif state.last_synced_date:
        data_inicio = state.last_synced_date - timedelta(days=SYNC_OVERLAP_DAYS)
    else:
        data_inicio = today - timedelta(days=FIRST_SYNC_DAYS)
    # Persiste a linha de estado (se nova) e fecha a transação: a fase de rede
    # abaixo não pode rodar com transação/lock em aberto.
    db.session.commit()

    logger.info('Sincronizando %s (OAB %s/%s) — período %s a %s%s...',
                lawyer.name, only_digits(lawyer.oab_number), lawyer.oab_uf,
                data_inicio.isoformat(), today.isoformat(),
                ' [FULL]' if full_from else '')

    try:
        window_start = data_inicio
        while window_start <= today:
            window_end = min(window_start + timedelta(days=SYNC_WINDOW_DAYS - 1), today)

            # Fase de rede: baixa toda a janela antes de tocar no banco.
            entries = []
            for item in client.iter_comunicacoes(
                numero_oab=lawyer.oab_number,
                uf_oab=lawyer.oab_uf,
                data_inicio=window_start,
                data_fim=window_end,
            ):
                entries.append((client.parse_comunicacao(item), item, lawyer.id))

            _ingest_batch(law_firm_id, entries, client, stats)

            # Progresso preservado por janela (dry-run desfaz cada janela).
            if dry_run:
                db.session.rollback()
            else:
                db.session.commit()
            if window_end < today:
                logger.info('%s: janela %s a %s concluída — %d nova(s), '
                            '%d processo(s) descoberto(s) até aqui.',
                            lawyer.name, window_start.isoformat(),
                            window_end.isoformat(), stats['created'],
                            stats['processes_created'])
            window_start = window_end + timedelta(days=1)

        if dry_run:
            stats['status'] = 'dry_run'
            return stats

        # Sucesso: avança a marca d'água.
        state = _get_or_create_sync_state(law_firm_id, lawyer.id)
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


def sync_law_firm(law_firm_id, client=None, dry_run=False, full_from=None):
    """Sincroniza todos os advogados monitoráveis de um escritório."""
    client = client or ComunicaPjeClient()
    ready, skipped = monitored_lawyers(law_firm_id)
    results = []
    for lawyer in skipped:
        logger.info('Advogado %s pulado (OAB/UF incompleta).', lawyer.name)
    for lawyer in ready:
        results.append(sync_lawyer(law_firm_id, lawyer, client=client,
                                   dry_run=dry_run, full_from=full_from))
    return {
        'law_firm_id': law_firm_id,
        'lawyers_synced': len(ready),
        'lawyers_skipped': [l.name for l in skipped],
        'results': results,
    }


def firm_tribunal_siglas(law_firm_id):
    """Tribunais em que o escritório já recebeu comunicações (histórico próprio)."""
    rows = (db.session.query(ProcessCommunication.sigla_tribunal)
            .filter(ProcessCommunication.law_firm_id == law_firm_id,
                    ProcessCommunication.sigla_tribunal.isnot(None))
            .distinct()
            .all())
    return sorted(r[0] for r in rows)


def sync_law_firm_from_cadernos(law_firm_id, data=None, siglas=None,
                                client=None, dry_run=False):
    """Sincroniza via cadernos diários do DJEN: 1 download por tribunal,
    filtrando localmente pelas OABs do escritório.

    Alternativa à consulta por advogado — vantajosa quando há muitos advogados
    (N advogados = mesmas requisições; N tribunais costuma ser menor) e não
    sofre o limite de 10.000 resultados das consultas por OAB. Usa o mesmo
    upsert por hash, então rodar junto com a sincronização por OAB não duplica.
    """
    client = client or ComunicaPjeClient()
    data = data or date.today()
    siglas = siglas or firm_tribunal_siglas(law_firm_id)

    summary = {'law_firm_id': law_firm_id, 'data': data.isoformat(),
               'mode': 'caderno', 'siglas': list(siglas), 'results': []}
    if not siglas:
        summary['status'] = 'no_tribunals'
        logger.warning('Escritório %s sem histórico de tribunais — informe as siglas '
                       'explicitamente para sincronizar por caderno.', law_firm_id)
        return summary

    ready, _skipped = monitored_lawyers(law_firm_id)
    oab_index = {}
    for lawyer in ready:
        key = (only_digits(lawyer.oab_number), (lawyer.oab_uf or '').strip().upper())
        oab_index.setdefault(key, lawyer.id)
    if not oab_index:
        summary['status'] = 'no_lawyers'
        return summary

    for sigla in siglas:
        stats = {'sigla': sigla, 'status': 'ok', 'error': None, 'scanned': 0,
                 'matched': 0, 'created': 0, 'updated': 0,
                 'processes_created': 0, 'skipped_no_hash': 0}
        try:
            meta = client.get_caderno(sigla, data)
            caderno_status = (meta or {}).get('status') or ''
            if caderno_status != 'Processado':
                # 'Sem comunicações', 'Em processamento', 'Não Processado', 'Cancelado'
                stats['status'] = 'skipped'
                stats['error'] = f'caderno {caderno_status or "indisponível"}'
                summary['results'].append(stats)
                continue

            # Varredura local do zip: só coleta os itens do escritório;
            # a persistência acontece de uma vez em _ingest_batch.
            entries = []
            for item in client.iter_caderno_comunicacoes(meta):
                stats['scanned'] += 1
                matched_lawyer_id = None
                for entry in item.get('destinatarioadvogados') or []:
                    adv = (entry or {}).get('advogado') or {}
                    key = (only_digits(str(adv.get('numero_oab') or '')),
                           str(adv.get('uf_oab') or '').strip().upper())
                    if key in oab_index:
                        matched_lawyer_id = oab_index[key]
                        break
                if matched_lawyer_id is None:
                    continue
                stats['matched'] += 1
                entries.append((client.parse_comunicacao(item), item, matched_lawyer_id))

            _ingest_batch(law_firm_id, entries, client, stats)

            if dry_run:
                db.session.rollback()
                stats['status'] = 'dry_run'
            else:
                db.session.commit()
        except ComunicaPjeError as exc:
            db.session.rollback()
            stats['status'] = 'failed'
            stats['error'] = str(exc)
            logger.error('Caderno %s/%s falhou: %s', sigla, data, exc)
        summary['results'].append(stats)

    return summary


def sync_all(law_firm_id=None, dry_run=False, full_from=None):
    """Sincroniza todos os escritórios (ou um específico). Usado pelo cron."""
    client = ComunicaPjeClient()
    query = LawFirm.query.order_by(LawFirm.id)
    if law_firm_id:
        query = query.filter_by(id=law_firm_id)
    summaries = []
    for firm in query.all():
        try:
            summaries.append(sync_law_firm(firm.id, client=client,
                                           dry_run=dry_run, full_from=full_from))
        except Exception:
            db.session.rollback()
            logger.exception('Erro inesperado sincronizando escritório %s', firm.id)
    return summaries


# ------------------------------------------------------------------- consultas

def communications_query(law_firm_id, sigla_tribunal=None, tipo_comunicacao=None,
                         lawyer_id=None, numero_processo=None, only_unread=False,
                         date_from=None, date_to=None, source=None):
    """Query base da tela, com filtros. Sempre filtra o tenant."""
    query = ProcessCommunication.query.filter_by(law_firm_id=law_firm_id)
    if source:
        query = query.filter(ProcessCommunication.source == source)
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
    fontes = [row[0] for row in base.with_entities(ProcessCommunication.source)
              .filter(ProcessCommunication.source.isnot(None))
              .distinct().order_by(ProcessCommunication.source).all()]
    return {'tribunais': tribunais, 'tipos': tipos, 'fontes': fontes}


def explain_communication(law_firm_id, communication_id, user_id=None, force=False):
    """Explicação da comunicação via IA, com cache em analysis_json.

    O teor é imutável, então a análise é gerada uma única vez por comunicação
    (``force=True`` regenera). Retorna dict: {'cached': bool, 'generated_at',
    'model', 'data': {...}} ou levanta ValueError com mensagem amigável.
    """
    comm = ProcessCommunication.query.filter_by(
        id=communication_id, law_firm_id=law_firm_id
    ).first()
    if not comm:
        raise ValueError('Comunicação não encontrada')
    if not comm.texto:
        raise ValueError('Esta comunicação não tem teor para explicar — abra o documento original no PJe')

    if comm.analysis_json and not force:
        return {**comm.analysis_json, 'cached': True}

    from app.agents.processes.communication_explainer_agent import CommunicationExplainerAgent

    contexto_processo = None
    if comm.judicial_process:
        process = comm.judicial_process
        recentes = (ProcessCommunication.query
                    .filter(ProcessCommunication.judicial_process_id == process.id,
                            ProcessCommunication.id != comm.id)
                    .order_by(ProcessCommunication.data_disponibilizacao.desc())
                    .limit(5).all())
        historico = '; '.join(
            f"{c.data_disponibilizacao.strftime('%d/%m/%Y') if c.data_disponibilizacao else '?'}: "
            f"{c.tipo_comunicacao or 'comunicação'}"
            for c in recentes
        ) or 'sem outras comunicações registradas'
        contexto_processo = (
            f"Título: {process.title or '—'} | Tribunal: {process.tribunal or '—'} | "
            f"Classe: {process.process_class or '—'} | Status: {process.status or '—'}\n"
            f"Últimas comunicações: {historico}"
        )

    advogados = None
    if comm.advogados_json:
        advogados = ', '.join(
            f"{a.get('nome')} (OAB {a.get('numero_oab')}/{a.get('uf_oab')})"
            for a in comm.advogados_json if isinstance(a, dict)
        )
    if comm.matched_lawyer:
        advogados = f"{advogados or ''} — capturada pela OAB de {comm.matched_lawyer.name}".strip(' —')

    agent = CommunicationExplainerAgent()
    explanation = agent.explain(
        {
            'teor': comm.texto,
            'data_disponibilizacao': comm.data_disponibilizacao.strftime('%d/%m/%Y') if comm.data_disponibilizacao else None,
            'sigla_tribunal': comm.sigla_tribunal,
            'tipo_comunicacao': comm.tipo_comunicacao,
            'tipo_documento': comm.tipo_documento,
            'nome_orgao': comm.nome_orgao,
            'nome_classe': comm.nome_classe,
            'numero_processo': comm.numero_processo_mascara or comm.numero_processo,
            'contexto_processo': contexto_processo,
            'advogados_escritorio': advogados,
        },
        user_id=user_id,
        law_firm_id=law_firm_id,
    )

    payload = {
        'generated_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
        'model': agent.model_name,
        'data': explanation.model_dump(),
    }
    comm.analysis_json = payload
    db.session.commit()
    return {**payload, 'cached': False}


def explain_new_communications(law_firm_id, since, limit=AUTO_EXPLAIN_LIMIT):
    """Gera e salva a explicação IA das comunicações criadas a partir de ``since``.

    Mesmo efeito do botão "Explicar com IA" da tela, em lote, chamado pelo cron
    DEPOIS do commit do sync — a chamada de IA é rede e nunca entra na transação
    de escrita. Falha em uma comunicação não interrompe as demais (fica para o
    botão manual). Retorna {'explained': n, 'failed': n, 'pending': n} —
    ``pending`` conta as elegíveis que ficaram de fora do teto ``limit``.
    """
    query = (ProcessCommunication.query
             .filter_by(law_firm_id=law_firm_id)
             .filter(cast(ProcessCommunication.analysis_json, String) == 'null',
                     ProcessCommunication.texto.isnot(None),
                     ProcessCommunication.texto != '',
                     ProcessCommunication.created_at >= since)
             .order_by(ProcessCommunication.data_disponibilizacao.desc(),
                       ProcessCommunication.id.desc()))
    total = query.count()
    comms = query.limit(limit).all() if limit else query.all()
    user_id = _system_user_id(law_firm_id)

    stats = {'explained': 0, 'failed': 0, 'pending': max(0, total - len(comms))}
    for comm in comms:
        try:
            explain_communication(law_firm_id, comm.id, user_id=user_id)
            stats['explained'] += 1
        except Exception as exc:  # IA nunca derruba o sync
            db.session.rollback()
            logger.warning(
                'Explicação IA falhou para comunicação %s (%s): %s', comm.id,
                comm.numero_processo_mascara or comm.numero_processo, exc)
            stats['failed'] += 1
    return stats


def mark_all_read(law_firm_id, user_id, **filters):
    """Marca como lidas todas as não lidas que casam com os filtros da tela.

    Retorna a quantidade marcada. ``filters`` aceita os mesmos parâmetros de
    ``communications_query`` (tribunal, tipo, fonte, advogado, processo, datas).
    """
    query = communications_query(law_firm_id, only_unread=True, **filters)
    now = datetime.now()
    count = query.order_by(None).update(
        {ProcessCommunication.read_at: now,
         ProcessCommunication.read_by_user_id: user_id},
        synchronize_session=False,
    )
    db.session.commit()
    return count


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
