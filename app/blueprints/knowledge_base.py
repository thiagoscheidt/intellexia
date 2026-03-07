from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from app.models import db, KnowledgeBase, KnowledgeCategory, KnowledgeTag, KnowledgeSummary, KnowledgeChatHistory, KnowledgeChatSession
from app.agents.knowledge_base.knowledge_query_agent import KnowledgeQueryAgent
from datetime import datetime
import builtins
from werkzeug.utils import secure_filename
from app.agents.document_processing.agent_document_summary import AgentDocumentSummary
from app.services.knowledge_base.chat_context import build_attachments_context
from app.services.knowledge_base.search_helpers import (
    highlight_search_terms,
    looks_like_name_query,
    name_tokens,
    normalize_for_match,
)
from app.services.knowledge_base.session_helpers import (
    generate_chat_title_from_question,
    get_current_law_firm_id,
    get_current_user_id,
)
import os
import json as json_lib
import hashlib

knowledge_base_bp = Blueprint('knowledge_base', __name__, url_prefix='/knowledge-base')


def _compute_file_hash(file_storage):
    """Calcula hash SHA-256 do arquivo enviado sem perder a posição para salvar depois."""
    hasher = hashlib.sha256()

    file_storage.stream.seek(0)
    while True:
        chunk = file_storage.stream.read(8192)
        if not chunk:
            break
        hasher.update(chunk)
    file_storage.stream.seek(0)

    return hasher.hexdigest()

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


@knowledge_base_bp.route('/folders')
def folders_view():
    """Visualização em pastas (estilo drive): categorias -> arquivos da categoria"""
    law_firm_id = get_current_law_firm_id()
    if not law_firm_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))

    search = request.args.get('search', '').strip()
    selected_category = request.args.get('category', '').strip()

    categories_from_db = KnowledgeCategory.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).order_by(KnowledgeCategory.display_order.asc()).all()

    base_query = KnowledgeBase.query.filter_by(law_firm_id=law_firm_id, is_active=True)
    total_files = base_query.count()

    # Modo 1: pasta selecionada -> listar arquivos da categoria
    if selected_category:
        category_query = base_query

        if selected_category == '__uncategorized__':
            category_query = category_query.filter(
                db.or_(
                    KnowledgeBase.category.is_(None),
                    KnowledgeBase.category == ''
                )
            )
            selected_category_label = 'Sem categoria'
        else:
            category_query = category_query.filter(KnowledgeBase.category == selected_category)
            selected_category_label = selected_category

        if search:
            category_query = category_query.filter(
                db.or_(
                    KnowledgeBase.original_filename.ilike(f'%{search}%'),
                    KnowledgeBase.description.ilike(f'%{search}%'),
                    KnowledgeBase.tags.ilike(f'%{search}%'),
                    KnowledgeBase.lawsuit_number.ilike(f'%{search}%')
                )
            )

        category_files = category_query.order_by(KnowledgeBase.uploaded_at.desc()).all()

        return render_template(
            'knowledge_base/folders_view.html',
            total_files=total_files,
            current_search=search,
            selected_category=selected_category,
            selected_category_label=selected_category_label,
            category_files=category_files,
            categories_data=[],
        )

    # Modo 2: raiz -> listar apenas pastas (categorias)
    all_files = base_query.all()
    category_counts = {}
    for file in all_files:
        category_name = (file.category or '').strip() or 'Sem categoria'
        category_counts[category_name] = category_counts.get(category_name, 0) + 1

    ordered_names = []
    for category in categories_from_db:
        category_name = (category.name or '').strip()
        if category_name and category_name not in ordered_names:
            ordered_names.append(category_name)

    # Categorias existentes em arquivos mas não cadastradas em KnowledgeCategory
    for category_name in category_counts.keys():
        if category_name != 'Sem categoria' and category_name not in ordered_names:
            ordered_names.append(category_name)

    # Sempre mostrar a pasta "Sem categoria"
    if 'Sem categoria' not in ordered_names:
        ordered_names.append('Sem categoria')

    categories_data = []
    search_lower = search.lower() if search else ''

    for category_name in ordered_names:
        if search_lower and search_lower not in category_name.lower():
            continue

        categories_data.append({
            'name': category_name,
            'count': category_counts.get(category_name, 0),
            'param_value': '__uncategorized__' if category_name == 'Sem categoria' else category_name,
        })

    categories_data.sort(key=lambda item: item['name'].lower())

    return render_template(
        'knowledge_base/folders_view.html',
        total_files=total_files,
        current_search=search,
        selected_category=None,
        selected_category_label=None,
        category_files=[],
        categories_data=categories_data,
    )

