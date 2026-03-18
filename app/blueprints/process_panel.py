from flask import Blueprint, render_template, request, session, jsonify, redirect, url_for, flash
from app.models import (
    db, JudicialProcess, JudicialSentenceAnalysis, JudicialAppeal, 
    KnowledgeBase, Case, User, Court, JudicialPhase, JudicialDocumentType, JudicialEvent,
    JudicialProcessNote, Client, JudicialDefendant, JudicialDocument, JudicialProcessBenefit,
    JudicialProcessPhaseHistory, JudicialLegalThesis
)
from datetime import datetime
from functools import wraps
from sqlalchemy import or_, and_
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename
import hashlib
import os
import re
import uuid
import unicodedata

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


def _register_phase_history(
    process,
    phase,
    occurred_at,
    entered_by_user_id,
    source_event_id=None,
    notes=None,
    location_text=None,
    metadata_payload=None,
):
    """Registra um item no histórico de fases com snapshot dos dados do processo."""
    db.session.add(
        JudicialProcessPhaseHistory(
            law_firm_id=process.law_firm_id,
            process_id=process.id,
            phase_id=phase.id,
            occurred_at=occurred_at,
            recorded_at=datetime.utcnow(),
            source_event_id=source_event_id,
            judge_name_snapshot=process.judge_name,
            tribunal_snapshot=process.tribunal_name,
            section_snapshot=process.section,
            origin_unit_snapshot=process.origin_unit,
            location_text=(location_text or '').strip() or None,
            notes=(notes or '').strip() or None,
            entered_by_user_id=entered_by_user_id,
            metadata_payload=metadata_payload,
        )
    )


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


@process_panel_bp.route('/config/polos-passivos')
@require_law_firm
def manage_defendants():
    """Tela para gerenciamento de polos passivos (réus)."""
    law_firm_id = get_current_law_firm_id()

    defendants = JudicialDefendant.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(JudicialDefendant.name.asc()).all()

    return render_template(
        'process_panel/defendants_management.html',
        defendants=defendants,
    )


@process_panel_bp.route('/config/polos-passivos/criar', methods=['POST'])
@require_law_firm
def create_defendant():
    """Cria novo polo passivo (réu)."""
    law_firm_id = get_current_law_firm_id()

    name = request.form.get('name', '').strip()

    if not name:
        flash('Informe o nome do polo passivo.', 'danger')
        return redirect(url_for('process_panel.manage_defendants'))

    exists = JudicialDefendant.query.filter_by(law_firm_id=law_firm_id, name=name).first()
    if exists:
        flash(f'Já existe um polo passivo com o nome "{name}".', 'warning')
        return redirect(url_for('process_panel.manage_defendants'))

    try:
        db.session.add(
            JudicialDefendant(
                law_firm_id=law_firm_id,
                name=name,
                is_active=True,
            )
        )
        db.session.commit()
        flash('Polo passivo cadastrado com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao cadastrar polo passivo: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_defendants'))


