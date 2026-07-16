"""
Middlewares e contexto da aplicação
"""
from flask import session, request, redirect, url_for, jsonify, flash
from sqlalchemy.orm import joinedload
from app.models import db, User, Case, CaseComment
from app.utils.permissions import (
    MODULE_PERMISSIONS,
    can_access_endpoint,
    get_landing_endpoint,
    has_module_permission,
    parse_module_permissions,
)
from app.utils.urls import app_public_url, mcp_public_url
from datetime import datetime
from functools import wraps

def init_app_middlewares(app):
    """Inicializa todos os middlewares da aplicação"""
    
    @app.before_request
    def check_session():
        """Verifica autenticação antes de cada requisição"""
        public_endpoints = ['auth.login', 'auth.login_post', 'auth.register', 'auth.register_post', 
                           'auth.forgot_password', 'auth.forgot_password_post', 'static']
        
        if 'user_id' not in session and request.endpoint not in public_endpoints:
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            else:
                return redirect(url_for('auth.login'))
        
        # Se está autenticado, atualizar última atividade
        if 'user_id' in session and request.endpoint not in public_endpoints:
            user = User.query.get(session['user_id'])
            if not user:
                session.clear()
                if request.is_json:
                    return jsonify({"error": "Unauthorized"}), 401
                return redirect(url_for('auth.login'))

            user.last_activity = datetime.now()
            db.session.commit()

            session['user_role'] = user.role
            session['user_module_permissions'] = user.get_module_permissions()

            if not can_access_endpoint(request.endpoint, user.role, user.module_permissions):
                if request.is_json:
                    return jsonify({"error": "Acesso negado"}), 403
                flash('Acesso negado para este modulo.', 'danger')
                landing_endpoint = get_landing_endpoint(user.role, user.module_permissions)
                return redirect(url_for(landing_endpoint))

    @app.context_processor
    def inject_recent_case_comments():
        """Injeta comentários recentes para o header"""
        law_firm_id = session.get('law_firm_id')
        if not law_firm_id:
            return {
                'recent_case_comments': [],
                'recent_case_comments_count': 0
            }

        comments = (CaseComment.query
            .join(Case, CaseComment.case_id == Case.id)
            .options(joinedload(CaseComment.user), joinedload(CaseComment.case))
            .filter(Case.law_firm_id == law_firm_id)
            .order_by(CaseComment.created_at.desc())
            .limit(5)
            .all()
        )

        recent_items = []
        for comment in comments:
            recent_items.append({
                'id': comment.id,
                'case_id': comment.case_id,
                'case_title': comment.case.title if comment.case else 'Caso',
                'user_name': comment.user.name if comment.user else 'Usuário',
                'title': comment.title or 'Comentário',
                'content': comment.content,
                'created_at': comment.created_at,
            })

        return {
            'recent_case_comments': recent_items,
            'recent_case_comments_count': len(recent_items)
        }

    @app.context_processor
    def inject_public_urls():
        """URLs públicas para os templates (modal do conector MCP, manual)."""
        return {
            'app_public_url': app_public_url(),
            'mcp_public_url': mcp_public_url(),
        }

    @app.context_processor
    def inject_module_permissions():
        role = session.get('user_role')
        permissions = parse_module_permissions(session.get('user_module_permissions'), role)
        permissions_set = set(permissions)

        def can_view_module(module_key):
            return module_key in permissions_set

        return {
            'module_permissions_catalog': MODULE_PERMISSIONS,
            'current_module_permissions': permissions,
            'can_view_module': can_view_module,
            'has_module_permission': lambda module_key: has_module_permission(module_key, role, permissions),
        }

def get_current_law_firm_id():
    """Retorna o law_firm_id do usuário logado"""
    return session.get('law_firm_id')

def require_law_firm(f):
    """Decorator para garantir que o usuário tem um escritório associado"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            else:
                return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function