@knowledge_base_bp.route('/upload', methods=['GET', 'POST'])
def upload():
    """Permite fazer upload de novos arquivos para a base de conhecimento"""
    law_firm_id = get_current_law_firm_id()
    user_id = get_current_user_id()
    
    if not law_firm_id or not user_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))
    
    # Buscar categorias do banco de dados
    categories = KnowledgeCategory.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).order_by(KnowledgeCategory.display_order).all()
    
    # Buscar tags do banco de dados
    tags = KnowledgeTag.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).order_by(KnowledgeTag.display_order).all()
    
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
        tags = request.form.getlist('tags')
        tags = ','.join(tags)
        lawsuit_number = request.form.get('lawsuit_number', '')
        
        # Salvar arquivo
        if file:
            file_hash = _compute_file_hash(file)

            duplicate = KnowledgeBase.query.filter_by(
                law_firm_id=law_firm_id,
                file_hash=file_hash
            ).first()

            if duplicate:
                flash(
                    f'Upload bloqueado: o arquivo "{file.filename}" está duplicado (mesmo conteúdo já cadastrado).',
                    'error'
                )
                return redirect(request.url)

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
                file_hash=file_hash,
                description=description,
                category=category,
                tags=tags,
                lawsuit_number=lawsuit_number,
                processing_status='pending'
            )
            
            try:
                db.session.add(knowledge_file)
                db.session.commit()

                flash(
                    f'Arquivo "{filename}" adicionado com sucesso e está aguardando processamento.',
                    'success'
                )
                
                return redirect(url_for('knowledge_base.list'))
            except Exception as e:
                db.session.rollback()
                # Remover arquivo em caso de erro, tags=tags
                if os.path.exists(file_path):
                    os.remove(file_path)
                flash(f'Erro ao salvar arquivo no banco de dados: {str(e)}', 'error')
                return redirect(request.url)
    
    return render_template('knowledge_base/upload.html', categories=categories)


@knowledge_base_bp.route('/upload-multiple', methods=['GET', 'POST'])
def upload_multiple():
    """Permite fazer upload de múltiplos arquivos (máximo 10) para a base de conhecimento"""
    law_firm_id = get_current_law_firm_id()
    user_id = get_current_user_id()

    if not law_firm_id or not user_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))

    categories = KnowledgeCategory.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).order_by(KnowledgeCategory.display_order).all()

    if request.method == 'POST':
        uploaded_files = request.files.getlist('files') if 'files' in request.files else []
        uploaded_files = [
            file for file in uploaded_files
            if file and file.filename and file.filename.strip()
        ]

        if not uploaded_files:
            flash('Nenhum arquivo foi selecionado.', 'error')
            return redirect(request.url)

        if len(uploaded_files) > 10:
            flash('Você pode enviar no máximo 10 arquivos por vez.', 'error')
            return redirect(request.url)

        description = request.form.get('description', '').strip()
        category = request.form.get('category', '').strip()
        lawsuit_number = request.form.get('lawsuit_number', '').strip()

        tags_text = request.form.get('tags', '').strip()
        tags_list = [tag.strip() for tag in tags_text.split(',') if tag.strip()]
        tags = ','.join(tags_list)

        allowed_extensions = {'pdf', 'doc', 'docx', 'txt', 'odt', 'rtf'}
        invalid_files = []
        duplicate_files = []
        seen_hashes_in_batch = set()

        for file in uploaded_files:
            ext = os.path.splitext(file.filename)[1].lower().lstrip('.')
            if ext not in allowed_extensions:
                invalid_files.append(file.filename)
                continue

            file_hash = _compute_file_hash(file)

            # Duplicado dentro do próprio lote
            if file_hash in seen_hashes_in_batch:
                duplicate_files.append(file.filename)
                continue

            seen_hashes_in_batch.add(file_hash)

            # Duplicado já existente no banco
            existing_duplicate = KnowledgeBase.query.filter_by(
                law_firm_id=law_firm_id,
                file_hash=file_hash
            ).first()
            if existing_duplicate:
                duplicate_files.append(file.filename)

        if invalid_files:
            flash(
                f'Formato não permitido: {", ".join(invalid_files)}. Formatos aceitos: PDF, DOC, DOCX, TXT, ODT, RTF.',
                'error'
            )
            return redirect(request.url)

        if duplicate_files:
            flash(
                f'Upload bloqueado: arquivo(s) duplicado(s) detectado(s): {", ".join(duplicate_files)}.',
                'error'
            )
            return redirect(request.url)

        upload_dir = f"uploads/knowledge_base/{law_firm_id}"
        os.makedirs(upload_dir, exist_ok=True)

        saved_paths = []
        saved_filenames = []

        try:
            for file in uploaded_files:
                file_hash = _compute_file_hash(file)
                filename = secure_filename(file.filename)

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                name, ext = os.path.splitext(filename)
                filename_with_timestamp = f"{name}_{timestamp}{ext}"

                file_path = os.path.join(upload_dir, filename_with_timestamp)
                file.save(file_path)

                file_size = os.path.getsize(file_path)
                file_type = ext.lstrip('.').upper() if ext else 'DESCONHECIDO'

                knowledge_file = KnowledgeBase(
                    user_id=user_id,
                    law_firm_id=law_firm_id,
                    original_filename=filename,
                    file_path=file_path,
                    file_size=file_size,
                    file_type=file_type,
                    file_hash=file_hash,
                    description=description,
                    category=category,
                    tags=tags,
                    lawsuit_number=lawsuit_number,
                    processing_status='pending'
                )

                db.session.add(knowledge_file)
                saved_paths.append(file_path)
                saved_filenames.append(filename)

            db.session.commit()
            flash(
                f'{len(saved_filenames)} arquivo(s) adicionado(s) com sucesso e aguardando processamento.',
                'success'
            )
            return redirect(url_for('knowledge_base.list'))

        except Exception as e:
            db.session.rollback()
            for path in saved_paths:
                if os.path.exists(path):
                    os.remove(path)
            flash(f'Erro ao salvar arquivos: {str(e)}', 'error')
            return redirect(request.url)

    return render_template('knowledge_base/upload_multiple.html', categories=categories)

# ROTAS PARA GERENCIAR CATEGORIAS

