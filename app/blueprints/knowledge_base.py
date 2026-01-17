from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app.models import db, KnowledgeBase
from datetime import datetime
from werkzeug.utils import secure_filename
import os

knowledge_base_bp = Blueprint('knowledge_base', __name__, url_prefix='/knowledge-base')

def get_current_law_firm_id():
    """Retorna o ID do escritório do usuário logado"""
    return session.get('law_firm_id')

def get_current_user_id():
    """Retorna o ID do usuário logado"""
    return session.get('user_id')

@knowledge_base_bp.route('/')
def list():
    """Lista todos os arquivos da base de conhecimento"""
    law_firm_id = get_current_law_firm_id()
    if not law_firm_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))
    
    # Filtros opcionais
    category = request.args.get('category', '')
    search = request.args.get('search', '')
    
    # Query base
    query = KnowledgeBase.query.filter_by(law_firm_id=law_firm_id, is_active=True)
    
    # Aplicar filtros
    if category:
        query = query.filter_by(category=category)
    if search:
        query = query.filter(
            db.or_(
                KnowledgeBase.original_filename.ilike(f'%{search}%'),
                KnowledgeBase.description.ilike(f'%{search}%'),
                KnowledgeBase.tags.ilike(f'%{search}%')
            )
        )
    
    # Ordenar por data de upload (mais recente primeiro)
    files = query.order_by(KnowledgeBase.uploaded_at.desc()).all()
    
    # Obter categorias únicas para o filtro
    categories = db.session.query(KnowledgeBase.category).filter_by(
        law_firm_id=law_firm_id, 
        is_active=True
    ).distinct().all()
    categories = [c[0] for c in categories if c[0]]
    
    return render_template(
        'knowledge_base/list.html', 
        files=files, 
        categories=categories,
        current_category=category,
        current_search=search
    )

@knowledge_base_bp.route('/upload', methods=['GET', 'POST'])
def upload():
    """Permite fazer upload de novos arquivos para a base de conhecimento"""
    law_firm_id = get_current_law_firm_id()
    user_id = get_current_user_id()
    
    if not law_firm_id or not user_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))
    
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
            upload_dir = f"uploads/knowledge_base/{law_firm_id}"
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
            knowledge_file = KnowledgeBase(
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
                db.session.add(knowledge_file)
                db.session.commit()
                flash(f'Arquivo "{filename}" adicionado com sucesso à base de conhecimento!', 'success')
                return redirect(url_for('knowledge_base.list'))
            except Exception as e:
                db.session.rollback()
                # Remover arquivo em caso de erro
                if os.path.exists(file_path):
                    os.remove(file_path)
                flash(f'Erro ao salvar arquivo no banco de dados: {str(e)}', 'error')
                return redirect(request.url)
    
    return render_template('knowledge_base/upload.html')

@knowledge_base_bp.route('/<int:file_id>/delete', methods=['POST'])
def delete(file_id):
    """Marca um arquivo como inativo (soft delete)"""
    law_firm_id = get_current_law_firm_id()
    
    if not law_firm_id:
        return jsonify({'success': False, 'message': 'Não autorizado'}), 401
    
    file = KnowledgeBase.query.filter_by(id=file_id, law_firm_id=law_firm_id).first()
    
    if not file:
        return jsonify({'success': False, 'message': 'Arquivo não encontrado'}), 404
    
    try:
        file.is_active = False
        file.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Arquivo removido da base de conhecimento.', 'success')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@knowledge_base_bp.route('/<int:file_id>/details')
def details(file_id):
    """Mostra os detalhes de um arquivo específico"""
    law_firm_id = get_current_law_firm_id()
    
    if not law_firm_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))
    
    file = KnowledgeBase.query.filter_by(
        id=file_id, 
        law_firm_id=law_firm_id,
        is_active=True
    ).first_or_404()
    
    return render_template('knowledge_base/details.html', file=file)
