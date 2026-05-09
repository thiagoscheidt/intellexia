"""
Blueprint: FAP Review - Módulo de Revisão de Petição Inicial FAP

Rotas principais:
- /fap-review - Dashboard principal
- /fap-review/revision - Revisão de petições
- /fap-review/training - Gerenciamento de treinamento
- /fap-review/settings - Configurações do módulo
"""

import os
import json
import hashlib
import asyncio
from datetime import datetime
from io import BytesIO
from decimal import Decimal
from pathlib import Path

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for, send_file
from werkzeug.utils import secure_filename
from sqlalchemy import and_, func

from app.models import (
    db, User, LawFirm,
    FapReviewPromptVersion, FapReviewReferenceVersion, FapReviewSetting,
    FapReviewExecution, FapReviewAuditLog
)
from app.agents.fap_review import FapPetitionReviewerAgent, FapTrainingEvolutionAgent
from app.services.openrouter_models_service import fetch_openrouter_text_models_for_info
from app.utils.timezone import now_sp

# Document processing
try:
    from docling.document_converter import DocumentConverter
    HAS_DOCLING = True
except ImportError:
    HAS_DOCLING = False

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None


fap_review_bp = Blueprint('fap_review', __name__, url_prefix='/fap-review')

# Configurações
ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt'}
ALLOWED_AUXILIARY_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'png', 'jpg', 'jpeg'}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB


def allowed_file(filename: str, allowed_extensions: set) -> bool:
    """Verifica se arquivo tem extensão permitida"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def get_current_law_firm_id() -> int:
    """Obtém ID do escritório da sessão"""
    return session.get('law_firm_id')


def require_law_firm(f):
    """Decorator para garantir que há escritório na sessão"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            flash('Acesso negado', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    
    return decorated_function