@knowledge_base_bp.route('/categories')
def categories_list():
    """Lista todas as categorias da base de conhecimento"""
    law_firm_id = get_current_law_firm_id()
    if not law_firm_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))
    
    categories = KnowledgeCategory.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(KnowledgeCategory.display_order).all()
    
    return render_template('knowledge_base/categories.html', categories=categories)

@knowledge_base_bp.route('/categories/create', methods=['POST'])
def category_create():
    """Cria uma nova categoria"""
    law_firm_id = get_current_law_firm_id()
    if not law_firm_id:
        return jsonify({'success': False, 'error': 'Não autenticado'}), 401
    
    try:
        name = request.form.get('name', '').strip()
        icon = request.form.get('icon', '').strip()
        description = request.form.get('description', '').strip()
        color = request.form.get('color', '#007bff')
        
        if not name:
            return jsonify({'success': False, 'error': 'Nome é obrigatório'}), 400
        
        # Verificar se já existe categoria com este nome
        existing = KnowledgeCategory.query.filter_by(
            law_firm_id=law_firm_id,
            name=name
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Já existe uma categoria com este nome'}), 400
        
        # Obter próxima ordem de exibição
        max_order = db.session.query(db.func.max(KnowledgeCategory.display_order)).filter_by(
            law_firm_id=law_firm_id
        ).scalar() or 0
        
        category = KnowledgeCategory(
            law_firm_id=law_firm_id,
            name=name,
            icon=icon,
            description=description,
            color=color,
            display_order=max_order + 1,
            is_active=True
        )
        
        db.session.add(category)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Categoria criada com sucesso'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@knowledge_base_bp.route('/categories/<int:category_id>/update', methods=['POST'])
def category_update(category_id):
    """Atualiza uma categoria existente"""
    law_firm_id = get_current_law_firm_id()
    if not law_firm_id:
        return jsonify({'success': False, 'error': 'Não autenticado'}), 401
    
    try:
        category = KnowledgeCategory.query.filter_by(
            id=category_id,
            law_firm_id=law_firm_id
        ).first()
        
        if not category:
            return jsonify({'success': False, 'error': 'Categoria não encontrada'}), 404
        
        name = request.form.get('name', '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'Nome é obrigatório'}), 400
        
        # Verificar duplicação de nome
        existing = KnowledgeCategory.query.filter(
            KnowledgeCategory.law_firm_id == law_firm_id,
            KnowledgeCategory.name == name,
            KnowledgeCategory.id != category_id
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Já existe uma categoria com este nome'}), 400
        
        category.name = name
        category.icon = request.form.get('icon', '').strip()
        category.description = request.form.get('description', '').strip()
        category.color = request.form.get('color', '#007bff')
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Categoria atualizada com sucesso'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@knowledge_base_bp.route('/categories/<int:category_id>/delete', methods=['POST'])
def category_delete(category_id):
    """Desativa uma categoria"""
    law_firm_id = get_current_law_firm_id()
    if not law_firm_id:
        return jsonify({'success': False, 'error': 'Não autenticado'}), 401
    
    try:
        category = KnowledgeCategory.query.filter_by(
            id=category_id,
            law_firm_id=law_firm_id
        ).first()
        
        if not category:
            return jsonify({'success': False, 'error': 'Categoria não encontrada'}), 404
        
        category.is_active = False
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Categoria desativada com sucesso'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# ROTAS PARA GERENCIAR TAGS

@knowledge_base_bp.route('/tags')
def tags_list():
    """Lista todas as tags da base de conhecimento"""
    law_firm_id = get_current_law_firm_id()
    if not law_firm_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))
    
    tags = KnowledgeTag.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(KnowledgeTag.display_order).all()
    
    return render_template('knowledge_base/tags.html', tags=tags)

@knowledge_base_bp.route('/tags/create', methods=['POST'])
def tag_create():
    """Cria uma nova tag"""
    law_firm_id = get_current_law_firm_id()
    if not law_firm_id:
        return jsonify({'success': False, 'error': 'Não autenticado'}), 401
    
    try:
        name = request.form.get('name', '').strip()
        icon = request.form.get('icon', '').strip()
        description = request.form.get('description', '').strip()
        color = request.form.get('color', '#007bff')
        
        if not name:
            return jsonify({'success': False, 'error': 'Nome é obrigatório'}), 400
        
        # Verificar se já existe tag com este nome
        existing = KnowledgeTag.query.filter_by(
            law_firm_id=law_firm_id,
            name=name
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Já existe uma tag com este nome'}), 400
        
        # Obter próxima ordem de exibição
        max_order = db.session.query(db.func.max(KnowledgeTag.display_order)).filter_by(
            law_firm_id=law_firm_id
        ).scalar() or 0
        
        tag = KnowledgeTag(
            law_firm_id=law_firm_id,
            name=name,
            icon=icon,
            description=description,
            color=color,
            display_order=max_order + 1,
            is_active=True
        )
        
        db.session.add(tag)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Tag criada com sucesso'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@knowledge_base_bp.route('/tags/<int:tag_id>/update', methods=['POST'])
def tag_update(tag_id):
    """Atualiza uma tag existente"""
    law_firm_id = get_current_law_firm_id()
    if not law_firm_id:
        return jsonify({'success': False, 'error': 'Não autenticado'}), 401
    
    try:
        tag = KnowledgeTag.query.filter_by(
            id=tag_id,
            law_firm_id=law_firm_id
        ).first()
        
        if not tag:
            return jsonify({'success': False, 'error': 'Tag não encontrada'}), 404
        
        name = request.form.get('name', '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'Nome é obrigatório'}), 400
        
        # Verificar duplicação de nome
        existing = KnowledgeTag.query.filter(
            KnowledgeTag.law_firm_id == law_firm_id,
            KnowledgeTag.name == name,
            KnowledgeTag.id != tag_id
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Já existe uma tag com este nome'}), 400
        
        tag.name = name
        tag.icon = request.form.get('icon', '').strip()
        tag.description = request.form.get('description', '').strip()
        tag.color = request.form.get('color', '#007bff')
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Tag atualizada com sucesso'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@knowledge_base_bp.route('/tags/<int:tag_id>/delete', methods=['POST'])
def tag_delete(tag_id):
    """Desativa uma tag"""
    law_firm_id = get_current_law_firm_id()
    if not law_firm_id:
        return jsonify({'success': False, 'error': 'Não autenticado'}), 401
    
    try:
        tag = KnowledgeTag.query.filter_by(
            id=tag_id,
            law_firm_id=law_firm_id
        ).first()
        
        if not tag:
            return jsonify({'success': False, 'error': 'Tag não encontrada'}), 404
        
        tag.is_active = False
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Tag desativada com sucesso'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

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
    
    # Buscar resumo existente
    summary = KnowledgeSummary.query.filter_by(knowledge_base_id=file_id).first()
    
    return render_template('knowledge_base/details.html', file=file, summary=summary)


@knowledge_base_bp.route('/<int:file_id>/generate-summary', methods=['POST'])
def generate_summary(file_id):
    """Gera um resumo para o arquivo usando IA"""
    law_firm_id = get_current_law_firm_id()
    user_id = get_current_user_id()
    
    if not law_firm_id or not user_id:
        return jsonify({'success': False, 'error': 'Não autorizado'}), 401
    
    # Verificar se o arquivo existe
    file = KnowledgeBase.query.filter_by(
        id=file_id,
        law_firm_id=law_firm_id,
        is_active=True
    ).first()
    
    if not file:
        return jsonify({'success': False, 'error': 'Arquivo não encontrado'}), 404
    
    agent = AgentDocumentSummary()

    # O agent já retorna um dict
    summary_payload = agent.summarizeDocument(file_path=file.file_path)
    
    # Extrair lawsuit_numbers do resumo e preencher na tabela se vazio
    lawsuit_numbers = []
    if summary_payload and isinstance(summary_payload, dict):
        lawsuit_numbers_raw = summary_payload.get('lawsuit_numbers', [])
        
        # Validar e limpar lawsuit_numbers
        if lawsuit_numbers_raw:
            if isinstance(lawsuit_numbers_raw, builtins.list):
                # Filtrar apenas strings não vazias
                lawsuit_numbers = [str(num).strip() for num in lawsuit_numbers_raw if num and str(num).strip()]
            elif isinstance(lawsuit_numbers_raw, str) and lawsuit_numbers_raw.strip():
                lawsuit_numbers = [lawsuit_numbers_raw.strip()]
                
        # Se encontrou números de processo válidos e o arquivo não tem preenchido
        if lawsuit_numbers and (not file.lawsuit_number or file.lawsuit_number.strip() == ''):
            try:
                file.lawsuit_number = ', '.join(lawsuit_numbers)
                print(f"Atribuído lawsuit_number ao arquivo: {file.lawsuit_number}")
            except Exception as e:
                print(f"Erro ao atribuir lawsuit_number: {str(e)}")
    
    # Verificar se já existe resumo
    print(f"Verificando existência de resumo para o arquivo ID {file_id}")
    existing_summary = KnowledgeSummary.query.filter_by(knowledge_base_id=file_id).first()
    print(f"Resumo gerado para o arquivo ID {file_id}: {summary_payload}")
    if existing_summary:
        existing_summary.payload = summary_payload
        existing_summary.updated_at = datetime.utcnow()
    else:
        summary = KnowledgeSummary(
            knowledge_base_id=file_id,
            payload=summary_payload
        )
        db.session.add(summary)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Resumo gerado com sucesso' if not lawsuit_numbers else f'Resumo gerado e {len(lawsuit_numbers) if isinstance(lawsuit_numbers, builtins.list) else 1} número(s) de processo adicionado(s)'
    })

@knowledge_base_bp.route('/<int:file_id>/get-summary', methods=['GET'])
def get_summary(file_id):
    """Retorna o resumo de um arquivo"""
    law_firm_id = get_current_law_firm_id()
    
    if not law_firm_id:
        return jsonify({'success': False, 'error': 'Não autorizado'}), 401
    
    # Verificar se o arquivo existe
    file = KnowledgeBase.query.filter_by(
        id=file_id,
        law_firm_id=law_firm_id,
        is_active=True
    ).first()
    
    if not file:
        return jsonify({'success': False, 'error': 'Arquivo não encontrado'}), 404
    
    # Buscar resumo
    summary = KnowledgeSummary.query.filter_by(knowledge_base_id=file_id).first()
    
    if not summary:
        return jsonify({'success': False, 'error': 'Resumo não encontrado'}), 404
    
    # Converter para dicionário se payload for uma string JSON
    import json as json_lib
    payload = summary.payload
    if isinstance(payload, str):
        try:
            payload = json_lib.loads(payload)
        except:
            payload = {'content': payload}
    
    return jsonify({
        'success': True,
        'summary': {
            'id': summary.id,
            'payload': payload,
            'created_at': summary.created_at.isoformat() if summary.created_at else None,
            'updated_at': summary.updated_at.isoformat() if summary.updated_at else None
        }
    })


@knowledge_base_bp.route('/<int:file_id>/view')
def view(file_id):
    """Visualiza um arquivo da base de conhecimento no navegador"""
    law_firm_id = get_current_law_firm_id()

    if not law_firm_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))

    file = KnowledgeBase.query.filter_by(
        id=file_id,
        law_firm_id=law_firm_id,
        is_active=True
    ).first()

    if not file:
        flash('Arquivo não encontrado.', 'error')
        return redirect(url_for('knowledge_base.list'))

    if not os.path.exists(file.file_path):
        flash('Arquivo não encontrado no servidor.', 'error')
        return redirect(url_for('knowledge_base.list'))

    try:
        return send_file(file.file_path, as_attachment=False, mimetype='application/pdf')
    except Exception as e:
        flash(f'Erro ao visualizar o arquivo: {str(e)}', 'error')
        return redirect(url_for('knowledge_base.list'))


