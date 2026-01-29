from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.models import db, KnowledgeBase, KnowledgeCategory, KnowledgeTag
from app.agents.knowledge_ingestor import KnowledgeIngestor
from datetime import datetime
from werkzeug.utils import secure_filename
from pathlib import Path
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
                tags=tags,
                lawsuit_number=lawsuit_number
            )
            
            try:
                db.session.add(knowledge_file)
                db.session.commit()
                
                # Processar arquivo com KnowledgeIngestor e inserir no Qdrant
                try:
                    print(f"Iniciando processamento do arquivo: {filename}")
                    ingestor = KnowledgeIngestor()
                    
                    # Processar arquivo e inserir no Qdrant
                    markdown_content = ingestor.process_file(
                        Path(file_path), 
                        source_name=filename,
                        category=category,
                        description=description,
                        tags=tags,
                        lawsuit_number=lawsuit_number,
                        file_id=knowledge_file.id
                    )
                    
                    if markdown_content:
                        print(f"Arquivo processado com sucesso: {filename}")
                        flash(
                            f'Arquivo "{filename}" adicionado com sucesso à base de conhecimento e processado pela IA!', 
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
                
                return redirect(url_for('knowledge_base.list'))
            except Exception as e:
                db.session.rollback()
                # Remover arquivo em caso de erro, tags=tags
                if os.path.exists(file_path):
                    os.remove(file_path)
                flash(f'Erro ao salvar arquivo no banco de dados: {str(e)}', 'error')
                return redirect(request.url)
    
    return render_template('knowledge_base/upload.html', categories=categories)

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
    
    return render_template('knowledge_base/details.html', file=file)


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
    
    data = request.get_json()
    question = data.get('question', '').strip()
    conversation_history = data.get('history', [])  # Histórico da conversa atual
    
    if not question:
        return jsonify({'success': False, 'error': 'Pergunta não pode estar vazia'}), 400
    
    try:
        user_id = get_current_user_id()
        
        # Inicializar o ingestor
        ingestor = KnowledgeIngestor()
        
        # Fazer a pergunta usando o método ask_with_llm com histórico
        result = ingestor.ask_with_llm(
            question=question,
            user_id=user_id,
            law_firm_id=law_firm_id,
            history=conversation_history if conversation_history else None
        )
        
        return jsonify({
            'success': True,
            'answer': result['answer'],
            'sources': result['sources'],
            'sources_detail': result.get('sources_detail', []),
            'history_id': result.get('history_id')
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
        from app.models import KnowledgeChatHistory
        import json as json_lib
        
        # Buscar últimas 50 conversas do usuário
        limit = request.args.get('limit', 50, type=int)
        
        history_entries = KnowledgeChatHistory.query.filter_by(
            user_id=user_id,
            law_firm_id=law_firm_id
        ).order_by(KnowledgeChatHistory.created_at.desc()).limit(limit).all()
        
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
        from app.models import KnowledgeChatHistory
        
        # Deletar histórico do usuário
        KnowledgeChatHistory.query.filter_by(
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
