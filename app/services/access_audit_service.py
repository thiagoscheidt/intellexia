"""
Auditoria de acesso de usuários — fonte única do dashboard admin de atividade.

Responsabilidades:
- Registrar visitas de tela (agregado diário em user_page_visits, upsert barato
  no mesmo commit que o middleware já faz para User.last_activity).
- Estatísticas: usuários online agora, logins/ativos do dia, atividade por
  usuário e telas acessadas por usuário.
- Uso do MCP: registro por chamada (agregado diário em user_mcp_calls, feito
  pelo middleware do servidor MCP), conexão do usuário (tokens OAuth do MCP) e
  funções usadas por usuário.
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from flask import request
from sqlalchemy.exc import IntegrityError

from app.models import db, McpOAuthClient, McpOAuthToken, User, UserMcpCall, UserPageVisit
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


def _find_visit(user_id: int, endpoint: str, visit_date) -> 'UserPageVisit | None':
    return UserPageVisit.query.filter_by(
        user_id=user_id, endpoint=endpoint, visit_date=visit_date
    ).first()


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

        visit = _find_visit(user.id, endpoint, today)

        if visit:
            visit.hits += 1
            visit.last_seen_at = datetime.now()
            return

        # SAVEPOINT força o INSERT a executar aqui (e não no commit do
        # middleware, onde o erro escaparia deste try/except).
        try:
            with db.session.begin_nested():
                db.session.add(UserPageVisit(
                    law_firm_id=user.law_firm_id,
                    user_id=user.id,
                    endpoint=endpoint,
                    visit_date=today,
                    hits=1,
                    last_seen_at=datetime.now(),
                ))
        except IntegrityError:
            # Outra request simultânea inseriu a linha primeiro (sob
            # REPEATABLE READ o SELECT acima pode não enxergá-la). O UPDATE
            # direto lê a versão corrente e apenas incrementa.
            UserPageVisit.query.filter_by(
                user_id=user.id, endpoint=endpoint, visit_date=today
            ).update({
                'hits': UserPageVisit.hits + 1,
                'last_seen_at': datetime.now(),
            }, synchronize_session=False)
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
    """Cards do dashboard: online agora, logins hoje, ativos hoje, total.

    Inclui a adoção do login com Google (quantos já usaram e quantos usaram
    hoje), para acompanhar se o caminho novo pegou.
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    base = User.query.filter_by(law_firm_id=law_firm_id)
    return {
        'online_now': base.filter(User.last_activity >= _online_cutoff()).count(),
        'logins_today': base.filter(User.last_login >= today_start).count(),
        'active_today': base.filter(User.last_activity >= today_start).count(),
        'total_users': base.count(),
        'google_users': base.filter(User.google_login_count > 0).count(),
        'google_logins_today': base.filter(User.google_last_login_at >= today_start).count(),
        **get_mcp_overview(law_firm_id),
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

    mcp_por_usuario = get_users_mcp(law_firm_id)

    result = []
    for user in users:
        last_visit = last_screen_by_user.get(user.id)
        result.append({
            'id': user.id,
            'name': user.name,
            'email': user.email,
            'picture': user.google_picture_url,
            'role': user.role,
            'is_active': user.is_active,
            'last_login': user.last_login,
            'last_activity': user.last_activity,
            'is_online': bool(user.last_activity and user.last_activity >= cutoff),
            'last_screen': screen_label(last_visit.endpoint) if last_visit else None,
            'screens_today': screens_today_by_user.get(user.id, 0),
            'google_last_login': user.google_last_login_at,
            'google_login_count': user.google_login_count or 0,
            # Último acesso veio pelo Google? As duas datas são gravadas no mesmo
            # instante quando o login é por Google, daí a comparação por >=.
            'last_login_via_google': bool(
                user.google_last_login_at and user.last_login
                and user.google_last_login_at >= user.last_login
            ),
            'mcp': mcp_por_usuario.get(user.id),
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


# ── Uso do MCP ────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_mcp_call(user_id: int, law_firm_id: int, kind: str, name: str,
                    ok: bool, elapsed_ms: int, error: str | None = None) -> None:
    """Soma uma chamada do MCP no agregado do dia. Comita sozinho; nunca levanta.

    Chamado pelo middleware do servidor MCP, fora de request Flask — por isso
    o commit é daqui, e qualquer falha só vai para o log: registrar uso nunca
    pode derrubar a ferramenta que o usuário chamou.
    """
    try:
        today = now_sp().date()
        agora = _utcnow()
        erro = (error or '')[:255] or None
        incremento = {
            'calls': UserMcpCall.calls + 1,
            'errors': UserMcpCall.errors + (0 if ok else 1),
            'total_ms': UserMcpCall.total_ms + max(0, int(elapsed_ms)),
            'last_called_at': agora,
        }
        if not ok:
            incremento['last_error'] = erro
        filtro = dict(user_id=user_id, kind=kind, name=name, call_date=today)
        if UserMcpCall.query.filter_by(**filtro).update(incremento, synchronize_session=False) == 0:
            try:
                with db.session.begin_nested():
                    db.session.add(UserMcpCall(
                        law_firm_id=law_firm_id, calls=1, errors=0 if ok else 1,
                        total_ms=max(0, int(elapsed_ms)), last_called_at=agora,
                        last_error=None if ok else erro, **filtro))
            except IntegrityError:
                # Chamada simultânea criou a linha primeiro: só incrementa.
                UserMcpCall.query.filter_by(**filtro).update(incremento, synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Falha ao registrar uso do MCP (ignorada)')


def _client_names() -> dict[str, str]:
    nomes = {}
    for c in McpOAuthClient.query.all():
        try:
            nomes[c.client_id] = json.loads(c.client_info_json).get('client_name') or 'Cliente MCP'
        except (TypeError, ValueError):
            nomes[c.client_id] = 'Cliente MCP'
    return nomes


def get_users_mcp(law_firm_id: int) -> dict[int, dict]:
    """Por usuário: conectado ao MCP agora?, clientes, primeiro/último uso, chamadas hoje.

    "Conectado" = tem token de renovação válido (não revogado e não vencido):
    é o que permite ao cliente continuar chamando sem novo login. Tokens
    vencidos são apagados com o tempo, então desde quando a pessoa usa o MCP
    sai do registro de uso, não do token.
    """
    agora = int(time.time())
    nomes = _client_names()
    por_usuario: dict[int, dict] = {}

    tokens = (McpOAuthToken.query
              .with_entities(McpOAuthToken.user_id, McpOAuthToken.client_id,
                             McpOAuthToken.token_type, McpOAuthToken.revoked,
                             McpOAuthToken.expires_at)
              .filter(McpOAuthToken.law_firm_id == law_firm_id).all())
    for user_id, client_id, token_type, revoked, expires_at in tokens:
        info = por_usuario.setdefault(user_id, {'connected': False, 'clients': set()})
        info['clients'].add(nomes.get(client_id, 'Cliente MCP'))
        if token_type == 'refresh' and not revoked and (expires_at is None or expires_at > agora):
            info['connected'] = True

    today = now_sp().date()
    # A API (/api/v1) grava na mesma tabela com kind='api'; conta à parte para
    # "chamadas do MCP" continuar sendo só ferramenta e comando pronto.
    eh_api = UserMcpCall.kind == 'api'
    eh_hoje = UserMcpCall.call_date == today
    uso = (db.session.query(
               UserMcpCall.user_id,
               db.func.min(db.case((eh_api, None), else_=UserMcpCall.call_date)),
               db.func.max(db.case((eh_api, None), else_=UserMcpCall.last_called_at)),
               db.func.sum(db.case((db.and_(eh_hoje, db.not_(eh_api)), UserMcpCall.calls), else_=0)),
               db.func.sum(db.case((eh_api, 0), else_=UserMcpCall.calls)),
               db.func.sum(db.case((db.and_(eh_hoje, eh_api), UserMcpCall.calls), else_=0)),
               db.func.sum(db.case((eh_api, UserMcpCall.calls), else_=0)))
           .filter(UserMcpCall.law_firm_id == law_firm_id)
           .group_by(UserMcpCall.user_id).all())
    for user_id, primeiro, ultimo, hoje, total, api_hoje, api_total in uso:
        info = por_usuario.setdefault(user_id, {'connected': False, 'clients': set()})
        info.update(first_use=primeiro, last_use=ultimo,
                    calls_today=int(hoje or 0), calls_total=int(total or 0),
                    api_calls_today=int(api_hoje or 0), api_calls_total=int(api_total or 0))

    for info in por_usuario.values():
        info['clients'] = sorted(info['clients'])
        info.setdefault('first_use', None)
        info.setdefault('last_use', None)
        info.setdefault('calls_today', 0)
        info.setdefault('calls_total', 0)
        info.setdefault('api_calls_today', 0)
        info.setdefault('api_calls_total', 0)
    return por_usuario


def get_mcp_overview(law_firm_id: int) -> dict:
    """Linha do topo: quantos estão conectados e quantos usaram hoje."""
    por_usuario = get_users_mcp(law_firm_id)
    ids = {u.id for u in User.query.with_entities(User.id).filter_by(law_firm_id=law_firm_id)}
    return {
        'mcp_connected': sum(1 for uid, i in por_usuario.items() if uid in ids and i['connected']),
        'mcp_active_today': sum(1 for uid, i in por_usuario.items() if uid in ids and i['calls_today']),
    }


def get_user_mcp_functions(law_firm_id: int, user_id: int, days: int = 30) -> list[dict]:
    """Funções do MCP usadas pelo usuário no período, agregadas por função."""
    since = now_sp().date() - timedelta(days=days)
    rows = (db.session.query(
                UserMcpCall.kind, UserMcpCall.name,
                db.func.sum(UserMcpCall.calls).label('calls'),
                db.func.sum(UserMcpCall.errors).label('errors'),
                db.func.sum(UserMcpCall.total_ms).label('total_ms'),
                db.func.max(UserMcpCall.last_called_at).label('last_called_at'),
            )
            .filter(UserMcpCall.law_firm_id == law_firm_id,
                    UserMcpCall.user_id == user_id,
                    UserMcpCall.call_date >= since)
            .group_by(UserMcpCall.kind, UserMcpCall.name)
            .order_by(db.func.max(UserMcpCall.last_called_at).desc(), UserMcpCall.name)
            .all())

    # Último erro de cada função: da linha mais recente que teve erro.
    ultimos_erros = {}
    for kind, name, erro in (UserMcpCall.query
                             .with_entities(UserMcpCall.kind, UserMcpCall.name, UserMcpCall.last_error)
                             .filter(UserMcpCall.law_firm_id == law_firm_id,
                                     UserMcpCall.user_id == user_id,
                                     UserMcpCall.call_date >= since,
                                     UserMcpCall.errors > 0)
                             .order_by(UserMcpCall.call_date)):
        ultimos_erros[(kind, name)] = erro

    return [{
        'kind': r.kind,
        'name': r.name,
        'calls': int(r.calls or 0),
        'errors': int(r.errors or 0),
        'avg_ms': int((r.total_ms or 0) / r.calls) if r.calls else 0,
        'last_called_at': r.last_called_at,
        'last_error': ultimos_erros.get((r.kind, r.name)),
    } for r in rows]