@knowledge_base_bp.route('/<int:file_id>/view-docx')
def view_docx(file_id):
    """Visualiza um arquivo DOCX da base de conhecimento em uma nova página"""
    law_firm_id = get_current_law_firm_id()

    if not law_firm_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))

    file = KnowledgeBase.query.filter_by(
        id=file_id,
        law_firm_id=law_firm_id,
        is_active=True
    ).first()

    if not file:
        flash('Arquivo não encontrado.', 'error')
        return redirect(url_for('knowledge_base.list'))

    if not os.path.exists(file.file_path):
        flash('Arquivo não encontrado no servidor.', 'error')
        return redirect(url_for('knowledge_base.list'))

    if file.file_type != 'DOCX':
        flash('Visualização disponível apenas para arquivos DOCX.', 'error')
        return redirect(url_for('knowledge_base.details', file_id=file_id))

    return render_template('knowledge_base/docx_viewer.html', file=file)

@knowledge_base_bp.route('/<int:file_id>/download')
def download(file_id):
    """Faz o download de um arquivo da base de conhecimento"""
    law_firm_id = get_current_law_firm_id()

    if not law_firm_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))

    file = KnowledgeBase.query.filter_by(
        id=file_id,
        law_firm_id=law_firm_id,
        is_active=True
    ).first()

    if not file:
        flash('Arquivo não encontrado.', 'error')
        return redirect(url_for('knowledge_base.list'))

    if not os.path.exists(file.file_path):
        flash('Arquivo não encontrado no servidor.', 'error')
        return redirect(url_for('knowledge_base.list'))

    try:
        return send_file(file.file_path, as_attachment=True, download_name=file.original_filename)
    except TypeError:
        return send_file(file.file_path, as_attachment=True, attachment_filename=file.original_filename)
    except Exception as e:
        flash(f'Erro ao baixar o arquivo: {str(e)}', 'error')
        return redirect(url_for('knowledge_base.list'))

