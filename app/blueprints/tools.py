from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify, send_file
from rich import print
from app.models import (
    db,
    AiDocumentSummary,
    JudicialSentenceAnalysis,
    JudicialAppeal,
    JudicialProcess,
    JudicialDocument,
)
from app.agents.core.file_agent import FileAgent
from app.agents.document_processing.agent_document_reader import AgentDocumentReader
from app.utils.document_utils import extract_text_from_docx, is_docx_file
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
import os
import unicodedata

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


# ========================
# Ferramentas DataJud - Pesquisa de Processos
# ========================

@tools_bp.route('/datajud', methods=['GET', 'POST'])
@require_law_firm
def datajud_search():
    """
    Ferramentas de busca na API DataJud - Consulta de processos judiciais
    """
    from app.services.data_jud_api import DataJudAPI
    from app.services.sgt_tpu_service import obter_assuntos_tpu, SgtTpuService
    
    resultado = None
    processos = []
    total_resultados = 0
    erro = None
    tempo_busca = 0
    
    # Dados para os selects
    tribunais = [
        ('STF', 'STF - Supremo Tribunal Federal'),
        ('STJ', 'STJ - Superior Tribunal de Justiça'),
        ('TST', 'TST - Tribunal Superior do Trabalho'),
        ('TSE', 'TSE - Tribunal Superior Eleitoral'),
        ('TRF1', 'TRF1 - 1ª Região'),
        ('TRF2', 'TRF2 - 2ª Região'),
        ('TRF3', 'TRF3 - 3ª Região'),
        ('TRF4', 'TRF4 - 4ª Região'),
        ('TRF5', 'TRF5 - 5ª Região'),
        ('TRF6', 'TRF6 - 6ª Região'),
        ('TJSP', 'TJSP - Tribunal de Justiça de SP'),
        ('TJRJ', 'TJRJ - Tribunal de Justiça do RJ'),
        ('TJMG', 'TJMG - Tribunal de Justiça de MG'),
        ('TJRS', 'TJRS - Tribunal de Justiça do RS'),
        ('TJPR', 'TJPR - Tribunal de Justiça do PR'),
        ('TJBA', 'TJBA - Tribunal de Justiça da BA'),
        ('TJCE', 'TJCE - Tribunal de Justiça do CE'),
        ('TJPE', 'TJPE - Tribunal de Justiça de PE'),
        ('TJGO', 'TJGO - Tribunal de Justiça de GO'),
        ('TJDFT', 'TJDFT - Tribunal de Justiça do DF'),
    ]
    assuntos = []
    classes = []
    try:
        service = SgtTpuService()
        assuntos = service.obter_assuntos_tpu()
        classes = service.obter_classes_tpu()
    except Exception:
        assuntos = []
        classes = []

    
    if request.method == 'POST':
        try:
            api = DataJudAPI()
            tipo_busca = request.form.get('tipo_busca', 'numero')
            
            if tipo_busca == 'numero':
                # Busca por número de processo
                numero_processo = request.form.get('numero_processo', '').strip()
                tribunal = request.form.get('tribunal', '').strip()
                
                if not numero_processo or not tribunal:
                    erro = "Preencha o número do processo e selecione um tribunal."
                    return render_template(
                        'tools/datajud_search.html',
                        tribunais=tribunais,
                        assuntos=assuntos,
                        classes=classes,
                        erro=erro,
                        tipo_busca=tipo_busca
                    )
                
                resultado = api.buscar_por_numero_processo(
                    numero_processo=numero_processo,
                    tribunal=tribunal,
                    size=20
                )
            
            elif tipo_busca == 'classe':
                # Busca por classe e órgão
                codigo_classe = request.form.get('codigo_classe', '').strip()
                tribunal = request.form.get('tribunal', '').strip()
                
                if not codigo_classe or not tribunal:
                    erro = "Preencha o código da classe e selecione um tribunal."
                    return render_template(
                        'tools/datajud_search.html',
                        tribunais=tribunais,
                        assuntos=assuntos,
                        classes=classes,
                        erro=erro,
                        tipo_busca=tipo_busca
                    )
                
                try:
                    codigo_classe = int(codigo_classe)
                except ValueError:
                    erro = "Código de classe deve ser um número."
                    return render_template(
                        'tools/datajud_search.html',
                        tribunais=tribunais,
                        assuntos=assuntos,
                        classes=classes,
                        erro=erro,
                        tipo_busca=tipo_busca
                    )
                
                resultado = api.buscar_por_classe_e_orgao(
                    codigo_classe=codigo_classe,
                    codigo_orgao=0,
                    tribunal=tribunal,
                    size=20
                )
            
            elif tipo_busca == 'assunto':
                # Busca por assunto
                codigo_assunto = request.form.get('codigo_assunto', '').strip()
                tribunal = request.form.get('tribunal', '').strip()
                
                if not codigo_assunto or not tribunal:
                    erro = "Preencha o código do assunto e selecione um tribunal."
                    return render_template(
                        'tools/datajud_search.html',
                        tribunais=tribunais,
                        assuntos=assuntos,
                        classes=classes,
                        erro=erro,
                        tipo_busca=tipo_busca
                    )
                
                try:
                    codigo_assunto = int(codigo_assunto)
                except ValueError:
                    erro = "Código do assunto deve ser um número."
                    return render_template(
                        'tools/datajud_search.html',
                        tribunais=tribunais,
                        assuntos=assuntos,
                        classes=classes,
                        erro=erro,
                        tipo_busca=tipo_busca
                    )
                
                resultado = api.buscar_por_assunto(
                    codigo_assunto=codigo_assunto,
                    tribunal=tribunal,
                    size=20
                )
            
            # Processar resultado
            if resultado.get('error'):
                erro = f"Erro na busca: {resultado.get('message')}"
            else:
                tempo_busca = resultado.get('took', 0)
                total_resultados = api.obter_total_resultados(resultado)
                processos = api.extrair_processos(resultado)
        
        except Exception as e:
            erro = f"Erro ao buscar: {str(e)}"
    
    return render_template(
        'tools/datajud_search.html',
        tribunais=tribunais,
        resultado=resultado,
        processos=processos,
        total_resultados=total_resultados,
        tempo_busca=tempo_busca,
        assuntos=assuntos,
        classes=classes,
        erro=erro
    )


