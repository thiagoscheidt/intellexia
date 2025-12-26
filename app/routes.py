from app.agents.file_agent import FileAgent
from app.agents.agent_document_reader import AgentDocumentReader
from main import app
from flask import jsonify, render_template, session, request, redirect, url_for, flash
from app.models import db, Client, Court, Lawyer, Case, CaseLawyer, CaseBenefit, Document, CaseCompetence, Petition, User, LawFirm
import hashlib
import uuid
import re
from datetime import datetime, date
from decimal import Decimal
import os
from werkzeug.utils import secure_filename
from functools import wraps

# Helper function to get current law_firm_id
def get_current_law_firm_id():
    """Retorna o law_firm_id do usuário logado"""
    return session.get('law_firm_id')

# Decorator to ensure law_firm context
def require_law_firm(f):
    """Decorator para garantir que o usuário tem um escritório associado"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            flash('Escritório não encontrado. Faça login novamente.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def check_session():
    # Allow access to authentication routes and static files
    public_endpoints = ['login', 'login_post', 'register', 'register_post', 'forgot_password', 'forgot_password_post', 'static']
    if 'user_id' not in session and request.endpoint not in public_endpoints:
        if request.is_json:
            return jsonify({"error": "Unauthorized"}), 401
        else:
            return redirect(url_for('login'))
    
    # Se está autenticado, atualizar última atividade
    if 'user_id' in session and request.endpoint not in public_endpoints:
        user = User.query.get(session['user_id'])
        if user:
            user.last_activity = datetime.utcnow()
            db.session.commit()

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
    remember = request.form.get('remember')
    
    # Validação básica
    if not email or not password:
        return jsonify({"success": False, "message": "Email e senha são obrigatórios"})
    
    # Buscar usuário no banco de dados
    user = User.query.filter_by(email=email).first()
    
    if not user:
        return jsonify({"success": False, "message": "Email ou senha incorretos"})
    
    # Verificar se o usuário está ativo
    if not user.is_active:
        return jsonify({"success": False, "message": "Sua conta está inativa. Entre em contato com o suporte."})
    
    # Verificar se o escritório está ativo
    if not user.law_firm.is_active:
        return jsonify({"success": False, "message": "O escritório está inativo. Entre em contato com o suporte."})
    
    # Verificar senha
    if not user.check_password(password):
        return jsonify({"success": False, "message": "Email ou senha incorretos"})
    
    # Atualizar último login
    user.last_login = datetime.utcnow()
    user.last_activity = datetime.utcnow()
    db.session.commit()
    
    # Criar sessão
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
        "redirect": url_for('index'),
        "user": user.to_dict()
    })

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
    law_firm_name = request.form.get('law_firm_name')
    law_firm_cnpj = request.form.get('law_firm_cnpj')
    oab_number = request.form.get('oab_number')
    
    # Validação
    if not all([full_name, email, password, password_confirm, law_firm_name, law_firm_cnpj]):
        return jsonify({"success": False, "message": "Todos os campos obrigatórios devem ser preenchidos"})
    
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
    
    # Verificar se email já existe
    if User.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "Este email já está cadastrado"})
    
    # Verificar se CNPJ já existe
    if LawFirm.query.filter_by(cnpj=law_firm_cnpj).first():
        return jsonify({"success": False, "message": "Este CNPJ já está cadastrado"})
    
    try:
        # Criar escritório
        law_firm = LawFirm(
            name=law_firm_name,
            cnpj=law_firm_cnpj,
            is_active=True,
            subscription_plan='trial'
        )
        db.session.add(law_firm)
        db.session.flush()  # Para obter o ID
        
        # Criar usuário
        user = User(
            law_firm_id=law_firm.id,
            name=full_name,
            email=email,
            role='admin',  # Primeiro usuário é admin
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
    flash('Você saiu do sistema com sucesso.', 'info')
    return redirect(url_for('login'))

# Law Firm Settings (Admin only)
@app.route('/settings/law-firm', methods=['GET'])
def law_firm_settings():
    """Página de configurações do escritório (apenas admin)"""
    if session.get('user_role') != 'admin':
        flash('Acesso negado. Apenas administradores podem acessar esta página.', 'danger')
        return redirect(url_for('dashboard'))
    
    law_firm_id = session.get('law_firm_id')
    if not law_firm_id:
        flash('Escritório não encontrado.', 'danger')
        return redirect(url_for('dashboard'))
    
    law_firm = LawFirm.query.get(law_firm_id)
    if not law_firm:
        flash('Escritório não encontrado.', 'danger')
        return redirect(url_for('dashboard'))
    
    return render_template('settings/law_firm.html', law_firm=law_firm)

@app.route('/settings/law-firm', methods=['POST'])
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
        # Dados básicos
        law_firm.name = request.form.get('name', law_firm.name)
        law_firm.trade_name = request.form.get('trade_name', law_firm.trade_name)
        law_firm.cnpj = request.form.get('cnpj', law_firm.cnpj)
        
        # Endereço
        law_firm.street = request.form.get('street', law_firm.street)
        law_firm.number = request.form.get('number', law_firm.number)
        law_firm.complement = request.form.get('complement', law_firm.complement)
        law_firm.district = request.form.get('district', law_firm.district)
        law_firm.city = request.form.get('city', law_firm.city)
        law_firm.state = request.form.get('state', law_firm.state)
        law_firm.zip_code = request.form.get('zip_code', law_firm.zip_code)
        
        # Contato
        law_firm.phone = request.form.get('phone', law_firm.phone)
        law_firm.email = request.form.get('email', law_firm.email)
        law_firm.website = request.form.get('website', law_firm.website)
        
        law_firm.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        # Atualizar nome do escritório na sessão
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

# Dashboard routes
@app.route('/')
def index():
    """Redireciona para o dashboard principal"""
    # Buscar dados do usuário e escritório
    user = User.query.get(session.get('user_id'))
    law_firm = user.law_firm if user else None
    
    # Estatísticas do escritório
    stats = {
        'total_cases': Case.query.count(),
        'total_clients': Client.query.count(),
        'total_users': User.query.filter_by(law_firm_id=session.get('law_firm_id')).count() if session.get('law_firm_id') else 0,
        'active_cases': Case.query.filter_by(status='active').count()
    }
    
    message = request.args.get('message')
    if message:
        flash(message) 
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
@require_law_firm
def dashboard():
    """Dashboard principal com estatísticas do sistema"""
    try:
        # Buscar dados do usuário e escritório
        user = User.query.get(session.get('user_id'))
        law_firm = user.law_firm if user else None
        law_firm_id = get_current_law_firm_id()
        
        # Estatísticas de Casos (filtradas por escritório)
        total_cases = Case.query.filter_by(law_firm_id=law_firm_id).count()
        active_cases = Case.query.filter_by(law_firm_id=law_firm_id, status='active').count()
        draft_cases = Case.query.filter_by(law_firm_id=law_firm_id, status='draft').count()
        filed_cases = Case.query.filter_by(law_firm_id=law_firm_id).filter(Case.filing_date.isnot(None)).count()
        
        # Estatísticas de Clientes (filtradas por escritório)
        total_clients = Client.query.filter_by(law_firm_id=law_firm_id).count()
        clients_with_branches = Client.query.filter_by(law_firm_id=law_firm_id, has_branches=True).count()
        
        # Estatísticas de Benefícios (filtradas por escritório através dos casos)
        total_benefits = CaseBenefit.query.join(Case).filter(Case.law_firm_id == law_firm_id).count()
        benefits_b91 = CaseBenefit.query.join(Case).filter(Case.law_firm_id == law_firm_id, CaseBenefit.benefit_type == 'B91').count()
        benefits_b94 = CaseBenefit.query.join(Case).filter(Case.law_firm_id == law_firm_id, CaseBenefit.benefit_type == 'B94').count()
        
        # Estatísticas de Advogados (filtradas por escritório)
        total_lawyers = Lawyer.query.filter_by(law_firm_id=law_firm_id).count()
        
        # Estatísticas de Documentos (filtradas por escritório através dos casos)
        total_documents = Document.query.join(Case).filter(Case.law_firm_id == law_firm_id).count()
        documents_for_ai = Document.query.join(Case).filter(Case.law_firm_id == law_firm_id, Document.use_in_ai == True).count()
        
        # Casos recentes (últimos 5, filtrados por escritório)
        recent_cases = Case.query.filter_by(law_firm_id=law_firm_id).order_by(Case.created_at.desc()).limit(5).all()
        
        # Valor total das causas (filtrado por escritório)
        total_cause_value = db.session.query(db.func.sum(Case.value_cause)).filter(Case.law_firm_id == law_firm_id).scalar() or Decimal('0')
        
        # Casos por tipo (filtrados por escritório)
        cases_by_type_result = db.session.query(
            Case.case_type, 
            db.func.count(Case.id).label('count')
        ).filter(Case.law_firm_id == law_firm_id).group_by(Case.case_type).all()
        cases_by_type = {case_type: count for case_type, count in cases_by_type_result}
        
        # Distribuição por status (filtrados por escritório)
        cases_by_status_result = db.session.query(
            Case.status,
            db.func.count(Case.id).label('count')
        ).filter(Case.law_firm_id == law_firm_id).group_by(Case.status).all()
        cases_by_status = {status: count for status, count in cases_by_status_result}
        
        # Estatísticas de usuários do escritório
        total_users = User.query.filter_by(law_firm_id=law_firm_id).count()
        total_courts = Court.query.filter_by(law_firm_id=law_firm_id).count()
        
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
            cases_by_type=cases_by_type,
            cases_by_status=cases_by_status,
            total_users=total_users,
            total_courts=total_courts,
            user=user,
            law_firm=law_firm
        )
    except Exception as e:
        print(f"Erro no dashboard: {str(e)}")
        flash(f'Erro ao carregar dashboard: {str(e)}', 'danger')
        return render_template('dashboard.html',
            total_cases=0,
            active_cases=0,
            draft_cases=0,
            filed_cases=0,
            total_clients=0,
            total_benefits=0,
            total_lawyers=0,
            total_documents=0,
            recent_cases=[],
            total_cause_value=0,
            cases_by_type={},
            cases_by_status={},
            user=user if 'user' in locals() else None,
            law_firm=law_firm if 'law_firm' in locals() else None
        )

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
@require_law_firm
def clients_list():
    law_firm_id = get_current_law_firm_id()
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.created_at.desc()).all()
    return render_template('clients/list.html', clients=clients)

@app.route('/clients/new', methods=['GET', 'POST'])
@require_law_firm
def client_new():
    from app.form import ClientForm
    form = ClientForm()
    
    if form.validate_on_submit():
        client = Client(
            law_firm_id=get_current_law_firm_id(),
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
@require_law_firm
def client_edit(client_id):
    from app.form import ClientForm
    law_firm_id = get_current_law_firm_id()
    client = Client.query.filter_by(id=client_id, law_firm_id=law_firm_id).first_or_404()
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
@require_law_firm
def client_delete(client_id):
    law_firm_id = get_current_law_firm_id()
    client = Client.query.filter_by(id=client_id, law_firm_id=law_firm_id).first_or_404()
    
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
@require_law_firm
def cases_list():
    law_firm_id = get_current_law_firm_id()
    cases = Case.query.filter_by(law_firm_id=law_firm_id).join(Client).order_by(Case.created_at.desc()).all()
    return render_template('cases/list.html', cases=cases)

@app.route('/cases/new', methods=['GET', 'POST'])
@require_law_firm
def case_new():
    from app.form import CaseForm
    form = CaseForm()
    
    law_firm_id = get_current_law_firm_id()
    
    # Carregar opções de clientes e varas do escritório
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.name).all()
    courts = Court.query.filter_by(law_firm_id=law_firm_id).order_by(Court.vara_name).all()
    
    form.client_id.choices = [(0, 'Selecione um cliente')] + [(c.id, c.name) for c in clients]
    form.court_id.choices = [(0, 'Selecione uma vara')] + [(c.id, f"{c.vara_name} - {c.city}/{c.state}") for c in courts]
    
    if form.validate_on_submit():
        case = Case(
            law_firm_id=get_current_law_firm_id(),
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
@require_law_firm
def case_edit(case_id):
    from app.form import CaseForm
    law_firm_id = get_current_law_firm_id()
    case = Case.query.filter_by(id=case_id, law_firm_id=law_firm_id).first_or_404()
    form = CaseForm(obj=case)
    
    # Carregar opções de clientes e varas do escritório
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.name).all()
    courts = Court.query.filter_by(law_firm_id=law_firm_id).order_by(Court.vara_name).all()
    
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

@app.route('/cases/<int:case_id>/lawyers/add', methods=['POST'])
def case_lawyer_add(case_id):
    """Adiciona um advogado ao caso"""
    case = Case.query.get_or_404(case_id)
    
    lawyer_id = request.form.get('lawyer_id')
    role = request.form.get('role', '')
    
    if not lawyer_id:
        flash('Selecione um advogado.', 'warning')
        return redirect(url_for('case_detail', case_id=case_id))
    
    # Verificar se advogado existe
    lawyer = Lawyer.query.get_or_404(int(lawyer_id))
    
    # Verificar se já está vinculado
    existing = CaseLawyer.query.filter_by(case_id=case_id, lawyer_id=lawyer_id).first()
    if existing:
        flash('Este advogado já está vinculado ao caso.', 'warning')
        return redirect(url_for('case_detail', case_id=case_id))
    
    # Adicionar vínculo
    case_lawyer = CaseLawyer(
        case_id=case_id,
        lawyer_id=lawyer_id,
        role=role
    )
    
    db.session.add(case_lawyer)
    try:
        db.session.commit()
        flash(f'Advogado {lawyer.name} vinculado ao caso com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao vincular advogado: {str(e)}', 'danger')
    
    return redirect(url_for('case_detail', case_id=case_id))

@app.route('/cases/<int:case_id>/lawyers/<int:case_lawyer_id>/remove', methods=['POST'])
def case_lawyer_remove(case_id, case_lawyer_id):
    """Remove um advogado do caso"""
    case_lawyer = CaseLawyer.query.get_or_404(case_lawyer_id)
    
    if case_lawyer.case_id != case_id:
        flash('Vínculo não pertence a este caso.', 'danger')
        return redirect(url_for('case_detail', case_id=case_id))
    
    lawyer_name = case_lawyer.lawyer.name
    
    try:
        db.session.delete(case_lawyer)
        db.session.commit()
        flash(f'Advogado {lawyer_name} removido do caso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao remover advogado: {str(e)}', 'danger')
    
    return redirect(url_for('case_detail', case_id=case_id))

@app.route('/cases/<int:case_id>')
def case_detail(case_id):
    case = Case.query.get_or_404(case_id)
    benefits = CaseBenefit.query.filter_by(case_id=case_id).order_by(CaseBenefit.created_at.desc()).all()
    documents = Document.query.filter_by(case_id=case_id).order_by(Document.uploaded_at.desc()).all()
    competences = CaseCompetence.query.filter_by(case_id=case_id).all()
    petitions = Petition.query.filter_by(case_id=case_id).order_by(Petition.version.desc()).all()
    case_lawyers = CaseLawyer.query.filter_by(case_id=case_id).all()
    all_lawyers = Lawyer.query.order_by(Lawyer.name).all()
    return render_template('cases/detail.html', case=case, case_id=case_id, benefits=benefits, documents=documents, competences=competences, petitions=petitions, case_lawyers=case_lawyers, all_lawyers=all_lawyers)

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
@require_law_firm
def lawyers_list():
    law_firm_id = get_current_law_firm_id()
    lawyers = Lawyer.query.filter_by(law_firm_id=law_firm_id).order_by(Lawyer.name).all()
    return render_template('lawyers/list.html', lawyers=lawyers)

@app.route('/lawyers/new', methods=['GET', 'POST'])
@require_law_firm
def lawyer_new():
    from app.form import LawyerForm
    form = LawyerForm()
    
    if form.validate_on_submit():
        lawyer = Lawyer(
            law_firm_id=get_current_law_firm_id(),
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
@require_law_firm
def lawyer_edit(lawyer_id):
    from app.form import LawyerForm
    law_firm_id = get_current_law_firm_id()
    lawyer = Lawyer.query.filter_by(id=lawyer_id, law_firm_id=law_firm_id).first_or_404()
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
@require_law_firm
def courts_list():
    law_firm_id = get_current_law_firm_id()
    courts = Court.query.filter_by(law_firm_id=law_firm_id).order_by(Court.vara_name).all()
    return render_template('courts/list.html', courts=courts)

@app.route('/courts/new', methods=['GET', 'POST'])
@require_law_firm
def court_new():
    from app.form import CourtForm
    form = CourtForm()
    
    if form.validate_on_submit():
        court = Court(
            law_firm_id=get_current_law_firm_id(),
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
@require_law_firm
def court_edit(court_id):
    from app.form import CourtForm
    law_firm_id = get_current_law_firm_id()
    court = Court.query.filter_by(id=court_id, law_firm_id=law_firm_id).first_or_404()
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
@require_law_firm
def court_delete(court_id):
    law_firm_id = get_current_law_firm_id()
    court = Court.query.filter_by(id=court_id, law_firm_id=law_firm_id).first_or_404()
    
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

# ========================
# Rotas de Petições (IA)
# ========================
@app.route('/cases/<int:case_id>/petitions')
def case_petitions_list(case_id):
    """Lista todas as petições geradas para um caso"""
    case = Case.query.get_or_404(case_id)
    petitions = Petition.query.filter_by(case_id=case_id).order_by(Petition.version.desc()).all()
    return render_template('cases/petitions_list.html', case=case, petitions=petitions, case_id=case_id)

@app.route('/cases/<int:case_id>/petitions/generate', methods=['GET', 'POST'])
def case_petition_generate(case_id):
    """Gera uma nova petição com IA"""
    case = Case.query.get_or_404(case_id)
    
    if request.method == 'POST':
        try:
            # Determinar próxima versão
            last_petition = Petition.query.filter_by(case_id=case_id).order_by(Petition.version.desc()).first()
            next_version = (last_petition.version + 1) if last_petition else 1
            
            # Coletar contexto do caso
            benefits = CaseBenefit.query.filter_by(case_id=case_id).all()
            documents = Document.query.filter_by(case_id=case_id, use_in_ai=True, ai_status='completed').all()
            
            # Preparar contexto para a IA
            context_summary = f"""