@knowledge_base_bp.route('/download-by-name')
def download_by_name():
    """Baixar arquivo da base de conhecimento por nome do arquivo"""
    law_firm_id = get_current_law_firm_id()
    
    if not law_firm_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))

    filename = request.args.get('filename', '')
    
    if not filename:
        flash('Nome do arquivo não especificado.', 'error')
        return redirect(url_for('knowledge_base.list'))

    # Busca pelo nome original do arquivo
    file = KnowledgeBase.query.filter_by(
        original_filename=filename,
        law_firm_id=law_firm_id,
        is_active=True
    ).first()

    if not file:
        flash('Arquivo não encontrado.', 'error')
        return redirect(url_for('knowledge_base.list'))

    if not os.path.exists(file.file_path):
        flash('Arquivo não encontrado no servidor.', 'error')
        return redirect(url_for('knowledge_base.list'))

    try:
        return send_file(file.file_path, as_attachment=True, download_name=file.original_filename)
    except TypeError:
        return send_file(file.file_path, as_attachment=True, attachment_filename=file.original_filename)
    except Exception as e:
        flash(f'Erro ao baixar o arquivo: {str(e)}', 'error')
        return redirect(url_for('knowledge_base.list'))

@knowledge_base_bp.route('/search')
def search_chat():
    """Tela de chat para pesquisa na base de conhecimento"""
    law_firm_id = get_current_law_firm_id()
    
    if not law_firm_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))
    
    # Contar documentos na base de conhecimento
    total_documents = KnowledgeBase.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).count()
    
    return render_template('knowledge_base/search_chat.html', total_documents=total_documents)