# ========================
# ANÁLISE DE SENTENÇA JUDICIAL
# ========================

@tools_bp.route('/sentence-analysis')
@require_law_firm
def judicial_sentence_analysis_list():
    """Lista todas as análises de sentenças judiciais"""
    law_firm_id = get_current_law_firm_id()
    sentences = JudicialSentenceAnalysis.query.filter_by(law_firm_id=law_firm_id).order_by(JudicialSentenceAnalysis.uploaded_at.desc()).all()
    return render_template('tools/sentence_analysis_list.html', sentences=sentences)


@tools_bp.route('/sentence-analysis/upload', methods=['GET', 'POST'])
@require_law_firm
def judicial_sentence_analysis_upload():
    """Seleciona um processo e enfileira suas sentenças para análise por IA."""
    from app.form import JudicialSentenceAnalysisForm

    def _normalize_doc_type(value: str) -> str:
        normalized = unicodedata.normalize('NFKD', str(value or '').strip().lower())
        return ''.join(ch for ch in normalized if not unicodedata.combining(ch))

    def _is_sentence_document(doc_type: str) -> bool:
        normalized = _normalize_doc_type(doc_type)
        return 'sentenca' in normalized or 'sentença' in normalized

    def _is_initial_petition_document(doc_type: str) -> bool:
        normalized = _normalize_doc_type(doc_type)
        return 'peticao' in normalized and 'inicial' in normalized

    def _resolve_existing_file_path(doc: JudicialDocument) -> str | None:
        """Tenta recuperar um caminho válido para o arquivo do documento."""
        current_path = str(doc.file_path or '').strip()
        if current_path and os.path.exists(current_path):
            return current_path

        if doc.knowledge_base and doc.knowledge_base.file_path:
            kb_path = str(doc.knowledge_base.file_path).strip()
            if kb_path and os.path.exists(kb_path):
                doc.file_path = kb_path
                return kb_path

        return None

    law_firm_id = get_current_law_firm_id()
    form = JudicialSentenceAnalysisForm()
    available_processes = JudicialProcess.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(JudicialProcess.created_at.desc()).all()

    form.process_id.choices = [
        (process.id, f"{process.process_number or 'Sem número'} - {process.title or 'Sem título'}")
        for process in available_processes
    ]

    if form.validate_on_submit():
        process = JudicialProcess.query.filter_by(
            id=form.process_id.data,
            law_firm_id=law_firm_id,
        ).first()

        if not process:
            flash('Processo não encontrado.', 'danger')
            return render_template('tools/sentence_analysis_upload.html', form=form)

        try:
            process_documents = JudicialDocument.query.filter_by(process_id=process.id).order_by(
                JudicialDocument.created_at.desc()
            ).all()

            sentence_docs = [doc for doc in process_documents if _is_sentence_document(doc.type)]
            petition_doc = next((doc for doc in process_documents if _is_initial_petition_document(doc.type)), None)

            if not sentence_docs:
                flash('Este processo não possui documentos do tipo sentença para análise.', 'warning')
                return render_template('tools/sentence_analysis_upload.html', form=form)

            queued = 0
            skipped = 0
            skipped_missing = 0
            skipped_existing = 0
            first_created_id = None

            for sentence_doc in sentence_docs:
                sentence_path = _resolve_existing_file_path(sentence_doc)
                print(f"Processando documento ID {sentence_doc.id} - Tipo: {sentence_doc.type} - Caminho: {sentence_path}")
                if not sentence_path:
                    skipped += 1
                    skipped_missing += 1
                    continue

                existing = JudicialSentenceAnalysis.query.filter_by(
                    law_firm_id=law_firm_id,
                    file_path=sentence_path,
                ).first()
                if existing:
                    skipped += 1
                    skipped_existing += 1
                    continue

                file_size = os.path.getsize(sentence_path)
                extension = os.path.splitext(sentence_doc.file_name or '')[1].lower().replace('.', '')
                sentence = JudicialSentenceAnalysis(
                    user_id=session.get('user_id'),
                    law_firm_id=law_firm_id,
                    original_filename=sentence_doc.file_name,
                    file_path=sentence_path,
                    file_size=file_size,
                    file_type=extension.upper() if extension else '',
                    process_number=process.process_number,
                    status='pending',
                )

                if petition_doc and petition_doc.file_path and os.path.exists(petition_doc.file_path):
                    petition_ext = os.path.splitext(petition_doc.file_name or '')[1].lower().replace('.', '')
                    sentence.petition_filename = petition_doc.file_name
                    sentence.petition_file_path = petition_doc.file_path
                    sentence.petition_file_size = os.path.getsize(petition_doc.file_path)
                    sentence.petition_file_type = petition_ext.upper() if petition_ext else ''

                db.session.add(sentence)
                db.session.flush()

                if first_created_id is None:
                    first_created_id = sentence.id

                queued += 1

            if queued == 0:
                db.session.rollback()
                flash(
                    'Nenhuma nova sentença foi enfileirada. '
                    f'Ignoradas por arquivo ausente: {skipped_missing}. '
                    f'Ignoradas por já cadastradas: {skipped_existing}.',
                    'info'
                )
                return render_template('tools/sentence_analysis_upload.html', form=form)

            db.session.commit()
            flash(
                f'Processo enviado para análise! {queued} sentença(s) enfileirada(s) '
                f'e {skipped} arquivo(s) ignorado(s).',
                'success'
            )

            if first_created_id:
                return redirect(url_for('tools.judicial_sentence_analysis_detail', sentence_id=first_created_id))
            return redirect(url_for('tools.judicial_sentence_analysis_list'))

        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao enfileirar análises do processo: {str(e)}', 'danger')
    
    return render_template('tools/sentence_analysis_upload.html', form=form)


