from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.models import db, Petition, Case
from datetime import datetime
from werkzeug.utils import secure_filename
import os

petitions_bp = Blueprint('petitions', __name__, url_prefix='/cases/<int:case_id>/petitions')

def _extract_text_from_docx(document):
    """Extrai texto completo de um documento DOCX"""
    text_parts = []
    
    for paragraph in document.paragraphs:
        if paragraph.text.strip():
            text_parts.append(paragraph.text)
    
    for table in document.tables:
        for row in table.rows:
            row_text = []
            for cell in row.cells:
                cell_text = ' '.join([p.text for p in cell.paragraphs if p.text.strip()])
                if cell_text:
                    row_text.append(cell_text)
            if row_text:
                text_parts.append(' | '.join(row_text))
    
    return '\n\n'.join(text_parts)

@petitions_bp.route('/')
def case_petitions_list(case_id):
    """Lista todas as petições geradas para um caso"""
    case = Case.query.get_or_404(case_id)
    petitions = Petition.query.filter_by(case_id=case_id).order_by(Petition.version.desc()).all()
    return render_template('cases/petitions_list.html', case=case, petitions=petitions, case_id=case_id)

@petitions_bp.route('/generate', methods=['GET', 'POST'])
def case_petition_generate(case_id):
    """Gera uma nova petição com IA"""
    from app.models import CaseBenefit, Document
    case = Case.query.get_or_404(case_id)
    
    if request.method == 'POST':
        try:
            use_template = 'template_file' in request.files and request.files['template_file'].filename != ''
            template_file_id = None
            
            if use_template:
                file = request.files['template_file']
                filename = secure_filename(file.filename)
                
                allowed_extensions = {'.pdf', '.docx', '.doc', '.txt', '.md'}
                file_extension = os.path.splitext(filename)[1].lower()
                
                if file_extension not in allowed_extensions:
                    flash(f'Tipo de arquivo não suportado. Use: {", ".join(allowed_extensions)}', 'danger')
                    return redirect(url_for('petitions.case_petition_generate', case_id=case_id))
                
                temp_path = os.path.join('uploads', 'temp', filename)
                os.makedirs(os.path.dirname(temp_path), exist_ok=True)
                file.save(temp_path)
                
                from app.agents.file_agent import FileAgent
                file_agent = FileAgent()
                template_file_id = file_agent.upload_file(os.path.abspath(temp_path))
                
                os.remove(temp_path)
            
            last_petition = Petition.query.filter_by(case_id=case_id).order_by(Petition.version.desc()).first()
            next_version = (last_petition.version + 1) if last_petition else 1
            
            benefits = CaseBenefit.query.filter_by(case_id=case_id).all()
            documents = Document.query.filter_by(case_id=case_id, use_in_ai=True, ai_status='completed').all()
            
            context_summary = f"""
Contexto da Petição - Versão {next_version} {"(Com Modelo)" if use_template else "(Padrão)"}:
- Cliente: {case.client.name if case.client else 'Não informado'}
- Tipo de Caso: {case.case_type}
- Total de Benefícios: {len(benefits)}
- Total de Documentos Analisados: {len(documents)}
- Valor da Causa: R$ {case.value_cause if case.value_cause else 'Não informado'}
- Modelo Usado: {filename if use_template else 'Template padrão'}
- Sistema: Intellexia - Geração com IA v2.0
"""
            
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
            
            try:
                is_fap_case = case.case_type in ['fap_trajeto', 'fap_outros']
                
                if is_fap_case:
                    from agent_document_generator import AgentDocumentGenerator
                    agent = AgentDocumentGenerator()
                    
                    docx_document = agent.generate_fap_petition(case_id)
                    
                    petitions_folder = os.path.join('uploads', 'petitions', 'fap')
                    os.makedirs(petitions_folder, exist_ok=True)
                    
                    output_filename = f"peticao_caso_{case_id}_versao_{next_version}.docx"
                    output_path = os.path.join(petitions_folder, output_filename)
                    
                    docx_document.save(output_path)
                    
                    petition_content = _extract_text_from_docx(docx_document)
                    
                    template_name = agent._select_template_by_fap_reason(case.fap_reason).split('/')[-1]
                    flash(f'Petição FAP gerada com sucesso usando template: {template_name}!', 'success')
                else:
                    from app.agents.agent_text_generator import AgentTextGenerator
                    agent = AgentTextGenerator()
                    
                    case_data = {
                        'title': case.title,
                        'client_name': case.client.name if case.client else '',
                        'client_cnpj': case.client.cnpj if case.client else '',
                        'case_type': case.case_type,
                        'value_cause': str(case.value_cause) if case.value_cause else '',
                        'facts_summary': case.facts_summary or '',
                        'thesis_summary': case.thesis_summary or '',
                        'court_name': case.court.vara_name if case.court else '',
                        'court_city': case.court.city if case.court else '',
                        'court_state': case.court.state if case.court else ''
                    }
                    
                    benefits_data = []
                    for benefit in benefits:
                        benefits_data.append({
                            'benefit_number': benefit.benefit_number,
                            'benefit_type': benefit.benefit_type,
                            'insured_name': benefit.insured_name,
                            'insured_nit': benefit.insured_nit,
                            'accident_date': str(benefit.accident_date) if benefit.accident_date else '',
                            'error_reason': benefit.error_reason
                        })
                    
                    documents_data = []
                    for doc in documents:
                        documents_data.append({
                            'original_filename': doc.original_filename,
                            'ai_summary': doc.ai_summary or ''
                        })
                    
                    if use_template and template_file_id:
                        agent.set_template_file(template_file_id)
                        petition_content = agent.generate_petition_with_template(case_data, benefits_data, documents_data)
                        flash('Petição gerada com sucesso usando modelo personalizado!', 'success')
                    else:
                        petition_content = agent.generate_simple_petition(case_data, benefits_data)
                        flash('Petição gerada com sucesso usando template padrão!', 'success')
                
                petition.content = petition_content
                petition.status = 'completed'
                petition.generated_at = datetime.utcnow()
                
                if is_fap_case:
                    petition.file_path = output_path
                
                db.session.commit()
                
                return redirect(url_for('petitions.case_petition_view', case_id=case_id, petition_id=petition.id))
                
            except Exception as e:
                petition.status = 'error'
                petition.error_message = str(e)
                db.session.commit()
                flash(f'Erro ao gerar petição: {str(e)}', 'danger')
                
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar petição: {str(e)}', 'danger')
    
    from app.models import CaseBenefit, Document
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

