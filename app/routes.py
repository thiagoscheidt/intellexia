from app.agents.file_agent import FileAgent
from app.agents.agent_document_reader import AgentDocumentReader
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
    """Redireciona para o dashboard principal"""
    message = request.args.get('message')
    if message:
        flash(message) 
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    """Dashboard principal com estatísticas do sistema"""
    try:
        # Estatísticas de Casos
        total_cases = Case.query.count()
        active_cases = Case.query.filter_by(status='active').count()
        draft_cases = Case.query.filter_by(status='draft').count()
        filed_cases = Case.query.filter(Case.filing_date.isnot(None)).count()
        
        # Estatísticas de Clientes
        total_clients = Client.query.count()
        clients_with_branches = Client.query.filter_by(has_branches=True).count()
        
        # Estatísticas de Benefícios
        total_benefits = CaseBenefit.query.count()
        benefits_b91 = CaseBenefit.query.filter_by(benefit_type='B91').count()
        benefits_b94 = CaseBenefit.query.filter_by(benefit_type='B94').count()
        
        # Estatísticas de Advogados
        total_lawyers = Lawyer.query.count()
        
        # Estatísticas de Documentos
        total_documents = Document.query.count()
        documents_for_ai = Document.query.filter_by(use_in_ai=True).count()
        
        # Casos recentes (últimos 5)
        recent_cases = Case.query.order_by(Case.created_at.desc()).limit(5).all()
        
        # Valor total das causas
        total_cause_value = db.session.query(db.func.sum(Case.value_cause)).scalar() or Decimal('0')
        
        # Casos por tipo
        cases_by_type = db.session.query(
            Case.case_type, 
            db.func.count(Case.id).label('count')
        ).group_by(Case.case_type).all()
        
        # Distribuição por status
        cases_by_status = db.session.query(
            Case.status,
            db.func.count(Case.id).label('count')
        ).group_by(Case.status).all()
        
        return render_template('dashboard.html',
            total_cases=total_cases,
            active_cases=active_cases,
            draft_cases=draft_cases,
            filed_cases=filed_cases,
            total_clients=total_clients,
            clients_with_branches=clients_with_branches,
            total_benefits=total_benefits,
            benefits_b91=benefits_b91,
            benefits_b94=benefits_b94,
            total_lawyers=total_lawyers,
            total_documents=total_documents,
            documents_for_ai=documents_for_ai,
            recent_cases=recent_cases,
            total_cause_value=total_cause_value,
            cases_by_type=dict(cases_by_type),
            cases_by_status=dict(cases_by_status)
        )
    except Exception as e:
        flash(f'Erro ao carregar dashboard: {str(e)}', 'error')
        return render_template('dashboard.html')

# ========================
# Assistente Jurídico (IA Chat)
# ========================
@app.route('/assistente-juridico')
def legal_assistant():
    """Interface do Assistente Jurídico - Chat com IA"""
    return render_template('assistant/chat.html')

