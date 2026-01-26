from flask import Blueprint, render_template, request, session, jsonify, redirect, url_for, flash, send_file
from app.models import db, Case, Client, CaseBenefit, Document, Petition, CaseLawyer, Lawyer, CaseCompetence, CasesKnowledgeBase, CaseTemplate
from app.agents.case_knowledge_ingestor import CaseKnowledgeIngestor
from datetime import datetime
from decimal import Decimal
from functools import wraps
from werkzeug.utils import secure_filename
from pathlib import Path
import os

cases_bp = Blueprint('cases', __name__, url_prefix='/cases')

# Mapeamento de categorias (slug -> nome amigável)
CATEGORIES_MAP = {
    'jurisprudencia': 'Jurisprudência',
    'legislacao': 'Legislação',
    'modelos-peticoes': 'Modelos de Petições',
    'exemplos-peticoes': 'Exemplos de Petições',
    'templates': 'Templates',
    'doutrinas': 'Doutrinas',
    'pareceres-tecnicos': 'Pareceres Técnicos',
    'sumulas': 'Súmulas',
    'orientacoes-normativas': 'Orientações Normativas',
    'outros': 'Outros'
}

def get_category_name(slug):
    """Converte slug de categoria para nome amigável"""
    return CATEGORIES_MAP.get(slug, slug)

def get_current_law_firm_id():
    return session.get('law_firm_id')

def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            else:
                return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@cases_bp.route('/')
@require_law_firm
def cases_list():
    law_firm_id = get_current_law_firm_id()
    
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.name).all()
    courts = None
    
    query = Case.query.filter_by(law_firm_id=law_firm_id).join(Client)
    
    client_id = request.args.get('client_id')
    if client_id:
        query = query.filter(Case.client_id == client_id)
    
    case_type = request.args.get('case_type')
    if case_type:
        query = query.filter(Case.case_type == case_type)
    
    status = request.args.get('status')
    if status:
        query = query.filter(Case.status == status)
    
    court_id = request.args.get('court_id')
    if court_id:
        query = query.filter(Case.court_id == court_id)
    
    fap_year = request.args.get('fap_year')
    if fap_year:
        try:
            year = int(fap_year)
            query = query.filter(
                db.or_(
                    Case.fap_start_year == year,
                    Case.fap_end_year == year,
                    db.and_(Case.fap_start_year <= year, Case.fap_end_year >= year)
                )
            )
        except ValueError:
            pass
    
    value_min = request.args.get('value_min')
    if value_min:
        try:
            min_val = float(value_min)
            query = query.filter(Case.value_cause >= min_val)
        except (ValueError, TypeError):
            pass
    
    value_max = request.args.get('value_max')
    if value_max:
        try:
            max_val = float(value_max)
            query = query.filter(Case.value_cause <= max_val)
        except (ValueError, TypeError):
            pass
    
    search_text = request.args.get('search')
    if search_text:
        search_pattern = f"%{search_text}%"
        query = query.filter(
            db.or_(
                Case.title.ilike(search_pattern),
                Case.facts_summary.ilike(search_pattern),
                Case.thesis_summary.ilike(search_pattern),
                Client.name.ilike(search_pattern)
            )
        )
    
    date_from = request.args.get('date_from')
    if date_from:
        try:
            from datetime import datetime
            date_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            query = query.filter(Case.filing_date >= date_obj)
        except ValueError:
            pass
    
    date_to = request.args.get('date_to')
    if date_to:
        try:
            from datetime import datetime
            date_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            query = query.filter(Case.filing_date <= date_obj)
        except ValueError:
            pass
    
    cases = query.order_by(Case.created_at.desc()).all()
    
    return render_template('cases/list.html', cases=cases, clients=clients, courts=courts)


@cases_bp.route('/knowledge-base')
@require_law_firm
def cases_knowledge_base_list():
    """Lista arquivos da base de conhecimento geral de casos"""
    law_firm_id = get_current_law_firm_id()
    
    # Buscar arquivos da base de conhecimento
    files = CasesKnowledgeBase.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).order_by(CasesKnowledgeBase.uploaded_at.desc()).all()
    
    # Contar total de arquivos
    total_files = len(files)
    
    return render_template(
        'cases/cases_knowledge_base_list.html',
        files=files,
        total_files=total_files,
        get_category_name=get_category_name
    )


