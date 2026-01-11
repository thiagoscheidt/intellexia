"""
Middlewares e contexto da aplicação
"""
from flask import session, request, redirect, url_for, jsonify
from app.models import db, User
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