@process_panel_bp.route('/config/polos-passivos/<int:defendant_id>/atualizar', methods=['POST'])
@require_law_firm
def update_defendant(defendant_id):
    """Atualiza polo passivo (réu)."""
    law_firm_id = get_current_law_firm_id()

    defendant = JudicialDefendant.query.filter_by(
        id=defendant_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    name = request.form.get('name', '').strip()

    if not name:
        flash('Nome do polo passivo é obrigatório.', 'danger')
        return redirect(url_for('process_panel.manage_defendants'))

    duplicated = JudicialDefendant.query.filter(
        JudicialDefendant.law_firm_id == law_firm_id,
        JudicialDefendant.name == name,
        JudicialDefendant.id != defendant.id,
    ).first()

    if duplicated:
        flash(f'Já existe outro polo passivo com o nome "{name}".', 'warning')
        return redirect(url_for('process_panel.manage_defendants'))

    try:
        defendant.name = name
        defendant.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Polo passivo atualizado com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar polo passivo: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_defendants'))


@process_panel_bp.route('/config/polos-passivos/<int:defendant_id>/status', methods=['POST'])
@require_law_firm
def toggle_defendant_status(defendant_id):
    """Ativa/desativa polo passivo (réu)."""
    law_firm_id = get_current_law_firm_id()

    defendant = JudicialDefendant.query.filter_by(
        id=defendant_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    try:
        defendant.is_active = not defendant.is_active
        defendant.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Status do polo passivo atualizado.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao alterar status do polo passivo: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_defendants'))


@process_panel_bp.route('/config/teses-juridicas')
@require_law_firm
def manage_legal_theses():
    """Tela para gerenciamento de teses jurídicas."""
    law_firm_id = get_current_law_firm_id()

    try:
        JudicialLegalThesis.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        db.session.rollback()

    legal_theses = JudicialLegalThesis.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(JudicialLegalThesis.name.asc()).all()

    return render_template(
        'process_panel/legal_theses_management.html',
        legal_theses=legal_theses,
    )


@process_panel_bp.route('/config/teses-juridicas/criar', methods=['POST'])
@require_law_firm
def create_legal_thesis():
    """Cria nova tese jurídica."""
    law_firm_id = get_current_law_firm_id()

    name = request.form.get('name', '').strip()
    key = _normalize_slug(request.form.get('key', '').strip() or name)
    description = request.form.get('description', '').strip()

    if not name or not key:
        flash('Nome e chave (slug) da tese são obrigatórios.', 'danger')
        return redirect(url_for('process_panel.manage_legal_theses'))

    exists = JudicialLegalThesis.query.filter_by(
        law_firm_id=law_firm_id,
        key=key,
    ).first()
    if exists:
        flash(f'Já existe uma tese jurídica com a chave "{key}".', 'warning')
        return redirect(url_for('process_panel.manage_legal_theses'))

    try:
        db.session.add(
            JudicialLegalThesis(
                law_firm_id=law_firm_id,
                name=name,
                key=key,
                description=description or None,
                is_active=True,
            )
        )
        db.session.commit()
        flash('Tese jurídica cadastrada com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao cadastrar tese jurídica: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_legal_theses'))


@process_panel_bp.route('/config/teses-juridicas/<int:thesis_id>/atualizar', methods=['POST'])
@require_law_firm
def update_legal_thesis(thesis_id):
    """Atualiza tese jurídica."""
    law_firm_id = get_current_law_firm_id()
    thesis = JudicialLegalThesis.query.filter_by(
        id=thesis_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    name = request.form.get('name', '').strip()
    key = _normalize_slug(request.form.get('key', '').strip())
    description = request.form.get('description', '').strip()

    if not name or not key:
        flash('Nome e chave (slug) da tese são obrigatórios.', 'danger')
        return redirect(url_for('process_panel.manage_legal_theses'))

    duplicated = JudicialLegalThesis.query.filter(
        JudicialLegalThesis.law_firm_id == law_firm_id,
        JudicialLegalThesis.key == key,
        JudicialLegalThesis.id != thesis.id,
    ).first()

    if duplicated:
        flash(f'Já existe outra tese jurídica com a chave "{key}".', 'warning')
        return redirect(url_for('process_panel.manage_legal_theses'))

    try:
        thesis.name = name
        thesis.key = key
        thesis.description = description or None
        thesis.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Tese jurídica atualizada com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar tese jurídica: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_legal_theses'))


@process_panel_bp.route('/config/teses-juridicas/<int:thesis_id>/status', methods=['POST'])
@require_law_firm
def toggle_legal_thesis_status(thesis_id):
    """Ativa/desativa tese jurídica."""
    law_firm_id = get_current_law_firm_id()
    thesis = JudicialLegalThesis.query.filter_by(
        id=thesis_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    try:
        thesis.is_active = not thesis.is_active
        thesis.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Status da tese jurídica atualizado.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao alterar status da tese jurídica: {str(e)}', 'danger')

    return redirect(url_for('process_panel.manage_legal_theses'))


@process_panel_bp.route('/')
@require_law_firm
def list_processes():
    """Lista todos os processos judiciais cadastrados"""
    law_firm_id = get_current_law_firm_id()
    
    # Filtros
    search_query = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '')
    client_filter = request.args.get('client_id', type=int)
    legal_thesis_filter = request.args.get('legal_thesis_id', type=int)
    view_mode = request.args.get('view', 'table').strip().lower()
    if view_mode not in {'table', 'kanban'}:
        view_mode = 'table'
    page = request.args.get('page', 1, type=int)
    
    query = JudicialProcess.query.filter_by(law_firm_id=law_firm_id)
    
    # Filtro por busca
    if search_query:
        query = query.outerjoin(Court, JudicialProcess.court_id == Court.id)
        query = query.filter(
            or_(
                JudicialProcess.process_number.ilike(f'%{search_query}%'),
                JudicialProcess.title.ilike(f'%{search_query}%'),
                JudicialProcess.tribunal.ilike(f'%{search_query}%'),
                Court.orgao_julgador.ilike(f'%{search_query}%'),
                Court.tribunal.ilike(f'%{search_query}%'),
                Court.secao_judiciaria.ilike(f'%{search_query}%'),
                Court.subsecao_judiciaria.ilike(f'%{search_query}%')
            )
        )
    
    # Filtro por status
    if status_filter:
        query = query.filter(JudicialProcess.status == status_filter)

    # Filtro por cliente (polo ativo)
    if client_filter:
        query = query.filter(JudicialProcess.plaintiff_client_id == client_filter)

    # Filtro por tese jurídica vinculada a benefícios do processo
    if legal_thesis_filter:
        query = query.filter(
            JudicialProcess.benefits.any(
                JudicialProcessBenefit.legal_theses.any(
                    JudicialLegalThesis.id == legal_thesis_filter
                )
            )
        )
    
    ordered_query = query.order_by(JudicialProcess.created_at.desc())

    if view_mode == 'kanban':
        processes_list = ordered_query.all()
    else:
        processes = ordered_query.paginate(page=page, per_page=15)
        processes_list = processes.items
    
    # Estatísticas
    stats = {
        'total': JudicialProcess.query.filter_by(law_firm_id=law_firm_id).count(),
        'ativo': JudicialProcess.query.filter_by(law_firm_id=law_firm_id, status='ativo').count(),
        'suspenso': JudicialProcess.query.filter_by(law_firm_id=law_firm_id, status='suspenso').count(),
        'encerrado': JudicialProcess.query.filter_by(law_firm_id=law_firm_id, status='encerrado').count(),
    }

    process_phases = {}
    process_legal_theses = {}
    process_ids = [process.id for process in processes_list]
    if process_ids:
        latest_events = JudicialEvent.query.filter(
            JudicialEvent.process_id.in_(process_ids)
        ).order_by(
            JudicialEvent.process_id.asc(),
            JudicialEvent.event_date.desc(),
            JudicialEvent.id.desc()
        ).all()

        for event in latest_events:
            if event.process_id not in process_phases:
                process_phases[event.process_id] = event.phase

        benefits_with_theses = JudicialProcessBenefit.query.options(
            selectinload(JudicialProcessBenefit.legal_theses)
        ).filter(
            JudicialProcessBenefit.process_id.in_(process_ids)
        ).all()

        thesis_names_by_process = {process_id: set() for process_id in process_ids}
        for benefit in benefits_with_theses:
            if not benefit.legal_theses:
                continue
            for thesis in benefit.legal_theses:
                thesis_names_by_process.setdefault(benefit.process_id, set()).add(thesis.name)

        process_legal_theses = {
            process_id: sorted(thesis_names)
            for process_id, thesis_names in thesis_names_by_process.items()
            if thesis_names
        }

    if view_mode == 'kanban':
        clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.name.asc()).all()
        legal_theses = JudicialLegalThesis.query.filter_by(
            law_firm_id=law_firm_id,
            is_active=True,
        ).order_by(JudicialLegalThesis.name.asc()).all()

        configured_phases = JudicialPhase.query.filter_by(
            law_firm_id=law_firm_id
        ).order_by(JudicialPhase.display_order.asc(), JudicialPhase.name.asc()).all()

        kanban_columns = []
        columns_by_key = {}

        for phase in configured_phases:
            column = {
                'key': phase.key,
                'label': phase.name,
                'processes': []
            }
            kanban_columns.append(column)
            columns_by_key[phase.key] = column

        unassigned_processes = []
        for process in processes_list:
            phase_key = process_phases.get(process.id)
            phase_column = columns_by_key.get(phase_key)
            if phase_column:
                phase_column['processes'].append(process)
            else:
                unassigned_processes.append(process)

        if unassigned_processes:
            kanban_columns.append({
                'key': '__unassigned__',
                'label': 'Sem fase',
                'processes': unassigned_processes,
            })

        return render_template(
            'process_panel/list_kanban.html',
            search_query=search_query,
            status_filter=status_filter,
            client_filter=client_filter,
            legal_thesis_filter=legal_thesis_filter,
            clients=clients,
            legal_theses=legal_theses,
            stats=stats,
            kanban_columns=kanban_columns,
            process_phases=process_phases,
            process_legal_theses=process_legal_theses,
            current_view=view_mode,
        )

    legal_theses = JudicialLegalThesis.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True,
    ).order_by(JudicialLegalThesis.name.asc()).all()

    return render_template(
        'process_panel/list.html',
        processes=processes,
        search_query=search_query,
        status_filter=status_filter,
        client_filter=client_filter,
        legal_thesis_filter=legal_thesis_filter,
        legal_theses=legal_theses,
        stats=stats,
        process_phases=process_phases,
        process_legal_theses=process_legal_theses,
        judicial_phases_labels=JUDICIAL_PHASES,
        current_view=view_mode,
    )