@knowledge_base_bp.route('/api/ask', methods=['POST'])
def api_ask():
    """API para fazer perguntas à base de conhecimento"""
    law_firm_id = get_current_law_firm_id()
    
    if not law_firm_id:
        return jsonify({'success': False, 'error': 'Não autorizado'}), 401
    
    data = request.get_json(silent=True) if request.is_json else None

    if data is not None:
        question = str(data.get('question', '')).strip()
        chat_id = data.get('chat_id')
        conversation_history = data.get('history', [])
        uploaded_files = []
    else:
        question = str(request.form.get('question', '')).strip()
        chat_id = request.form.get('chat_id')
        raw_history = request.form.get('history', '[]')
        try:
            conversation_history = json_lib.loads(raw_history) if raw_history else []
        except Exception:
            conversation_history = []
        uploaded_files = request.files.getlist('files')

    try:
        chat_id = int(chat_id) if chat_id not in (None, '', 'null') else None
    except (ValueError, TypeError):
        chat_id = None
    
    if not question:
        return jsonify({'success': False, 'error': 'Pergunta não pode estar vazia'}), 400
    
    try:
        user_id = get_current_user_id()
        attachments_context, attachments_file_ids = build_attachments_context(
            uploaded_files,
            law_firm_id=law_firm_id,
            user_id=user_id,
            question=question,
            history=conversation_history if conversation_history else None,
        )

        chat_session = None
        if chat_id:
            chat_session = KnowledgeChatSession.query.filter_by(
                id=chat_id,
                user_id=user_id,
                law_firm_id=law_firm_id,
                is_active=True,
            ).first()
            if not chat_session:
                return jsonify({'success': False, 'error': 'Chat não encontrado'}), 404

            # Se for o primeiro envio de um chat recém-criado, define título automático
            if (not chat_session.title or chat_session.title.strip().lower() == 'novo chat'):
                has_messages = KnowledgeChatHistory.query.filter_by(
                    chat_session_id=chat_session.id,
                    user_id=user_id,
                    law_firm_id=law_firm_id,
                ).first()
                if not has_messages:
                    chat_session.title = generate_chat_title_from_question(question)
                    db.session.commit()
        else:
            generated_title = generate_chat_title_from_question(question)
            chat_session = KnowledgeChatSession(
                user_id=user_id,
                law_firm_id=law_firm_id,
                title=generated_title,
            )
            db.session.add(chat_session)
            db.session.commit()
        
        # Inicializar o agente de consulta
        query_agent = KnowledgeQueryAgent()
        
        # Fazer a pergunta usando o método ask_with_llm com histórico
        result = query_agent.ask_with_llm(
            question=question,
            user_id=user_id,
            law_firm_id=law_firm_id,
            history=conversation_history if conversation_history else None,
            chat_session_id=chat_session.id,
            attachments_context=attachments_context,
            attachments_file_ids=attachments_file_ids,
            has_attachments=bool(uploaded_files),
        )
        
        return jsonify({
            'success': True,
            'answer': result['answer'],
            'sources': result['sources'],
            'sources_detail': result.get('sources_detail', []),
            'suggested_questions': result.get('suggested_questions', []),
            'history_id': result.get('history_id'),
            'chat_id': chat_session.id,
            'chat_title': chat_session.title,
        })
    except Exception as e:
        print(f"Erro ao processar pergunta: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Erro ao processar pergunta: {str(e)}'
        }), 500

@knowledge_base_bp.route('/api/history', methods=['GET'])
def api_history():
    """API para recuperar histórico de conversas do usuário"""
    law_firm_id = get_current_law_firm_id()
    user_id = get_current_user_id()
    
    if not law_firm_id or not user_id:
        return jsonify({'success': False, 'error': 'Não autorizado'}), 401
    
    try:
        chat_id = request.args.get('chat_id', type=int)
        
        # Buscar últimas 50 conversas do usuário
        limit = request.args.get('limit', 50, type=int)
        
        history_query = KnowledgeChatHistory.query.filter_by(
            user_id=user_id,
            law_firm_id=law_firm_id,
        )

        if chat_id:
            history_query = history_query.filter_by(chat_session_id=chat_id)

        history_entries = history_query.order_by(KnowledgeChatHistory.created_at.desc()).limit(limit).all()
        
        # Formatar para o frontend
        history_data = []
        for entry in reversed(history_entries):  # Inverter para mostrar do mais antigo ao mais recente
            sources_detail = []
            if entry.sources:
                try:
                    sources_list = json_lib.loads(entry.sources)
                    for source in sources_list:
                        sources_detail.append(source)
                except:
                    pass
            
            history_data.append({
                'id': entry.id,
                'question': entry.question,
                'answer': entry.answer,
                'sources': sources_detail,
                'created_at': entry.created_at.isoformat() if entry.created_at else None
            })
        
        return jsonify({
            'success': True,
            'history': history_data
        })
    except Exception as e:
        print(f"Erro ao recuperar histórico: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Erro ao recuperar histórico: {str(e)}'
        }), 500

@knowledge_base_bp.route('/api/clear-history', methods=['POST'])
def api_clear_history():
    """API para limpar histórico de conversas do usuário"""
    law_firm_id = get_current_law_firm_id()
    user_id = get_current_user_id()
    
    if not law_firm_id or not user_id:
        return jsonify({'success': False, 'error': 'Não autorizado'}), 401
    
    try:
        # Deletar histórico do usuário
        KnowledgeChatHistory.query.filter_by(
            user_id=user_id,
            law_firm_id=law_firm_id
        ).delete()

        KnowledgeChatSession.query.filter_by(
            user_id=user_id,
            law_firm_id=law_firm_id
        ).delete()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Histórico limpo com sucesso'
        })
    except Exception as e:
        print(f"Erro ao limpar histórico: {str(e)}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Erro ao limpar histórico: {str(e)}'
        }), 500


