"""
Dashboard admin de atividade de usuários: último login, telas acessadas,
usuários online agora. Admin-only (módulo admin_users).
"""
from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify, flash
from functools import wraps

from datetime import datetime

from app.models import User
from app.services import access_audit_service

access_audit_bp = Blueprint('access_audit', __name__, url_prefix='/admin/access-audit')


def _fmt_local(value):
    """Formata datetimes gravados em horário local (TZ do processo = São Paulo)."""
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime('%d/%m/%Y %H:%M')


def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('law_firm_id'):
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)

    return decorated_function


def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_role') != 'admin':
            if request.is_json:
                return jsonify({"error": "Acesso negado"}), 403
            flash('Acesso negado. Apenas administradores podem acessar esta página.', 'danger')
            return redirect(url_for('dashboard.dashboard'))
        return f(*args, **kwargs)

    return decorated_function


@access_audit_bp.route('/', methods=['GET'])
@require_law_firm
@require_admin
def index():
    law_firm_id = session.get('law_firm_id')
    stats = access_audit_service.get_overview_stats(law_firm_id)
    users_activity = access_audit_service.get_users_activity(law_firm_id)
    return render_template(
        'admin/access_audit.html',
        stats=stats,
        users_activity=users_activity,
        online_window_minutes=access_audit_service.ONLINE_WINDOW_MINUTES,
    )


@access_audit_bp.route('/users/<int:user_id>/screens', methods=['GET'])
@require_law_firm
@require_admin
def user_screens(user_id):
    law_firm_id = session.get('law_firm_id')
    user = User.query.filter_by(id=user_id, law_firm_id=law_firm_id).first()
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404

    days = request.args.get('days', 30, type=int)
    days = max(1, min(days, 365))
    screens = access_audit_service.get_user_screens(law_firm_id, user_id, days=days)
    return jsonify({
        "user": {"id": user.id, "name": user.name, "email": user.email},
        "days": days,
        "screens": [{
            "endpoint": s['endpoint'],
            "label": s['label'],
            "hits": s['hits'],
            "last_seen_at": _fmt_local(s['last_seen_at']),
        } for s in screens],
    })
