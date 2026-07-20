"""
Auditoria de acesso de usuários — fonte única do dashboard admin de atividade.

Responsabilidades:
- Registrar visitas de tela (agregado diário em user_page_visits, upsert barato
  no mesmo commit que o middleware já faz para User.last_activity).
- Estatísticas: usuários online agora, logins/ativos do dia, atividade por
  usuário e telas acessadas por usuário.
"""
import logging
from datetime import datetime, timedelta

from flask import request

from app.models import db, User, UserPageVisit
from app.utils.permissions import MODULE_PERMISSIONS, get_module_from_endpoint
from app.utils.timezone import now_sp

logger = logging.getLogger(__name__)

# Janela para considerar um usuário "online" (última atividade recente)
ONLINE_WINDOW_MINUTES = 15

# Endpoints que não representam navegação de tela
_SKIP_ENDPOINTS = {'static', 'favicon'}


def _is_page_navigation() -> bool:
    """True se a request atual parece ser uma navegação de tela (HTML via GET)."""
    if request.method != 'GET':
        return False
    endpoint = request.endpoint
    if not endpoint or endpoint in _SKIP_ENDPOINTS or endpoint.startswith('auth.'):
        return False
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return False
    accept = request.headers.get('Accept', '')
    if 'text/html' not in accept and '*/*' != accept.strip() and accept:
        return False
    # Chamadas fetch/AJAX de dados costumam ter Accept application/json
    if accept.startswith('application/json'):
        return False
    return True


def record_page_visit(user: User) -> None:
    """Registra a visita de tela da request atual para o usuário.

    Não comita — o commit fica a cargo do chamador (middleware, que já
    comita a atualização de last_activity). Nunca levanta exceção.
    """
    try:
        if not _is_page_navigation():
            return

        endpoint = request.endpoint
        today = now_sp().date()

        visit = UserPageVisit.query.filter_by(
            user_id=user.id, endpoint=endpoint, visit_date=today
        ).first()

        if visit:
            visit.hits += 1
            visit.last_seen_at = datetime.now()
        else:
            db.session.add(UserPageVisit(
                law_firm_id=user.law_firm_id,
                user_id=user.id,
                endpoint=endpoint,
                visit_date=today,
                hits=1,
                last_seen_at=datetime.now(),
            ))
    except Exception:
        logger.exception('Falha ao registrar visita de tela (ignorada)')


def screen_label(endpoint: str) -> str:
    """Rótulo amigável para um endpoint (módulo + nome da rota)."""
    module_key = get_module_from_endpoint(endpoint)
    module_label = MODULE_PERMISSIONS.get(module_key, module_key or 'Outros')
    route_name = endpoint.split('.', 1)[-1].replace('_', ' ').strip().capitalize()
    return f'{module_label} — {route_name}' if module_label else route_name


def _online_cutoff() -> datetime:
    return datetime.now() - timedelta(minutes=ONLINE_WINDOW_MINUTES)


def get_overview_stats(law_firm_id: int) -> dict:
    """Cards do dashboard: online agora, logins hoje, ativos hoje, total."""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    base = User.query.filter_by(law_firm_id=law_firm_id)
    return {
        'online_now': base.filter(User.last_activity >= _online_cutoff()).count(),
        'logins_today': base.filter(User.last_login >= today_start).count(),
        'active_today': base.filter(User.last_activity >= today_start).count(),
        'total_users': base.count(),
    }


def get_users_activity(law_firm_id: int) -> list[dict]:
    """Atividade por usuário: último login, última atividade, online, última tela."""
    # is_(None) primeiro: portável entre SQLite e MySQL (sem NULLS LAST)
    users = (User.query
             .filter_by(law_firm_id=law_firm_id)
             .order_by(User.last_activity.is_(None), User.last_activity.desc())
             .all())

    today = now_sp().date()
    cutoff = _online_cutoff()

    # Última tela e telas distintas de hoje, em uma query só para todos os usuários
    today_visits = (UserPageVisit.query
                    .filter_by(law_firm_id=law_firm_id, visit_date=today)
                    .all())
    last_screen_by_user: dict[int, UserPageVisit] = {}
    screens_today_by_user: dict[int, int] = {}
    for visit in today_visits:
        screens_today_by_user[visit.user_id] = screens_today_by_user.get(visit.user_id, 0) + 1
        current = last_screen_by_user.get(visit.user_id)
        if current is None or (visit.last_seen_at and visit.last_seen_at > current.last_seen_at):
            last_screen_by_user[visit.user_id] = visit

    result = []
    for user in users:
        last_visit = last_screen_by_user.get(user.id)
        result.append({
            'id': user.id,
            'name': user.name,
            'email': user.email,
            'role': user.role,
            'is_active': user.is_active,
            'last_login': user.last_login,
            'last_activity': user.last_activity,
            'is_online': bool(user.last_activity and user.last_activity >= cutoff),
            'last_screen': screen_label(last_visit.endpoint) if last_visit else None,
            'screens_today': screens_today_by_user.get(user.id, 0),
        })
    return result


def get_user_screens(law_firm_id: int, user_id: int, days: int = 30) -> list[dict]:
    """Telas acessadas pelo usuário no período, agregadas por endpoint."""
    since = now_sp().date() - timedelta(days=days)
    rows = (db.session.query(
                UserPageVisit.endpoint,
                db.func.sum(UserPageVisit.hits).label('total_hits'),
                db.func.max(UserPageVisit.last_seen_at).label('last_seen_at'),
            )
            .filter(UserPageVisit.law_firm_id == law_firm_id,
                    UserPageVisit.user_id == user_id,
                    UserPageVisit.visit_date >= since)
            .group_by(UserPageVisit.endpoint)
            .order_by(db.func.max(UserPageVisit.last_seen_at).desc())
            .all())

    return [{
        'endpoint': row.endpoint,
        'label': screen_label(row.endpoint),
        'hits': int(row.total_hits or 0),
        'last_seen_at': row.last_seen_at,
    } for row in rows]