Contexto da Petição - Versão {next_version}:
- Cliente: {case.client.name if case.client else 'Não informado'}
- Tipo de Caso: {case.case_type}
- Total de Benefícios: {len(benefits)}
- Total de Documentos Analisados: {len(documents)}
- Valor da Causa: R$ {case.value_cause if case.value_cause else 'Não informado'}
"""
            
            # Criar petição pendente
            petition = Petition(
                case_id=case_id,
                version=next_version,
                title=f"Petição Inicial - {case.title}",
                content="Gerando conteúdo com IA...",
                status='processing',
                context_summary=context_summary
            )
            
            db.session.add(petition)
            db.session.commit()
            
            # Gerar conteúdo com IA (simulado por enquanto)
            try:
                # TODO: Integrar com a IA real
                petition_content = generate_petition_with_ai(case, benefits, documents)
                
                # Atualizar petição com conteúdo gerado
                petition.content = petition_content
                petition.status = 'completed'
                petition.generated_at = datetime.utcnow()
                db.session.commit()
                
                flash('Petição gerada com sucesso pela IA!', 'success')
                return redirect(url_for('case_petition_view', case_id=case_id, petition_id=petition.id))
                
            except Exception as e:
                petition.status = 'error'
                petition.error_message = str(e)
                db.session.commit()
                flash(f'Erro ao gerar petição: {str(e)}', 'danger')
                
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar petição: {str(e)}', 'danger')
    
    # GET - Mostrar formulário de confirmação
    benefits_count = CaseBenefit.query.filter_by(case_id=case_id).count()
    documents_count = Document.query.filter_by(case_id=case_id, use_in_ai=True).count()
    last_petition = Petition.query.filter_by(case_id=case_id).order_by(Petition.version.desc()).first()
    next_version = (last_petition.version + 1) if last_petition else 1
    
    return render_template(
        'cases/petition_generate.html',
        case=case,
        case_id=case_id,
        next_version=next_version,
        benefits_count=benefits_count,
        documents_count=documents_count
    )

@app.route('/cases/<int:case_id>/petitions/<int:petition_id>')
def case_petition_view(case_id, petition_id):
    """Visualiza uma petição específica"""
    case = Case.query.get_or_404(case_id)
    petition = Petition.query.get_or_404(petition_id)
    
    if petition.case_id != case_id:
        flash('Petição não pertence a este caso.', 'danger')
        return redirect(url_for('case_petitions_list', case_id=case_id))
    
    return render_template(
        'cases/petition_view.html',
        case=case,
        petition=petition,
        case_id=case_id
    )

@app.route('/cases/<int:case_id>/petitions/<int:petition_id>/delete', methods=['POST'])
def case_petition_delete(case_id, petition_id):
    """Exclui uma petição"""
    petition = Petition.query.get_or_404(petition_id)
    
    if petition.case_id != case_id:
        flash('Petição não pertence a este caso.', 'danger')
        return redirect(url_for('case_petitions_list', case_id=case_id))
    
    try:
        db.session.delete(petition)
        db.session.commit()
        flash('Petição excluída com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir petição: {str(e)}', 'danger')
    
    return redirect(url_for('case_petitions_list', case_id=case_id))

def generate_petition_with_ai(case, benefits, documents):
    """
    Gera o conteúdo da petição usando IA
    TODO: Integrar com modelo de IA real
    """
    # Simulação por enquanto
    petition_content = f"""EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) DE DIREITO DA {case.court.vara_name if case.court else 'VARA COMPETENTE'}