@knowledge_base_bp.route('/api/chats', methods=['GET'])
def api_chats_list():
    """Lista chats do usuário (estilo threads)."""
    law_firm_id = get_current_law_firm_id()
    user_id = get_current_user_id()

    if not law_firm_id or not user_id:
        return jsonify({'success': False, 'error': 'Não autorizado'}), 401

    try:
        chats = KnowledgeChatSession.query.filter_by(
            user_id=user_id,
            law_firm_id=law_firm_id,
            is_active=True,
        ).order_by(KnowledgeChatSession.updated_at.desc()).all()

        chats_data = []
        for chat in chats:
            last_message = KnowledgeChatHistory.query.filter_by(
                chat_session_id=chat.id,
                user_id=user_id,
                law_firm_id=law_firm_id,
            ).order_by(KnowledgeChatHistory.created_at.desc()).first()

            chat_title = (chat.title or '').strip()
            if (not chat_title or chat_title.lower() == 'novo chat') and last_message and last_message.question:
                chat_title = generate_chat_title_from_question(last_message.question)
            if not chat_title:
                chat_title = 'Novo chat'

            chats_data.append({
                'id': chat.id,
                'title': chat_title,
                'last_message': last_message.question if last_message else '',
                'updated_at': chat.updated_at.isoformat() if chat.updated_at else None,
                'created_at': chat.created_at.isoformat() if chat.created_at else None,
                'messages_count': len(chat.messages),
            })

        return jsonify({'success': True, 'chats': chats_data})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Erro ao listar chats: {str(e)}'}), 500


