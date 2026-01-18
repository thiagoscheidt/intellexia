from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify, flash
from functools import wraps
from app.models import db, User

admin_users_bp = Blueprint('admin_users', __name__, url_prefix='/admin/users')


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


@admin_users_bp.route('/', methods=['GET'])
@require_law_firm
@require_admin
def list_users():
    law_firm_id = session.get('law_firm_id')
    users = User.query.filter_by(law_firm_id=law_firm_id).order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)


@admin_users_bp.route('/', methods=['POST'])
@require_law_firm
@require_admin
def create_user():
    law_firm_id = session.get('law_firm_id')
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'user').strip() or 'user'

    if not name or not email or not password:
        return jsonify({"success": False, "message": "Nome, email e senha são obrigatórios."}), 400

    existing = User.query.filter_by(email=email).first()
    if existing:
        return jsonify({"success": False, "message": "Já existe um usuário com esse email."}), 400

    try:
        user = User(
            law_firm_id=law_firm_id,
            name=name,
            email=email,
            role=role,
            is_active=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return jsonify({"success": True, "message": "Usuário criado com sucesso."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Erro ao criar usuário: {str(e)}"}), 500


@admin_users_bp.route('/<int:user_id>/toggle', methods=['POST'])
@require_law_firm
@require_admin
def toggle_user(user_id):
    law_firm_id = session.get('law_firm_id')
    user = User.query.filter_by(id=user_id, law_firm_id=law_firm_id).first()
    if not user:
        return jsonify({"success": False, "message": "Usuário não encontrado."}), 404

    try:
        user.is_active = not user.is_active
        db.session.commit()
        return jsonify({"success": True, "active": user.is_active})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Erro ao atualizar: {str(e)}"}), 500


@admin_users_bp.route('/<int:user_id>', methods=['POST'])
@require_law_firm
@require_admin
def update_user(user_id):
    law_firm_id = session.get('law_firm_id')
    user = User.query.filter_by(id=user_id, law_firm_id=law_firm_id).first()
    if not user:
        return jsonify({"success": False, "message": "Usuário não encontrado."}), 404

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    role = request.form.get('role', '').strip() or user.role
    password = request.form.get('password', '').strip()

    if not name or not email:
        return jsonify({"success": False, "message": "Nome e email são obrigatórios."}), 400

    existing = User.query.filter(User.email == email, User.id != user.id).first()
    if existing:
        return jsonify({"success": False, "message": "Já existe um usuário com esse email."}), 400

    try:
        user.name = name
        user.email = email
        user.role = role
        if password:
            user.set_password(password)
        db.session.commit()
        return jsonify({"success": True, "message": "Usuário atualizado com sucesso."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Erro ao atualizar usuário: {str(e)}"}), 500