{case.client.name if case.client else 'EMPRESA AUTORA'}, pessoa jurídica de direito privado, inscrita no CNPJ sob nº {case.client.cnpj if case.client else 'XX.XXX.XXX/XXXX-XX'}, com sede em {case.client.city if case.client else 'CIDADE'}/{case.client.state if case.client else 'UF'}, vem, por meio de seu advogado signatário, com fundamento nos artigos da Lei nº 8.213/91 e demais legislações pertinentes, propor a presente

AÇÃO DECLARATÓRIA DE INEXISTÊNCIA DE NEXO CAUSAL

em face do INSTITUTO NACIONAL DO SEGURO SOCIAL – INSS, autarquia federal, pelos motivos de fato e de direito a seguir expostos:

I – DOS FATOS

{case.facts_summary if case.facts_summary else 'A empresa autora foi surpreendida com a vinculação indevida de benefícios acidentários que não guardam relação com suas atividades laborais.'}

"""

    # Adicionar informações sobre benefícios
    if benefits:
        petition_content += f"\n\nII – DOS BENEFÍCIOS CONTESTADOS\n\n"
        petition_content += f"Foram vinculados à empresa os seguintes benefícios:\n\n"
        
        for i, benefit in enumerate(benefits, 1):
            petition_content += f"{i}. Benefício nº {benefit.benefit_number} - {benefit.benefit_type}\n"
            petition_content += f"   Segurado: {benefit.insured_name}\n"
            if benefit.accident_date:
                petition_content += f"   Data do Acidente: {benefit.accident_date.strftime('%d/%m/%Y')}\n"
            if benefit.error_reason:
                petition_content += f"   Motivo da Contestação: {benefit.error_reason}\n"
            petition_content += "\n"
    
    petition_content += f"""
III – DO DIREITO

{case.thesis_summary if case.thesis_summary else 'A vinculação indevida de benefícios acidentários impacta diretamente no FAP (Fator Acidentário de Prevenção) da empresa, majorando indevidamente suas contribuições previdenciárias.'}

IV – DOS PEDIDOS

Diante do exposto, requer-se a Vossa Excelência:

a) A procedência do pedido para declarar a inexistência de nexo causal entre os benefícios relacionados e as atividades da empresa autora;

b) A determinação ao INSS para exclusão dos benefícios do cálculo do FAP da empresa;

c) A condenação do INSS ao pagamento das custas processuais e honorários advocatícios.

Termos em que,
Pede deferimento.

{case.client.city if case.client else 'Cidade'}/{case.client.state if case.client else 'UF'}, {datetime.now().strftime('%d de %B de %Y')}.

___________________________________
Advogado(a) OAB/XX XXXXX
"""
    
    return petition_content