@process_panel_bp.route('/novo', methods=['GET', 'POST'])
@require_law_firm
def new_process():
    """Criar processo simplificado (número CNJ + documentos para base de conhecimento)."""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')
    
    if request.method == 'POST':
        process_number = request.form.get('process_number', '').strip().upper() or None
        if not process_number:
            process_number = f'TEMP-{uuid.uuid4().hex[:8].upper()}'
        plaintiff_client_id = request.form.get('plaintiff_client_id', type=int)
        defendant_id = request.form.get('defendant_id', type=int)
        uploaded_files = [
            file for file in request.files.getlist('documents')
            if file and file.filename and file.filename.strip()
        ]

        plaintiff_client = None
        if plaintiff_client_id:
            plaintiff_client = Client.query.filter_by(
                id=plaintiff_client_id,
                law_firm_id=law_firm_id
            ).first()
            if not plaintiff_client:
                flash('Polo ativo (cliente) inválido.', 'danger')
                return redirect(url_for('process_panel.new_process'))

        defendant = None
        if defendant_id:
            defendant = JudicialDefendant.query.filter_by(
                id=defendant_id,
                law_firm_id=law_firm_id
            ).first()
            if not defendant:
                flash('Polo passivo (réu) inválido.', 'danger')
                return redirect(url_for('process_panel.new_process'))

        if not uploaded_files:
            flash('Envie ao menos um documento para a base de conhecimento.', 'danger')
            return redirect(url_for('process_panel.new_process'))

        # Verificar duplicata apenas se o número foi informado
        if process_number:
            existing = JudicialProcess.query.filter_by(
                law_firm_id=law_firm_id,
                process_number=process_number
            ).first()

            if existing:
                flash(f'Processo {process_number} já existe', 'danger')
                return redirect(url_for('process_panel.new_process'))
        
        # Criar novo processo
        try:
            process_label = process_number or '(sem número)'
            new_proc = JudicialProcess(
                law_firm_id=law_firm_id,
                user_id=user_id,
                process_number=process_number,
                title=process_number,
                status='ativo',
                plaintiff_client_id=plaintiff_client.id if plaintiff_client else None,
                defendant_id=defendant.id if defendant else None,
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
                    file_hash=file_hash,
                    is_active=True
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
                    f'Processo {process_label} criado. {uploaded_count} documento(s) enviado(s) e {duplicates_count} duplicado(s) ignorado(s).',
                    'success'
                )
            else:
                flash(
                    f'Processo {process_label} criado com sucesso! {uploaded_count} documento(s) enviado(s) para a base de conhecimento.',
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
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.name.asc()).all()
    defendants = JudicialDefendant.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).order_by(JudicialDefendant.name.asc()).all()

    return render_template(
        'process_panel/form_new_simple.html',
        action='novo',
        clients=clients,
        defendants=defendants,
    )


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

    phase_history = JudicialProcessPhaseHistory.query.filter_by(
        process_id=process.id,
        law_firm_id=law_firm_id
    ).order_by(
        JudicialProcessPhaseHistory.occurred_at.desc(),
        JudicialProcessPhaseHistory.id.desc()
    ).all()

    process_benefits = JudicialProcessBenefit.query.options(
        selectinload(JudicialProcessBenefit.legal_theses)
    ).filter_by(
        process_id=process.id
    ).order_by(JudicialProcessBenefit.created_at.desc(), JudicialProcessBenefit.id.desc()).all()

    legal_theses = JudicialLegalThesis.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True,
    ).order_by(JudicialLegalThesis.name.asc()).all()

    benefits_grouped_by_thesis = []
    for thesis in legal_theses:
        thesis_benefits = [
            benefit for benefit in process_benefits
            if any(linked_thesis.id == thesis.id for linked_thesis in benefit.legal_theses)
        ]
        if thesis_benefits:
            benefits_grouped_by_thesis.append({
                'id': thesis.id,
                'name': thesis.name,
                'benefits': thesis_benefits,
                'is_unassigned': False,
            })

    unassigned_benefits = [benefit for benefit in process_benefits if not benefit.legal_theses]
    if unassigned_benefits:
        benefits_grouped_by_thesis.append({
            'id': 'unassigned',
            'name': 'Sem tese vinculada',
            'benefits': unassigned_benefits,
            'is_unassigned': True,
        })
    
    # Buscar documentos da knowledge base com o mesmo process_number
    # Pesquisar com e sem pontuação
    if process.process_number:
        process_number_clean = ''.join(c for c in process.process_number if c.isdigit())
        kb_documents = KnowledgeBase.query.filter(
            KnowledgeBase.law_firm_id == law_firm_id,
            KnowledgeBase.is_active.is_(True),
            or_(
                KnowledgeBase.lawsuit_number == process.process_number,
                KnowledgeBase.lawsuit_number == process_number_clean,
                db.func.replace(db.func.replace(db.func.replace(
                    KnowledgeBase.lawsuit_number, '-', ''), '.', ''), ' ', ''
                ) == process_number_clean
            )
        ).all()
    else:
        kb_documents = []

    configured_phases = JudicialPhase.query.filter_by(law_firm_id=law_firm_id).all()
    phase_labels_by_key = {phase.key: phase.name for phase in configured_phases}
    phase_order_by_key = {phase.key: (phase.display_order or 0) for phase in configured_phases}

    configured_document_types = JudicialDocumentType.query.filter_by(law_firm_id=law_firm_id).all()
    document_type_labels_by_key = {doc_type.key: doc_type.name for doc_type in configured_document_types}

    judicial_documents = JudicialDocument.query.filter_by(
        process_id=process.id
    ).order_by(JudicialDocument.created_at.desc(), JudicialDocument.id.desc()).all()

    judicial_documents_by_kb = {}
    for judicial_doc in judicial_documents:
        if judicial_doc.knowledge_base_id and judicial_doc.knowledge_base_id not in judicial_documents_by_kb:
            judicial_documents_by_kb[judicial_doc.knowledge_base_id] = judicial_doc

    documents_list = []

    for kb_doc in kb_documents:
        judicial_doc = judicial_documents_by_kb.get(kb_doc.id)

        phase_key = judicial_doc.event.phase if judicial_doc and judicial_doc.event else None
        phase_label = None
        if phase_key:
            phase_label = phase_labels_by_key.get(
                phase_key,
                JUDICIAL_PHASES.get(phase_key, phase_key.replace('_', ' ').title())
            )

        doc_type_key = judicial_doc.type if judicial_doc else None
        doc_type_label = None
        if doc_type_key:
            doc_type_label = document_type_labels_by_key.get(
                doc_type_key,
                doc_type_key.replace('_', ' ').title()
            )

        documents_list.append({
            'filename': kb_doc.original_filename,
            'category': kb_doc.category,
            'uploaded_at': kb_doc.uploaded_at,
            'phase_label': phase_label,
            'doc_type_label': doc_type_label,
            'knowledge_base_id': kb_doc.id,
            'judicial_document_id': judicial_doc.id if judicial_doc else None,
            'phase_order': phase_order_by_key.get(phase_key, 9999),
        })

    for judicial_doc in judicial_documents:
        if judicial_doc.knowledge_base_id:
            continue

        phase_key = judicial_doc.event.phase if judicial_doc.event else None
        phase_label = None
        if phase_key:
            phase_label = phase_labels_by_key.get(
                phase_key,
                JUDICIAL_PHASES.get(phase_key, phase_key.replace('_', ' ').title())
            )

        doc_type_key = judicial_doc.type
        doc_type_label = document_type_labels_by_key.get(
            doc_type_key,
            doc_type_key.replace('_', ' ').title() if doc_type_key else None
        )

        documents_list.append({
            'filename': judicial_doc.file_name,
            'category': None,
            'uploaded_at': judicial_doc.created_at,
            'phase_label': phase_label,
            'doc_type_label': doc_type_label,
            'knowledge_base_id': None,
            'judicial_document_id': judicial_doc.id,
            'phase_order': phase_order_by_key.get(phase_key, 9999),
        })

    documents_list.sort(
        key=lambda item: (
            item.get('phase_order', 9999),
            (item.get('filename') or '').lower(),
        )
    )
    
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
        'phase_history': phase_history,
        'phase_options': sorted(
            configured_phases,
            key=lambda item: ((item.display_order or 0), (item.name or '').lower())
        ),
        'process_benefits': process_benefits,
        'benefits_grouped_by_thesis': benefits_grouped_by_thesis,
        'legal_theses': legal_theses,
        'kb_documents': kb_documents,
        'documents_list': documents_list,
        'case': process.case if process.case_id else None,
        'stats': {
            'analyses_count': len(related_analyses),
            'appeals_count': len(related_appeals),
            'documents_count': len(documents_list),
            'benefits_count': len(process_benefits),
        }
    }
    
    return render_template('process_panel/detail.html', **data)


