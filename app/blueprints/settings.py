import re

from flask import Blueprint, render_template, session, redirect, url_for, jsonify, flash, request
from app.models import db, LawFirm, User
from datetime import datetime
from functools import wraps

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')

EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
MIN_PASSWORD_LENGTH = 6

def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('law_firm_id'):
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            else:
                return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@settings_bp.route('/law-firm', methods=['GET'])
@require_law_firm
def law_firm_settings():
    """Página de configurações do escritório (apenas admin)"""
    if session.get('user_role') != 'admin':
        flash('Acesso negado. Apenas administradores podem acessar esta página.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    
    law_firm_id = session.get('law_firm_id')
    if not law_firm_id:
        flash('Escritório não encontrado.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    
    law_firm = LawFirm.query.get(law_firm_id)
    if not law_firm:
        flash('Escritório não encontrado.', 'danger')
        return redirect(url_for('dashboard.dashboard'))
    
    return render_template('settings/law_firm.html', law_firm=law_firm)

@settings_bp.route('/law-firm', methods=['POST'])
@require_law_firm
def law_firm_settings_post():
    """Atualizar dados do escritório (apenas admin)"""
    if session.get('user_role') != 'admin':
        return jsonify({"success": False, "message": "Acesso negado"}), 403
    
    law_firm_id = session.get('law_firm_id')
    if not law_firm_id:
        return jsonify({"success": False, "message": "Escritório não encontrado"}), 404
    
    law_firm = LawFirm.query.get(law_firm_id)
    if not law_firm:
        return jsonify({"success": False, "message": "Escritório não encontrado"}), 404
    
    try:
        law_firm.name = request.form.get('name', law_firm.name)
        law_firm.trade_name = request.form.get('trade_name', law_firm.trade_name)
        law_firm.cnpj = request.form.get('cnpj', law_firm.cnpj)
        
        law_firm.street = request.form.get('street', law_firm.street)
        law_firm.number = request.form.get('number', law_firm.number)
        law_firm.complement = request.form.get('complement', law_firm.complement)
        law_firm.district = request.form.get('district', law_firm.district)
        law_firm.city = request.form.get('city', law_firm.city)
        law_firm.state = request.form.get('state', law_firm.state)
        law_firm.zip_code = request.form.get('zip_code', law_firm.zip_code)
        
        law_firm.phone = request.form.get('phone', law_firm.phone)
        law_firm.email = request.form.get('email', law_firm.email)
        law_firm.website = request.form.get('website', law_firm.website)
        
        law_firm.updated_at = datetime.now()
        
        db.session.commit()
        
        session['law_firm_name'] = law_firm.name
        
        return jsonify({
            "success": True, 
            "message": "Dados do escritório atualizados com sucesso!"
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "message": f"Erro ao atualizar dados: {str(e)}"
        }), 500


def _get_logged_user():
    """Usuário da sessão. Nunca aceita id vindo da requisição."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(user_id)


@settings_bp.route('/profile', methods=['GET'])
@require_law_firm
def profile():
    """Página de perfil do usuário logado"""
    user = _get_logged_user()
    if not user:
        flash('Usuário não encontrado.', 'danger')
        return redirect(url_for('auth.login'))

    return render_template('settings/profile.html', user=user)


@settings_bp.route('/profile', methods=['POST'])
@require_law_firm
def profile_post():
    """Atualizar dados pessoais do usuário logado"""
    user = _get_logged_user()
    if not user:
        return jsonify({"success": False, "message": "Usuário não encontrado"}), 404

    name = (request.form.get('name') or '').strip()
    email = (request.form.get('email') or '').strip()

    if not name or not email:
        return jsonify({"success": False, "message": "Nome e e-mail são obrigatórios"}), 400

    if not EMAIL_PATTERN.match(email):
        return jsonify({"success": False, "message": "E-mail inválido"}), 400

    email_owner = User.query.filter(User.email == email, User.id != user.id).first()
    if email_owner:
        return jsonify({"success": False, "message": "Este e-mail já está em uso por outro usuário"}), 400

    try:
        # role, law_firm_id e is_active não são editáveis aqui, mesmo que venham no form.
        user.name = name
        user.email = email
        user.phone = (request.form.get('phone') or '').strip() or None
        user.oab_number = (request.form.get('oab_number') or '').strip() or None
        user.updated_at = datetime.now()

        db.session.commit()

        session['user_name'] = user.name
        session['user_email'] = user.email

        return jsonify({"success": True, "message": "Perfil atualizado com sucesso!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Erro ao atualizar perfil: {str(e)}"}), 500


@settings_bp.route('/profile/password', methods=['POST'])
@require_law_firm
def profile_password_post():
    """Alterar a senha do usuário logado"""
    user = _get_logged_user()
    if not user:
        return jsonify({"success": False, "message": "Usuário não encontrado"}), 404

    current_password = request.form.get('current_password') or ''
    new_password = request.form.get('new_password') or ''
    confirm_password = request.form.get('confirm_password') or ''

    if not all([current_password, new_password, confirm_password]):
        return jsonify({"success": False, "message": "Preencha todos os campos de senha"}), 400

    if not user.check_password(current_password):
        return jsonify({"success": False, "message": "A senha atual está incorreta"}), 400

    if new_password != confirm_password:
        return jsonify({"success": False, "message": "A nova senha e a confirmação não coincidem"}), 400

    if len(new_password) < MIN_PASSWORD_LENGTH:
        return jsonify({
            "success": False,
            "message": f"A nova senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres",
        }), 400

    if new_password == current_password:
        return jsonify({"success": False, "message": "A nova senha deve ser diferente da atual"}), 400

    try:
        user.set_password(new_password)
        user.updated_at = datetime.now()
        db.session.commit()

        return jsonify({"success": True, "message": "Senha alterada com sucesso!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Erro ao alterar senha: {str(e)}"}), 500