@tools_bp.route('/sentence-analysis/<int:sentence_id>')
@require_law_firm
def judicial_sentence_analysis_detail(sentence_id):
    """Detalhes da análise de uma sentença judicial"""
    sentence = JudicialSentenceAnalysis.query.get_or_404(sentence_id)
    
    if sentence.law_firm_id != get_current_law_firm_id():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_list'))
    
    return render_template('tools/sentence_analysis_detail.html', sentence=sentence)


@tools_bp.route('/sentence-analysis/<int:sentence_id>/delete', methods=['POST'])
@require_law_firm
def judicial_sentence_analysis_delete(sentence_id):
    """Deletar análise de sentença judicial"""
    sentence = JudicialSentenceAnalysis.query.get_or_404(sentence_id)
    
    if sentence.law_firm_id != get_current_law_firm_id():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_list'))
    
    try:
        db.session.delete(sentence)
        db.session.commit()
        
        flash('Análise deletada com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar análise: {str(e)}', 'danger')
    
    return redirect(url_for('tools.judicial_sentence_analysis_list'))


@tools_bp.route('/sentence-analysis/<int:sentence_id>/reprocess', methods=['POST'])
@require_law_firm
def judicial_sentence_analysis_reprocess(sentence_id):
    """Reprocessar análise de sentença judicial - coloca de volta na fila"""
    sentence = JudicialSentenceAnalysis.query.get_or_404(sentence_id)
    
    if sentence.law_firm_id != get_current_law_firm_id():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_list'))
    
    try:
        # Retorna para a fila (pending) para ser processada novamente
        sentence.status = 'pending'
        sentence.error_message = None
        sentence.analysis_result = None
        db.session.commit()
        
        flash('Sentença marcada para reprocessamento! O script irá processar em breve.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao reprocessar sentença: {str(e)}', 'danger')
    
    return redirect(url_for('tools.judicial_sentence_analysis_detail', sentence_id=sentence_id))


