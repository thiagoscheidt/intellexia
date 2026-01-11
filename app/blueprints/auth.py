from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from app.models import db, User, LawFirm
from datetime import datetime
import re

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard.dashboard'))
    return render_template('login.html')

@auth_bp.route('/login', methods=['POST'])
def login_post():
    email = request.form.get('email')
    password = request.form.get('password')
    remember = request.form.get('remember')
    
    if not email or not password:
        return jsonify({"success": False, "message": "Email e senha são obrigatórios"})
    
    user = User.query.filter_by(email=email).first()
    
    if not user:
        return jsonify({"success": False, "message": "Email ou senha incorretos"})
    
    if not user.is_active:
        return jsonify({"success": False, "message": "Sua conta está inativa. Entre em contato com o suporte."})
    
    if not user.law_firm.is_active:
        return jsonify({"success": False, "message": "O escritório está inativo. Entre em contato com o suporte."})
    
    if not user.check_password(password):
        return jsonify({"success": False, "message": "Email ou senha incorretos"})
    
    user.last_login = datetime.utcnow()
    user.last_activity = datetime.utcnow()
    db.session.commit()
    
    session['user_id'] = user.id
    session['user_email'] = user.email
    session['user_name'] = user.name
    session['user_role'] = user.role
    session['law_firm_id'] = user.law_firm_id
    session['law_firm_name'] = user.law_firm.name
    
    if remember:
        session.permanent = True
    
    return jsonify({
        "success": True, 
        "redirect": url_for('dashboard.dashboard'),
        "user": user.to_dict()
    })

@auth_bp.route('/register', methods=['GET'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard.dashboard'))
    return render_template('register.html')

@auth_bp.route('/register', methods=['POST'])
def register_post():
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    password = request.form.get('password')
    password_confirm = request.form.get('password_confirm')
    terms = request.form.get('terms')
    law_firm_name = request.form.get('law_firm_name')
    law_firm_cnpj = request.form.get('law_firm_cnpj')
    oab_number = request.form.get('oab_number')
    
    if not all([full_name, email, password, password_confirm, law_firm_name, law_firm_cnpj]):
        return jsonify({"success": False, "message": "Todos os campos obrigatórios devem ser preenchidos"})
    
    if password != password_confirm:
        return jsonify({"success": False, "message": "As senhas não coincidem"})
    
    if len(password) < 6:
        return jsonify({"success": False, "message": "A senha deve ter pelo menos 6 caracteres"})
    
    if not terms:
        return jsonify({"success": False, "message": "Você deve aceitar os termos de uso"})
    
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    if not email_pattern.match(email):
        return jsonify({"success": False, "message": "Email inválido"})
    
    if User.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "Este email já está cadastrado"})
    
    if LawFirm.query.filter_by(cnpj=law_firm_cnpj).first():
        return jsonify({"success": False, "message": "Este CNPJ já está cadastrado"})
    
    try:
        law_firm = LawFirm(
            name=law_firm_name,
            cnpj=law_firm_cnpj,
            is_active=True,
            subscription_plan='trial'
        )
        db.session.add(law_firm)
        db.session.flush()
        
        user = User(
            law_firm_id=law_firm.id,
            name=full_name,
            email=email,
            role='admin',
            oab_number=oab_number,
            is_active=True,
            is_verified=False
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "message": "Conta criada com sucesso! Faça login para continuar."
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False, 
            "message": f"Erro ao criar conta: {str(e)}"
        })

@auth_bp.route('/forgot-password', methods=['GET'])
def forgot_password():
    return render_template('forgot_password.html')

@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password_post():
    email = request.form.get('email')
    
    if not email:
        return jsonify({"success": False, "message": "Email é obrigatório"})
    
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    if not email_pattern.match(email):
        return jsonify({"success": False, "message": "Email inválido"})
    
    return jsonify({"success": True, "message": "Se o email existir em nosso sistema, você receberá as instruções para redefinir sua senha."})

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Você saiu do sistema com sucesso.', 'info')
    return redirect(url_for('auth.login'))