@cases_bp.route('/knowledge-base/upload', methods=['GET', 'POST'])
@require_law_firm
def cases_knowledge_base_upload():
    """Upload de arquivos para a base de conhecimento geral de casos"""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')
    
    if request.method == 'POST':
        # Validar se o arquivo foi enviado
        if 'file' not in request.files:
            flash('Nenhum arquivo foi enviado.', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        
        if file.filename == '':
            flash('Nenhum arquivo foi selecionado.', 'error')
            return redirect(request.url)
        
        # Obter dados do formulário
        description = request.form.get('description', '')
        category = request.form.get('category', '')
        tags = request.form.get('tags', '')
        
        # Salvar arquivo
        if file:
            filename = secure_filename(file.filename)
            upload_dir = f"uploads/cases_knowledge_base/{law_firm_id}"
            os.makedirs(upload_dir, exist_ok=True)
            
            # Adicionar timestamp ao nome do arquivo para evitar duplicatas
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            name, ext = os.path.splitext(filename)
            filename_with_timestamp = f"{name}_{timestamp}{ext}"
            
            file_path = os.path.join(upload_dir, filename_with_timestamp)
            file.save(file_path)
            
            # Obter informações do arquivo
            file_size = os.path.getsize(file_path)
            file_type = ext.lstrip('.').upper() if ext else 'DESCONHECIDO'
            
            # Criar registro no banco de dados
            cases_kb_file = CasesKnowledgeBase(
                user_id=user_id,
                law_firm_id=law_firm_id,
                original_filename=filename,
                file_path=file_path,
                file_size=file_size,
                file_type=file_type,
                description=description,
                category=category,
                tags=tags
            )
            
            try:
                db.session.add(cases_kb_file)
                db.session.commit()
                
                # Processar arquivo com CaseKnowledgeIngestor e inserir no Qdrant
                try:
                    print(f"Iniciando processamento do arquivo: {filename}")
                    # Usar CaseKnowledgeIngestor para base de conhecimento de casos
                    ingestor = CaseKnowledgeIngestor()
                    
                    # Processar arquivo e inserir no Qdrant
                    markdown_content = ingestor.process_file(
                        Path(file_path), 
                        source_name=filename,
                        category=category,
                        description=description,
                        tags=tags,
                        file_id=cases_kb_file.id
                    )
                    
                    if markdown_content:
                        print(f"Arquivo processado com sucesso: {filename}")
                        flash(
                            f'Arquivo "{filename}" adicionado com sucesso à base de conhecimento de casos e processado pela IA!', 
                            'success'
                        )
                    else:
                        print(f"Aviso: Arquivo salvo mas não foi possível processar: {filename}")
                        flash(
                            f'Arquivo "{filename}" adicionado à base de conhecimento, mas houve problema no processamento pela IA.', 
                            'warning'
                        )
                except Exception as e:
                    print(f"Erro ao processar arquivo com IA: {str(e)}")
                    flash(
                        f'Arquivo "{filename}" foi salvo, mas ocorreu um erro no processamento pela IA: {str(e)}', 
                        'warning'
                    )
                
                return redirect(url_for('cases.cases_knowledge_base_list'))
            except Exception as e:
                db.session.rollback()
                # Remover arquivo em caso de erro
                if os.path.exists(file_path):
                    os.remove(file_path)
                flash(f'Erro ao salvar arquivo no banco de dados: {str(e)}', 'error')
                return redirect(request.url)
    
    return render_template(
        'cases/cases_knowledge_base_upload.html',
        categories=CATEGORIES_MAP
    )


@cases_bp.route('/knowledge-base/chat')
@require_law_firm
def cases_knowledge_base_chat():
    """Tela de chat para pesquisa na base de conhecimento de casos"""
    law_firm_id = get_current_law_firm_id()
    
    # Contar documentos na base de conhecimento
    total_documents = CasesKnowledgeBase.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).count()
    
    return render_template('cases/cases_knowledge_base_chat.html', total_documents=total_documents)


