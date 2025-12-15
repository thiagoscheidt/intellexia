from main import app
from flask import jsonify, render_template, session, request, redirect, url_for, flash
from app.models import db, Client, Court, Lawyer, Case, CaseLawyer, CaseBenefit, Document, CaseCompetence
import hashlib
import uuid
import re
from datetime import datetime, date
from decimal import Decimal
import os
from werkzeug.utils import secure_filename

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
    clients = Client.query.order_by(Client.created_at.desc()).all()
    return render_template('clients/list.html', clients=clients)

@app.route('/clients/new', methods=['GET', 'POST'])
def client_new():
    from app.form import ClientForm
    form = ClientForm()
    
    if form.validate_on_submit():
        client = Client(
            name=form.name.data,
            cnpj=form.cnpj.data,
            street=form.street.data,
            number=form.number.data,
            district=form.district.data,
            city=form.city.data,
            state=form.state.data,
            zip_code=form.zip_code.data,
            has_branches=form.has_branches.data,
            branches_description=form.branches_description.data
        )
        
        db.session.add(client)
        try:
            db.session.commit()
            flash('Cliente cadastrado com sucesso!', 'success')
            return redirect(url_for('clients_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar cliente: {str(e)}', 'danger')
    
    return render_template('clients/form.html', form=form, title='Novo Cliente')

@app.route('/clients/<int:client_id>/edit', methods=['GET', 'POST'])
def client_edit(client_id):
    from app.form import ClientForm
    client = Client.query.get_or_404(client_id)
    form = ClientForm(obj=client)
    
    if form.validate_on_submit():
        client.name = form.name.data
        client.cnpj = form.cnpj.data
        client.street = form.street.data
        client.number = form.number.data
        client.district = form.district.data
        client.city = form.city.data
        client.state = form.state.data
        client.zip_code = form.zip_code.data
        client.has_branches = form.has_branches.data
        client.branches_description = form.branches_description.data
        client.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash('Cliente atualizado com sucesso!', 'success')
            return redirect(url_for('clients_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar cliente: {str(e)}', 'danger')
    
    return render_template('clients/form.html', form=form, title='Editar Cliente', client_id=client_id)

@app.route('/clients/<int:client_id>/delete', methods=['POST'])
def client_delete(client_id):
    client = Client.query.get_or_404(client_id)
    
    # Verificar se cliente tem casos associados
    if client.cases:
        flash('Não é possível excluir cliente que possui casos associados.', 'warning')
        return redirect(url_for('clients_list'))
    
    try:
        db.session.delete(client)
        db.session.commit()
        flash('Cliente excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir cliente: {str(e)}', 'danger')
    
    return redirect(url_for('clients_list'))

# ========================
# Rotas de Casos
# ========================
@app.route('/cases')
def cases_list():
    cases = Case.query.join(Client).order_by(Case.created_at.desc()).all()
    return render_template('cases/list.html', cases=cases)

@app.route('/cases/new', methods=['GET', 'POST'])
def case_new():
    from app.form import CaseForm
    form = CaseForm()
    
    # Carregar opções de clientes e varas
    clients = Client.query.order_by(Client.name).all()
    courts = Court.query.order_by(Court.vara_name).all()
    
    form.client_id.choices = [(0, 'Selecione um cliente')] + [(c.id, c.name) for c in clients]
    form.court_id.choices = [(0, 'Selecione uma vara')] + [(c.id, f"{c.vara_name} - {c.city}/{c.state}") for c in courts]
    
    if form.validate_on_submit():
        case = Case(
            client_id=form.client_id.data if form.client_id.data != 0 else None,
            court_id=form.court_id.data if form.court_id.data != 0 else None,
            title=form.title.data,
            case_type=form.case_type.data,
            fap_start_year=form.fap_start_year.data,
            fap_end_year=form.fap_end_year.data,
            facts_summary=form.facts_summary.data,
            thesis_summary=form.thesis_summary.data,
            prescription_summary=form.prescription_summary.data,
            value_cause=form.value_cause.data,
            status=form.status.data,
            filing_date=form.filing_date.data
        )
        
        db.session.add(case)
        try:
            db.session.commit()
            flash('Caso cadastrado com sucesso!', 'success')
            return redirect(url_for('cases_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar caso: {str(e)}', 'danger')
    
    return render_template('cases/form.html', form=form, title='Novo Caso')

@app.route('/cases/<int:case_id>/edit', methods=['GET', 'POST'])
def case_edit(case_id):
    from app.form import CaseForm
    case = Case.query.get_or_404(case_id)
    form = CaseForm(obj=case)
    
    # Carregar opções de clientes e varas
    clients = Client.query.order_by(Client.name).all()
    courts = Court.query.order_by(Court.vara_name).all()
    
    form.client_id.choices = [(0, 'Selecione um cliente')] + [(c.id, c.name) for c in clients]
    form.court_id.choices = [(0, 'Selecione uma vara')] + [(c.id, f"{c.vara_name} - {c.city}/{c.state}") for c in courts]
    
    if form.validate_on_submit():
        case.client_id = form.client_id.data if form.client_id.data != 0 else None
        case.court_id = form.court_id.data if form.court_id.data != 0 else None
        case.title = form.title.data
        case.case_type = form.case_type.data
        case.fap_start_year = form.fap_start_year.data
        case.fap_end_year = form.fap_end_year.data
        case.facts_summary = form.facts_summary.data
        case.thesis_summary = form.thesis_summary.data
        case.prescription_summary = form.prescription_summary.data
        case.value_cause = form.value_cause.data
        case.status = form.status.data
        case.filing_date = form.filing_date.data
        case.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash('Caso atualizado com sucesso!', 'success')
            return redirect(url_for('cases_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar caso: {str(e)}', 'danger')
@app.route('/cases/<int:case_id>/delete', methods=['POST'])
def case_delete(case_id):
    case = Case.query.get_or_404(case_id)
    
    try:
        db.session.delete(case)
        db.session.commit()
        flash('Caso excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir caso: {str(e)}', 'danger')
    
    return redirect(url_for('cases_list'))

@app.route('/cases/<int:case_id>')
def case_detail(case_id):
    case = Case.query.get_or_404(case_id)
    benefits = CaseBenefit.query.filter_by(case_id=case_id).all()
    documents = Document.query.filter_by(case_id=case_id).all()
    competences = CaseCompetence.query.filter_by(case_id=case_id).all()
    return render_template('cases/detail.html', case=case, benefits=benefits, documents=documents, competences=competences)

# ========================
# Rotas de Documentos do Caso
# ========================
@app.route('/cases/<int:case_id>/documents')
def case_documents_list(case_id):
    case = Case.query.get_or_404(case_id)
    documents = Document.query.filter_by(case_id=case_id).order_by(Document.uploaded_at.desc()).all()
    return render_template('cases/documents_list.html', case=case, documents=documents)

@app.route('/cases/<int:case_id>/documents/new', methods=['GET', 'POST'])
def case_document_new(case_id):
    from app.form import DocumentForm
    case = Case.query.get_or_404(case_id)
    form = DocumentForm()
    
    # Carregar benefícios do caso
    benefits = CaseBenefit.query.filter_by(case_id=case_id).all()
    form.related_benefit_id.choices = [(0, 'Nenhum')] + [(b.id, f"{b.benefit_number} - {b.insured_name}") for b in benefits]
    
    if form.validate_on_submit():
        # Processar upload do arquivo
        file = form.file.data
        if file:
            filename = secure_filename(file.filename)
            # Criar diretório se não existir
            upload_dir = f"uploads/cases/{case_id}"
            os.makedirs(upload_dir, exist_ok=True)
            file_path = os.path.join(upload_dir, filename)
            file.save(file_path)
            
            document = Document(
                case_id=case_id,
                related_benefit_id=form.related_benefit_id.data if form.related_benefit_id.data != 0 else None,
                original_filename=filename,
                file_path=file_path,
                document_type=form.document_type.data,
                description=form.description.data,
                use_in_ai=form.use_in_ai.data
            )
            
            db.session.add(document)
            try:
                db.session.commit()
                flash('Documento enviado com sucesso!', 'success')
                return redirect(url_for('case_documents_list', case_id=case_id))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao salvar documento: {str(e)}', 'danger')
        else:
            flash('Nenhum arquivo foi selecionado.', 'warning')
    
    return render_template('cases/document_form.html', form=form, case=case, title='Upload Documento')

@app.route('/cases/<int:case_id>/documents/<int:document_id>/delete', methods=['POST'])
def case_document_delete(case_id, document_id):
    document = Document.query.get_or_404(document_id)
    
    # Verificar se o documento pertence ao caso
    if document.case_id != case_id:
        flash('Documento não encontrado neste caso.', 'error')
        return redirect(url_for('case_documents_list', case_id=case_id))
    
    try:
        # Deletar arquivo físico
        if os.path.exists(document.file_path):
            os.remove(document.file_path)
        
        db.session.delete(document)
        db.session.commit()
        flash('Documento excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir documento: {str(e)}', 'danger')
    
    return redirect(url_for('case_documents_list', case_id=case_id))

# ========================
# Rotas de Advogados
# ========================
@app.route('/lawyers')
def lawyers_list():
    lawyers = Lawyer.query.order_by(Lawyer.name).all()
    return render_template('lawyers/list.html', lawyers=lawyers)

@app.route('/lawyers/new', methods=['GET', 'POST'])
def lawyer_new():
    from app.form import LawyerForm
    form = LawyerForm()
    
    if form.validate_on_submit():
        lawyer = Lawyer(
            name=form.name.data,
            oab_number=form.oab_number.data,
            email=form.email.data,
            phone=form.phone.data,
            is_default_for_publications=form.is_default_for_publications.data
        )
        
        db.session.add(lawyer)
        try:
            db.session.commit()
            flash('Advogado cadastrado com sucesso!', 'success')
            return redirect(url_for('lawyers_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar advogado: {str(e)}', 'danger')
    
    return render_template('lawyers/form.html', form=form, title='Novo Advogado')

@app.route('/lawyers/<int:lawyer_id>/edit', methods=['GET', 'POST'])
def lawyer_edit(lawyer_id):
    from app.form import LawyerForm
    lawyer = Lawyer.query.get_or_404(lawyer_id)
    form = LawyerForm(obj=lawyer)
    
    if form.validate_on_submit():
        lawyer.name = form.name.data
        lawyer.oab_number = form.oab_number.data
        lawyer.email = form.email.data
        lawyer.phone = form.phone.data
        lawyer.is_default_for_publications = form.is_default_for_publications.data
        lawyer.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash('Advogado atualizado com sucesso!', 'success')
            return redirect(url_for('lawyers_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar advogado: {str(e)}', 'danger')
    
    return render_template('lawyers/form.html', form=form, title='Editar Advogado', lawyer_id=lawyer_id)

# ========================
# Rotas de Varas
# ========================
@app.route('/courts')
def courts_list():
    courts = Court.query.order_by(Court.vara_name).all()
    return render_template('courts/list.html', courts=courts)

@app.route('/courts/new', methods=['GET', 'POST'])
def court_new():
    from app.form import CourtForm
    form = CourtForm()
    
    if form.validate_on_submit():
        court = Court(
            section=form.section.data,
            vara_name=form.vara_name.data,
            city=form.city.data,
            state=form.state.data
        )
        
        db.session.add(court)
        try:
            db.session.commit()
            flash('Vara cadastrada com sucesso!', 'success')
            return redirect(url_for('courts_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar vara: {str(e)}', 'danger')
    
    return render_template('courts/form.html', form=form, title='Nova Vara')

# ========================
# Rotas de Benefícios
# ========================
@app.route('/benefits')
def benefits_list():
    benefits = CaseBenefit.query.join(Case).join(Client).order_by(CaseBenefit.created_at.desc()).all()
    return render_template('benefits/list.html', benefits=benefits)

@app.route('/benefits/new', methods=['GET', 'POST'])
def benefit_new():
    from app.form import CaseBenefitForm
    form = CaseBenefitForm()
    
    # Carregar opções de casos
    cases = Case.query.join(Client).order_by(Case.title).all()
    form.case_id.choices = [(0, 'Selecione um caso')] + [(c.id, f"{c.title} - {c.client.name}") for c in cases]
    
    if form.validate_on_submit():
        benefit = CaseBenefit(
            case_id=form.case_id.data,
            benefit_number=form.benefit_number.data,
            benefit_type=form.benefit_type.data,
            insured_name=form.insured_name.data,
            insured_nit=form.insured_nit.data,
            accident_date=form.accident_date.data,
            accident_company_name=form.accident_company_name.data,
            error_reason=form.error_reason.data,
            notes=form.notes.data
        )
        
        db.session.add(benefit)
        try:
            db.session.commit()
            flash('Benefício cadastrado com sucesso!', 'success')
            return redirect(url_for('benefits_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar benefício: {str(e)}', 'danger')
    
    return render_template('benefits/form.html', form=form, title='Novo Benefício')

# Rotas adicionais que faltaram

@app.route('/lawyers/<int:lawyer_id>/delete', methods=['POST'])
def lawyer_delete(lawyer_id):
    lawyer = Lawyer.query.get_or_404(lawyer_id)
    
    # Verificar se advogado tem casos associados
    if lawyer.case_lawyers:
        flash('Não é possível excluir advogado que possui casos associados.', 'warning')
        return redirect(url_for('lawyers_list'))
    
    try:
        db.session.delete(lawyer)
        db.session.commit()
        flash('Advogado excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir advogado: {str(e)}', 'danger')
    
    return redirect(url_for('lawyers_list'))

@app.route('/courts/<int:court_id>/edit', methods=['GET', 'POST'])
def court_edit(court_id):
    from app.form import CourtForm
    court = Court.query.get_or_404(court_id)
    form = CourtForm(obj=court)
    
    if form.validate_on_submit():
        court.section = form.section.data
        court.vara_name = form.vara_name.data
        court.city = form.city.data
        court.state = form.state.data
        court.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash('Vara atualizada com sucesso!', 'success')
            return redirect(url_for('courts_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar vara: {str(e)}', 'danger')
    
    return render_template('courts/form.html', form=form, title='Editar Vara', court_id=court_id)

@app.route('/courts/<int:court_id>/delete', methods=['POST'])
def court_delete(court_id):
    court = Court.query.get_or_404(court_id)
    
    # Verificar se vara tem casos associados
    if court.cases:
        flash('Não é possível excluir vara que possui casos associados.', 'warning')
        return redirect(url_for('courts_list'))
    
    try:
        db.session.delete(court)
        db.session.commit()
        flash('Vara excluída com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir vara: {str(e)}', 'danger')
    
    return redirect(url_for('courts_list'))

@app.route('/benefits/<int:benefit_id>/edit', methods=['GET', 'POST'])
def benefit_edit(benefit_id):
    from app.form import CaseBenefitForm
    benefit = CaseBenefit.query.get_or_404(benefit_id)
    form = CaseBenefitForm(obj=benefit)
    
    # Carregar opções de casos
    cases = Case.query.join(Client).order_by(Case.title).all()
    form.case_id.choices = [(0, 'Selecione um caso')] + [(c.id, f"{c.title} - {c.client.name}") for c in cases]
    
    if form.validate_on_submit():
        benefit.case_id = form.case_id.data
        benefit.benefit_number = form.benefit_number.data
        benefit.benefit_type = form.benefit_type.data
        benefit.insured_name = form.insured_name.data
        benefit.insured_nit = form.insured_nit.data
        benefit.accident_date = form.accident_date.data
        benefit.accident_company_name = form.accident_company_name.data
        benefit.error_reason = form.error_reason.data
        benefit.notes = form.notes.data
        benefit.updated_at = datetime.utcnow()
        
        try:
            db.session.commit()
            flash('Benefício atualizado com sucesso!', 'success')
            return redirect(url_for('benefits_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar benefício: {str(e)}', 'danger')
    
    return render_template('benefits/form.html', form=form, title='Editar Benefício', benefit_id=benefit_id)

@app.route('/benefits/<int:benefit_id>/delete', methods=['POST'])
def benefit_delete(benefit_id):
    benefit = CaseBenefit.query.get_or_404(benefit_id)
    
    try:
        db.session.delete(benefit)
        db.session.commit()
        flash('Benefício excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir benefício: {str(e)}', 'danger')
    
    return redirect(url_for('benefits_list'))