@app.route('/api/assistente-juridico', methods=['POST'])
def legal_assistant_api():
    """API para processar mensagens do Assistente Jurídico"""
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        
        if not user_message:
            return jsonify({'error': 'Mensagem é obrigatória'}), 400
        
        # Obter contexto dos dados do sistema
        context = get_system_context()
        
        # Processar mensagem com IA (simulação por enquanto)
        ai_response = process_legal_assistant_message(user_message, context)
        
        return jsonify({
            'response': ai_response,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': f'Erro interno: {str(e)}'}), 500

def get_system_context():
    """Obtém contexto atual do sistema para a IA"""
    try:
        context = {
            'total_cases': Case.query.count(),
            'active_cases': Case.query.filter_by(status='active').count(),
            'total_clients': Client.query.count(),
            'total_benefits': CaseBenefit.query.count(),
            'recent_cases': Case.query.order_by(Case.created_at.desc()).limit(3).all(),
            'case_types': db.session.query(Case.case_type, db.func.count(Case.id)).group_by(Case.case_type).all(),
            'clients_list': Client.query.all(),
            'lawyers_list': Lawyer.query.all()
        }
        return context
    except Exception as e:
        return {'error': str(e)}

def process_legal_assistant_message(message, context):
    """Processa mensagem do usuário e gera resposta da IA"""
    message_lower = message.lower()
    
    # Respostas baseadas em contexto do sistema
    if 'quantos casos' in message_lower or 'total de casos' in message_lower:
        total = context.get('total_cases', 0)
        active = context.get('active_cases', 0)
        return f"📊 **Estatísticas de Casos:**\n\n• **Total de casos:** {total}\n• **Casos ativos:** {active}\n• **Casos inativos:** {total - active}\n\nPosso ajudar com mais informações sobre algum caso específico?"
    
    elif 'clientes' in message_lower and ('quantos' in message_lower or 'total' in message_lower):
        total = context.get('total_clients', 0)
        return f"👥 **Clientes cadastrados:** {total} empresas\n\nGostaria de saber mais detalhes sobre algum cliente específico?"
    
    elif 'benefícios' in message_lower or 'beneficios' in message_lower:
        total = context.get('total_benefits', 0)
        return f"💰 **Benefícios previdenciários:** {total} cadastrados\n\nPosso ajudar a analisar benefícios por tipo (B91, B94) ou buscar informações específicas."
    
    elif 'fap' in message_lower:
        fap_cases = [case for case in context.get('recent_cases', []) if case.case_type and 'fap' in case.case_type]
        count = len(fap_cases)
        return f"⚖️ **Casos FAP:** Encontrei {count} casos relacionados ao FAP\n\n**Tipos de FAP mais comuns:**\n• FAP Trajeto\n• FAP Nexo Causal\n• FAP Múltiplos Benefícios\n\nQuer detalhes sobre algum tipo específico?"
    
    elif 'casos recentes' in message_lower or 'últimos casos' in message_lower:
        recent = context.get('recent_cases', [])
        if recent:
            response = "📋 **Casos mais recentes:**\n\n"
            for case in recent[:3]:
                status_emoji = "🟢" if case.status == 'active' else "🟡" if case.status == 'draft' else "⚪"
                response += f"• {status_emoji} **{case.title}**\n  Cliente: {case.client.name if case.client else 'N/A'}\n  Status: {case.status}\n\n"
            return response + "Precisa de mais detalhes sobre algum destes casos?"
        else:
            return "📋 Nenhum caso encontrado no sistema. Que tal criar o primeiro caso?"
    
    elif 'tipos de caso' in message_lower or 'case_type' in message_lower:
        types = context.get('case_types', [])
        if types:
            response = "📂 **Tipos de casos no sistema:**\n\n"
            for case_type, count in types:
                type_name = {
                    'fap_trajeto': 'FAP - Acidente de Trajeto',
                    'fap_nexo': 'FAP - Nexo Causal',
                    'fap_multiplos': 'FAP - Múltiplos Benefícios',
                    'auto_infracao': 'Auto de Infração'
                }.get(case_type, case_type.title())
                response += f"• **{type_name}:** {count} casos\n"
            return response + "\nQual tipo você gostaria de analisar em detalhes?"
        else:
            return "📂 Nenhum tipo de caso encontrado no sistema."
    
    elif 'ajuda' in message_lower or 'help' in message_lower:
        return "🤖 **Como posso ajudar?**\n\n**Perguntas que posso responder:**\n\n📊 • Quantos casos temos?\n👥 • Informações sobre clientes\n💰 • Estatísticas de benefícios\n⚖️ • Casos FAP\n📋 • Casos recentes\n📂 • Tipos de casos\n\n**Exemplos de perguntas:**\n• \"Quantos casos ativos temos?\"\n• \"Quais são os casos recentes?\"\n• \"Informações sobre FAP\"\n• \"Tipos de casos no sistema\""
    
    elif 'oi' in message_lower or 'olá' in message_lower or 'hello' in message_lower:
        return "👋 **Olá! Sou o Assistente Jurídico do IntellexIA**\n\nSou especializado em casos trabalhistas e posso ajudar você com:\n\n• 📊 Estatísticas e relatórios\n• ⚖️ Informações sobre casos FAP\n• 👥 Dados de clientes\n• 💰 Análise de benefícios\n• 📋 Consultas sobre processos\n\nO que gostaria de saber?"
    
    else:
        # Resposta genérica inteligente
        return f"🤔 Entendi sua pergunta: \"{message}\"\n\n💡 **Sugestões do que posso ajudar:**\n\n• Digite \"ajuda\" para ver todas as funcionalidades\n• Pergunte sobre \"casos\", \"clientes\" ou \"benefícios\"\n• Peça \"estatísticas\" para um resumo geral\n• Mencione \"FAP\" para casos específicos\n\nEstou aqui para ajudar com informações jurídicas do sistema! 💼⚖️"

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
        
    return render_template('cases/form.html', form=form, title='Editar Caso', case_id=case_id)

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
    benefits = CaseBenefit.query.filter_by(case_id=case_id).order_by(CaseBenefit.created_at.desc()).all()
    documents = Document.query.filter_by(case_id=case_id).order_by(Document.uploaded_at.desc()).all()
    competences = CaseCompetence.query.filter_by(case_id=case_id).all()
    return render_template('cases/detail.html', case=case, case_id=case_id, benefits=benefits, documents=documents, competences=competences)

# ========================
# Rotas de Documentos do Caso
# ========================
@app.route('/cases/<int:case_id>/documents')
def case_documents_list(case_id):
    case = Case.query.get_or_404(case_id)
    documents = Document.query.filter_by(case_id=case_id).order_by(Document.uploaded_at.desc()).all()
    return render_template('cases/documents_list.html', case=case, case_id=case_id, documents=documents)

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
                use_in_ai=form.use_in_ai.data,
                ai_status='pending'  # Inicializa como pendente
            )
            
            db.session.add(document)
            try:
                db.session.commit()
                
                # Processar com IA se marcado para uso
                if form.use_in_ai.data:
                    try:
                        # Atualiza status para processing
                        document.ai_status = 'processing'
                        db.session.commit()
                        
                        # Inicializa agentes
                        file_agent = FileAgent()
                        doc_reader = AgentDocumentReader()
                        
                        # Faz upload do arquivo para a OpenAI (usando caminho absoluto)
                        file_id = file_agent.upload_file(os.path.abspath(file_path))
                        
                        # Analisa o documento
                        ai_summary = doc_reader.analyze_document(file_id)
                        
                        # Salva o resumo e atualiza status
                        document.ai_summary = ai_summary
                        document.ai_processed_at = datetime.utcnow()
                        document.ai_status = 'completed'
                        db.session.commit()
                        
                        flash('Documento enviado e analisado com sucesso pela IA!', 'success')
                    except Exception as e:
                        # Em caso de erro na IA, registra mas não impede o upload
                        document.ai_status = 'error'
                        document.ai_error_message = str(e)
                        db.session.commit()
                        flash(f'Documento enviado, mas houve erro na análise de IA: {str(e)}', 'warning')
                else:
                    flash('Documento enviado com sucesso!', 'success')
                
                return redirect(url_for('case_documents_list', case_id=case_id))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao salvar documento: {str(e)}', 'danger')
        else:
            flash('Nenhum arquivo foi selecionado.', 'warning')
    
    return render_template('cases/document_form.html', form=form, case=case, case_id=case_id, title='Upload Documento')

@app.route('/cases/<int:case_id>/documents/<int:document_id>/view', methods=['GET'])
def case_document_view(case_id, document_id):
    """Visualiza documento e informações extraídas pela IA"""
    case = Case.query.get_or_404(case_id)
    document = Document.query.get_or_404(document_id)
    
    # Verificar se o documento pertence ao caso
    if document.case_id != case_id:
        flash('Documento não pertence a este caso.', 'danger')
        return redirect(url_for('case_documents_list', case_id=case_id))
    
    # Buscar benefício relacionado se existir
    related_benefit = None
    if document.related_benefit_id:
        related_benefit = CaseBenefit.query.get(document.related_benefit_id)
    
    return render_template(
        'cases/document_view.html',
        case=case,
        document=document,
        related_benefit=related_benefit,
        case_id=case_id,
        title=f'Visualizar Documento - {document.original_filename}'
    )

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
# Rotas de Benefícios do Caso
# ========================
@app.route('/cases/<int:case_id>/benefits')
def case_benefits_list(case_id):
    case = Case.query.get_or_404(case_id)
    benefits = CaseBenefit.query.filter_by(case_id=case_id).order_by(CaseBenefit.created_at.desc()).all()
    return render_template('cases/benefits_list.html', case=case, benefits=benefits)

@app.route('/cases/<int:case_id>/benefits/new', methods=['GET', 'POST'])
def case_benefit_new(case_id):
    from app.form import CaseBenefitContextForm
    case = Case.query.get_or_404(case_id)
    form = CaseBenefitContextForm()
    
    if form.validate_on_submit():
        benefit = CaseBenefit(
            case_id=case_id,  # Usar o case_id da URL
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
            return redirect(url_for('case_benefits_list', case_id=case_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar benefício: {str(e)}', 'danger')
    
    return render_template('cases/benefit_form.html', form=form, case=case, title='Novo Benefício')

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

@app.route('/cases/<int:case_id>/benefits/<int:benefit_id>/edit', methods=['GET', 'POST'])
def case_benefit_edit(case_id, benefit_id):
    from app.form import CaseBenefitContextForm
    case = Case.query.get_or_404(case_id)
    benefit = CaseBenefit.query.get_or_404(benefit_id)
    
    # Verificar se o benefício pertence ao caso
    if benefit.case_id != case_id:
        flash('Benefício não encontrado neste caso.', 'error')
        return redirect(url_for('case_benefits_list', case_id=case_id))
    
    form = CaseBenefitContextForm(obj=benefit)
    
    if form.validate_on_submit():
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
            return redirect(url_for('case_benefits_list', case_id=case_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar benefício: {str(e)}', 'danger')
    
    return render_template('cases/benefit_form.html', form=form, case=case, title='Editar Benefício', benefit_id=benefit_id)

@app.route('/cases/<int:case_id>/benefits/<int:benefit_id>/delete', methods=['POST'])
def case_benefit_delete(case_id, benefit_id):
    case = Case.query.get_or_404(case_id)
    benefit = CaseBenefit.query.get_or_404(benefit_id)
    
    # Verificar se o benefício pertence ao caso
    if benefit.case_id != case_id:
        flash('Benefício não encontrado neste caso.', 'error')
        return redirect(url_for('case_benefits_list', case_id=case_id))
    
    try:
        db.session.delete(benefit)
        db.session.commit()
        flash('Benefício excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir benefício: {str(e)}', 'danger')
    
    return redirect(url_for('case_benefits_list', case_id=case_id))

@app.route('/ia/test')
def ia_test():
    """Rota de teste para funcionalidades de IA"""
    file_agent = FileAgent()
    file_id = file_agent.upload_file(
        "https://emsportal.com.br/controle/includes/anexoProtocoloDownload.php?id=372094&anexo=2025-11/1c0a60f97ee2ab4a81ff18916d451091.pdf"
    )

    agent = AgentDocumentReader()
    result = agent.analyze_document(file_id)
    print(result)
    return jsonify(result)

# ========================
# Rota global de benefícios (apenas visualização)
# ========================
@app.route('/benefits')
def benefits_list():
    """Lista todos os benefícios do sistema para visualização geral"""
    benefits = CaseBenefit.query.join(Case).join(Client).order_by(CaseBenefit.created_at.desc()).all()
    return render_template('benefits/list.html', benefits=benefits)