@cases_bp.route('/knowledge-base/<int:file_id>/download')
@require_law_firm
def cases_knowledge_base_download(file_id):
    """Download de um arquivo da base de conhecimento de casos"""
    law_firm_id = get_current_law_firm_id()

    file = CasesKnowledgeBase.query.filter_by(
        id=file_id,
        law_firm_id=law_firm_id,
        is_active=True
    ).first()

    if not file:
        flash('Arquivo não encontrado.', 'error')
        return redirect(url_for('cases.cases_knowledge_base_list'))

    if not os.path.exists(file.file_path):
        flash('Arquivo não encontrado no servidor.', 'error')
        return redirect(url_for('cases.cases_knowledge_base_list'))

    try:
        # Preferência por `download_name` em versões mais novas do Flask
        return send_file(file.file_path, as_attachment=True, download_name=file.original_filename)
    except TypeError:
        # Compatibilidade com versões mais antigas do Flask
        return send_file(file.file_path, as_attachment=True, attachment_filename=file.original_filename)
    except Exception as e:
        flash(f'Erro ao baixar o arquivo: {str(e)}', 'error')
        return redirect(url_for('cases.cases_knowledge_base_list'))


@cases_bp.route('/knowledge-base/api/ask', methods=['POST'])
@require_law_firm
def cases_knowledge_base_api_ask():
    """API para fazer perguntas à base de conhecimento de casos"""
    law_firm_id = get_current_law_firm_id()
    
    if not law_firm_id:
        return jsonify({'success': False, 'error': 'Não autorizado'}), 401
    
    data = request.get_json()
    question = data.get('question', '').strip()
    
    if not question:
        return jsonify({'success': False, 'error': 'Pergunta não pode estar vazia'}), 400
    
    try:
        user_id = session.get('user_id')
        
        # Inicializar o CaseKnowledgeIngestor
        ingestor = CaseKnowledgeIngestor()
        
        # Fazer a pergunta usando o método ask_with_llm
        result = ingestor.ask_with_llm(
            question=question,
            user_id=user_id,
            law_firm_id=law_firm_id
        )
        
        return jsonify({
            'success': True,
            'answer': result['answer'],
            'sources': result['sources'],
            'history_id': result.get('history_id')
        })
    except Exception as e:
        print(f"Erro ao processar pergunta: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Erro ao processar pergunta: {str(e)}'
        }), 500


@cases_bp.route('/new', methods=['GET', 'POST'])
@require_law_firm
def case_new():
    from app.form import CaseForm
    form = CaseForm()
    
    law_firm_id = get_current_law_firm_id()
    
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.name).all()
    courts = None
    
    form.client_id.choices = [(0, 'Selecione um cliente')] + [(c.id, c.name) for c in clients]
    form.court_id.choices = [(0, 'Selecione uma vara')] if courts else [(0, 'Selecione uma vara')]
    
    if form.validate_on_submit():
        case = Case(
            law_firm_id=get_current_law_firm_id(),
            client_id=form.client_id.data if form.client_id.data != 0 else None,
            court_id=form.court_id.data if form.court_id.data != 0 else None,
            title=form.title.data,
            case_type=form.case_type.data,
            fap_reason=form.fap_reason.data if form.fap_reason.data else None,
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
            from flask import flash
            flash('Caso cadastrado com sucesso!', 'success')
            return redirect(url_for('cases.case_detail', case_id=case.id))
        except Exception as e:
            db.session.rollback()
            from flask import flash
            flash(f'Erro ao cadastrar caso: {str(e)}', 'danger')
    
    return render_template('cases/form.html', form=form, title='Novo Caso')

@cases_bp.route('/<int:case_id>')
def case_detail(case_id):
    case = Case.query.get_or_404(case_id)
    benefits = CaseBenefit.query.filter_by(case_id=case_id).order_by(CaseBenefit.created_at.desc()).all()
    documents = Document.query.filter_by(case_id=case_id).order_by(Document.uploaded_at.desc()).all()
    competences = CaseCompetence.query.filter_by(case_id=case_id).all()
    petitions = Petition.query.filter_by(case_id=case_id).order_by(Petition.version.desc()).all()
    case_lawyers = CaseLawyer.query.filter_by(case_id=case_id).all()
    all_lawyers = Lawyer.query.order_by(Lawyer.name).all()
    return render_template('cases/detail.html', case=case, case_id=case_id, benefits=benefits, documents=documents, competences=competences, petitions=petitions, case_lawyers=case_lawyers, all_lawyers=all_lawyers)

@cases_bp.route('/<int:case_id>/edit', methods=['GET', 'POST'])
@require_law_firm
def case_edit(case_id):
    from app.form import CaseForm
    law_firm_id = get_current_law_firm_id()
    case = Case.query.filter_by(id=case_id, law_firm_id=law_firm_id).first_or_404()
    form = CaseForm(obj=case)
    
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.name).all()
    courts = None
    
    form.client_id.choices = [(0, 'Selecione um cliente')] + [(c.id, c.name) for c in clients]
    form.court_id.choices = [(0, 'Selecione uma vara')] if courts else [(0, 'Selecione uma vara')]
    
    if form.validate_on_submit():
        case.client_id = form.client_id.data if form.client_id.data != 0 else None
        case.court_id = form.court_id.data if form.court_id.data != 0 else None
        case.title = form.title.data
        case.case_type = form.case_type.data
        case.fap_reason = form.fap_reason.data if form.fap_reason.data else None
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
            from flask import flash
            flash('Caso atualizado com sucesso!', 'success')
            return redirect(url_for('cases.cases_list'))
        except Exception as e:
            db.session.rollback()
            from flask import flash
            flash(f'Erro ao atualizar caso: {str(e)}', 'danger')
        
    return render_template('cases/form.html', form=form, title='Editar Caso', case_id=case_id)