@process_panel_bp.route('/<int:process_id>/analises-sentenca/enfileirar', methods=['POST'])
@require_law_firm
def queue_sentence_analyses_for_process(process_id):
    """Enfileira sentenças do processo atual para análise de IA."""
    law_firm_id = get_current_law_firm_id()
    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    def _normalize_doc_type(value: str | None) -> str:
        normalized = unicodedata.normalize('NFKD', str(value or '').strip().lower())
        return ''.join(ch for ch in normalized if not unicodedata.combining(ch))

    def _is_sentence_document(doc_type: str | None) -> bool:
        normalized = _normalize_doc_type(doc_type)
        return 'sentenca' in normalized

    def _is_initial_petition_document(doc_type: str | None) -> bool:
        normalized = _normalize_doc_type(doc_type)
        return 'peticao' in normalized and 'inicial' in normalized

    def _resolve_existing_file_path(doc: JudicialDocument) -> str | None:
        current_path = str(doc.file_path or '').strip()
        if current_path and os.path.exists(current_path):
            return current_path

        if doc.knowledge_base and doc.knowledge_base.file_path:
            kb_path = str(doc.knowledge_base.file_path).strip()
            if kb_path and os.path.exists(kb_path):
                doc.file_path = kb_path
                return kb_path

        return None

    try:
        process_documents = JudicialDocument.query.filter_by(process_id=process.id).order_by(
            JudicialDocument.created_at.desc()
        ).all()

        sentence_docs = [doc for doc in process_documents if _is_sentence_document(doc.type)]
        petition_doc = next((doc for doc in process_documents if _is_initial_petition_document(doc.type)), None)

        if not sentence_docs:
            flash('Este processo não possui documentos do tipo sentença para análise.', 'warning')
            return redirect(url_for('process_panel.detail', process_id=process.id) + '#analyses')

        queued = 0
        skipped = 0
        skipped_missing = 0
        skipped_existing = 0

        for sentence_doc in sentence_docs:
            sentence_path = _resolve_existing_file_path(sentence_doc)
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

            petition_path = _resolve_existing_file_path(petition_doc) if petition_doc else None
            if petition_doc and petition_path:
                petition_ext = os.path.splitext(petition_doc.file_name or '')[1].lower().replace('.', '')
                sentence.petition_filename = petition_doc.file_name
                sentence.petition_file_path = petition_path
                sentence.petition_file_size = os.path.getsize(petition_path)
                sentence.petition_file_type = petition_ext.upper() if petition_ext else ''

            db.session.add(sentence)
            queued += 1

        if queued == 0:
            db.session.rollback()
            flash(
                'Nenhuma nova sentença foi enfileirada. '
                f'Ignoradas por arquivo ausente: {skipped_missing}. '
                f'Ignoradas por já cadastradas: {skipped_existing}.',
                'info'
            )
            return redirect(url_for('process_panel.detail', process_id=process.id) + '#analyses')

        db.session.commit()
        flash(
            f'Processo enviado para análise! {queued} sentença(s) enfileirada(s) '
            f'e {skipped} arquivo(s) ignorado(s).',
            'success'
        )
        return redirect(url_for('process_panel.detail', process_id=process.id) + '#analyses')

    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao enfileirar análises do processo: {str(e)}', 'danger')
        return redirect(url_for('process_panel.detail', process_id=process.id) + '#analyses')


