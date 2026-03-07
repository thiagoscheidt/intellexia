from flask import Blueprint, render_template, request, session, jsonify, redirect, url_for, flash
from app.models import (
    db, JudicialProcess, JudicialSentenceAnalysis, JudicialAppeal, 
    KnowledgeBase, Case, User, JudicialPhase, JudicialDocumentType, JudicialEvent,
    JudicialProcessNote
)
from datetime import datetime
from functools import wraps
from sqlalchemy import or_, and_
from werkzeug.utils import secure_filename
import hashlib
import os
import re

process_panel_bp = Blueprint('process_panel', __name__, url_prefix='/process-panel')


PHASE_ORDER = {
    "inicio_processo": 1,
    "citacao": 2,
    "defesa_reu": 3,
    "manifestacao_autor": 4,
    "saneamento": 5,
    "producao_provas": 6,
    "audiencia": 7,
    "alegacoes_finais": 8,
    "julgamento": 9,
    "recursos": 10,
    "julgamento_tribunal": 11,
    "execucao": 12,
}


LEGACY_PHASE_ORDER = {
    "inicio_processo": 1,
    "citacao": 2,
    "defesa_reu": 3,
    "manifestacao_autor": 4,
    "saneamento": 5,
    "producao_provas": 6,
    "audiencia": 7,
    "alegacoes_finais": 8,
    "julgamento": 9,
    "decisoes_judiciais": 10,
    "recursos": 11,
    "julgamento_tribunal": 12,
    "execucao": 13,
    "medidas_urgentes": 14,
    "documentos_processuais": 15,
    "peticoes_diversas": 16,
}


JUDICIAL_PHASES = {
    "inicio_processo": "Início do Processo",
    "citacao": "Citação e Intimação",
    "defesa_reu": "Defesa do Réu",
    "manifestacao_autor": "Manifestação do Autor",
    "saneamento": "Saneamento do Processo",
    "producao_provas": "Produção de Provas",
    "audiencia": "Audiência",
    "alegacoes_finais": "Alegações Finais",
    "julgamento": "Julgamento",
    "recursos": "Recursos",
    "julgamento_tribunal": "Julgamento em Tribunal",
    "execucao": "Execução / Cumprimento de Sentença",
    "decisoes_judiciais": "Decisões Judiciais",
    "medidas_urgentes": "Tutelas e Medidas Urgentes",
    "documentos_processuais": "Documentos Processuais",
    "peticoes_diversas": "Petições Diversas"
}


