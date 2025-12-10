from main import app
from flask import jsonify, render_template, session, request, redirect, url_for, flash
import hashlib
import uuid
import re

@app.before_request
def check_session():
    # Allow access to authentication routes and static files
    public_endpoints = ['login', 'login_post', 'register', 'register_post', 'forgot_password', 'forgot_password_post', 'static']
    if 'user_id' not in session and request.endpoint not in public_endpoints:
        if request.is_json:
            return jsonify({"error": "Unauthorized"}), 401
        else:
            return redirect(url_for('login'))

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200 

# Authentication routes
@app.route('/login', methods=['GET'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login_post():
    email = request.form.get('email')
    password = request.form.get('password')
    
    # Simple validation (in production, use proper authentication)
    if not email or not password:
        return jsonify({"success": False, "message": "Email e senha são obrigatórios"})
    
    # Demo user for testing (replace with real database authentication)
    if email == "admin@intellexia.com.br" and password == "admin123":
        session['user_id'] = str(uuid.uuid4())
        session['user_email'] = email
        session['user_name'] = "Administrador"
        return jsonify({"success": True, "redirect": url_for('index')})
    else:
        return jsonify({"success": False, "message": "Email ou senha inválidos"})

@app.route('/register', methods=['GET'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/register', methods=['POST'])
def register_post():
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    password = request.form.get('password')
    password_confirm = request.form.get('password_confirm')
    terms = request.form.get('terms')
    
    # Validation
    if not all([full_name, email, password, password_confirm]):
        return jsonify({"success": False, "message": "Todos os campos são obrigatórios"})
    
    if password != password_confirm:
        return jsonify({"success": False, "message": "As senhas não coincidem"})
    
    if len(password) < 6:
        return jsonify({"success": False, "message": "A senha deve ter pelo menos 6 caracteres"})
    
    if not terms:
        return jsonify({"success": False, "message": "Você deve aceitar os termos de uso"})
    
    # Email validation
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    if not email_pattern.match(email):
        return jsonify({"success": False, "message": "Email inválido"})
    
    # In production, save to database
    # For demo purposes, just return success
    return jsonify({"success": True, "message": "Conta criada com sucesso! Faça login para continuar."})

@app.route('/forgot-password', methods=['GET'])
def forgot_password():
    return render_template('forgot_password.html')

@app.route('/forgot-password', methods=['POST'])
def forgot_password_post():
    email = request.form.get('email')
    
    if not email:
        return jsonify({"success": False, "message": "Email é obrigatório"})
    
    # Email validation
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    if not email_pattern.match(email):
        return jsonify({"success": False, "message": "Email inválido"})
    
    # In production, send email with reset link
    # For demo purposes, always return success
    return jsonify({"success": True, "message": "Se o email existir em nosso sistema, você receberá as instruções para redefinir sua senha."})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Dashboard routes
@app.route('/')
def index():
    message = request.args.get('message')
    if message:
        flash(message) 
    return render_template('dashboard1.html')
@app.route('/cases')
def cases():
    return render_template('cases.html')

@app.route('/case/<int:case_id>')
def case_detail(case_id):
    return render_template('case_detail.html', case_id=case_id)

@app.route('/dashboard2')
def index2():
    return render_template('dashboard2.html')

@app.route('/dashboard3')
def index3():
    return render_template('index3.html')
