from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from app.models import db, AiDocumentSummary
from app.agents.file_agent import FileAgent
from app.agents.agent_document_reader import AgentDocumentReader
from app.utils.document_utils import extract_text_from_docx, is_docx_file
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
import os

tools_bp = Blueprint('tools', __name__, url_prefix='/tools')

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

@tools_bp.route('/document-summary')
@require_law_firm
def tools_document_summary_list():
    """Lista todos os documentos enviados para resumo"""
    law_firm_id = get_current_law_firm_id()
    
    documents = AiDocumentSummary.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(AiDocumentSummary.uploaded_at.desc()).all()
    
    return render_template('tools/document_summary_list.html', documents=documents)

@tools_bp.route('/document-summary/upload', methods=['GET', 'POST'])
@require_law_firm
def tools_document_summary_upload():
    """Upload de documento para resumo por IA"""
    from app.form import AiDocumentSummaryForm
    
    form = AiDocumentSummaryForm()
    
    if form.validate_on_submit():
        file = form.file.data
        
        if file:
            try:
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                unique_filename = f"{timestamp}_{filename}"
                
                upload_dir = os.path.join('uploads', 'ai_summaries')
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, unique_filename)
                
                file.save(file_path)
                
                file_size = os.path.getsize(file_path)
                file_extension = os.path.splitext(filename)[1].lower().replace('.', '')
                
                document = AiDocumentSummary(
                    user_id=session.get('user_id'),
                    law_firm_id=get_current_law_firm_id(),
                    original_filename=filename,
                    file_path=file_path,
                    file_size=file_size,
                    file_type=file_extension.upper(),
                    status='pending'
                )
                
                db.session.add(document)
                db.session.commit()
                
                # Processar com IA imediatamente
                try:
                    document.status = 'processing'
                    db.session.commit()
                    
                    # Inicializar agente
                    doc_reader = AgentDocumentReader()
                    
                    # Verificar se é DOCX
                    if is_docx_file(file_path):
                        # Para DOCX: extrair texto e enviar diretamente
                        text_content = extract_text_from_docx(os.path.abspath(file_path))
                        ai_summary = doc_reader.analyze_document(text_content=text_content)
                    else:
                        # Para PDF e outros: usar file_id
                        file_agent = FileAgent()
                        file_id = file_agent.upload_file(os.path.abspath(file_path))
                        ai_summary = doc_reader.analyze_document(file_id=file_id)
                    
                    # Salvar resultado
                    document.summary_text = ai_summary
                    document.processed_at = datetime.utcnow()
                    document.status = 'completed'
                    db.session.commit()
                    
                    flash('Documento analisado com sucesso pela IA!', 'success')
                except Exception as e:
                    document.status = 'error'
                    document.error_message = str(e)
                    db.session.commit()
                    flash(f'Erro ao analisar documento: {str(e)}', 'danger')
                
                return redirect(url_for('tools.tools_document_summary_detail', document_id=document.id))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao enviar documento: {str(e)}', 'danger')
    
    return render_template('tools/document_summary_upload.html', form=form)

@tools_bp.route('/document-summary/<int:document_id>')
@require_law_firm
def tools_document_summary_detail(document_id):
    """Visualiza detalhes e resumo de um documento"""
    law_firm_id = get_current_law_firm_id()
    document = AiDocumentSummary.query.filter_by(
        id=document_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    return render_template('tools/document_summary_detail.html', document=document)

@tools_bp.route('/document-summary/<int:document_id>/delete', methods=['POST'])
@require_law_firm
def tools_document_summary_delete(document_id):
    """Exclui um documento de resumo"""
    law_firm_id = get_current_law_firm_id()
    document = AiDocumentSummary.query.filter_by(
        id=document_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    try:
        if document.file_path and os.path.exists(document.file_path):
            os.remove(document.file_path)
        
        db.session.delete(document)
        db.session.commit()
        
        flash('Documento excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir documento: {str(e)}', 'danger')
    
    return redirect(url_for('tools.tools_document_summary_list'))

@tools_bp.route('/document-summary/<int:document_id>/reprocess', methods=['POST'])
@require_law_firm
def tools_document_summary_reprocess(document_id):
    """Reprocessa um documento com a IA"""
    law_firm_id = get_current_law_firm_id()
    document = AiDocumentSummary.query.filter_by(
        id=document_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    try:
        # Resetar status
        document.status = 'processing'
        document.error_message = None
        db.session.commit()
        
        # Processar com IA
        doc_reader = AgentDocumentReader()
        
        # Verificar se é DOCX
        if is_docx_file(document.file_path):
            # Para DOCX: extrair texto e enviar diretamente
            text_content = extract_text_from_docx(os.path.abspath(document.file_path))
            ai_summary = doc_reader.analyze_document(text_content=text_content)
        else:
            # Para PDF e outros: usar file_id
            file_agent = FileAgent()
            file_id = file_agent.upload_file(os.path.abspath(document.file_path))
            ai_summary = doc_reader.analyze_document(file_id=file_id)
        
        # Atualizar documento
        document.summary_text = ai_summary
        document.processed_at = datetime.utcnow()
        document.status = 'completed'
        db.session.commit()
        
        flash('Documento reprocessado com sucesso!', 'success')
    except Exception as e:
        document.status = 'error'
        document.error_message = str(e)
        db.session.commit()
        flash(f'Erro ao reprocessar documento: {str(e)}', 'danger')
    
    return redirect(url_for('tools.tools_document_summary_detail', document_id=document_id))
