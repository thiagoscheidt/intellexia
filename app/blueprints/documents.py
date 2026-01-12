from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.models import db, Document, Case, CaseBenefit, Petition, AiDocumentSummary
from app.agents.file_agent import FileAgent
from app.agents.agent_document_reader import AgentDocumentReader
from app.utils.document_utils import extract_text_from_docx, is_docx_file
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
import os

documents_bp = Blueprint('documents', __name__, url_prefix='/cases/<int:case_id>/documents')

def get_current_law_firm_id():
    return session.get('law_firm_id')

@documents_bp.route('/')
def case_documents_list(case_id):
    case = Case.query.get_or_404(case_id)
    documents = Document.query.filter_by(case_id=case_id).order_by(Document.uploaded_at.desc()).all()
    return render_template('cases/documents_list.html', case=case, case_id=case_id, documents=documents)

@documents_bp.route('/new', methods=['GET', 'POST'])
def case_document_new(case_id):
    from app.form import DocumentForm
    case = Case.query.get_or_404(case_id)
    form = DocumentForm()
    
    benefits = CaseBenefit.query.filter_by(case_id=case_id).all()
    form.related_benefit_id.choices = [(0, 'Nenhum')] + [(b.id, f"{b.benefit_number} - {b.insured_name}") for b in benefits]
    
    if form.validate_on_submit():
        file = form.file.data
        if file:
            filename = secure_filename(file.filename)
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
                ai_status='pending'
            )
            
            db.session.add(document)
            try:
                db.session.commit()
                
                if form.use_in_ai.data:
                    try:
                        document.ai_status = 'processing'
                        db.session.commit()
                        
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
                        
                        document.ai_summary = ai_summary
                        document.ai_processed_at = datetime.utcnow()
                        document.ai_status = 'completed'
                        db.session.commit()
                        
                        flash('Documento enviado e analisado com sucesso pela IA!', 'success')
                    except Exception as e:
                        document.ai_status = 'error'
                        document.ai_error_message = str(e)
                        db.session.commit()
                        flash(f'Documento enviado, mas houve erro na análise de IA: {str(e)}', 'warning')
                else:
                    flash('Documento enviado com sucesso!', 'success')
                
                return redirect(url_for('documents.case_documents_list', case_id=case_id))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao salvar documento: {str(e)}', 'danger')
        else:
            flash('Nenhum arquivo foi selecionado.', 'warning')
    
    return render_template('cases/document_form.html', form=form, case=case, case_id=case_id, title='Upload Documento')

@documents_bp.route('/<int:document_id>/view')
def case_document_view(case_id, document_id):
    case = Case.query.get_or_404(case_id)
    document = Document.query.get_or_404(document_id)
    
    if document.case_id != case_id:
        flash('Documento não pertence a este caso.', 'danger')
        return redirect(url_for('documents.case_documents_list', case_id=case_id))
    
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

@documents_bp.route('/<int:document_id>/delete', methods=['POST'])
def case_document_delete(case_id, document_id):
    document = Document.query.get_or_404(document_id)
    
    if document.case_id != case_id:
        flash('Documento não encontrado neste caso.', 'error')
        return redirect(url_for('documents.case_documents_list', case_id=case_id))
    
    try:
        if os.path.exists(document.file_path):
            os.remove(document.file_path)
        
        db.session.delete(document)
        db.session.commit()
        flash('Documento excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir documento: {str(e)}', 'danger')
    
    return redirect(url_for('documents.case_documents_list', case_id=case_id))

@documents_bp.route('/<int:document_id>/reprocess', methods=['POST'])
def case_document_reprocess(case_id, document_id):
    """Reprocessa um documento com a IA"""
    document = Document.query.get_or_404(document_id)
    
    if document.case_id != case_id:
        flash('Documento não encontrado neste caso.', 'error')
        return redirect(url_for('documents.case_documents_list', case_id=case_id))
    
    try:
        # Resetar status
        document.ai_status = 'processing'
        document.ai_error_message = None
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
        document.ai_summary = ai_summary
        document.ai_processed_at = datetime.utcnow()
        document.ai_status = 'completed'
        db.session.commit()
        
        flash('Documento reprocessado com sucesso!', 'success')
    except Exception as e:
        document.ai_status = 'error'
        document.ai_error_message = str(e)
        db.session.commit()
        flash(f'Erro ao reprocessar documento: {str(e)}', 'danger')
    
    return redirect(url_for('documents.case_document_view', case_id=case_id, document_id=document_id))