@knowledge_base_bp.route('/api/chats', methods=['POST'])
def api_chats_create():
    """Cria um novo chat."""
    law_firm_id = get_current_law_firm_id()
    user_id = get_current_user_id()

    if not law_firm_id or not user_id:
        return jsonify({'success': False, 'error': 'Não autorizado'}), 401

    try:
        data = request.get_json(silent=True) or {}
        title = (data.get('title') or '').strip()[:255] or 'Novo chat'

        chat = KnowledgeChatSession(
            user_id=user_id,
            law_firm_id=law_firm_id,
            title=title,
        )
        db.session.add(chat)
        db.session.commit()

        return jsonify({
            'success': True,
            'chat': {
                'id': chat.id,
                'title': chat.title,
                'updated_at': chat.updated_at.isoformat() if chat.updated_at else None,
                'created_at': chat.created_at.isoformat() if chat.created_at else None,
                'messages_count': 0,
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Erro ao criar chat: {str(e)}'}), 500


@knowledge_base_bp.route('/api/chats/<int:chat_id>/history', methods=['GET'])
def api_chat_history(chat_id: int):
    """Recupera histórico de uma conversa específica."""
    law_firm_id = get_current_law_firm_id()
    user_id = get_current_user_id()

    if not law_firm_id or not user_id:
        return jsonify({'success': False, 'error': 'Não autorizado'}), 401

    try:
        chat = KnowledgeChatSession.query.filter_by(
            id=chat_id,
            user_id=user_id,
            law_firm_id=law_firm_id,
            is_active=True,
        ).first()
        if not chat:
            return jsonify({'success': False, 'error': 'Chat não encontrado'}), 404

        entries = KnowledgeChatHistory.query.filter_by(
            chat_session_id=chat.id,
            user_id=user_id,
            law_firm_id=law_firm_id,
        ).order_by(KnowledgeChatHistory.created_at.asc()).all()

        history_data = []
        for entry in entries:
            sources_detail = []
            if entry.sources:
                try:
                    sources_list = json_lib.loads(entry.sources)
                    for source in sources_list:
                        sources_detail.append(source)
                except Exception:
                    pass

            history_data.append({
                'id': entry.id,
                'question': entry.question,
                'answer': entry.answer,
                'sources': sources_detail,
                'created_at': entry.created_at.isoformat() if entry.created_at else None,
            })

        return jsonify({
            'success': True,
            'chat': {
                'id': chat.id,
                'title': chat.title,
            },
            'history': history_data,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Erro ao recuperar histórico do chat: {str(e)}'}), 500


@knowledge_base_bp.route('/api/chats/<int:chat_id>', methods=['DELETE'])
def api_chat_delete(chat_id: int):
    """Remove um chat e seu histórico."""
    law_firm_id = get_current_law_firm_id()
    user_id = get_current_user_id()

    if not law_firm_id or not user_id:
        return jsonify({'success': False, 'error': 'Não autorizado'}), 401

    try:
        chat = KnowledgeChatSession.query.filter_by(
            id=chat_id,
            user_id=user_id,
            law_firm_id=law_firm_id,
        ).first()

        if not chat:
            return jsonify({'success': False, 'error': 'Chat não encontrado'}), 404

        KnowledgeChatHistory.query.filter_by(
            chat_session_id=chat.id,
            user_id=user_id,
            law_firm_id=law_firm_id,
        ).delete()

        db.session.delete(chat)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Chat removido com sucesso'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Erro ao remover chat: {str(e)}'}), 500


@knowledge_base_bp.route('/intelligent-search', methods=['GET', 'POST'])
def intelligent_search():
    """Pesquisa Inteligente - Busca semântica no Qdrant com resultados detalhados"""
    law_firm_id = get_current_law_firm_id()
    user_id = get_current_user_id()
    
    if not law_firm_id or not user_id:
        flash('Você precisa estar logado para acessar esta página.', 'error')
        return redirect(url_for('auth.login'))
    
    # Contar documentos na base de conhecimento
    total_documents = KnowledgeBase.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).count()
    
    search_query = ''
    results = []
    grouped_results = []
    search_performed = False
    
    if request.method == 'POST':
        search_query = request.form.get('query', '').strip()
        
        if search_query:
            try:
                # Inicializar o agente de consulta
                query_agent = KnowledgeQueryAgent()
                
                # Fazer a busca vetorial diretamente
                search_data = query_agent.ask_knowledge_base(search_query, history=None, limit=50)
                
                # Processar os resultados
                if search_data and search_data.get('results') and search_data['results'].points:
                    query_normalized = normalize_for_match(search_query)
                    name_query = looks_like_name_query(search_query)
                    query_tokens = name_tokens(search_query)

                    for idx, point in enumerate(search_data['results'].points):
                        payload = point.payload
                        base_score = float(point.score or 0)
                        
                        # Buscar informações do arquivo no banco
                        file_info = None
                        if 'file_id' in payload and payload['file_id']:
                            file_info = KnowledgeBase.query.filter_by(
                                id=payload['file_id'],
                                law_firm_id=law_firm_id
                            ).first()
                        
                        # Obter o texto e aplicar highlight
                        original_text = payload.get('text', '')
                        highlighted_text = highlight_search_terms(original_text, search_query)

                        source_name = payload.get('source', '') or ''
                        description_text = payload.get('description', '') or ''
                        candidate_text = f"{original_text} {source_name} {description_text}"
                        candidate_normalized = normalize_for_match(candidate_text)

                        has_literal_match = (
                            bool(query_normalized) and query_normalized in candidate_normalized
                        )

                        adjusted_score = base_score
                        if has_literal_match:
                            adjusted_score += 0.30 if name_query else 0.08

                        if name_query and query_tokens:
                            matched_tokens = sum(1 for token in query_tokens if token in candidate_normalized)
                            token_coverage = matched_tokens / len(query_tokens)

                            adjusted_score += 0.22 * token_coverage
                            if token_coverage >= 0.95:
                                adjusted_score += 0.10
                            elif token_coverage >= 0.75:
                                adjusted_score += 0.05

                        adjusted_score = min(adjusted_score, 1.0)
                        if adjusted_score <= 0.30:
                            continue
                        
                        result_item = {
                            'rank': idx + 1,
                            'text': original_text,  # Texto original sem HTML
                            'highlighted_text': highlighted_text,  # Texto com highlight HTML
                            'source': payload.get('source', 'Documento sem nome'),
                            'page': payload.get('page'),
                            'lawsuit_number': payload.get('lawsuit_number'),
                            'category': payload.get('category'),
                            'tags': payload.get('tags', '').split(',') if payload.get('tags') else [],
                            'score': adjusted_score,
                            'score_percent': round(adjusted_score * 100, 2),
                            'base_score': base_score,
                            'literal_match': has_literal_match,
                            'file_id': payload.get('file_id'),
                            'file_info': {
                                'original_filename': file_info.original_filename if file_info else None,
                                'description': file_info.description if file_info else None,
                                'file_type': file_info.file_type if file_info else None,
                            } if file_info else None
                        }
                        
                        results.append(result_item)

                    results.sort(key=lambda item: item['score'], reverse=True)
                    for position, item in enumerate(results, start=1):
                        item['rank'] = position

                    grouped_map = {}
                    grouped_keys = []
                    for item in results:
                        group_key = item.get('file_id') or item.get('source') or f"unknown-{item.get('rank')}"

                        if group_key not in grouped_map:
                            grouped_map[group_key] = {
                                'group_rank': item['rank'],
                                'file_id': item.get('file_id'),
                                'source': item.get('source'),
                                'file_info': item.get('file_info'),
                                'category': item.get('category'),
                                'lawsuit_number': item.get('lawsuit_number'),
                                'tags': [],
                                'score': item.get('score', 0),
                                'score_percent': item.get('score_percent', 0),
                                'snippets': []
                            }
                            grouped_keys.append(group_key)

                        group = grouped_map[group_key]
                        group['snippets'].append(item)

                        item_category = item.get('category')
                        if item_category and not group.get('category'):
                            group['category'] = item_category

                        item_lawsuit = item.get('lawsuit_number')
                        if item_lawsuit and not group.get('lawsuit_number'):
                            group['lawsuit_number'] = item_lawsuit

                        item_score = item.get('score', 0)
                        if item_score > group.get('score', 0):
                            group['score'] = item_score
                            group['score_percent'] = item.get('score_percent', round(item_score * 100, 2))
                            group['group_rank'] = item['rank']

                        for tag in item.get('tags', []):
                            normalized_tag = (tag or '').strip()
                            if normalized_tag and normalized_tag not in group['tags']:
                                group['tags'].append(normalized_tag)

                    grouped_results = [grouped_map[key] for key in grouped_keys]
                    grouped_results.sort(key=lambda group: group.get('score', 0), reverse=True)
                    for group_position, group in enumerate(grouped_results, start=1):
                        group['group_rank'] = group_position
                
                search_performed = True
                
                if not results:
                    flash('Nenhum resultado encontrado. Tente reformular sua busca.', 'info')
                    
            except Exception as e:
                flash(f'Erro ao realizar a busca: {str(e)}', 'error')
                print(f"Erro na pesquisa inteligente: {str(e)}")
    
    return render_template(
        'knowledge_base/intelligent_search.html',
        total_documents=total_documents,
        search_query=search_query,
        results=results,
        grouped_results=grouped_results,
        search_performed=search_performed
    )