@process_panel_bp.route('/<int:process_id>/documentos/novo', methods=['GET', 'POST'])
@require_law_firm
def new_process_document(process_id):
    """Tela própria para adicionar documento ao processo e à base de conhecimento."""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    try:
        _ensure_judicial_config_defaults(law_firm_id)
    except Exception:
        db.session.rollback()

    document_types = JudicialDocumentType.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).join(JudicialPhase, JudicialPhase.id == JudicialDocumentType.phase_id).order_by(
        JudicialPhase.display_order.asc(),
        JudicialDocumentType.display_order.asc(),
        JudicialDocumentType.name.asc()
    ).all()

    if request.method == 'POST':
        doc_type_id = request.form.get('document_type_id', type=int)
        description = request.form.get('description', '').strip()
        file = request.files.get('document')

        if not doc_type_id:
            flash('Selecione o tipo de documento.', 'danger')
            return redirect(url_for('process_panel.new_process_document', process_id=process.id))

        if not file or not file.filename or not file.filename.strip():
            flash('Selecione um arquivo para upload.', 'danger')
            return redirect(url_for('process_panel.new_process_document', process_id=process.id))

        document_type = JudicialDocumentType.query.filter_by(
            id=doc_type_id,
            law_firm_id=law_firm_id,
            is_active=True
        ).first()

        if not document_type:
            flash('Tipo de documento inválido.', 'danger')
            return redirect(url_for('process_panel.new_process_document', process_id=process.id))

        saved_file_path = None

        try:
            upload_dir = os.path.join('uploads', 'knowledge_base', str(law_firm_id), f'process_{process.id}')
            os.makedirs(upload_dir, exist_ok=True)

            original_filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            name, ext = os.path.splitext(original_filename)
            filename_with_timestamp = f"{name}_{timestamp}{ext}"
            saved_file_path = os.path.join(upload_dir, filename_with_timestamp)

            file_hash = _compute_file_hash(file)
            file.save(saved_file_path)

            file_size = os.path.getsize(saved_file_path)
            file_type = ext.lstrip('.').upper() if ext else 'DESCONHECIDO'

            kb_entry = KnowledgeBase(
                user_id=user_id,
                law_firm_id=law_firm_id,
                original_filename=original_filename,
                file_path=saved_file_path,
                file_size=file_size,
                file_type=file_type,
                file_hash=file_hash,
                description=description,
                category=document_type.phase.name if document_type.phase else '',
                tags=document_type.name,
                lawsuit_number=process.process_number,
                processing_status='pending',
            )
            db.session.add(kb_entry)
            db.session.flush()

            event = JudicialEvent(
                process_id=process.id,
                type=document_type.key,
                phase=document_type.phase.key,
                description=(
                    f'Documento {document_type.name} adicionado ao processo.'
                    if not description else description
                ),
                event_date=datetime.utcnow(),
            )
            db.session.add(event)
            db.session.flush()

            if document_type.phase:
                _register_phase_history(
                    process=process,
                    phase=document_type.phase,
                    occurred_at=event.event_date,
                    entered_by_user_id=user_id,
                    source_event_id=event.id,
                    notes=f'Fase registrada automaticamente ao adicionar documento: {document_type.name}.',
                    metadata_payload={
                        'origin': 'new_process_document',
                        'document_type_key': document_type.key,
                    },
                )

            db.session.add(
                JudicialDocument(
                    process_id=process.id,
                    event_id=event.id,
                    knowledge_base_id=kb_entry.id,
                    type=document_type.key,
                    file_name=original_filename,
                    file_path=saved_file_path,
                    uploaded_by=user_id,
                )
            )

            process.updated_at = datetime.utcnow()
            db.session.commit()

            flash('Documento adicionado ao processo com sucesso.', 'success')
            return redirect(url_for('process_panel.detail', process_id=process.id) + '#documents')
        except Exception as e:
            db.session.rollback()
            if saved_file_path and os.path.exists(saved_file_path):
                os.remove(saved_file_path)
            flash(f'Erro ao adicionar documento: {str(e)}', 'danger')
            return redirect(url_for('process_panel.new_process_document', process_id=process.id))

    return render_template(
        'process_panel/document_form.html',
        process=process,
        document_types=document_types,
    )