DOCUMENT_TYPES = {
    "peticao_inicial": {"name": "Petição Inicial", "phase": "inicio_processo"},
    "emenda_inicial": {"name": "Emenda à Petição Inicial", "phase": "inicio_processo"},
    "citacao": {"name": "Citação", "phase": "citacao"},
    "contestacao": {"name": "Contestação", "phase": "defesa_reu"},
    "reconvencao": {"name": "Reconvenção", "phase": "defesa_reu"},
    "replica": {"name": "Réplica", "phase": "manifestacao_autor"},
    "manifestacao": {"name": "Manifestação", "phase": "peticoes_diversas"},
    "peticao_intermediaria": {"name": "Petição Intermediária", "phase": "peticoes_diversas"},
    "juntada_documentos": {"name": "Juntada de Documentos", "phase": "peticoes_diversas"},
    "pedido_tutela_urgencia": {"name": "Pedido de Tutela de Urgência", "phase": "medidas_urgentes"},
    "pedido_liminar": {"name": "Pedido de Liminar", "phase": "medidas_urgentes"},
    "despacho": {"name": "Despacho", "phase": "decisoes_judiciais"},
    "decisao_interlocutoria": {"name": "Decisão Interlocutória", "phase": "decisoes_judiciais"},
    "decisao_saneamento": {"name": "Decisão de Saneamento", "phase": "saneamento"},
    "requerimento_prova": {"name": "Requerimento de Prova", "phase": "producao_provas"},
    "laudo_pericial": {"name": "Laudo Pericial", "phase": "producao_provas"},
    "manifestacao_laudo": {"name": "Manifestação sobre Laudo", "phase": "producao_provas"},
    "ata_audiencia": {"name": "Ata de Audiência", "phase": "audiencia"},
    "termo_audiencia": {"name": "Termo de Audiência", "phase": "audiencia"},
    "memoriais": {"name": "Memoriais / Alegações Finais", "phase": "alegacoes_finais"},
    "sentenca": {"name": "Sentença", "phase": "julgamento"},
    "embargos_declaracao": {"name": "Embargos de Declaração", "phase": "recursos"},
    "apelacao": {"name": "Apelação", "phase": "recursos"},
    "contrarrazoes_apelacao": {"name": "Contrarrazões de Apelação", "phase": "recursos"},
    "agravo_instrumento": {"name": "Agravo de Instrumento", "phase": "recursos"},
    "agravo_interno": {"name": "Agravo Interno", "phase": "recursos"},
    "recurso_especial": {"name": "Recurso Especial", "phase": "recursos"},
    "recurso_extraordinario": {"name": "Recurso Extraordinário", "phase": "recursos"},
    "acordao": {"name": "Acórdão", "phase": "julgamento_tribunal"},
    "certidao_julgamento": {"name": "Certidão de Julgamento", "phase": "julgamento_tribunal"},
    "cumprimento_sentenca": {"name": "Pedido de Cumprimento de Sentença", "phase": "execucao"},
    "impugnacao_cumprimento": {"name": "Impugnação ao Cumprimento de Sentença", "phase": "execucao"},
    "calculo_liquidacao": {"name": "Cálculo de Liquidação", "phase": "execucao"},
    "pedido_penhora": {"name": "Pedido de Penhora", "phase": "execucao"},
    "auto_penhora": {"name": "Auto de Penhora", "phase": "execucao"},
    "avaliacao_bens": {"name": "Avaliação de Bens", "phase": "execucao"},
    "edital_leilao": {"name": "Edital de Leilão", "phase": "execucao"},
    "certidao": {"name": "Certidão", "phase": "documentos_processuais"},
    "oficio": {"name": "Ofício Judicial", "phase": "documentos_processuais"},
    "mandado": {"name": "Mandado Judicial", "phase": "documentos_processuais"},
    "alvara": {"name": "Alvará Judicial", "phase": "documentos_processuais"}
}


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


def _normalize_slug(value):
    """Normaliza texto para chave em snake_case."""
    value = (value or '').strip().lower()
    value = re.sub(r'[^a-z0-9]+', '_', value)
    return value.strip('_')


def _ensure_judicial_config_defaults(law_firm_id):
    """Garante tabelas e registros padrão de fases e tipos de documento por escritório."""
    JudicialPhase.__table__.create(bind=db.engine, checkfirst=True)
    JudicialDocumentType.__table__.create(bind=db.engine, checkfirst=True)

    created_any = False

    phases_by_key = {
        phase.key: phase
        for phase in JudicialPhase.query.filter_by(law_firm_id=law_firm_id).all()
    }

    # Migração automática de ordem legada para a ordem solicitada pelo usuário.
    has_legacy_order = bool(phases_by_key) and all(
        (phases_by_key[key].display_order or 0) == legacy_order
        for key, legacy_order in LEGACY_PHASE_ORDER.items()
        if key in phases_by_key
    )

    if has_legacy_order:
        for phase_key, phase_order in PHASE_ORDER.items():
            phase = phases_by_key.get(phase_key)
            if phase and phase.display_order != phase_order:
                phase.display_order = phase_order
                created_any = True

    for order, (phase_key, phase_name) in enumerate(JUDICIAL_PHASES.items(), start=1):
        if phase_key in phases_by_key:
            continue

        display_order = PHASE_ORDER.get(phase_key, order)

        phase = JudicialPhase(
            law_firm_id=law_firm_id,
            key=phase_key,
            name=phase_name,
            display_order=display_order,
            is_active=True,
        )
        db.session.add(phase)
        phases_by_key[phase_key] = phase
        created_any = True

    if created_any:
        db.session.flush()

    existing_type_keys = {
        doc_type.key
        for doc_type in JudicialDocumentType.query.filter_by(law_firm_id=law_firm_id).all()
    }

    for order, (doc_key, doc_payload) in enumerate(DOCUMENT_TYPES.items(), start=1):
        if doc_key in existing_type_keys:
            continue

        phase = phases_by_key.get(doc_payload['phase'])
        if not phase:
            continue

        db.session.add(
            JudicialDocumentType(
                law_firm_id=law_firm_id,
                phase_id=phase.id,
                key=doc_key,
                name=doc_payload['name'],
                display_order=order,
                is_active=True,
            )
        )
        created_any = True

    if created_any:
        db.session.commit()


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


