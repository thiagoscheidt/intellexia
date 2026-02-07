"""
Middlewares e contexto da aplicação
"""
from flask import session, request, redirect, url_for, jsonify
from sqlalchemy.orm import joinedload
from app.models import db, User, Case, CaseComment
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
            if user:
                user.last_activity = datetime.utcnow()
                db.session.commit()

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