@process_panel_bp.route('/<int:process_id>/beneficios/<int:benefit_id>/tese', methods=['POST'])
@require_law_firm
def update_process_benefit_legal_thesis(process_id, benefit_id):
    """Atualiza as teses jurídicas vinculadas a um benefício do processo."""
    law_firm_id = get_current_law_firm_id()

    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    benefit = JudicialProcessBenefit.query.filter_by(
        id=benefit_id,
        process_id=process.id,
    ).first_or_404()

    thesis_ids = sorted({
        thesis_id
        for thesis_id in request.form.getlist('legal_thesis_ids', type=int)
        if thesis_id
    })

    theses = []
    if thesis_ids:
        theses = JudicialLegalThesis.query.filter(
            JudicialLegalThesis.id.in_(thesis_ids),
            JudicialLegalThesis.law_firm_id == law_firm_id,
            JudicialLegalThesis.is_active.is_(True),
        ).order_by(JudicialLegalThesis.name.asc()).all()

        if len(theses) != len(thesis_ids):
            flash('Uma ou mais teses jurídicas selecionadas são inválidas para este escritório.', 'danger')
            return redirect(url_for('process_panel.detail', process_id=process.id) + '#benefits')

    benefit.legal_theses = theses
    benefit.legal_thesis_id = theses[0].id if theses else None

    try:
        benefit.updated_at = datetime.utcnow()
        process.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Teses jurídicas do benefício atualizadas com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar teses jurídicas do benefício: {str(e)}', 'danger')

    return redirect(url_for('process_panel.detail', process_id=process.id) + '#benefits')


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