@process_panel_bp.route('/config/fases-documentos')
@require_law_firm
def manage_judicial_config_legacy():
    """Rota legada: redireciona para tela separada de fases judiciais."""
    return redirect(url_for('process_panel.manage_judicial_phases'))


@process_panel_bp.route('/config/fases')
@require_law_firm
def manage_judicial_phases():
    """Tela para gerenciamento de fases judiciais."""
    law_firm_id = get_current_law_firm_id()

    try:
        _ensure_judicial_config_defaults(law_firm_id)
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao preparar configuração judicial: {str(e)}', 'danger')

    phases = JudicialPhase.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(JudicialPhase.display_order.asc(), JudicialPhase.name.asc()).all()

    return render_template(
        'process_panel/phases_management.html',
        phases=phases,
    )


@process_panel_bp.route('/config/tipos-documento')
@require_law_firm
def manage_document_types():
    """Tela para gerenciamento de tipos de documento judiciais."""
    law_firm_id = get_current_law_firm_id()

    try:
        _ensure_judicial_config_defaults(law_firm_id)
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao preparar configuração judicial: {str(e)}', 'danger')

    phases = JudicialPhase.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(JudicialPhase.display_order.asc(), JudicialPhase.name.asc()).all()

    document_types = JudicialDocumentType.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(JudicialDocumentType.display_order.asc(), JudicialDocumentType.name.asc()).all()

    return render_template(
        'process_panel/document_types_management.html',
        phases=phases,
        document_types=document_types
    )


@process_panel_bp.route('/config/fases/criar', methods=['POST'])
@require_law_firm
def create_judicial_phase():
    """Cria nova fase judicial."""
    law_firm_id = get_current_law_firm_id()

    name = request.form.get('name', '').strip()
    key = _normalize_slug(request.form.get('key', '').strip() or name)

    if not name or not key:
        flash('Informe nome e chave válidos para a fase.', 'danger')
        return redirect(url_for('process_panel.manage_judicial_phases'))

    exists = JudicialPhase.query.filter_by(law_firm_id=law_firm_id, key=key).first()
    if exists:
        flash(f'Já existe uma fase com a chave "{key}".', 'warning')
        return redirect(url_for('process_panel.manage_judicial_phases'))

    max_order = db.session.query(db.func.max(JudicialPhase.display_order)).filter_by(
        law_firm_id=law_firm_id
    ).scalar() or 0

    try:
        db.session.add(
            JudicialPhase(
                law_firm_id=law_firm_id,
                key=key,
                name=name,
                display_order=max_order + 1,
                is_active=True,
            )
        )
        db.session.commit()
        flash('Fase judicial criada com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao criar fase judicial: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_judicial_phases'))


@process_panel_bp.route('/config/fases/<int:phase_id>/atualizar', methods=['POST'])
@require_law_firm
def update_judicial_phase(phase_id):
    """Atualiza fase judicial."""
    law_firm_id = get_current_law_firm_id()
    phase = JudicialPhase.query.filter_by(id=phase_id, law_firm_id=law_firm_id).first_or_404()

    name = request.form.get('name', '').strip()
    key = _normalize_slug(request.form.get('key', '').strip())

    if not name or not key:
        flash('Nome e chave são obrigatórios.', 'danger')
        return redirect(url_for('process_panel.manage_judicial_phases'))

    duplicated = JudicialPhase.query.filter(
        JudicialPhase.law_firm_id == law_firm_id,
        JudicialPhase.key == key,
        JudicialPhase.id != phase.id,
    ).first()

    if duplicated:
        flash(f'Já existe outra fase com a chave "{key}".', 'warning')
        return redirect(url_for('process_panel.manage_judicial_phases'))

    try:
        phase.name = name
        phase.key = key
        phase.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Fase judicial atualizada com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar fase judicial: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_judicial_phases'))