@petitions_bp.route('/<int:petition_id>')
def case_petition_view(case_id, petition_id):
    """Visualiza uma petição específica"""
    case = Case.query.get_or_404(case_id)
    petition = Petition.query.get_or_404(petition_id)
    
    if petition.case_id != case_id:
        flash('Petição não pertence a este caso.', 'danger')
        return redirect(url_for('petitions.case_petitions_list', case_id=case_id))
    
    return render_template(
        'cases/petition_view.html',
        case=case,
        petition=petition,
        case_id=case_id
    )

@petitions_bp.route('/<int:petition_id>/delete', methods=['POST'])
def case_petition_delete(case_id, petition_id):
    """Exclui uma petição"""
    petition = Petition.query.get_or_404(petition_id)
    
    if petition.case_id != case_id:
        flash('Petição não pertence a este caso.', 'danger')
        return redirect(url_for('petitions.case_petitions_list', case_id=case_id))
    
    try:
        if petition.file_path and os.path.exists(petition.file_path):
            os.remove(petition.file_path)
        
        db.session.delete(petition)
        db.session.commit()
        flash('Petição excluída com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir petição: {str(e)}', 'danger')
    
    return redirect(url_for('petitions.case_petitions_list', case_id=case_id))

@petitions_bp.route('/<int:petition_id>/download')
def case_petition_download(case_id, petition_id):
    """Faz download do arquivo DOCX da petição"""
    petition = Petition.query.get_or_404(petition_id)
    
    if petition.case_id != case_id:
        flash('Petição não pertence a este caso.', 'danger')
        return redirect(url_for('petitions.case_petitions_list', case_id=case_id))
    
    if not petition.file_path or not os.path.exists(petition.file_path):
        flash('Arquivo DOCX não encontrado para esta petição.', 'warning')
        return redirect(url_for('petitions.case_petition_view', case_id=case_id, petition_id=petition_id))
    
    return send_file(
        petition.file_path,
        as_attachment=True,
        download_name=f"peticao_caso_{case_id}_v{petition.version}.docx",
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