@process_panel_bp.route('/<int:process_id>/phase', methods=['POST'])
@require_law_firm
def update_process_phase_kanban(process_id):
    """Atualiza a fase do processo via interação no Kanban."""
    law_firm_id = get_current_law_firm_id()

    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    payload = request.get_json(silent=True) or {}
    new_phase_key = (payload.get('phase_key') or '').strip()

    if not new_phase_key:
        return jsonify({'success': False, 'error': 'Fase inválida'}), 400

    phase = JudicialPhase.query.filter_by(
        law_firm_id=law_firm_id,
        key=new_phase_key,
        is_active=True
    ).first()

    if not phase:
        return jsonify({'success': False, 'error': 'Fase não encontrada'}), 404

    latest_event = JudicialEvent.query.filter_by(process_id=process.id).order_by(
        JudicialEvent.event_date.desc(),
        JudicialEvent.id.desc()
    ).first()
    current_phase_key = latest_event.phase if latest_event else None

    if current_phase_key == new_phase_key:
        return jsonify({'success': True, 'message': 'Fase já está atualizada'})

    try:
        event = JudicialEvent(
            process_id=process.id,
            type='atualizacao_fase_kanban',
            phase=new_phase_key,
            description='Fase atualizada por arrastar e soltar no Kanban.',
            event_date=datetime.utcnow(),
        )
        db.session.add(event)
        db.session.flush()

        _register_phase_history(
            process=process,
            phase=phase,
            occurred_at=event.event_date,
            entered_by_user_id=session.get('user_id'),
            source_event_id=event.id,
            notes='Fase atualizada via Kanban (arrastar e soltar).',
            location_text='Kanban',
            metadata_payload={
                'origin': 'kanban',
                'previous_phase_key': current_phase_key,
                'new_phase_key': new_phase_key,
            },
        )

        process.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({
            'success': True,
            'phase_key': new_phase_key,
            'phase_label': phase.name,
            'history_recorded': True,
            'message': 'Fase atualizada e registrada no histórico.',
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


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
        plaintiff_client_id = request.form.get('plaintiff_client_id', type=int)
        defendant_id = request.form.get('defendant_id', type=int)
        court_id = request.form.get('court_id', type=int)

        if selected_phase_key and selected_phase_key not in valid_phase_keys:
            flash('Fase selecionada é inválida.', 'danger')
            return redirect(url_for('process_panel.edit', process_id=process.id))

        if plaintiff_client_id:
            plaintiff_client = Client.query.filter_by(
                id=plaintiff_client_id,
                law_firm_id=law_firm_id
            ).first()
            if not plaintiff_client:
                flash('Polo ativo (cliente) inválido.', 'danger')
                return redirect(url_for('process_panel.edit', process_id=process.id))

        if defendant_id:
            defendant = JudicialDefendant.query.filter_by(
                id=defendant_id,
                law_firm_id=law_firm_id
            ).first()
            if not defendant:
                flash('Polo passivo (réu) inválido.', 'danger')
                return redirect(url_for('process_panel.edit', process_id=process.id))

        selected_court = None
        if court_id:
            selected_court = Court.query.filter_by(
                id=court_id,
                law_firm_id=law_firm_id,
            ).first()
            if not selected_court:
                flash('Tribunal inválido.', 'danger')
                return redirect(url_for('process_panel.edit', process_id=process.id))

        # Permitir substituição de identificador temporário pelo número real
        if process.process_number and process.process_number.startswith('TEMP-'):
            new_number = request.form.get('process_number', '').strip().upper()
            if new_number and not new_number.startswith('TEMP-'):
                existing = JudicialProcess.query.filter(
                    JudicialProcess.id != process.id,
                    JudicialProcess.law_firm_id == law_firm_id,
                    JudicialProcess.process_number == new_number
                ).first()
                if existing:
                    flash(f'Processo {new_number} já existe.', 'danger')
                    return redirect(url_for('process_panel.edit', process_id=process.id))
                process.process_number = new_number

        # Atualizar campos
        process.title = request.form.get('title', '').strip() or process.title
        process.description = request.form.get('description', '').strip()
        process.judge_name = request.form.get('judge_name', '').strip()
        process.court_id = court_id or None
        process.tribunal = selected_court.orgao_julgador if selected_court else None
        process.section = request.form.get('section', '').strip()
        process.origin_unit = request.form.get('origin_unit', '').strip()
        process.status = request.form.get('status', process.status)
        process.case_id = request.form.get('case_id') or None
        process.plaintiff_client_id = plaintiff_client_id or None
        process.defendant_id = defendant_id or None

        # Campos extras
        process.process_class = request.form.get('process_class', '').strip() or None
        process.valor_causa_texto = request.form.get('valor_causa_texto', '').strip() or None
        assuntos_raw = request.form.get('assuntos_texto', '').strip()
        process.assuntos = [a.strip() for a in assuntos_raw.split(',') if a.strip()] if assuntos_raw else None
        segredo_raw = request.form.get('segredo_justica', '')
        process.segredo_justica = (segredo_raw == '1') if segredo_raw in ('0', '1') else None
        gratuita_raw = request.form.get('justica_gratuita', '')
        process.justica_gratuita = (gratuita_raw == '1') if gratuita_raw in ('0', '1') else None
        liminar_raw = request.form.get('liminar_tutela', '')
        process.liminar_tutela = (liminar_raw == '1') if liminar_raw in ('0', '1') else None

        should_create_phase_event = bool(selected_phase_key) and selected_phase_key != current_phase_key
        
        try:
            if should_create_phase_event:
                selected_phase = JudicialPhase.query.filter_by(
                    law_firm_id=law_firm_id,
                    key=selected_phase_key,
                    is_active=True
                ).first()

                event = JudicialEvent(
                    process_id=process.id,
                    type='atualizacao_fase_manual',
                    phase=selected_phase_key,
                    description='Fase atualizada manualmente na edição do processo.',
                    event_date=datetime.utcnow(),
                )
                db.session.add(event)
                db.session.flush()

                if selected_phase:
                    _register_phase_history(
                        process=process,
                        phase=selected_phase,
                        occurred_at=event.event_date,
                        entered_by_user_id=session.get('user_id'),
                        source_event_id=event.id,
                        notes='Fase atualizada manualmente na edição do processo.',
                        metadata_payload={'origin': 'edit_form'},
                    )

            process.updated_at = datetime.utcnow()
            db.session.commit()
            flash('Processo atualizado com sucesso!', 'success')
            return redirect(url_for('process_panel.detail', process_id=process.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar: {str(e)}', 'danger')
    
    cases = Case.query.filter_by(law_firm_id=law_firm_id).order_by(Case.title).all()
    courts = Court.query.filter_by(law_firm_id=law_firm_id).order_by(Court.orgao_julgador.asc()).all()
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.name.asc()).all()
    defendants = JudicialDefendant.query.filter_by(
        law_firm_id=law_firm_id
    ).order_by(JudicialDefendant.name.asc()).all()

    return render_template(
        'process_panel/form.html',
        process=process,
        cases=cases,
        courts=courts,
        clients=clients,
        defendants=defendants,
        action='editar',
        phase_options=phase_options,
        current_phase_key=current_phase_key,
        phase_labels=JUDICIAL_PHASES,
    )


@process_panel_bp.route('/<int:process_id>/phase-history', methods=['POST'])
@require_law_firm
def create_process_phase_history(process_id):
    """Registra manualmente um item no histórico de fase do processo."""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id
    ).first_or_404()

    phase_id = request.form.get('phase_id', type=int)
    occurred_at_raw = (request.form.get('occurred_at') or '').strip()
    location_text = (request.form.get('location_text') or '').strip()
    notes = (request.form.get('notes') or '').strip()

    if not phase_id:
        flash('Selecione uma fase para registrar no histórico.', 'warning')
        return redirect(url_for('process_panel.detail', process_id=process.id) + '#phase-history')

    phase = JudicialPhase.query.filter_by(
        id=phase_id,
        law_firm_id=law_firm_id,
        is_active=True
    ).first()

    if not phase:
        flash('Fase selecionada é inválida.', 'danger')
        return redirect(url_for('process_panel.detail', process_id=process.id) + '#phase-history')

    if not occurred_at_raw:
        flash('Informe a data/hora de ocorrência da fase.', 'warning')
        return redirect(url_for('process_panel.detail', process_id=process.id) + '#phase-history')

    try:
        occurred_at = datetime.strptime(occurred_at_raw, '%Y-%m-%dT%H:%M')
    except ValueError:
        flash('Data/hora inválida para o histórico de fase.', 'danger')
        return redirect(url_for('process_panel.detail', process_id=process.id) + '#phase-history')

    try:
        _register_phase_history(
            process=process,
            phase=phase,
            occurred_at=occurred_at,
            entered_by_user_id=user_id,
            notes=notes,
            location_text=location_text,
            metadata_payload={'origin': 'manual_form'},
        )

        process.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Histórico de fase registrado com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao registrar histórico de fase: {str(e)}', 'danger')

    return redirect(url_for('process_panel.detail', process_id=process.id) + '#phase-history')


@process_panel_bp.route('/<int:process_id>/documentos/<int:doc_id>/deletar', methods=['POST'])
@require_law_firm
def delete_process_document(process_id, doc_id):
    """Deletar um documento vinculado ao processo"""
    from app.agents.knowledge_base.knowledge_ingestion_agent import KnowledgeIngestionAgent
    
    law_firm_id = get_current_law_firm_id()
    
    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id
    ).first_or_404()
    
    judicial_doc = JudicialDocument.query.filter_by(
        id=doc_id,
        process_id=process_id
    ).first_or_404()
    
    try:
        # Se o documento está vinculado a um arquivo da base de conhecimento,
        # remover também dos índices (Qdrant e Meilisearch)
        if judicial_doc.knowledge_base_id:
            KnowledgeIngestionAgent(
                require_embeddings=False,
                create_missing_indexes=False,
            ).delete_document_by_file_id(judicial_doc.knowledge_base_id)
        
        # Deletar o registro do documento judicial
        db.session.delete(judicial_doc)
        db.session.commit()
        
        flash('Documento removido do processo com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao remover documento: {str(e)}', 'danger')
    
    return redirect(url_for('process_panel.detail', process_id=process.id) + '#documents')


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
