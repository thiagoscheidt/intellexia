from flask import Blueprint, render_template, request, session, jsonify, redirect, url_for, flash
from app.models import (
    db, JudicialProcess, JudicialSentenceAnalysis, JudicialAppeal, 
    KnowledgeBase, Case, User
)
from datetime import datetime
from functools import wraps
from sqlalchemy import or_, and_
from werkzeug.utils import secure_filename
import hashlib
import os

process_panel_bp = Blueprint('process_panel', __name__, url_prefix='/process-panel')


def _compute_file_hash(file_storage):
    """Calcula hash SHA-256 sem perder posição do stream para salvar depois."""
    hasher = hashlib.sha256()

    file_storage.stream.seek(0)
    while True:
        chunk = file_storage.stream.read(8192)
        if not chunk:
            break
        hasher.update(chunk)
    file_storage.stream.seek(0)

    return hasher.hexdigest()


def get_current_law_firm_id():
    """Obtém o ID do escritório do usuário atual"""
    return session.get('law_firm_id')


def require_law_firm(f):
    """Decorator para validar se usuário está autenticado"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            else:
                return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@process_panel_bp.route('/')
@require_law_firm
def list_processes():
    """Lista todos os processos judiciais cadastrados"""
    law_firm_id = get_current_law_firm_id()
    
    # Filtros
    search_query = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)
    
    query = JudicialProcess.query.filter_by(law_firm_id=law_firm_id)
    
    # Filtro por busca
    if search_query:
        query = query.filter(
            or_(
                JudicialProcess.process_number.ilike(f'%{search_query}%'),
                JudicialProcess.title.ilike(f'%{search_query}%'),
                JudicialProcess.tribunal.ilike(f'%{search_query}%')
            )
        )
    
    # Filtro por status
    if status_filter:
        query = query.filter(JudicialProcess.status == status_filter)
    
    # Paginação
    processes = query.order_by(JudicialProcess.created_at.desc()).paginate(
        page=page, per_page=15
    )
    
    # Estatísticas
    stats = {
        'total': JudicialProcess.query.filter_by(law_firm_id=law_firm_id).count(),
        'ativo': JudicialProcess.query.filter_by(law_firm_id=law_firm_id, status='ativo').count(),
        'suspenso': JudicialProcess.query.filter_by(law_firm_id=law_firm_id, status='suspenso').count(),
        'encerrado': JudicialProcess.query.filter_by(law_firm_id=law_firm_id, status='encerrado').count(),
    }
    
    return render_template(
        'process_panel/list.html',
        processes=processes,
        search_query=search_query,
        status_filter=status_filter,
        stats=stats
    )


@process_panel_bp.route('/novo', methods=['GET', 'POST'])
@require_law_firm
def new_process():
    """Criar processo simplificado (número CNJ + documentos para base de conhecimento)."""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')
    
    if request.method == 'POST':
        process_number = request.form.get('process_number', '').strip().upper()
        uploaded_files = [
            file for file in request.files.getlist('documents')
            if file and file.filename and file.filename.strip()
        ]
        
        # Validações
        if not process_number:
            flash('Número do processo é obrigatório', 'danger')
            return redirect(url_for('process_panel.new_process'))

        if not uploaded_files:
            flash('Envie ao menos um documento para a base de conhecimento.', 'danger')
            return redirect(url_for('process_panel.new_process'))
        
        # Verificar se processo já existe
        existing = JudicialProcess.query.filter_by(
            law_firm_id=law_firm_id,
            process_number=process_number
        ).first()
        
        if existing:
            flash(f'Processo {process_number} já existe', 'danger')
            return redirect(url_for('process_panel.new_process'))
        
        # Criar novo processo
        try:
            new_proc = JudicialProcess(
                law_firm_id=law_firm_id,
                user_id=user_id,
                process_number=process_number,
                title=process_number,
                status='ativo'
            )

            upload_dir = f"uploads/knowledge_base/{law_firm_id}"
            os.makedirs(upload_dir, exist_ok=True)

            saved_file_paths = []
            duplicates_count = 0
            uploaded_count = 0

            for file in uploaded_files:
                file_hash = _compute_file_hash(file)

                duplicate = KnowledgeBase.query.filter_by(
                    law_firm_id=law_firm_id,
                    file_hash=file_hash
                ).first()

                if duplicate:
                    duplicates_count += 1
                    continue

                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                name, ext = os.path.splitext(filename)
                filename_with_timestamp = f"{name}_{timestamp}{ext}"
                file_path = os.path.join(upload_dir, filename_with_timestamp)

                file.save(file_path)
                saved_file_paths.append(file_path)

                file_size = os.path.getsize(file_path)
                file_type = ext.lstrip('.').upper() if ext else 'DESCONHECIDO'

                kb_entry = KnowledgeBase(
                    user_id=user_id,
                    law_firm_id=law_firm_id,
                    original_filename=filename,
                    file_path=file_path,
                    file_size=file_size,
                    file_type=file_type,
                    file_hash=file_hash,
                    description='',
                    category='',
                    tags='',
                    lawsuit_number=process_number,
                    processing_status='pending'
                )
                db.session.add(kb_entry)
                uploaded_count += 1

            if uploaded_count == 0:
                flash('Nenhum arquivo novo foi enviado (todos os arquivos já existem na base).', 'warning')
                return redirect(url_for('process_panel.new_process'))
            
            db.session.add(new_proc)
            db.session.commit()

            if duplicates_count > 0:
                flash(
                    f'Processo {process_number} criado. {uploaded_count} documento(s) enviado(s) e {duplicates_count} duplicado(s) ignorado(s).',
                    'success'
                )
            else:
                flash(
                    f'Processo {process_number} criado com sucesso! {uploaded_count} documento(s) enviado(s) para a base de conhecimento.',
                    'success'
                )

            return redirect(url_for('process_panel.detail', process_id=new_proc.id))
            
        except Exception as e:
            db.session.rollback()
            for file_path in locals().get('saved_file_paths', []):
                if os.path.exists(file_path):
                    os.remove(file_path)
            flash(f'Erro ao criar processo: {str(e)}', 'danger')
            return redirect(url_for('process_panel.new_process'))
    
    # GET - Mostrar formulário simplificado
    return render_template('process_panel/form_new_simple.html', action='novo')


@process_panel_bp.route('/<int:process_id>')
@require_law_firm
def detail(process_id):
    """Visualizar detalhe de um processo e seus dados relacionados"""
    law_firm_id = get_current_law_firm_id()
    
    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    # Buscar analyses de sentença relacionadas
    sentence_analyses = JudicialSentenceAnalysis.query.filter(
        JudicialSentenceAnalysis.user_id == session.get('user_id')
    ).all()
    
    # Buscar appeals relacionados
    appeals = JudicialAppeal.query.filter(
        JudicialAppeal.user_id == session.get('user_id')
    ).all()
    
    # Buscar documentos da knowledge base com o mesmo process_number
    # Pesquisar com e sem pontuação
    process_number_clean = ''.join(c for c in process.process_number if c.isdigit())
    kb_documents = KnowledgeBase.query.filter(
        KnowledgeBase.law_firm_id == law_firm_id,
        or_(
            KnowledgeBase.lawsuit_number == process.process_number,
            KnowledgeBase.lawsuit_number == process_number_clean,
            db.func.replace(db.func.replace(db.func.replace(
                KnowledgeBase.lawsuit_number, '-', ''), '.', ''), ' ', ''
            ) == process_number_clean
        )
    ).all()
    
    # Filtrar analyses e appeals por process_number
    related_analyses = [a for a in sentence_analyses if hasattr(a, 'process_number') and a.process_number == process.process_number]
    related_appeals = [a for a in appeals if a.sentence_analysis and (hasattr(a.sentence_analysis, 'process_number') and a.sentence_analysis.process_number == process.process_number)]
    
    # Dados para a dashboard
    data = {
        'process': process,
        'sentence_analyses': related_analyses,
        'appeals': related_appeals,
        'kb_documents': kb_documents,
        'case': process.case if process.case_id else None,
        'stats': {
            'analyses_count': len(related_analyses),
            'appeals_count': len(related_appeals),
            'documents_count': len(kb_documents),
        }
    }
    
    return render_template('process_panel/detail.html', **data)


@process_panel_bp.route('/<int:process_id>/editar', methods=['GET', 'POST'])
@require_law_firm
def edit(process_id):
    """Editar um processo judicial"""
    law_firm_id = get_current_law_firm_id()
    
    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    if request.method == 'POST':
        # Atualizar campos
        process.title = request.form.get('title', '').strip() or process.title
        process.description = request.form.get('description', '').strip()
        process.judge_name = request.form.get('judge_name', '').strip()
        process.tribunal = request.form.get('tribunal', '').strip()
        process.section = request.form.get('section', '').strip()
        process.origin_unit = request.form.get('origin_unit', '').strip()
        process.status = request.form.get('status', process.status)
        process.internal_notes = request.form.get('internal_notes', '').strip()
        process.case_id = request.form.get('case_id') or None
        
        try:
            process.updated_at = datetime.utcnow()
            db.session.commit()
            flash('Processo atualizado com sucesso!', 'success')
            return redirect(url_for('process_panel.detail', process_id=process.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar: {str(e)}', 'danger')
    
    cases = Case.query.filter_by(law_firm_id=law_firm_id).order_by(Case.title).all()
    return render_template('process_panel/form.html', process=process, cases=cases, action='editar')


@process_panel_bp.route('/<int:process_id>/deletar', methods=['POST'])
@require_law_firm
def delete(process_id):
    """Deletar um processo judicial"""
    law_firm_id = get_current_law_firm_id()
    
    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    try:
        db.session.delete(process)
        db.session.commit()
        flash(f'Processo {process.process_number} deletado com sucesso', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar: {str(e)}', 'danger')
    
    return redirect(url_for('process_panel.list_processes'))


@process_panel_bp.route('/api/search')
@require_law_firm
def api_search():
    """API para buscar processos (AJAX)"""
    law_firm_id = get_current_law_firm_id()
    query = request.args.get('q', '').strip()
    
    if len(query) < 3:
        return jsonify([])
    
    processes = JudicialProcess.query.filter_by(law_firm_id=law_firm_id).filter(
        or_(
            JudicialProcess.process_number.ilike(f'%{query}%'),
            JudicialProcess.title.ilike(f'%{query}%')
        )
    ).limit(10).all()
    
    results = [
        {
            'id': p.id,
            'process_number': p.process_number,
            'title': p.title,
            'status': p.status,
            'tribunal': p.tribunal
        }
        for p in processes
    ]
    
    return jsonify(results)


@process_panel_bp.route('/<int:process_id>/status', methods=['POST'])
@require_law_firm
def update_status(process_id):
    """Atualizar status do processo (AJAX)"""
    law_firm_id = get_current_law_firm_id()
    
    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    new_status = request.json.get('status')
    valid_statuses = ['ativo', 'suspenso', 'encerrado', 'aguardando']
    
    if new_status not in valid_statuses:
        return jsonify({'error': 'Status inválido'}), 400
    
    try:
        process.status = new_status
        process.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'status': new_status})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
