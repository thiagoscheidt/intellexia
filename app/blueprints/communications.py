"""
Monitoramento de Comunicações — comunicações processuais do Comunica PJe (DJEN).

Tela do radar por OAB: lista com filtros, detalhe com inteiro teor e link para o
documento original, controle de lidas e sincronização manual.
"""
from datetime import datetime

from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from functools import wraps

from app.models import db, Lawyer, ProcessCommunication
from app.services import communication_monitor_service as monitor

communications_bp = Blueprint('communications', __name__, url_prefix='/comunicacoes')

PER_PAGE = 20


def get_current_law_firm_id():
    return session.get('law_firm_id')


def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@communications_bp.app_context_processor
def inject_unread_communications():
    """Badge de não-lidas no menu lateral (barato: count com índice)."""
    law_firm_id = session.get('law_firm_id')
    if not law_firm_id:
        return {'communications_unread_count': 0}
    try:
        return {'communications_unread_count': monitor.unread_count(law_firm_id)}
    except Exception:
        return {'communications_unread_count': 0}


@communications_bp.route('/')
@require_law_firm
def list_communications():
    law_firm_id = get_current_law_firm_id()

    sigla_tribunal = request.args.get('tribunal', '').strip()
    tipo = request.args.get('tipo', '').strip()
    lawyer_id = request.args.get('lawyer_id', type=int)
    numero_processo = request.args.get('processo', '').strip()
    only_unread = request.args.get('nao_lidas') == '1'
    date_from = _parse_date(request.args.get('de'))
    date_to = _parse_date(request.args.get('ate'))
    page = request.args.get('page', 1, type=int)

    query = monitor.communications_query(
        law_firm_id,
        sigla_tribunal=sigla_tribunal or None,
        tipo_comunicacao=tipo or None,
        lawyer_id=lawyer_id,
        numero_processo=numero_processo or None,
        only_unread=only_unread,
        date_from=date_from,
        date_to=date_to,
    )
    communications = query.paginate(page=page, per_page=PER_PAGE)

    options = monitor.filter_options(law_firm_id)
    lawyers, lawyers_skipped = monitor.monitored_lawyers(law_firm_id)

    stats = {
        'total': ProcessCommunication.query.filter_by(law_firm_id=law_firm_id).count(),
        'nao_lidas': monitor.unread_count(law_firm_id),
    }

    return render_template(
        'communications/list.html',
        communications=communications,
        stats=stats,
        tribunais=options['tribunais'],
        tipos=options['tipos'],
        lawyers=lawyers,
        lawyers_skipped=lawyers_skipped,
        f_tribunal=sigla_tribunal,
        f_tipo=tipo,
        f_lawyer_id=lawyer_id,
        f_processo=numero_processo,
        f_nao_lidas=only_unread,
        f_de=request.args.get('de', ''),
        f_ate=request.args.get('ate', ''),
    )


@communications_bp.route('/<int:communication_id>')
@require_law_firm
def communication_detail(communication_id):
    law_firm_id = get_current_law_firm_id()
    comm = ProcessCommunication.query.filter_by(
        id=communication_id, law_firm_id=law_firm_id
    ).first_or_404()

    # Abrir o detalhe marca como lida.
    if comm.read_at is None:
        comm.read_at = datetime.now()
        comm.read_by_user_id = session.get('user_id')
        db.session.commit()

    return render_template('communications/detail.html', comm=comm)


@communications_bp.route('/<int:communication_id>/marcar-lida', methods=['POST'])
@require_law_firm
def mark_as_read(communication_id):
    comm = monitor.mark_read(get_current_law_firm_id(), communication_id, session.get('user_id'))
    if comm is None:
        return jsonify({"success": False, "message": "Comunicação não encontrada"}), 404
    return jsonify({"success": True})


@communications_bp.route('/sincronizar', methods=['POST'])
@require_law_firm
def sync_now():
    """Sincronização manual do escritório (o cron faz isso diariamente)."""
    law_firm_id = get_current_law_firm_id()
    try:
        summary = monitor.sync_law_firm(law_firm_id)
    except Exception as e:
        db.session.rollback()
        flash(f'Erro na sincronização: {e}', 'danger')
        return redirect(url_for('communications.list_communications'))

    created = sum(r['created'] for r in summary['results'])
    discovered = sum(r['processes_created'] for r in summary['results'])
    failed = [r['lawyer_name'] for r in summary['results'] if r['status'] == 'failed']

    if not summary['results']:
        flash('Nenhum advogado com OAB + UF cadastradas para monitorar. '
              'Complete o cadastro em Advogados.', 'warning')
    elif failed:
        flash(f'Sincronização concluída com falhas ({", ".join(failed)}). '
              f'{created} nova(s) comunicação(ões).', 'warning')
    else:
        msg = f'Sincronização concluída: {created} nova(s) comunicação(ões)'
        if discovered:
            msg += f', {discovered} processo(s) descoberto(s)'
        flash(msg + '.', 'success')
    return redirect(url_for('communications.list_communications'))


def _parse_date(raw):
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), '%Y-%m-%d').date()
    except ValueError:
        return None