@cases_bp.route('/<int:case_id>/delete', methods=['POST'])
def case_delete(case_id):
    case = Case.query.get_or_404(case_id)
    
    try:
        db.session.delete(case)
        db.session.commit()
        from flask import flash
        flash('Caso excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        from flask import flash
        flash(f'Erro ao excluir caso: {str(e)}', 'danger')
    
    return redirect(url_for('cases.cases_list'))

@cases_bp.route('/<int:case_id>/lawyers/add', methods=['POST'])
def case_lawyer_add(case_id):
    case = Case.query.get_or_404(case_id)
    
    lawyer_id = request.form.get('lawyer_id')
    role = request.form.get('role', '')
    
    if not lawyer_id:
        from flask import flash
        flash('Selecione um advogado.', 'warning')
        return redirect(url_for('cases.case_detail', case_id=case_id))
    
    lawyer = Lawyer.query.get_or_404(int(lawyer_id))
    
    existing = CaseLawyer.query.filter_by(case_id=case_id, lawyer_id=lawyer_id).first()
    if existing:
        from flask import flash
        flash('Este advogado já está vinculado ao caso.', 'warning')
        return redirect(url_for('cases.case_detail', case_id=case_id))
    
    case_lawyer = CaseLawyer(
        case_id=case_id,
        lawyer_id=lawyer_id,
        role=role
    )
    
    db.session.add(case_lawyer)
    try:
        db.session.commit()
        from flask import flash
        flash(f'Advogado {lawyer.name} vinculado ao caso com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        from flask import flash
        flash(f'Erro ao vincular advogado: {str(e)}', 'danger')
    
    return redirect(url_for('cases.case_detail', case_id=case_id))

@cases_bp.route('/<int:case_id>/lawyers/<int:case_lawyer_id>/remove', methods=['POST'])
def case_lawyer_remove(case_id, case_lawyer_id):
    case_lawyer = CaseLawyer.query.get_or_404(case_lawyer_id)
    
    if case_lawyer.case_id != case_id:
        from flask import flash
        flash('Vínculo não pertence a este caso.', 'danger')
        return redirect(url_for('cases.case_detail', case_id=case_id))
    
    lawyer_name = case_lawyer.lawyer.name
    
    try:
        db.session.delete(case_lawyer)
        db.session.commit()
        from flask import flash
        flash(f'Advogado {lawyer_name} removido do caso.', 'success')
    except Exception as e:
        db.session.rollback()
        from flask import flash
        flash(f'Erro ao remover advogado: {str(e)}', 'danger')
    
    return redirect(url_for('cases.case_detail', case_id=case_id))


# ============================================================================
# ROTAS DE TEMPLATES
# ============================================================================

@cases_bp.route('/templates')
@require_law_firm
def templates_list():
    """Lista todos os templates disponíveis"""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')
    
    # Filtros
    categoria = request.args.get('categoria')
    status = request.args.get('status')
    search = request.args.get('search', '').strip()
    
    query = CaseTemplate.query.filter_by(law_firm_id=law_firm_id)
    
    if categoria:
        query = query.filter(CaseTemplate.categoria == categoria)
    
    if status:
        if status == 'active':
            query = query.filter(CaseTemplate.is_active == True)
        elif status == 'inactive':
            query = query.filter(CaseTemplate.is_active == False)
    
    if search:
        search_pattern = f'%{search}%'
        query = query.filter(
            db.or_(
                CaseTemplate.template_name.ilike(search_pattern),
                CaseTemplate.resumo_curto.ilike(search_pattern),
                CaseTemplate.categoria.ilike(search_pattern)
            )
        )
    
    templates = query.order_by(CaseTemplate.uploaded_at.desc()).all()
    
    # Estatísticas
    total_templates = CaseTemplate.query.filter_by(law_firm_id=law_firm_id).count()
    active_templates = CaseTemplate.query.filter_by(law_firm_id=law_firm_id, is_active=True).count()
    
    # Categorias únicas
    categorias = db.session.query(CaseTemplate.categoria).filter_by(law_firm_id=law_firm_id).distinct().all()
    categorias = [c[0] for c in categorias if c[0]]
    
    return render_template(
        'cases/templates_list.html',
        templates=templates,
        total_templates=total_templates,
        active_templates=active_templates,
        categorias=categorias,
        current_categoria=categoria,
        current_status=status,
        search=search
    )


@cases_bp.route('/templates/upload', methods=['GET', 'POST'])
@require_law_firm
def templates_upload():
    """Upload de novo template"""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')
    
    if request.method == 'POST':
        try:
            # Validar campos obrigatórios
            template_name = request.form.get('template_name', '').strip()
            resumo_curto = request.form.get('resumo_curto', '').strip()
            categoria = request.form.get('categoria', '').strip()
            
            if not template_name or not resumo_curto or not categoria:
                flash('Todos os campos obrigatórios devem ser preenchidos.', 'danger')
                return redirect(url_for('cases.templates_upload'))
            
            # Processar arquivo
            if 'file' not in request.files:
                flash('Nenhum arquivo foi enviado.', 'danger')
                return redirect(url_for('cases.templates_upload'))
            
            file = request.files['file']
            if file.filename == '':
                flash('Nenhum arquivo foi selecionado.', 'danger')
                return redirect(url_for('cases.templates_upload'))
            
            # Validar extensão
            allowed_extensions = {'.docx', '.doc', '.pdf'}
            file_ext = Path(file.filename).suffix.lower()
            if file_ext not in allowed_extensions:
                flash(f'Formato de arquivo não permitido. Use: {" ".join(allowed_extensions)}', 'danger')
                return redirect(url_for('cases.templates_upload'))
            
            # Criar diretório
            upload_dir = Path('uploads') / 'templates' / str(law_firm_id)
            upload_dir.mkdir(parents=True, exist_ok=True)
            
            # Salvar arquivo
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            unique_filename = f"{timestamp}_{filename}"
            file_path = upload_dir / unique_filename
            
            file.save(str(file_path))
            
            # Criar registro no banco
            template = CaseTemplate(
                user_id=user_id,
                law_firm_id=law_firm_id,
                template_name=template_name,
                resumo_curto=resumo_curto,
                categoria=categoria,
                original_filename=filename,
                file_path=str(file_path),
                file_size=file_path.stat().st_size,
                file_type=file_ext.upper().replace('.', ''),
                is_active=request.form.get('is_active') == 'on',
                status='available',
                tags=request.form.get('tags', '')
            )
            
            db.session.add(template)
            db.session.commit()
            
            flash(f'Template "{template_name}" adicionado com sucesso!', 'success')
            return redirect(url_for('cases.templates_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao adicionar template: {str(e)}', 'danger')
            return redirect(url_for('cases.templates_upload'))
    
    return render_template('cases/templates_upload.html')


@cases_bp.route('/templates/<int:template_id>/toggle', methods=['POST'])
@require_law_firm
def templates_toggle(template_id):
    """Ativa ou desativa um template"""
    law_firm_id = get_current_law_firm_id()
    
    template = CaseTemplate.query.filter_by(
        id=template_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    template.is_active = not template.is_active
    db.session.commit()
    
    status = 'ativado' if template.is_active else 'desativado'
    flash(f'Template "{template.template_name}" {status} com sucesso!', 'success')
    
    return redirect(url_for('cases.templates_list'))


@cases_bp.route('/templates/<int:template_id>/delete', methods=['POST'])
@require_law_firm
def templates_delete(template_id):
    """Deleta um template"""
    law_firm_id = get_current_law_firm_id()
    
    template = CaseTemplate.query.filter_by(
        id=template_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    try:
        # Deletar arquivo físico
        if os.path.exists(template.file_path):
            os.remove(template.file_path)
        
        template_name = template.template_name
        db.session.delete(template)
        db.session.commit()
        
        flash(f'Template "{template_name}" removido com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao remover template: {str(e)}', 'danger')
    
    return redirect(url_for('cases.templates_list'))