@tools_bp.route('/sentence-analysis/<int:sentence_id>/view-sentence')
@require_law_firm
def view_sentence_file(sentence_id):
    """Visualizar arquivo da sentença"""
    sentence = JudicialSentenceAnalysis.query.get_or_404(sentence_id)
    
    if sentence.law_firm_id != get_current_law_firm_id():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_list'))
    
    if not sentence.file_path or not os.path.exists(sentence.file_path):
        flash('Arquivo da sentença não encontrado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_detail', sentence_id=sentence_id))
    
    return send_file(
        sentence.file_path,
        as_attachment=False,
        download_name=sentence.original_filename,
        mimetype='application/pdf' if sentence.file_type.lower() == 'pdf' else 'application/msword'
    )


@tools_bp.route('/sentence-analysis/<int:sentence_id>/download-sentence')
@require_law_firm
def download_sentence_file(sentence_id):
    """Baixar arquivo da sentença"""
    sentence = JudicialSentenceAnalysis.query.get_or_404(sentence_id)
    
    if sentence.law_firm_id != get_current_law_firm_id():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_list'))
    
    if not sentence.file_path or not os.path.exists(sentence.file_path):
        flash('Arquivo da sentença não encontrado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_detail', sentence_id=sentence_id))
    
    return send_file(
        sentence.file_path,
        as_attachment=True,
        download_name=sentence.original_filename
    )


@tools_bp.route('/sentence-analysis/<int:sentence_id>/view-petition')
@require_law_firm
def view_petition_file(sentence_id):
    """Visualizar arquivo da petição"""
    sentence = JudicialSentenceAnalysis.query.get_or_404(sentence_id)
    
    if sentence.law_firm_id != get_current_law_firm_id():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_list'))
    
    if not sentence.petition_file_path or not os.path.exists(sentence.petition_file_path):
        flash('Arquivo de petição não encontrado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_detail', sentence_id=sentence_id))
    
    return send_file(
        sentence.petition_file_path,
        as_attachment=False,
        download_name=sentence.petition_filename,
        mimetype='application/pdf' if sentence.petition_file_type.lower() == 'pdf' else 'application/msword'
    )


@tools_bp.route('/sentence-analysis/<int:sentence_id>/download-petition')
@require_law_firm
def download_petition_file(sentence_id):
    """Baixar arquivo da petição"""
    sentence = JudicialSentenceAnalysis.query.get_or_404(sentence_id)
    
    if sentence.law_firm_id != get_current_law_firm_id():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_list'))
    
    if not sentence.petition_file_path or not os.path.exists(sentence.petition_file_path):
        flash('Arquivo de petição não encontrado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_detail', sentence_id=sentence_id))
    
    return send_file(
        sentence.petition_file_path,
        as_attachment=True,
        download_name=sentence.petition_filename
    )