@process_panel_bp.route('/config/fases/<int:phase_id>/status', methods=['POST'])
@require_law_firm
def toggle_judicial_phase_status(phase_id):
    """Ativa/desativa fase judicial."""
    law_firm_id = get_current_law_firm_id()
    phase = JudicialPhase.query.filter_by(id=phase_id, law_firm_id=law_firm_id).first_or_404()

    try:
        phase.is_active = not phase.is_active
        phase.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Status da fase atualizado.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao alterar status da fase: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_judicial_phases'))


@process_panel_bp.route('/config/fases/reordenar', methods=['POST'])
@require_law_firm
def reorder_judicial_phases():
    """Reordena fases judiciais via drag-and-drop."""
    law_firm_id = get_current_law_firm_id()
    payload = request.get_json(silent=True) or {}
    phase_ids = payload.get('phase_ids')

    if not isinstance(phase_ids, list) or not phase_ids:
        return jsonify({'success': False, 'error': 'Lista de fases inválida'}), 400

    try:
        normalized_ids = [int(phase_id) for phase_id in phase_ids]
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'IDs de fases inválidos'}), 400

    unique_ids = list(dict.fromkeys(normalized_ids))
    if len(unique_ids) != len(normalized_ids):
        return jsonify({'success': False, 'error': 'IDs de fases duplicados'}), 400

    phases = JudicialPhase.query.filter(
        JudicialPhase.law_firm_id == law_firm_id,
        JudicialPhase.id.in_(unique_ids)
    ).all()

    if len(phases) != len(unique_ids):
        return jsonify({'success': False, 'error': 'Uma ou mais fases não foram encontradas'}), 404

    phases_by_id = {phase.id: phase for phase in phases}

    try:
        for order, phase_id in enumerate(unique_ids, start=1):
            phase = phases_by_id[phase_id]
            phase.display_order = order
            phase.updated_at = datetime.utcnow()

        db.session.commit()
        return jsonify({'success': True, 'message': 'Ordem atualizada com sucesso'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@process_panel_bp.route('/config/fases/restaurar-ordem', methods=['POST'])
@require_law_firm
def restore_judicial_phases_default_order():
    """Restaura a ordem padrão configurada para as fases judiciais."""
    law_firm_id = get_current_law_firm_id()

    phases = JudicialPhase.query.filter_by(law_firm_id=law_firm_id).all()
    phases_by_key = {phase.key: phase for phase in phases}

    try:
        assigned_order = 0

        for phase_key, phase_order in PHASE_ORDER.items():
            phase = phases_by_key.get(phase_key)
            if not phase:
                continue

            phase.display_order = phase_order
            phase.updated_at = datetime.utcnow()
            assigned_order = max(assigned_order, phase_order)

        remaining_phases = [
            phase for phase in phases
            if phase.key not in PHASE_ORDER
        ]
        remaining_phases.sort(key=lambda phase: ((phase.display_order or 9999), phase.name or ''))

        for index, phase in enumerate(remaining_phases, start=assigned_order + 1):
            phase.display_order = index
            phase.updated_at = datetime.utcnow()

        db.session.commit()
        flash('Ordem padrão das fases restaurada com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao restaurar ordem padrão: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_judicial_phases'))


@process_panel_bp.route('/config/tipos-documento/criar', methods=['POST'])
@require_law_firm
def create_document_type():
    """Cria novo tipo de documento judicial."""
    law_firm_id = get_current_law_firm_id()

    name = request.form.get('name', '').strip()
    key = _normalize_slug(request.form.get('key', '').strip() or name)
    phase_id = request.form.get('phase_id', type=int)

    if not name or not key or not phase_id:
        flash('Informe nome, chave e fase para o tipo de documento.', 'danger')
        return redirect(url_for('process_panel.manage_document_types'))

    phase = JudicialPhase.query.filter_by(id=phase_id, law_firm_id=law_firm_id).first()
    if not phase:
        flash('Fase selecionada é inválida.', 'danger')
        return redirect(url_for('process_panel.manage_document_types'))

    exists = JudicialDocumentType.query.filter_by(law_firm_id=law_firm_id, key=key).first()
    if exists:
        flash(f'Já existe tipo de documento com a chave "{key}".', 'warning')
        return redirect(url_for('process_panel.manage_document_types'))

    max_order = db.session.query(db.func.max(JudicialDocumentType.display_order)).filter_by(
        law_firm_id=law_firm_id
    ).scalar() or 0

    try:
        db.session.add(
            JudicialDocumentType(
                law_firm_id=law_firm_id,
                phase_id=phase_id,
                key=key,
                name=name,
                display_order=max_order + 1,
                is_active=True,
            )
        )
        db.session.commit()
        flash('Tipo de documento criado com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao criar tipo de documento: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_document_types'))


