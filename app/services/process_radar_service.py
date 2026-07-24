"""
Radar da Mesa de Trabalho — fonte única (tela do Painel de Processos + e-mail).

O Radar agrega, por escritório, o que exige atenção nos processos vinculados:

- **providências apontadas pela IA** (`kind='ia'`): publicações analisadas cuja
  análise pede ação (`acao_requerida == 'exige_acao'`) e que ainda não viraram
  prazo gerenciado nem venceram;
- **publicações não lidas** (`kind='publicacao'`) dos últimos 30 dias em processos
  vinculados, fora as que já entraram como providência da IA;
- **movimentação recente do DataJud** (`kind='decisao'`/`'movimentacao'`) lida do
  snapshot (nunca consulta a API), ainda não marcada como "ciente".

Nada aqui consulta serviços externos — lê apenas o que já está persistido.

`build_radar` devolve os itens da tela; `build_radar_digest` embrulha o mesmo
estado para o e-mail de resumo, marcando `is_new` (novidade desde o último envio)
e contando decisões.
"""
from datetime import datetime, date, timedelta, time as dt_time

from flask import url_for

from app.models import (
    ProcessCommunication, ProcessDeadline, ProcessDatajudSnapshot,
)
from app.services import datajud_snapshot_service

RADAR_DIGEST_LIMIT = 15


def _is_decision_text(*parts):
    """True se algum trecho contiver palavra de decisão (mesma lista do DataJud)."""
    return any(datajud_snapshot_service.is_decision_movement(p) for p in parts if p)


def build_radar(law_firm_id, limit=8):
    """Itens do Radar ordenados por recência. Retorna ``(items, total)``.

    Cada item: ``kind``, ``label``, ``process_id``, ``communication_id`` (None nos
    itens do DataJud), ``process_number``, ``when`` (datetime p/ ordenação),
    ``url``, ``is_decision``; itens de publicação ainda trazem ``tipo``.
    """
    radar_items = []
    cutoff_comms = date.today() - timedelta(days=30)
    recent_comms = (ProcessCommunication.query
                    .filter(ProcessCommunication.law_firm_id == law_firm_id,
                            ProcessCommunication.judicial_process_id.isnot(None),
                            ProcessCommunication.data_disponibilizacao >= cutoff_comms)
                    .order_by(ProcessCommunication.data_disponibilizacao.desc())
                    .limit(60).all())

    linked_deadline_comm_ids = {
        row.communication_id
        for row in ProcessDeadline.query.filter(
            ProcessDeadline.law_firm_id == law_firm_id,
            ProcessDeadline.communication_id.isnot(None)).all()
    }

    # Providências da IA: varre TODAS as publicações analisadas (sem janela de data —
    # providência pendente não expira com a idade da publicação). Volume limitado:
    # só publicações com análise gerada.
    analyzed_comms = (ProcessCommunication.query
                      .filter(ProcessCommunication.law_firm_id == law_firm_id,
                              ProcessCommunication.judicial_process_id.isnot(None),
                              ProcessCommunication.analysis_json.isnot(None))
                      .order_by(ProcessCommunication.data_disponibilizacao.desc())
                      .limit(200).all())

    ai_comm_ids = set()
    for comm in analyzed_comms:
        analysis = (comm.analysis_json or {}).get('data') if comm.analysis_json else None
        if not analysis or analysis.get('acao_requerida') != 'exige_acao':
            continue
        if comm.id in linked_deadline_comm_ids:
            continue
        due_raw = ((analysis.get('prazo') or {}).get('data_limite_estimada') or '').strip()
        try:
            due_date = datetime.strptime(due_raw, '%Y-%m-%d').date() if due_raw else None
        except ValueError:
            due_date = None
        if due_date and due_date < date.today():
            continue
        ai_comm_ids.add(comm.id)
        label = (analysis.get('acao_descricao') or analysis.get('resumo')
                 or 'Providência apontada pela IA').strip()
        radar_items.append({
            'kind': 'ia',
            'due': due_date,
            'label': label,
            'process_id': comm.judicial_process_id,
            'communication_id': comm.id,
            'process_number': comm.numero_processo_mascara or comm.numero_processo or '',
            'when': datetime.combine(comm.data_disponibilizacao, dt_time.min)
            if comm.data_disponibilizacao else datetime.now(),
            'url': url_for('communications.communication_detail', communication_id=comm.id),
            'is_decision': _is_decision_text(comm.tipo_comunicacao, comm.tipo_documento, label),
        })

    for comm in recent_comms:
        if comm.is_read or comm.id in ai_comm_ids:
            continue
        label = comm.tipo_documento or comm.nome_orgao or 'Publicação'
        radar_items.append({
            'kind': 'publicacao',
            'tipo': comm.tipo_comunicacao or 'Comunicação',
            'label': label,
            'process_id': comm.judicial_process_id,
            'communication_id': comm.id,
            'process_number': comm.numero_processo_mascara or comm.numero_processo or '',
            'when': datetime.combine(comm.data_disponibilizacao, dt_time.min)
            if comm.data_disponibilizacao else datetime.now(),
            'url': url_for('communications.communication_detail', communication_id=comm.id),
            'is_decision': _is_decision_text(comm.tipo_comunicacao, comm.tipo_documento),
        })

    week_ago = datetime.now() - timedelta(days=7)
    recent_snapshots = (ProcessDatajudSnapshot.query
                        .filter(ProcessDatajudSnapshot.law_firm_id == law_firm_id,
                                ProcessDatajudSnapshot.last_movement_at >= week_ago)
                        .all())
    for snap in recent_snapshots:
        if snap.movement_ack_at and snap.last_movement_at <= snap.movement_ack_at:
            continue
        latest_name, _latest_iso = datajud_snapshot_service.latest_movement(snap)
        if not latest_name:
            continue
        is_decision = datajud_snapshot_service.is_decision_movement(latest_name)
        radar_items.append({
            'kind': 'decisao' if is_decision else 'movimentacao',
            'label': latest_name,
            'process_id': snap.process_id,
            'communication_id': None,
            'process_number': snap.process.process_number if snap.process else '',
            'when': snap.last_movement_at,
            'url': url_for('process_panel.detail', process_id=snap.process_id),
            'is_decision': is_decision,
        })

    radar_items.sort(key=lambda item: item['when'], reverse=True)
    total = len(radar_items)
    return radar_items[:limit], total


def build_radar_digest(law_firm_id, since, limit=RADAR_DIGEST_LIMIT):
    """Estado atual do Radar para o e-mail de resumo.

    Mostra as pendências abertas (não só a janela), marcando ``is_new`` quando o
    item é mais recente que ``since`` (último envio). ``has_novidades`` — o gatilho
    do envio — exige ao menos um item novo. Decisões vêm primeiro (destaque).

    A comparação de novidade é por dia (a data das publicações não tem hora), o
    que basta para o gatilho do resumo periódico.
    """
    items, total = build_radar(law_firm_id, limit=limit)

    for item in items:
        item['is_new'] = bool(item.get('when') and since and item['when'] > since)

    # Decisões no topo; dentro de cada grupo, mais recentes primeiro.
    items.sort(key=lambda i: (not i.get('is_decision'), i['when'] is None,
                              -(i['when'].timestamp() if i.get('when') else 0)))

    novos = sum(1 for i in items if i['is_new'])
    decisoes = sum(1 for i in items if i['is_decision'])

    return {
        'radar_items': items,
        'totais': {'total': total, 'novos': novos, 'decisoes': decisoes},
        'periodo': {'inicio': since},
        'has_novidades': novos > 0,
    }