# ==================== Rotas de Recursos Judiciais ====================

@tools_bp.route('/appeals')
@require_law_firm
def appeal_list():
    """Lista de recursos judiciais gerados"""
    law_firm_id = get_current_law_firm_id()
    appeals = (
        JudicialAppeal.query
        .filter_by(law_firm_id=law_firm_id)
        .order_by(JudicialAppeal.created_at.desc())
        .all()
    )
    return render_template('tools/appeal_list.html', appeals=appeals)

@tools_bp.route('/appeal/create/<int:sentence_id>', methods=['GET', 'POST'])
@require_law_firm
def appeal_create(sentence_id):
    """Formulário para criar um recurso judicial"""
    from app.form import JudicialAppealForm
    
    # Verificar se a sentença existe e pertence ao escritório
    sentence = JudicialSentenceAnalysis.query.get_or_404(sentence_id)
    
    if sentence.law_firm_id != get_current_law_firm_id():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_list'))
    
    if sentence.status != 'completed':
        flash('A análise da sentença precisa estar concluída para gerar recursos', 'warning')
        return redirect(url_for('tools.judicial_sentence_analysis_detail', sentence_id=sentence_id))
    
    form = JudicialAppealForm()
    
    if form.validate_on_submit():
        try:
            # Criar registro do recurso
            appeal = JudicialAppeal(
                user_id=session.get('user_id'),
                law_firm_id=get_current_law_firm_id(),
                sentence_analysis_id=sentence_id,
                appeal_type=form.appeal_type.data,
                user_notes=form.user_notes.data,
                status='pending'
            )
            
            db.session.add(appeal)
            db.session.commit()
            
            flash('Recurso criado com sucesso! Será processado em breve.', 'success')
            return redirect(url_for('tools.appeal_detail', appeal_id=appeal.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar recurso: {str(e)}', 'danger')
    
    return render_template('tools/appeal_create.html', form=form, sentence=sentence)


@tools_bp.route('/appeal/<int:appeal_id>')
@require_law_firm
def appeal_detail(appeal_id):
    """Detalhes de um recurso judicial"""
    appeal = JudicialAppeal.query.get_or_404(appeal_id)
    
    if appeal.law_firm_id != get_current_law_firm_id():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_list'))
    
    return render_template('tools/appeal_detail.html', appeal=appeal)


@tools_bp.route('/appeal/<int:appeal_id>/delete', methods=['POST'])
@require_law_firm
def appeal_delete(appeal_id):
    """Deletar um recurso"""
    appeal = JudicialAppeal.query.get_or_404(appeal_id)
    
    if appeal.law_firm_id != get_current_law_firm_id():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_list'))
    
    try:
        sentence_id = appeal.sentence_analysis_id
        
        # Deletar arquivo gerado se existir
        if appeal.generated_file_path and os.path.exists(appeal.generated_file_path):
            os.remove(appeal.generated_file_path)
        
        db.session.delete(appeal)
        db.session.commit()
        
        flash('Recurso deletado com sucesso', 'success')
        return redirect(url_for('tools.judicial_sentence_analysis_detail', sentence_id=sentence_id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar recurso: {str(e)}', 'danger')
        return redirect(url_for('tools.appeal_detail', appeal_id=appeal_id))


@tools_bp.route('/appeal/<int:appeal_id>/download')
@require_law_firm
def appeal_download(appeal_id):
    """Download do arquivo do recurso gerado"""
    appeal = JudicialAppeal.query.get_or_404(appeal_id)
    
    if appeal.law_firm_id != get_current_law_firm_id():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('tools.judicial_sentence_analysis_list'))
    
    if not appeal.generated_file_path or not os.path.exists(appeal.generated_file_path):
        flash('Arquivo de recurso não encontrado', 'danger')
        return redirect(url_for('tools.appeal_detail', appeal_id=appeal_id))
    
    filename = f"Recurso_{appeal.appeal_type.replace(' ', '_')}_{appeal.id}.docx"
    
    return send_file(
        appeal.generated_file_path,
        as_attachment=True,
        download_name=filename
    )