@process_panel_bp.route('/config/tipos-documento/<int:doc_type_id>/atualizar', methods=['POST'])
@require_law_firm
def update_document_type(doc_type_id):
    """Atualiza tipo de documento judicial."""
    law_firm_id = get_current_law_firm_id()
    doc_type = JudicialDocumentType.query.filter_by(
        id=doc_type_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    name = request.form.get('name', '').strip()
    key = _normalize_slug(request.form.get('key', '').strip())
    phase_id = request.form.get('phase_id', type=int)

    if not name or not key or not phase_id:
        flash('Nome, chave e fase são obrigatórios.', 'danger')
        return redirect(url_for('process_panel.manage_document_types'))

    phase = JudicialPhase.query.filter_by(id=phase_id, law_firm_id=law_firm_id).first()
    if not phase:
        flash('Fase selecionada é inválida.', 'danger')
        return redirect(url_for('process_panel.manage_document_types'))

    duplicated = JudicialDocumentType.query.filter(
        JudicialDocumentType.law_firm_id == law_firm_id,
        JudicialDocumentType.key == key,
        JudicialDocumentType.id != doc_type.id,
    ).first()

    if duplicated:
        flash(f'Já existe outro tipo de documento com a chave "{key}".', 'warning')
        return redirect(url_for('process_panel.manage_document_types'))

    try:
        doc_type.name = name
        doc_type.key = key
        doc_type.phase_id = phase_id
        doc_type.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Tipo de documento atualizado com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar tipo de documento: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_document_types'))


@process_panel_bp.route('/config/tipos-documento/<int:doc_type_id>/status', methods=['POST'])
@require_law_firm
def toggle_document_type_status(doc_type_id):
    """Ativa/desativa tipo de documento."""
    law_firm_id = get_current_law_firm_id()
    doc_type = JudicialDocumentType.query.filter_by(
        id=doc_type_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    try:
        doc_type.is_active = not doc_type.is_active
        doc_type.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Status do tipo de documento atualizado.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao alterar status do tipo de documento: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_document_types'))


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

    process_phases = {}
    for process in processes.items:
        latest_event = JudicialEvent.query.filter_by(process_id=process.id).order_by(
            JudicialEvent.event_date.desc(),
            JudicialEvent.id.desc()
        ).first()
        process_phases[process.id] = latest_event.phase if latest_event else None
    
    return render_template(
        'process_panel/list.html',
        processes=processes,
        search_query=search_query,
        status_filter=status_filter,
        stats=stats,
        process_phases=process_phases,
        judicial_phases_labels=JUDICIAL_PHASES,
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

    latest_event = JudicialEvent.query.filter_by(process_id=process.id).order_by(
        JudicialEvent.event_date.desc(),
        JudicialEvent.id.desc()
    ).first()
    current_phase_key = latest_event.phase if latest_event else None
    current_phase_label = JUDICIAL_PHASES.get(
        current_phase_key,
        (current_phase_key or '').replace('_', ' ').title()
    ) if current_phase_key else None

    notes = JudicialProcessNote.query.filter_by(
        process_id=process.id,
        law_firm_id=law_firm_id
    ).order_by(JudicialProcessNote.created_at.desc(), JudicialProcessNote.id.desc()).all()
    
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
        'current_phase_key': current_phase_key,
        'current_phase_label': current_phase_label,
        'sentence_analyses': related_analyses,
        'appeals': related_appeals,
        'notes': notes,
        'kb_documents': kb_documents,
        'case': process.case if process.case_id else None,
        'stats': {
            'analyses_count': len(related_analyses),
            'appeals_count': len(related_appeals),
            'documents_count': len(kb_documents),
        }
    }
    
    return render_template('process_panel/detail.html', **data)


@process_panel_bp.route('/<int:process_id>/notes', methods=['POST'])
@require_law_firm
def create_process_note(process_id):
    """Cria uma nova nota/comentário para o processo judicial."""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    content = (request.form.get('note_content') or '').strip()
    if not content or content == '<p><br></p>':
        flash('Escreva uma anotação antes de salvar.', 'warning')
        return redirect(url_for('process_panel.detail', process_id=process.id) + '#notes')

    try:
        db.session.add(
            JudicialProcessNote(
                law_firm_id=law_firm_id,
                process_id=process.id,
                user_id=user_id,
                content=content,
            )
        )
        process.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Anotação adicionada com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao adicionar anotação: {str(e)}', 'danger')

    return redirect(url_for('process_panel.detail', process_id=process.id) + '#notes')


@process_panel_bp.route('/<int:process_id>/editar', methods=['GET', 'POST'])
@require_law_firm
def edit(process_id):
    """Editar um processo judicial"""
    law_firm_id = get_current_law_firm_id()
    
    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    phase_options = JudicialPhase.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).order_by(JudicialPhase.display_order.asc(), JudicialPhase.name.asc()).all()
    valid_phase_keys = {phase.key for phase in phase_options}

    latest_event = JudicialEvent.query.filter_by(process_id=process.id).order_by(
        JudicialEvent.event_date.desc(),
        JudicialEvent.id.desc()
    ).first()
    current_phase_key = latest_event.phase if latest_event else ''
    
    if request.method == 'POST':
        selected_phase_key = request.form.get('current_phase', '').strip()
        if selected_phase_key and selected_phase_key not in valid_phase_keys:
            flash('Fase selecionada é inválida.', 'danger')
            return redirect(url_for('process_panel.edit', process_id=process.id))

        # Atualizar campos
        process.title = request.form.get('title', '').strip() or process.title
        process.description = request.form.get('description', '').strip()
        process.judge_name = request.form.get('judge_name', '').strip()
        process.tribunal = request.form.get('tribunal', '').strip()
        process.section = request.form.get('section', '').strip()
        process.origin_unit = request.form.get('origin_unit', '').strip()
        process.status = request.form.get('status', process.status)
        process.case_id = request.form.get('case_id') or None

        should_create_phase_event = bool(selected_phase_key) and selected_phase_key != current_phase_key
        
        try:
            if should_create_phase_event:
                db.session.add(
                    JudicialEvent(
                        process_id=process.id,
                        type='atualizacao_fase_manual',
                        phase=selected_phase_key,
                        description='Fase atualizada manualmente na edição do processo.',
                        event_date=datetime.utcnow(),
                    )
                )

            process.updated_at = datetime.utcnow()
            db.session.commit()
            flash('Processo atualizado com sucesso!', 'success')
            return redirect(url_for('process_panel.detail', process_id=process.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar: {str(e)}', 'danger')
    
    cases = Case.query.filter_by(law_firm_id=law_firm_id).order_by(Case.title).all()
    return render_template(
        'process_panel/form.html',
        process=process,
        cases=cases,
        action='editar',
        phase_options=phase_options,
        current_phase_key=current_phase_key,
        phase_labels=JUDICIAL_PHASES,
    )


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