def require_admin_user(f):
    """Decorator para garantir que é admin"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return redirect(url_for('auth.login'))
        
        user = User.query.get(user_id)
        if not user or user.role != 'admin':
            flash('Acesso negado: privilégio de administrador necessário', 'error')
            return redirect(url_for('fap_review.index'))
        
        return f(*args, **kwargs)
    
    return decorated_function


def _get_fap_setting(law_firm_id: int) -> FapReviewSetting:
    """Obtém ou cria configuração padrão do FAP Review"""
    setting = FapReviewSetting.query.filter_by(law_firm_id=law_firm_id).first()
    
    if not setting:
        setting = FapReviewSetting(
            law_firm_id=law_firm_id,
            reviewer_model='gpt-4o-mini',
            training_model='gpt-4o-mini',
            reviewer_temperature=0.7,
            training_temperature=0.7,
            reviewer_enabled=True,
            training_enabled=True
        )
        db.session.add(setting)
        db.session.commit()
    
    return setting


def _log_audit(law_firm_id: int, action: str, entity_type: str, 
               entity_id: int = None, description: str = "", 
               old_value: str = "", new_value: str = ""):
    """Registra ação de auditoria"""
    user_id = session.get('user_id')
    
    log_entry = FapReviewAuditLog(
        law_firm_id=law_firm_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        change_description=description,
        old_value=old_value,
        new_value=new_value
    )
    db.session.add(log_entry)
    db.session.commit()


def _create_upload_directory(law_firm_id: int, subdir: str = "") -> Path:
    """Cria diretório de upload se não existir"""
    base_dir = Path('uploads/fap_review') / str(law_firm_id)
    if subdir:
        base_dir = base_dir / subdir
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _extract_text_from_document(filepath: str) -> str:
    """Extrai texto de um documento (PDF, DOCX ou TXT)"""
    filepath = Path(filepath)
    extension = filepath.suffix.lower()
    text = ""
    
    try:
        if extension == '.pdf':
            # Tentar Docling primeiro (melhor qualidade)
            if HAS_DOCLING:
                try:
                    converter = DocumentConverter()
                    doc_result = converter.convert(str(filepath))
                    text = doc_result.document.export_to_markdown()
                except Exception as e:
                    current_app.logger.warning(f"Docling falhou: {e}, tentando PyPDF2")
                    # Fallback para PyPDF2
                    if PyPDF2:
                        with open(filepath, 'rb') as f:
                            reader = PyPDF2.PdfReader(f)
                            for page in reader.pages:
                                text += page.extract_text() + "\n"
            elif PyPDF2:
                with open(filepath, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
            else:
                raise ImportError("PyPDF2 não está instalado")
        
        elif extension in ['.docx', '.doc']:
            if DocxDocument:
                try:
                    doc = DocxDocument(filepath)
                    for para in doc.paragraphs:
                        text += para.text + "\n"
                    for table in doc.tables:
                        for row in table.rows:
                            for cell in row.cells:
                                text += cell.text + " | "
                            text += "\n"
                except Exception as e:
                    raise ValueError(f"Erro ao ler DOCX: {e}")
            else:
                raise ImportError("python-docx não está instalado")
        
        elif extension == '.txt':
            with open(filepath, 'r', encoding='utf-8') as f:
                text = f.read()
        
        else:
            raise ValueError(f"Tipo de arquivo não suportado: {extension}")
        
        # Limpar espaços em branco excessivos
        text = '\n'.join([line.strip() for line in text.split('\n') if line.strip()])
        
        return text
    
    except Exception as e:
        current_app.logger.error(f"Erro ao extrair texto: {e}")
        raise


def _execute_reviewer_agent(execution_id: int, law_firm_id: int, petition_text: str, 
                           compared_text: str = None) -> dict:
    """Executa o agente revisor e armazena resultado"""
    try:
        execution = FapReviewExecution.query.get(execution_id)
        if not execution:
            raise ValueError(f"Execução {execution_id} não encontrada")
        
        # Carregar configurações
        setting = _get_fap_setting(law_firm_id)
        openai_api_key = os.getenv('OPENAI_API_KEY')
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY não configurada")
        
        # Carregar referências ativas
        manual = FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id,
            reference_type='manual_fap',
            is_active=True
        ).first()
        
        cases = FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id,
            reference_type='casos_referencia',
            is_active=True
        ).first()
        
        project_instructions = FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id,
            reference_type='project_instructions',
            is_active=True
        ).first()
        
        # Instanciar agente revisor
        agent = FapPetitionReviewerAgent(
            openai_api_key=openai_api_key,
            model=setting.reviewer_model,
            temperature=setting.reviewer_temperature
        )
        
        # Carregar referências no agente
        agent.load_reference_documents(
            manual_md=manual.content if manual else "",
            cases_md=cases.content if cases else "",
            project_instructions_md=project_instructions.content if project_instructions else ""
        )
        
        # Executar análise (async)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            if compared_text and execution.comparative_analysis:
                # Análise comparativa
                result = loop.run_until_complete(
                    agent.review_petition_comparative(
                        original_petition=petition_text,
                        revised_petition=compared_text
                    )
                )
            else:
                # Análise simples
                result = loop.run_until_complete(
                    agent.review_petition_single_version(
                        petition_content=petition_text
                    )
                )
            
            # Armazenar resultado
            execution.result_json = result.model_dump_json(indent=2)
            execution.status = 'completed'
            execution.completed_at = datetime.utcnow()
            
            # Se o resultado tem tokens, armazenar
            if hasattr(result, 'tokens_used'):
                execution.tokens_used = result.tokens_used
            if hasattr(result, 'cost_usd'):
                execution.cost_usd = Decimal(str(result.cost_usd))
            
            db.session.commit()
            
            # Log de auditoria
            _log_audit(law_firm_id, 'revision_completed', 'execution', execution_id,
                      'Revisão concluída com sucesso')
            
            return {'success': True, 'execution_id': execution_id}
        
        finally:
            loop.close()
    
    except Exception as e:
        current_app.logger.error(f"Erro ao executar agente revisor: {e}")
        
        # Atualizar status para falha
        try:
            execution = FapReviewExecution.query.get(execution_id)
            if execution:
                execution.status = 'failed'
                execution.error_message = str(e)
                execution.completed_at = datetime.utcnow()
                db.session.commit()
                
                _log_audit(law_firm_id, 'revision_failed', 'execution', execution_id,
                          f'Erro: {str(e)[:200]}')
        except Exception as inner_e:
            current_app.logger.error(f"Erro ao registrar falha: {inner_e}")
        
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# ROTAS PRINCIPAIS
# ═══════════════════════════════════════════════════════════════════════════════


@fap_review_bp.route('/')
@require_law_firm
def index():
    """Dashboard principal do módulo"""
    law_firm_id = get_current_law_firm_id()
    
    # Estatísticas
    total_executions = FapReviewExecution.query.filter_by(law_firm_id=law_firm_id).count()
    completed_executions = FapReviewExecution.query.filter_by(
        law_firm_id=law_firm_id,
        status='completed'
    ).count()
    failed_executions = FapReviewExecution.query.filter_by(
        law_firm_id=law_firm_id,
        status='failed'
    ).count()
    
    # Últimas execuções
    recent_executions = FapReviewExecution.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(FapReviewExecution.created_at.desc()).limit(5).all()
    
    # Configurações
    setting = _get_fap_setting(law_firm_id)
    
    return render_template('fap_review/index.html',
                          total_executions=total_executions,
                          completed_executions=completed_executions,
                          failed_executions=failed_executions,
                          recent_executions=recent_executions,
                          setting=setting)


@fap_review_bp.route('/revision', methods=['GET', 'POST'])
@require_law_firm
def revision():
    """Página de revisão de petições"""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')
    
    if request.method == 'POST':
        try:
            # Validar upload de arquivo principal
            if 'main_document' not in request.files:
                return jsonify({'error': 'Documento principal não fornecido'}), 400
            
            main_file = request.files['main_document']
            if main_file.filename == '':
                return jsonify({'error': 'Arquivo vazio'}), 400
            
            if not allowed_file(main_file.filename, ALLOWED_DOCUMENT_EXTENSIONS):
                return jsonify({'error': 'Tipo de arquivo não permitido'}), 400
            
            # Salvar arquivo principal
            upload_dir = _create_upload_directory(law_firm_id, 'revisions')
            filename = secure_filename(main_file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
            filename = timestamp + filename
            filepath = upload_dir / filename
            main_file.save(str(filepath))
            
            # Processar documentos auxiliares
            auxiliary_count = 0
            auxiliary_files = []
            if 'auxiliary_documents' in request.files:
                files = request.files.getlist('auxiliary_documents')
                for file in files:
                    if file and file.filename and allowed_file(file.filename, ALLOWED_AUXILIARY_EXTENSIONS):
                        aux_filename = secure_filename(file.filename)
                        aux_filename = timestamp + f'aux_{auxiliary_count}_' + aux_filename
                        aux_filepath = upload_dir / aux_filename
                        file.save(str(aux_filepath))
                        auxiliary_files.append({
                            'name': file.filename,
                            'path': str(aux_filepath)
                        })
                        auxiliary_count += 1
            
            # Verificar se há análise comparativa
            compared_document = None
            comparative_analysis = False
            if 'compared_document' in request.files:
                compared_file = request.files['compared_document']
                if compared_file and compared_file.filename and allowed_file(compared_file.filename, ALLOWED_DOCUMENT_EXTENSIONS):
                    compared_filename = secure_filename(compared_file.filename)
                    compared_filename = timestamp + 'compared_' + compared_filename
                    compared_filepath = upload_dir / compared_filename
                    compared_file.save(str(compared_filepath))
                    compared_document = str(compared_filepath)
                    comparative_analysis = True
            
            # Criar registro de execução
            execution = FapReviewExecution(
                law_firm_id=law_firm_id,
                user_id=user_id,
                execution_type='revision',
                status='processing',
                main_document_path=str(filepath),
                main_document_filename=main_file.filename,
                auxiliary_documents_count=auxiliary_count,
                auxiliary_documents_json=json.dumps(auxiliary_files),
                comparative_analysis=comparative_analysis,
                compared_document_path=compared_document
            )
            db.session.add(execution)
            db.session.commit()
            
            # Log de auditoria
            _log_audit(law_firm_id, 'revision_started', 'execution', execution.id,
                      f'Revisão iniciada: {main_file.filename}')
            
            # ===== INVOCAR AGENTE REVISOR =====
            try:
                # Extrair texto do documento principal
                petition_text = _extract_text_from_document(str(filepath))
                
                if not petition_text.strip():
                    raise ValueError("Documento principal está vazio ou não foi possível extrair texto")
                
                # Extrair texto do documento comparado (se houver)
                compared_text = None
                if comparative_analysis and compared_document:
                    compared_text = _extract_text_from_document(compared_document)
                    if not compared_text.strip():
                        raise ValueError("Documento comparado está vazio ou não foi possível extrair texto")
                
                # Executar agente revisor
                _execute_reviewer_agent(
                    execution.id,
                    law_firm_id,
                    petition_text,
                    compared_text
                )
            
            except Exception as agent_error:
                current_app.logger.error(f"Erro na execução do agente: {agent_error}")
                # A função _execute_reviewer_agent já atualiza o status para 'failed'
                # Mas vamos garantir que foi marcado como falha
                execution = FapReviewExecution.query.get(execution.id)
                if execution and execution.status == 'processing':
                    execution.status = 'failed'
                    execution.error_message = str(agent_error)
                    db.session.commit()
            
            return jsonify({
                'success': True,
                'execution_id': execution.id,
                'message': 'Revisão iniciada com sucesso'
            })
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao processar upload: {e}")
            return jsonify({'error': str(e)}), 500
    
    # GET - Exibir página
    setting = _get_fap_setting(law_firm_id)
    return render_template('fap_review/revision.html', setting=setting)


@fap_review_bp.route('/revision/<int:execution_id>', methods=['GET'])
@require_law_firm
def revision_result(execution_id: int):
    """Exibe resultado de uma revisão"""
    law_firm_id = get_current_law_firm_id()
    
    execution = FapReviewExecution.query.filter_by(
        id=execution_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    result_data = {}
    if execution.result_json:
        try:
            result_data = json.loads(execution.result_json)
        except json.JSONDecodeError:
            result_data = {}
    
    return render_template('fap_review/revision_result.html',
                          execution=execution,
                          result_data=result_data)


@fap_review_bp.route('/training', methods=['GET', 'POST'])
@require_law_firm
@require_admin_user
def training():
    """Página de gerenciamento de treinamento e evolução"""
    law_firm_id = get_current_law_firm_id()
    
    if request.method == 'POST':
        # Lógica de treinamento
        pass
    
    setting = _get_fap_setting(law_firm_id)
    
    # Últimas execuções de treinamento
    recent_training = FapReviewExecution.query.filter_by(
        law_firm_id=law_firm_id,
        execution_type='training'
    ).order_by(FapReviewExecution.created_at.desc()).limit(10).all()
    
    return render_template('fap_review/training.html',
                          setting=setting,
                          recent_training=recent_training)


@fap_review_bp.route('/settings', methods=['GET', 'POST'])
@require_law_firm
@require_admin_user
def settings():
    """Página de configurações do módulo"""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')
    
    setting = _get_fap_setting(law_firm_id)
    
    if request.method == 'POST':
        try:
            data = request.json
            
            # Atualizar configurações
            setting.reviewer_model = data.get('reviewer_model', setting.reviewer_model)
            setting.training_model = data.get('training_model', setting.training_model)
            setting.reviewer_temperature = float(data.get('reviewer_temperature', setting.reviewer_temperature))
            setting.training_temperature = float(data.get('training_temperature', setting.training_temperature))
            setting.auto_update_manual = data.get('auto_update_manual', setting.auto_update_manual)
            setting.auto_update_cases = data.get('auto_update_cases', setting.auto_update_cases)
            setting.require_approval_before_publish = data.get('require_approval_before_publish', setting.require_approval_before_publish)
            setting.enable_continuous_learning = data.get('enable_continuous_learning', setting.enable_continuous_learning)
            setting.reviewer_enabled = data.get('reviewer_enabled', setting.reviewer_enabled)
            setting.training_enabled = data.get('training_enabled', setting.training_enabled)
            setting.updated_at = now_sp()
            
            db.session.commit()
            
            # Log de auditoria
            _log_audit(law_firm_id, 'settings_updated', 'setting', setting.id,
                      'Configurações do FAP Review atualizadas')
            
            return jsonify({'success': True, 'message': 'Configurações salvas com sucesso'})
        
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
    
    # GET - Exibir página
    available_models, model_options_error = fetch_openrouter_text_models_for_info(
        selected_model=setting.reviewer_model or '',
        fallback_model=setting.reviewer_model or '',
    )
    return render_template('fap_review/settings.html',
                           setting=setting,
                           available_models=available_models,
                           model_options_error=model_options_error)


# ═══════════════════════════════════════════════════════════════════════════════
# ROTAS DE PROMPTS E REFERENCIAS
# ═══════════════════════════════════════════════════════════════════════════════


@fap_review_bp.route('/settings/prompts', methods=['GET'])
@require_law_firm
@require_admin_user
def list_prompts():
    """Lista prompts por tipo"""
    law_firm_id = get_current_law_firm_id()
    
    prompt_types = [
        'revisor_identity',
        'revisor_rules',
        'revisor_prompt',
        'revisor_output_format',
        'training_identity',
        'training_rules',
        'training_prompt',
        'training_update_policy'
    ]
    
    prompts = {}
    for ptype in prompt_types:
        versions = FapReviewPromptVersion.query.filter_by(
            law_firm_id=law_firm_id,
            prompt_type=ptype
        ).order_by(FapReviewPromptVersion.version_number.desc()).all()
        prompts[ptype] = versions
    
    return jsonify({
        'prompts': {
            k: [{'version': v.version_number, 'is_active': v.is_active, 'created_at': v.created_at.isoformat()} for v in v]
            for k, v in prompts.items()
        }
    })


@fap_review_bp.route('/settings/prompts/<int:prompt_version_id>', methods=['GET', 'POST'])
@require_law_firm
@require_admin_user
def edit_prompt(prompt_version_id: int):
    """Edita um prompt específico"""
    law_firm_id = get_current_law_firm_id()
    
    prompt = FapReviewPromptVersion.query.filter_by(
        id=prompt_version_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    # Carregar todas as versões deste tipo
    all_versions = FapReviewPromptVersion.query.filter_by(
        law_firm_id=law_firm_id,
        prompt_type=prompt.prompt_type
    ).order_by(FapReviewPromptVersion.version_number.desc()).all()
    
    if request.method == 'POST':
        try:
            content = request.json.get('content', '')
            
            # Criar nova versão
            new_version = FapReviewPromptVersion(
                law_firm_id=law_firm_id,
                version_number=prompt.version_number + 1,
                prompt_type=prompt.prompt_type,
                content=content,
                is_active=False,
                created_by_id=session.get('user_id')
            )
            db.session.add(new_version)
            db.session.commit()
            
            # Log
            _log_audit(law_firm_id, 'prompt_updated', 'prompt', new_version.id,
                      f'Nova versão criada: v{new_version.version_number}')
            
            return jsonify({'success': True, 'version_id': new_version.id})
        
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
    
    # GET
    return render_template('fap_review/edit_prompt.html', prompt=prompt, versions=all_versions)


@fap_review_bp.route('/settings/prompts/<int:prompt_version_id>/activate', methods=['POST'])
@require_law_firm
@require_admin_user
def activate_prompt(prompt_version_id: int):
    """Ativa uma versão de prompt"""
    law_firm_id = get_current_law_firm_id()
    
    prompt = FapReviewPromptVersion.query.filter_by(
        id=prompt_version_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    try:
        # Desativar outras versões do mesmo tipo
        FapReviewPromptVersion.query.filter_by(
            law_firm_id=law_firm_id,
            prompt_type=prompt.prompt_type,
            is_active=True
        ).update({'is_active': False})
        
        # Ativar esta versão
        prompt.is_active = True
        db.session.commit()
        
        _log_audit(law_firm_id, 'prompt_activated', 'prompt', prompt.id,
                  f'Versão v{prompt.version_number} ativada')
        
        return jsonify({'success': True})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@fap_review_bp.route('/settings/references', methods=['GET'])
@require_law_firm
@require_admin_user
def list_references():
    """Lista documentos de referência"""
    law_firm_id = get_current_law_firm_id()
    
    reference_types = ['manual_fap', 'casos_referencia', 'project_instructions']
    
    references = {}
    for rtype in reference_types:
        versions = FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id,
            reference_type=rtype
        ).order_by(FapReviewReferenceVersion.version_number.desc()).all()
        references[rtype] = versions
    
    return jsonify({
        'references': {
            k: [{'version': v.version_number, 'is_active': v.is_active, 'created_at': v.created_at.isoformat()} for v in v]
            for k, v in references.items()
        }
    })


@fap_review_bp.route('/settings/references/<int:reference_version_id>', methods=['GET', 'POST'])
@require_law_firm
@require_admin_user
def edit_reference(reference_version_id: int):
    """Edita um documento de referência"""
    law_firm_id = get_current_law_firm_id()
    
    reference = FapReviewReferenceVersion.query.filter_by(
        id=reference_version_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    # Carregar todas as versões deste tipo
    all_versions = FapReviewReferenceVersion.query.filter_by(
        law_firm_id=law_firm_id,
        reference_type=reference.reference_type
    ).order_by(FapReviewReferenceVersion.version_number.desc()).all()
    
    if request.method == 'POST':
        try:
            content = request.json.get('content', '')
            
            # Criar nova versão
            new_version = FapReviewReferenceVersion(
                law_firm_id=law_firm_id,
                version_number=reference.version_number + 1,
                reference_type=reference.reference_type,
                content=content,
                is_active=False,
                created_by_id=session.get('user_id')
            )
            db.session.add(new_version)
            db.session.commit()
            
            _log_audit(law_firm_id, 'reference_updated', 'reference', new_version.id,
                      f'Nova versão criada: v{new_version.version_number}')
            
            return jsonify({'success': True, 'version_id': new_version.id})
        
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
    
    # GET
    return render_template('fap_review/edit_reference.html', reference=reference, versions=all_versions)


@fap_review_bp.route('/settings/references/<int:reference_version_id>/activate', methods=['POST'])
@require_law_firm
@require_admin_user
def activate_reference(reference_version_id: int):
    """Ativa uma versão de referência"""
    law_firm_id = get_current_law_firm_id()
    
    reference = FapReviewReferenceVersion.query.filter_by(
        id=reference_version_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    try:
        # Desativar outras versões do mesmo tipo
        FapReviewReferenceVersion.query.filter_by(
            law_firm_id=law_firm_id,
            reference_type=reference.reference_type,
            is_active=True
        ).update({'is_active': False})
        
        # Ativar esta versão
        reference.is_active = True
        db.session.commit()
        
        _log_audit(law_firm_id, 'reference_activated', 'reference', reference.id,
                  f'Versão v{reference.version_number} ativada')
        
        return jsonify({'success': True})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# ROTAS DE AUDITORIA
# ═══════════════════════════════════════════════════════════════════════════════


@fap_review_bp.route('/audit-logs', methods=['GET'])
@require_law_firm
@require_admin_user
def audit_logs():
    """Exibe logs de auditoria"""
    law_firm_id = get_current_law_firm_id()
    
    page = request.args.get('page', 1, type=int)
    logs = FapReviewAuditLog.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(FapReviewAuditLog.created_at.desc()).paginate(page=page, per_page=50)
    
    return render_template('fap_review/audit_logs.html', logs=logs)


@fap_review_bp.route('/api/audit-logs', methods=['GET'])
@require_law_firm
@require_admin_user
def api_audit_logs():
    """API para obter logs de auditoria"""
    law_firm_id = get_current_law_firm_id()
    
    action_filter = request.args.get('action', '')
    entity_filter = request.args.get('entity_type', '')
    limit = request.args.get('limit', 50, type=int)
    
    query = FapReviewAuditLog.query.filter_by(law_firm_id=law_firm_id)
    
    if action_filter:
        query = query.filter_by(action=action_filter)
    if entity_filter:
        query = query.filter_by(entity_type=entity_filter)
    
    logs = query.order_by(FapReviewAuditLog.created_at.desc()).limit(limit).all()
    
    return jsonify({
        'logs': [{
            'id': log.id,
            'action': log.action,
            'entity_type': log.entity_type,
            'user': log.user.name if log.user else 'System',
            'created_at': log.created_at.isoformat(),
            'description': log.change_description
        } for log in logs]
    })
