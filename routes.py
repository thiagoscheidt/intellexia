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

@app.route('/dashboard2')
def index2():
    return render_template('dashboard2.html')

@app.route('/dashboard3')
def index3():
    return render_template('index3.html')

# ========================
# Rotas de Clientes
# ========================
@app.route('/clients')
def clients_list():
    # TODO: Buscar clientes do banco de dados
    clients = []
    return render_template('clients/list.html', clients=clients)

@app.route('/clients/new', methods=['GET', 'POST'])
def client_new():
    from app.form import ClientForm
    form = ClientForm()
    
    if form.validate_on_submit():
        # TODO: Salvar no banco de dados
        flash('Cliente cadastrado com sucesso!', 'success')
        return redirect(url_for('clients_list'))
    
    return render_template('clients/form.html', form=form, title='Novo Cliente')

@app.route('/clients/<int:client_id>/edit', methods=['GET', 'POST'])
def client_edit(client_id):
    from app.form import ClientForm
    # TODO: Buscar cliente do banco de dados
    form = ClientForm()
    
    if form.validate_on_submit():
        # TODO: Atualizar no banco de dados
        flash('Cliente atualizado com sucesso!', 'success')
        return redirect(url_for('clients_list'))
    
    return render_template('clients/form.html', form=form, title='Editar Cliente', client_id=client_id)

@app.route('/clients/<int:client_id>/delete', methods=['POST'])
def client_delete(client_id):
    # TODO: Deletar do banco de dados
    flash('Cliente excluído com sucesso!', 'success')
    return redirect(url_for('clients_list'))

# ========================
# Rotas de Casos
# ========================
@app.route('/cases')
def cases_list():
    # TODO: Buscar casos do banco de dados
    cases = []
    return render_template('cases/list.html', cases=cases)

@app.route('/cases/new', methods=['GET', 'POST'])
def case_new():
    from app.form import CaseForm
    form = CaseForm()
    
    # TODO: Carregar opções de clientes e varas do banco
    form.client_id.choices = [(0, 'Selecione um cliente')]
    form.court_id.choices = [(0, 'Selecione uma vara')]
    
    if form.validate_on_submit():
        # TODO: Salvar no banco de dados
        flash('Caso cadastrado com sucesso!', 'success')
        return redirect(url_for('cases_list'))
    
    return render_template('cases/form.html', form=form, title='Novo Caso')

@app.route('/cases/<int:case_id>/edit', methods=['GET', 'POST'])
def case_edit(case_id):
    from app.form import CaseForm
    form = CaseForm()
    
    # TODO: Carregar opções de clientes e varas do banco
    form.client_id.choices = [(0, 'Selecione um cliente')]
    form.court_id.choices = [(0, 'Selecione uma vara')]
    
    if form.validate_on_submit():
        # TODO: Atualizar no banco de dados
        flash('Caso atualizado com sucesso!', 'success')
        return redirect(url_for('cases_list'))
    
    return render_template('cases/form.html', form=form, title='Editar Caso', case_id=case_id)

@app.route('/cases/<int:case_id>/delete', methods=['POST'])
def case_delete(case_id):
    # TODO: Deletar do banco de dados
    flash('Caso excluído com sucesso!', 'success')
    return redirect(url_for('cases_list'))

@app.route('/cases/<int:case_id>')
def case_detail(case_id):
    # TODO: Buscar caso do banco de dados
    return render_template('cases/detail.html', case_id=case_id)

# ========================
# Rotas de Documentos do Caso
# ========================
@app.route('/cases/<int:case_id>/documents')
def case_documents_list(case_id):
    # TODO: Buscar documentos do caso no banco de dados
    documents = []
    return render_template('cases/documents_list.html', case_id=case_id, documents=documents)

@app.route('/cases/<int:case_id>/documents/new', methods=['GET', 'POST'])
def case_document_new(case_id):
    from app.form import DocumentForm
    form = DocumentForm()
    
    # TODO: Carregar opções de benefícios do caso
    form.related_benefit_id.choices = [(0, 'Nenhum')]
    
    if form.validate_on_submit():
        # TODO: Salvar arquivo e cadastrar no banco de dados
        flash('Documento enviado com sucesso!', 'success')
        return redirect(url_for('case_documents_list', case_id=case_id))
    
    return render_template('cases/document_form.html', form=form, case_id=case_id, title='Upload Documento')

@app.route('/cases/<int:case_id>/documents/<int:document_id>/delete', methods=['POST'])
def case_document_delete(case_id, document_id):
    # TODO: Deletar documento do banco de dados
    flash('Documento excluído com sucesso!', 'success')
    return redirect(url_for('case_documents_list', case_id=case_id))

# ========================
# Rotas de Advogados
# ========================
@app.route('/lawyers')
def lawyers_list():
    # TODO: Buscar advogados do banco de dados
    lawyers = []
    return render_template('lawyers/list.html', lawyers=lawyers)

@app.route('/lawyers/new', methods=['GET', 'POST'])
def lawyer_new():
    from app.form import LawyerForm
    form = LawyerForm()
    
    if form.validate_on_submit():
        # TODO: Salvar no banco de dados
        flash('Advogado cadastrado com sucesso!', 'success')
        return redirect(url_for('lawyers_list'))
    
    return render_template('lawyers/form.html', form=form, title='Novo Advogado')

@app.route('/lawyers/<int:lawyer_id>/edit', methods=['GET', 'POST'])
def lawyer_edit(lawyer_id):
    from app.form import LawyerForm
    form = LawyerForm()
    
    if form.validate_on_submit():
        # TODO: Atualizar no banco de dados
        flash('Advogado atualizado com sucesso!', 'success')
        return redirect(url_for('lawyers_list'))
    
    return render_template('lawyers/form.html', form=form, title='Editar Advogado', lawyer_id=lawyer_id)

# ========================
# Rotas de Varas
# ========================
@app.route('/courts')
def courts_list():
    # TODO: Buscar varas do banco de dados
    courts = []
    return render_template('courts/list.html', courts=courts)

@app.route('/courts/new', methods=['GET', 'POST'])
def court_new():
    from app.form import CourtForm
    form = CourtForm()
    
    if form.validate_on_submit():
        # TODO: Salvar no banco de dados
        flash('Vara cadastrada com sucesso!', 'success')
        return redirect(url_for('courts_list'))
    
    return render_template('courts/form.html', form=form, title='Nova Vara')

# ========================
# Rotas de Benefícios
# ========================
@app.route('/benefits')
def benefits_list():
    # TODO: Buscar benefícios do banco de dados
    benefits = []
    return render_template('benefits/list.html', benefits=benefits)

@app.route('/benefits/new', methods=['GET', 'POST'])
def benefit_new():
    from app.form import CaseBenefitForm
    form = CaseBenefitForm()
    
    # TODO: Carregar opções de casos do banco
    form.case_id.choices = [(0, 'Selecione um caso')]
    
    if form.validate_on_submit():
        # TODO: Salvar no banco de dados
        flash('Benefício cadastrado com sucesso!', 'success')
        return redirect(url_for('benefits_list'))
    
    return render_template('benefits/form.html', form=form, title='Novo Benefício')

