from flask import Blueprint, render_template, request, session, jsonify, redirect, url_for, flash, send_file
from meilisearch_python_sdk import Client as MeilisearchClient
from app.models import (
    db, JudicialProcess,
    KnowledgeBase, Case, User, Court, JudicialPhase, JudicialDocumentType, JudicialEvent,
    JudicialProcessNote, Client, JudicialDefendant, JudicialDocument, JudicialDocumentSummary,
    JudicialProcessBenefit, JudicialProcessPhaseHistory, JudicialLegalThesis, JudicialProcessCitedBenefit,
    JudicialProcessBenefitThesisContestation, JudicialProcessAttachment,
    JudicialProcessGeneratedDocument, JudicialProcessGeneratedDocumentVersion,
    JudicialProcessGeneratedDocumentSelection,
)
from app.agents.legal_drafting.agent_generated_document import AgentGeneratedDocument, DOCUMENT_TYPE_LABELS
from app.agents.legal_drafting.document_docx_export_agent import OfficeDocxExportAgent
from app.agents.legal_drafting.impugnacao_enrichment_agent import ImpugnacaoEnrichmentAgent
from datetime import datetime
from functools import wraps
from sqlalchemy import or_, and_
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename
from types import SimpleNamespace
from collections import defaultdict
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
    "replica": {"name": "Impugnação à Contestação", "phase": "manifestacao_autor"},
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
    "decisao_ed": {"name": "Decisão de ED", "phase": "recursos"},
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


def _resolve_latest_contestation_pdf_path(process):
    """Retorna o caminho do PDF de contestação mais recente do processo."""
    contestation_doc = JudicialDocument.query.filter_by(
        process_id=process.id,
        type='contestacao',
    ).order_by(JudicialDocument.created_at.desc(), JudicialDocument.id.desc()).first()

    if not contestation_doc:
        raise ValueError(
            'Não foi encontrado documento de contestação no processo. '
            'Faça o upload da contestação em PDF antes de gerar a impugnação.'
        )

    primary_path = str(contestation_doc.file_path or '').strip()
    if primary_path and os.path.exists(primary_path):
        resolved_path = primary_path
    else:
        kb_path = ''
        if contestation_doc.knowledge_base and contestation_doc.knowledge_base.file_path:
            kb_path = str(contestation_doc.knowledge_base.file_path or '').strip()

        if kb_path and os.path.exists(kb_path):
            resolved_path = kb_path
        else:
            raise FileNotFoundError(
                'Arquivo de contestação não encontrado no servidor para este processo.'
            )

    extension = os.path.splitext(resolved_path)[1].lower()
    if extension != '.pdf':
        raise ValueError(
            'A contestação vinculada ao processo precisa estar em PDF para geração da impugnação.'
        )

    return resolved_path


def _resolve_latest_contestation_summary_payload(process, law_firm_id):
    """Retorna payload estruturado do resumo da contestação mais recente."""
    contestation_doc = JudicialDocument.query.filter_by(
        process_id=process.id,
        type='contestacao',
    ).order_by(JudicialDocument.created_at.desc(), JudicialDocument.id.desc()).first()

    if not contestation_doc:
        raise ValueError(
            'Não foi encontrado documento de contestação no processo. '
            'Faça o upload da contestação para gerar o resumo e então criar a impugnação.'
        )

    summary = JudicialDocumentSummary.query.filter_by(
        judicial_document_id=contestation_doc.id,
        law_firm_id=law_firm_id,
    ).first()

    if not summary:
        raise ValueError(
            'Resumo da contestação não encontrado. '
            'Gere o resumo da contestação antes de criar a impugnação.'
        )

    payload = summary.summary_payload if isinstance(summary.summary_payload, dict) else {}
    summary_text = str(summary.summary_text or '').strip()
    summary_short = str(payload.get('summary_short') or '').strip()
    summary_long = str(payload.get('summary_long') or payload.get('summary') or '').strip()
    requests = [str(item).strip() for item in (payload.get('requests') or []) if str(item).strip()]
    key_points = [str(item).strip() for item in (payload.get('key_points') or []) if str(item).strip()]
    union_arguments_by_thesis = payload.get('union_arguments_by_thesis')
    if not isinstance(union_arguments_by_thesis, list):
        union_arguments_by_thesis = []
    notes = str(payload.get('notes') or '').strip()

    has_minimum_context = bool(summary_text or summary_short or summary_long or requests or key_points)
    if not has_minimum_context:
        raise ValueError(
            'Resumo da contestação ainda está vazio. '
            'Finalize o processamento da contestação e tente novamente.'
        )

    return {
        'source_filename': str(contestation_doc.file_name or '').strip(),
        'source_document_type_key': str(contestation_doc.type or '').strip(),
        'source_document_kind': 'Contestação',
        'source_origin': 'Arquivo',
        'summary_text': summary_text,
        'summary_short': summary_short,
        'summary_long': summary_long,
        'requests': requests,
        'key_points': key_points,
        'union_arguments_by_thesis': union_arguments_by_thesis,
        'summary_document_type': str(payload.get('document_type') or '').strip(),
        'summary_file_type': str(payload.get('file_type') or '').strip(),
        'notes': notes,
        'document_event_identifier': str(
            payload.get('document_event_identifier')
            or contestation_doc.event_identifier
            or ''
        ).strip(),
        'summary_status': summary.status,
        'summary_processed_at': summary.processed_at.isoformat() if summary.processed_at else None,
        'judicial_document_id': contestation_doc.id,
    }


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


@process_panel_bp.route('/beneficios')
@require_law_firm
def list_all_benefits():
    """Lista todos os benefícios de processos judiciais do escritório."""
    law_firm_id = get_current_law_firm_id()
    
    # Filtros
    search_query = request.args.get('q', '').strip()
    client_filter = request.args.get('client_id', type=int)
    decision_filter = request.args.get('decision', '').strip()
    page = request.args.get('page', 1, type=int)
    
    # Busca todos os benefícios do escritório com preload dos relacionamentos necessários
    benefits_query = (
        JudicialProcessBenefit.query
        .join(JudicialProcess)
        .filter(JudicialProcess.law_firm_id == law_firm_id)
        .filter(JudicialProcessBenefit.benefit_number.isnot(None))  # Apenas benefícios com número
        .filter(JudicialProcessBenefit.benefit_number != '')
        .options(
            selectinload(JudicialProcessBenefit.process).selectinload(JudicialProcess.plaintiff_client),
            selectinload(JudicialProcessBenefit.legal_theses)
        )
    )
    
    # Filtro por busca no nome do beneficiário, NIT ou número do benefício
    if search_query:
        benefits_query = benefits_query.filter(
            or_(
                JudicialProcessBenefit.insured_name.ilike(f'%{search_query}%'),
                JudicialProcessBenefit.nit_number.ilike(f'%{search_query}%'),
                JudicialProcessBenefit.benefit_number.ilike(f'%{search_query}%'),
            )
        )
    
    # Filtro por cliente (polo ativo do processo)
    if client_filter:
        benefits_query = benefits_query.filter(
            JudicialProcess.plaintiff_client_id == client_filter
        )
    
    # Buscar todos os benefícios (sem paginação inicial para agrupamento)
    all_benefits = benefits_query.order_by(JudicialProcessBenefit.benefit_number.asc()).all()
    
    # Agrupar por número do benefício
    grouped_benefits = defaultdict(list)
    for benefit in all_benefits:
        grouped_benefits[benefit.benefit_number].append(benefit)
    
    # Criar lista de grupos ordenada
    benefit_groups = []
    for benefit_number, benefits_list in grouped_benefits.items():
        # Pegar informações do primeiro benefício para dados principais
        main_benefit = benefits_list[0]
        thesis_names = sorted({thesis.name for benefit in benefits_list for thesis in benefit.legal_theses})
        
        # Calcular estatísticas do grupo
        group_stats = {
            'total_processes': len(benefits_list),
            'procedentes': len([b for b in benefits_list if (b.first_instance_decision or '').lower().find('procedente') != -1]),
            'improcedentes': len([b for b in benefits_list if (b.first_instance_decision or '').lower().find('improcedente') != -1]),
        }
        
        benefit_groups.append({
            'benefit_number': benefit_number,
            'main_benefit': main_benefit,
            'benefits_count': len(benefits_list),
            'group_stats': group_stats,
            'thesis_names': thesis_names,
            'benefits': benefits_list
        })
    
    # Filtro por resultado de decisão (qualquer instância)
    if decision_filter:
        def _decision_matches(val):
            v = (val or '').lower().strip()
            if decision_filter == 'procedente':
                return v in ('procedente', 'aceito') or (v.startswith('procedente') and 'improcedente' not in v)
            elif decision_filter == 'improcedente':
                return 'improcedente' in v
            elif decision_filter == 'nao_mencionado':
                return 'mencionado' in v
            return False

        def _group_matches_decision(group):
            return any(
                _decision_matches(b.first_instance_decision)
                or _decision_matches(b.second_instance_decision)
                or _decision_matches(b.third_instance_decision)
                for b in group['benefits']
            )

        benefit_groups = [g for g in benefit_groups if _group_matches_decision(g)]

    # Paginação dos grupos
    per_page = 20  # 20 grupos de benefícios por página
    total_groups = len(benefit_groups)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_groups = benefit_groups[start_idx:end_idx]
    
    # Simular objeto de paginação
    pagination = SimpleNamespace(
        page=page,
        per_page=per_page,
        total=total_groups,
        pages=(total_groups + per_page - 1) // per_page,
        has_prev=page > 1,
        has_next=page < ((total_groups + per_page - 1) // per_page),
        prev_num=page - 1 if page > 1 else None,
        next_num=page + 1 if page < ((total_groups + per_page - 1) // per_page) else None,
        items=paginated_groups
    )
    pagination.iter_pages = lambda **kwargs: range(1, pagination.pages + 1)
    
    # Estatísticas globais
    stats = {
        'total': len(benefit_groups),
        'total_processes': sum(g['benefits_count'] for g in benefit_groups),
        'procedentes': sum(g['group_stats']['procedentes'] for g in benefit_groups),
        'improcedentes': sum(g['group_stats']['improcedentes'] for g in benefit_groups),
    }
    
    # Lista de clientes para o filtro
    clients = Client.query.filter_by(law_firm_id=law_firm_id).order_by(Client.name.asc()).all()
    
    return render_template(
        'process_panel/benefits_list.html',
        benefit_groups=paginated_groups,
        pagination=pagination,
        stats=stats,
        clients=clients,
        search_query=search_query,
        client_filter=client_filter,
        decision_filter=decision_filter
    )


@process_panel_bp.route('/api/beneficio/<benefit_number>/processos')
@require_law_firm
def api_benefit_processes(benefit_number):
    """API para buscar processos relacionados a um benefício específico."""
    law_firm_id = get_current_law_firm_id()
    
    try:
        # Buscar todos os benefícios com esse número
        benefits = (
            JudicialProcessBenefit.query
            .join(JudicialProcess)
            .filter(JudicialProcess.law_firm_id == law_firm_id)
            .filter(JudicialProcessBenefit.benefit_number == benefit_number)
            .options(
                selectinload(JudicialProcessBenefit.process).selectinload(JudicialProcess.plaintiff_client),
                selectinload(JudicialProcessBenefit.legal_theses)
            )
            .all()
        )
        
        if not benefits:
            return jsonify({'error': 'Benefício não encontrado'}), 404
        
        # Estruturar dados dos processos
        processes_data = []
        for benefit in benefits:
            process = benefit.process
            processes_data.append({
                'process_id': process.id,
                'process_number': process.process_number,
                'process_title': process.title or '',
                'client_name': process.plaintiff_client.name if process.plaintiff_client else '',
                'nit_number': benefit.nit_number or '',
                'insured_name': benefit.insured_name or '',
                'benefit_type': benefit.benefit_type or '',
                'fap_vigencia_year': benefit.fap_vigencia_year,
                'request_type': benefit.request_type or '',
                'first_instance_decision': benefit.first_instance_decision or '',
                'second_instance_decision': benefit.second_instance_decision or '',
                'third_instance_decision': benefit.third_instance_decision or '',
                'legal_theses': [{'id': thesis.id, 'name': thesis.name} for thesis in benefit.legal_theses],
                'created_at': benefit.created_at.strftime('%d/%m/%Y %H:%M') if benefit.created_at else ''
            })
        
        return jsonify({
            'benefit_number': benefit_number,
            'processes_count': len(processes_data),
            'processes': processes_data
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@process_panel_bp.route('/novo', methods=['GET', 'POST'])
@require_law_firm
def new_process():
    """Criar processo simplificado (número CNJ + documentos para base de conhecimento)."""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    try:
        _ensure_judicial_config_defaults(law_firm_id)
    except Exception:
        db.session.rollback()
    
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
        document_type_ids = request.form.getlist('document_type_ids', type=int)

        if not uploaded_files:
            flash('Envie ao menos um documento para a base de conhecimento.', 'danger')
            return redirect(url_for('process_panel.new_process'))

        if len(document_type_ids) != len(uploaded_files) or any(not item for item in document_type_ids):
            flash('Selecione o tipo de documento para cada arquivo enviado.', 'danger')
            return redirect(url_for('process_panel.new_process'))

        selected_type_ids = sorted(set(document_type_ids))
        document_types = JudicialDocumentType.query.options(
            selectinload(JudicialDocumentType.phase)
        ).filter(
            JudicialDocumentType.law_firm_id == law_firm_id,
            JudicialDocumentType.is_active.is_(True),
            JudicialDocumentType.id.in_(selected_type_ids)
        ).all()

        if len(document_types) != len(selected_type_ids):
            flash('Um ou mais tipos de documento são inválidos ou inativos.', 'danger')
            return redirect(url_for('process_panel.new_process'))

        document_types_by_id = {doc_type.id: doc_type for doc_type in document_types}

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
            db.session.add(new_proc)
            db.session.flush()

            upload_dir = f"uploads/knowledge_base/{law_firm_id}"
            os.makedirs(upload_dir, exist_ok=True)

            saved_file_paths = []
            duplicates_count = 0
            uploaded_count = 0
            reused_count = 0
            seen_file_hashes = set()

            for index, file in enumerate(uploaded_files):
                document_type_id = document_type_ids[index]
                document_type = document_types_by_id.get(document_type_id)
                if not document_type or not document_type.phase:
                    continue

                file_hash = _compute_file_hash(file)

                if file_hash in seen_file_hashes:
                    duplicates_count += 1
                    continue
                seen_file_hashes.add(file_hash)

                existing_process_doc = JudicialDocument.query.filter_by(
                    process_id=new_proc.id,
                    file_hash=file_hash,
                ).first()
                if existing_process_doc:
                    duplicates_count += 1
                    continue

                duplicate = KnowledgeBase.query.filter_by(
                    law_firm_id=law_firm_id,
                    file_hash=file_hash,
                    is_active=True
                ).first()

                if duplicate:
                    event_date = datetime.utcnow()
                    event = JudicialEvent(
                        process_id=new_proc.id,
                        type=document_type.key,
                        phase=document_type.phase.key,
                        description=(
                            f'Documento {document_type.name} vinculado no cadastro inicial do processo '
                            'a partir de arquivo já existente na base de conhecimento.'
                        ),
                        event_date=event_date,
                    )
                    db.session.add(event)
                    db.session.flush()

                    _register_phase_history(
                        process=new_proc,
                        phase=document_type.phase,
                        occurred_at=event_date,
                        entered_by_user_id=user_id,
                        source_event_id=event.id,
                        notes=(
                            'Fase registrada automaticamente no cadastro inicial '
                            f'via documento vinculado: {document_type.name}.'
                        ),
                        location_text='Cadastro inicial',
                        metadata_payload={
                            'origin': 'new_process_initial_linked_existing_kb',
                            'document_type_key': document_type.key,
                            'knowledge_base_id': duplicate.id,
                        },
                    )

                    db.session.add(
                        JudicialDocument(
                            process_id=new_proc.id,
                            event_id=event.id,
                            knowledge_base_id=duplicate.id,
                            type=document_type.key,
                            file_name=duplicate.original_filename or file.filename,
                            file_path=duplicate.file_path,
                            file_hash=file_hash,
                            uploaded_by=user_id,
                        )
                    )
                    reused_count += 1
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
                    category=document_type.phase.name or '',
                    tags=document_type.name or '',
                    lawsuit_number=process_number,
                    processing_status='pending'
                )
                db.session.add(kb_entry)
                db.session.flush()

                event_date = datetime.utcnow()
                event = JudicialEvent(
                    process_id=new_proc.id,
                    type=document_type.key,
                    phase=document_type.phase.key,
                    description=(
                        f'Documento {document_type.name} adicionado no cadastro inicial do processo.'
                    ),
                    event_date=event_date,
                )
                db.session.add(event)
                db.session.flush()

                _register_phase_history(
                    process=new_proc,
                    phase=document_type.phase,
                    occurred_at=event_date,
                    entered_by_user_id=user_id,
                    source_event_id=event.id,
                    notes=(
                        'Fase registrada automaticamente no cadastro inicial '
                        f'via documento: {document_type.name}.'
                    ),
                    location_text='Cadastro inicial',
                    metadata_payload={
                        'origin': 'new_process_initial_upload',
                        'document_type_key': document_type.key,
                    },
                )

                db.session.add(
                    JudicialDocument(
                        process_id=new_proc.id,
                        event_id=event.id,
                        knowledge_base_id=kb_entry.id,
                        type=document_type.key,
                        file_name=filename,
                        file_path=file_path,
                        file_hash=file_hash,
                        uploaded_by=user_id,
                    )
                )
                uploaded_count += 1

            if uploaded_count == 0 and reused_count == 0:
                db.session.rollback()
                flash('Nenhum arquivo novo foi enviado (todos os arquivos já existem na base).', 'warning')
                return redirect(url_for('process_panel.new_process'))

            new_proc.updated_at = datetime.utcnow()
            db.session.commit()

            if duplicates_count > 0 or reused_count > 0:
                flash(
                    (
                        f'Processo {process_label} criado. '
                        f'{uploaded_count} documento(s) enviado(s), '
                        f'{reused_count} documento(s) reaproveitado(s) da base e '
                        f'{duplicates_count} duplicado(s) ignorado(s).'
                    ),
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
    document_types = JudicialDocumentType.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True
    ).join(JudicialPhase, JudicialPhase.id == JudicialDocumentType.phase_id).order_by(
        JudicialPhase.display_order.asc(),
        JudicialDocumentType.display_order.asc(),
        JudicialDocumentType.name.asc()
    ).all()

    return render_template(
        'process_panel/form_new_simple.html',
        action='novo',
        clients=clients,
        defendants=defendants,
        document_types=document_types,
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

    cited_benefits = JudicialProcessCitedBenefit.query.filter_by(
        process_id=process.id
    ).order_by(JudicialProcessCitedBenefit.insured_name.asc(), JudicialProcessCitedBenefit.id.asc()).all()

    legal_theses = JudicialLegalThesis.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True,
    ).order_by(JudicialLegalThesis.name.asc()).all()

    benefit_thesis_contestation_map = {}
    if process_benefits:
        benefit_ids = [benefit.id for benefit in process_benefits]
        contestation_rows = JudicialProcessBenefitThesisContestation.query.filter(
            JudicialProcessBenefitThesisContestation.law_firm_id == law_firm_id,
            JudicialProcessBenefitThesisContestation.process_id == process.id,
            JudicialProcessBenefitThesisContestation.process_benefit_id.in_(benefit_ids),
        ).all()

        for row in contestation_rows:
            if row.process_benefit_id not in benefit_thesis_contestation_map:
                benefit_thesis_contestation_map[row.process_benefit_id] = {}
            benefit_thesis_contestation_map[row.process_benefit_id][row.legal_thesis_id] = row

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

    documents_list = []

    for judicial_doc in judicial_documents:
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
            'event_identifier': str(judicial_doc.event_identifier or '').strip(),
            'knowledge_base_id': judicial_doc.knowledge_base_id,
            'processing_status': (judicial_doc.status or '').strip().lower(),
            'judicial_document_id': judicial_doc.id,
            'phase_order': phase_order_by_key.get(phase_key, 9999),
        })

    documents_list.sort(
        key=lambda item: (
            item.get('phase_order', 9999),
            (item.get('filename') or '').lower(),
        )
    )

    attachments_list = JudicialProcessAttachment.query.options(
        selectinload(JudicialProcessAttachment.benefits)
    ).filter_by(
        process_id=process.id,
        law_firm_id=law_firm_id,
        is_active=True,
    ).order_by(JudicialProcessAttachment.created_at.desc(), JudicialProcessAttachment.id.desc()).all()
    
    generated_documents = (
        JudicialProcessGeneratedDocument.query
        .filter_by(process_id=process.id, law_firm_id=law_firm_id)
        .order_by(JudicialProcessGeneratedDocument.created_at.desc())
        .all()
    )

    # Dados para a dashboard
    data = {
        'process': process,
        'current_phase_key': current_phase_key,
        'current_phase_label': current_phase_label,
        'notes': notes,
        'phase_history': phase_history,
        'phase_options': sorted(
            configured_phases,
            key=lambda item: ((item.display_order or 0), (item.name or '').lower())
        ),
        'process_benefits': process_benefits,
        'benefits_grouped_by_thesis': benefits_grouped_by_thesis,
        'cited_benefits': cited_benefits,
        'legal_theses': legal_theses,
        'benefit_thesis_contestation_map': benefit_thesis_contestation_map,
        'kb_documents': kb_documents,
        'documents_list': documents_list,
        'attachments_list': attachments_list,
        'generated_documents': generated_documents,
        'document_type_labels': DOCUMENT_TYPE_LABELS,
        'case': process.case if process.case_id else None,
        'stats': {
            'documents_count': len(documents_list),
            'benefits_count': len(process_benefits),
            'attachments_count': len(attachments_list),
            'generated_documents_count': len(generated_documents),
        },
    }
    
    return render_template('process_panel/detail.html', **data)


@process_panel_bp.route('/<int:process_id>/anexos', methods=['POST'])
@require_law_firm
def create_process_attachment(process_id):
    """Adiciona um anexo auxiliar ao processo judicial."""
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    file = request.files.get('attachment')
    description = request.form.get('description', '').strip()
    benefit_ids = sorted({
        benefit_id
        for benefit_id in request.form.getlist('benefit_ids', type=int)
        if benefit_id
    })

    selected_benefits = []
    if benefit_ids:
        selected_benefits = JudicialProcessBenefit.query.filter(
            JudicialProcessBenefit.id.in_(benefit_ids),
            JudicialProcessBenefit.process_id == process.id,
        ).order_by(JudicialProcessBenefit.benefit_number.asc()).all()

        if len(selected_benefits) != len(benefit_ids):
            flash('Um ou mais benefícios selecionados são inválidos para este processo.', 'danger')
            return redirect(url_for('process_panel.detail', process_id=process.id) + '#attachments')

    if not file or not file.filename or not file.filename.strip():
        flash('Selecione um arquivo de anexo para upload.', 'danger')
        return redirect(url_for('process_panel.detail', process_id=process.id) + '#attachments')

    safe_filename = secure_filename(file.filename)
    if not safe_filename:
        flash('Nome de arquivo inválido para o anexo.', 'danger')
        return redirect(url_for('process_panel.detail', process_id=process.id) + '#attachments')

    saved_file_path = None

    try:
        upload_dir = os.path.join('uploads', 'process_attachments', str(law_firm_id), f'process_{process.id}')
        os.makedirs(upload_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        name, ext = os.path.splitext(safe_filename)
        filename_with_timestamp = f"{name}_{timestamp}{ext}"
        saved_file_path = os.path.join(upload_dir, filename_with_timestamp)

        file.save(saved_file_path)

        file_size = os.path.getsize(saved_file_path)
        file_type = ext.lstrip('.').upper() if ext else 'DESCONHECIDO'

        attachment = JudicialProcessAttachment(
            law_firm_id=law_firm_id,
            process_id=process.id,
            uploaded_by_user_id=user_id,
            original_filename=safe_filename,
            file_path=saved_file_path,
            file_size=file_size,
            file_type=file_type,
            description=description or None,
            is_active=True,
        )
        attachment.benefits = selected_benefits

        db.session.add(attachment)
        process.updated_at = datetime.utcnow()
        db.session.commit()

        flash('Anexo adicionado ao processo com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        if saved_file_path and os.path.exists(saved_file_path):
            os.remove(saved_file_path)
        flash(f'Erro ao adicionar anexo: {str(e)}', 'danger')

    return redirect(url_for('process_panel.detail', process_id=process.id) + '#attachments')


@process_panel_bp.route('/<int:process_id>/anexos/<int:attachment_id>/download', methods=['GET'])
@require_law_firm
def download_process_attachment(process_id, attachment_id):
    """Baixa um anexo auxiliar do processo judicial."""
    law_firm_id = get_current_law_firm_id()

    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    attachment = JudicialProcessAttachment.query.filter_by(
        id=attachment_id,
        process_id=process.id,
        law_firm_id=law_firm_id,
        is_active=True,
    ).first_or_404()

    file_path = str(attachment.file_path or '').strip()
    if not file_path or not os.path.exists(file_path):
        flash('Arquivo de anexo não encontrado no servidor.', 'warning')
        return redirect(url_for('process_panel.detail', process_id=process.id) + '#attachments')

    return send_file(
        file_path,
        as_attachment=True,
        download_name=attachment.original_filename,
    )


@process_panel_bp.route('/<int:process_id>/anexos/<int:attachment_id>/excluir', methods=['POST'])
@require_law_firm
def delete_process_attachment(process_id, attachment_id):
    """Remove um anexo do processo e seus vínculos com benefícios."""
    law_firm_id = get_current_law_firm_id()

    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    attachment = JudicialProcessAttachment.query.filter_by(
        id=attachment_id,
        process_id=process.id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    try:
        attachment.benefits.clear()

        file_path = str(attachment.file_path or '').strip()
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

        db.session.delete(attachment)
        db.session.commit()
        flash('Anexo removido com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao remover o anexo: {str(e)}', 'danger')

    return redirect(url_for('process_panel.detail', process_id=process.id) + '#attachments')


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

            existing_process_doc = JudicialDocument.query.filter_by(
                process_id=process.id,
                file_hash=file_hash,
            ).first()
            if existing_process_doc:
                flash('Este arquivo já está vinculado a este processo.', 'warning')
                return redirect(url_for('process_panel.new_process_document', process_id=process.id))

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
                    file_hash=file_hash,
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


@process_panel_bp.route('/<int:process_id>/documentos/<int:doc_id>/reprocessar', methods=['POST'])
@require_law_firm
def reprocess_process_document(process_id, doc_id):
    """Reprocessar um documento judicial via IA."""
    law_firm_id = get_current_law_firm_id()

    process = JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    judicial_doc = JudicialDocument.query.filter_by(
        id=doc_id,
        process_id=process_id,
    ).first_or_404()

    if not judicial_doc.knowledge_base_id:
        flash('Documento sem vínculo com a base de conhecimento.', 'warning')
        return redirect(url_for('process_panel.detail', process_id=process.id) + '#documents')

    try:
        judicial_doc.status = 'pending'
        judicial_doc.error_message = None
        judicial_doc.processed_at = None
        judicial_doc.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Documento enviado para reprocessamento com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao reenviar documento: {str(e)}', 'danger')

    return redirect(url_for('process_panel.detail', process_id=process.id) + '#documents')


@process_panel_bp.route('/<int:process_id>/documentos/<int:doc_id>/resumo', methods=['GET'])
@require_law_firm
def get_process_document_summary(process_id, doc_id):
    """Retorna o resumo de IA de um documento judicial."""
    law_firm_id = get_current_law_firm_id()

    JudicialProcess.query.filter_by(
        id=process_id,
        law_firm_id=law_firm_id,
    ).first_or_404()

    judicial_doc = JudicialDocument.query.filter_by(
        id=doc_id,
        process_id=process_id,
    ).first_or_404()

    summary = JudicialDocumentSummary.query.filter_by(
        judicial_document_id=judicial_doc.id,
        law_firm_id=law_firm_id,
    ).first()

    if not summary:
        return jsonify({
            'status': 'missing',
            'summary_text': None,
            'payload': None,
        })

    return jsonify({
        'status': summary.status,
        'summary_text': summary.summary_text,
        'payload': summary.summary_payload,
        'error_message': summary.error_message,
        'processed_at': summary.processed_at.isoformat() if summary.processed_at else None,
    })


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


@process_panel_bp.route('/api/benefit-documents')
@require_law_firm
def api_benefit_documents():
    """Busca documentos pelo NB no Meilisearch (full-text) e no Qdrant (semântico)."""
    benefit_number = request.args.get('benefit_number', '').strip()
    if not benefit_number:
        return jsonify({'results': [], 'error': 'Número do benefício não informado'}), 400

    meilisearch_host = os.getenv('MEILISEARCH_HOST', 'http://localhost:7700')
    meilisearch_key  = os.getenv('MEILISEARCH_API_KEY')
    collection       = os.getenv('QDRANT_COLLECTION', 'knowledge_base')
    qdrant_host      = os.getenv('QDRANT_HOST', 'localhost')
    qdrant_port      = int(os.getenv('QDRANT_PORT', '6333'))
    embedding_model  = os.getenv('EMBEDDING_MODEL')
    vector_size      = int(os.getenv('VECTOR_SIZE', '0'))

    # key → result dict; preserva o melhor score entre as duas fontes
    merged: dict[str, dict] = {}

    def _upsert(key, entry):
        existing = merged.get(key)
        if not existing or (entry.get('score') or 0) > (existing.get('score') or 0):
            merged[key] = entry

    # ── 1. Meilisearch (full-text) ────────────────────────────────────────
    try:
        from meilisearch_python_sdk.models.search import SearchParams
        meili = MeilisearchClient(meilisearch_host, meilisearch_key)
        search_result = meili.index(collection).search(benefit_number, limit=15, show_ranking_score=True)
        hits = search_result.hits or []
        print(f'[api_benefit_documents] Meilisearch hits: {len(hits)}, raw sample: {hits[:1]}')
        for hit in hits:
            fid  = hit.get('file_id')
            page = hit.get('page')
            key  = f"{fid}|{page}"
            # _rankingScore pode vir como float ou estar ausente dependendo da versão do SDK
            ranking_score = hit.get('_rankingScore') or hit.get('_ranking_score')
            _upsert(key, {
                'file_id': fid,
                'source':  hit.get('source', ''),
                'page':    page,
                'score':   float(ranking_score) if ranking_score is not None else None,
                'excerpt': (hit.get('content') or hit.get('text') or '').strip(),
                'origin':  'full_text',
            })
    except Exception as meili_err:
        print(f'[api_benefit_documents] Meilisearch error: {meili_err}')

    # ── 2. Qdrant (semântico) ─────────────────────────────────────────────
    if embedding_model and vector_size > 0:
        try:
            from openai import OpenAI
            from qdrant_client import QdrantClient

            openai_client = OpenAI()
            embedding_resp = openai_client.embeddings.create(model=embedding_model, input=benefit_number)
            vector = embedding_resp.data[0].embedding

            qdrant = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=30)
            points = qdrant.query_points(collection_name=collection, query=vector, limit=15).points
            for point in points:
                payload = point.payload or {}
                fid  = payload.get('file_id')
                page = payload.get('page')
                key  = f"{fid}|{page}"
                _upsert(key, {
                    'file_id': fid,
                    'source':  payload.get('source', ''),
                    'page':    page,
                    'score':   float(point.score) if hasattr(point, 'score') else None,
                    'excerpt': (payload.get('text') or '').strip(),
                    'origin':  'semantic',
                })
        except Exception as qdrant_err:
            print(f'[api_benefit_documents] Qdrant error: {qdrant_err}')

    all_scores = [(r.get('origin'), r.get('score')) for r in merged.values()]
    print(f'[api_benefit_documents] All scores before filter: {all_scores}')
    results = sorted(
        (r for r in merged.values() if (r.get('score') or 0) >= 0.60),
        key=lambda r: r.get('score') or 0,
        reverse=True,
    )
    print(f'[api_benefit_documents] Results after filter >= 0.60: {len(results)}')
    return jsonify({'results': results, 'query': benefit_number})


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


# ── Documentos Gerados ────────────────────────────────────────────────────


@process_panel_bp.route('/<int:process_id>/documentos-gerados/novo', methods=['GET'])
@require_law_firm
def generated_document_new(process_id):
    law_firm_id = get_current_law_firm_id()
    process = JudicialProcess.query.filter_by(
        id=process_id, law_firm_id=law_firm_id
    ).first_or_404()
    benefits = (
        JudicialProcessBenefit.query
        .filter_by(process_id=process.id)
        .options(selectinload(JudicialProcessBenefit.legal_theses))
        .order_by(JudicialProcessBenefit.benefit_number.asc())
        .all()
    )
    # Build map: benefit_id → { thesis_id → JudicialProcessBenefitThesisContestation }
    benefit_ids = [b.id for b in benefits]
    thesis_contestation_map = {}
    if benefit_ids:
        rows = JudicialProcessBenefitThesisContestation.query.filter(
            JudicialProcessBenefitThesisContestation.process_benefit_id.in_(benefit_ids)
        ).all()
        for row in rows:
            thesis_contestation_map.setdefault(row.process_benefit_id, {})[row.legal_thesis_id] = row

    # Agrupa por tese usando benefit.legal_theses como fonte de verdade.
    # Contestation data enriquece onde existir, mas não é obrigatória.
    from collections import OrderedDict
    thesis_groups_map = OrderedDict()
    no_thesis_entries = []
    for b in benefits:
        if b.legal_theses:
            b_conts = thesis_contestation_map.get(b.id, {})
            for thesis in b.legal_theses:
                # Apenas contestação específica da tese; fallback para campos diretos do benefit no template
                cont = b_conts.get(thesis.id)
                if thesis.id not in thesis_groups_map:
                    thesis_groups_map[thesis.id] = {'label': thesis.name, 'entries': []}
                thesis_groups_map[thesis.id]['entries'].append({'benefit': b, 'cont': cont})
        else:
            no_thesis_entries.append({'benefit': b, 'cont': None})

    thesis_groups = [
        {'thesis_id': tid, 'label': data['label'], 'entries': data['entries']}
        for tid, data in thesis_groups_map.items()
    ]
    if no_thesis_entries:
        thesis_groups.append({
            'thesis_id': None,
            'label': 'Sem tese vinculada',
            'entries': no_thesis_entries,
        })

    return render_template(
        'process_panel/generated_document_new.html',
        process=process,
        benefits=benefits,
        thesis_contestation_map=thesis_contestation_map,
        thesis_groups=thesis_groups,
        document_type_labels=DOCUMENT_TYPE_LABELS,
    )


@process_panel_bp.route('/<int:process_id>/documentos-gerados/gerar', methods=['POST'])
@require_law_firm
def generated_document_create(process_id):
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    process = JudicialProcess.query.filter_by(
        id=process_id, law_firm_id=law_firm_id
    ).first_or_404()

    document_type = request.form.get('document_type', '').strip()
    if document_type not in DOCUMENT_TYPE_LABELS:
        flash('Tipo de documento inválido.', 'danger')
        return redirect(url_for('process_panel.generated_document_new', process_id=process_id))

    # selections[] values are "benefit_id:thesis_id" or "benefit_id:" for no thesis
    raw_selections = request.form.getlist('selections[]')
    instructions = request.form.get('instructions', '').strip() or None
    model_name = request.form.get('model_name') or None

    # Parse and validate selections
    parsed = []  # list of (benefit_id, thesis_id_or_None)
    for raw in raw_selections:
        parts = raw.split(':', 1)
        try:
            b_id = int(parts[0])
            t_id = int(parts[1]) if len(parts) > 1 and parts[1] else None
            parsed.append((b_id, t_id))
        except (ValueError, IndexError):
            continue

    # Load benefits (validate ownership)
    benefit_id_set = {b_id for b_id, _ in parsed}
    benefits_by_id = {
        b.id: b for b in JudicialProcessBenefit.query.filter(
            JudicialProcessBenefit.id.in_(benefit_id_set),
            JudicialProcessBenefit.process_id == process.id,
        ).all()
    }

    # Load thesis contestations
    thesis_id_set = {t_id for _, t_id in parsed if t_id}
    contestations_by_key = {}
    if thesis_id_set:
        rows = JudicialProcessBenefitThesisContestation.query.filter(
            JudicialProcessBenefitThesisContestation.process_benefit_id.in_(benefit_id_set),
            JudicialProcessBenefitThesisContestation.legal_thesis_id.in_(thesis_id_set),
        ).all()
        for row in rows:
            contestations_by_key[(row.process_benefit_id, row.legal_thesis_id)] = row

    # Load theses by ID as fallback for benefits without contestation records
    theses_by_id = {}
    if thesis_id_set:
        theses_by_id = {
            t.id: t for t in JudicialLegalThesis.query.filter(
                JudicialLegalThesis.id.in_(thesis_id_set)
            ).all()
        }

    # Build agent input: list of dicts with benefit + contestation data
    agent_selections = []
    for b_id, t_id in parsed:
        benefit = benefits_by_id.get(b_id)
        if not benefit:
            continue
        contestation = contestations_by_key.get((b_id, t_id)) if t_id else None
        thesis = (
            contestation.legal_thesis
            if contestation and contestation.legal_thesis
            else theses_by_id.get(t_id) if t_id else None
        )
        agent_selections.append({
            'benefit': benefit,
            'thesis': thesis,
            'contestation': contestation,
        })

    title = DOCUMENT_TYPE_LABELS.get(document_type, document_type)

    generated_doc = JudicialProcessGeneratedDocument(
        law_firm_id=law_firm_id,
        process_id=process.id,
        created_by_id=user_id,
        document_type=document_type,
        title=title,
    )
    db.session.add(generated_doc)
    db.session.flush()

    # Persist selections
    for b_id, t_id in parsed:
        if b_id in benefits_by_id:
            db.session.add(JudicialProcessGeneratedDocumentSelection(
                generated_document_id=generated_doc.id,
                benefit_id=b_id,
                legal_thesis_id=t_id,
            ))

    version = JudicialProcessGeneratedDocumentVersion(
        generated_document_id=generated_doc.id,
        created_by_id=user_id,
        version_number=1,
        source='ai_generated',
        generation_status='processing',
        model_used=model_name,
    )
    db.session.add(version)
    db.session.flush()

    generated_doc.current_version_id = version.id
    db.session.commit()

    try:
        contestation_file_path = None
        contestation_summary_payload = None
        if document_type == 'impugnacao_contestacao':
            contestation_file_path = _resolve_latest_contestation_pdf_path(process)
            contestation_summary_payload = _resolve_latest_contestation_summary_payload(
                process,
                law_firm_id,
            )

        agent = AgentGeneratedDocument(model_name=model_name)
        result_dict, full_text = agent.dispatch(
            document_type,
            process,
            agent_selections,
            instructions,
            contestation_file_path=contestation_file_path,
            contestation_summary_payload=contestation_summary_payload,
            law_firm_id=law_firm_id,
        )

        # Enriquecimento jurisprudencial (apenas para impugnação)
        if document_type == 'impugnacao_contestacao':
            try:
                trf_region = getattr(process, 'trf_region', None) or ''
                full_text = ImpugnacaoEnrichmentAgent().enrich(
                    document_text=full_text,
                    selections=agent_selections,
                    law_firm_id=law_firm_id,
                    trf_region=trf_region,
                )
            except Exception as enrich_err:
                print(f'[EnrichmentAgent] Falha silenciosa: {enrich_err}')

        internal_notes = None
        if isinstance(result_dict, dict):
            internal_notes = (result_dict.get('internal_review_notes') or '').strip() or None

        version.content = full_text
        version.internal_notes = internal_notes
        version.generation_status = 'completed'
        db.session.commit()

        flash('Documento gerado com sucesso!', 'success')
    except Exception as e:
        version.generation_status = 'failed'
        version.error_message = str(e)
        db.session.commit()
        flash(f'Erro ao gerar o documento: {str(e)}', 'danger')

    return redirect(url_for(
        'process_panel.generated_document_detail',
        process_id=process.id,
        doc_id=generated_doc.id,
    ))


@process_panel_bp.route('/<int:process_id>/documentos-gerados/<int:doc_id>', methods=['GET'])
@require_law_firm
def generated_document_detail(process_id, doc_id):
    law_firm_id = get_current_law_firm_id()
    process = JudicialProcess.query.filter_by(
        id=process_id, law_firm_id=law_firm_id
    ).first_or_404()
    generated_doc = JudicialProcessGeneratedDocument.query.filter_by(
        id=doc_id, process_id=process.id, law_firm_id=law_firm_id
    ).first_or_404()
    return render_template(
        'process_panel/generated_document_detail.html',
        process=process,
        generated_doc=generated_doc,
        document_type_labels=DOCUMENT_TYPE_LABELS,
    )


@process_panel_bp.route('/<int:process_id>/documentos-gerados/<int:doc_id>/salvar', methods=['POST'])
@require_law_firm
def generated_document_save(process_id, doc_id):
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    process = JudicialProcess.query.filter_by(
        id=process_id, law_firm_id=law_firm_id
    ).first_or_404()
    generated_doc = JudicialProcessGeneratedDocument.query.filter_by(
        id=doc_id, process_id=process.id, law_firm_id=law_firm_id
    ).first_or_404()

    content = request.form.get('content', '').strip()
    if not content:
        flash('O conteúdo não pode estar vazio.', 'warning')
        return redirect(url_for(
            'process_panel.generated_document_detail',
            process_id=process_id, doc_id=doc_id,
        ))

    last_version = (
        JudicialProcessGeneratedDocumentVersion.query
        .filter_by(generated_document_id=generated_doc.id)
        .order_by(JudicialProcessGeneratedDocumentVersion.version_number.desc())
        .first()
    )
    next_version_number = (last_version.version_number + 1) if last_version else 1

    version = JudicialProcessGeneratedDocumentVersion(
        generated_document_id=generated_doc.id,
        created_by_id=user_id,
        version_number=next_version_number,
        content=content,
        internal_notes=(generated_doc.current_version.internal_notes if generated_doc.current_version else None),
        source='manually_edited',
        generation_status='completed',
    )
    db.session.add(version)
    db.session.flush()

    generated_doc.current_version_id = version.id
    db.session.commit()

    flash('Alterações salvas como nova versão.', 'success')
    return redirect(url_for(
        'process_panel.generated_document_detail',
        process_id=process_id, doc_id=doc_id,
    ))


@process_panel_bp.route('/<int:process_id>/documentos-gerados/<int:doc_id>/regerar', methods=['POST'])
@require_law_firm
def generated_document_regenerate(process_id, doc_id):
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    process = JudicialProcess.query.filter_by(
        id=process_id, law_firm_id=law_firm_id
    ).first_or_404()
    generated_doc = JudicialProcessGeneratedDocument.query.filter_by(
        id=doc_id, process_id=process.id, law_firm_id=law_firm_id
    ).first_or_404()

    instructions = request.form.get('instructions', '').strip() or None
    model_name = request.form.get('model_name') or None

    last_version = (
        JudicialProcessGeneratedDocumentVersion.query
        .filter_by(generated_document_id=generated_doc.id)
        .order_by(JudicialProcessGeneratedDocumentVersion.version_number.desc())
        .first()
    )
    next_version_number = (last_version.version_number + 1) if last_version else 1

    version = JudicialProcessGeneratedDocumentVersion(
        generated_document_id=generated_doc.id,
        created_by_id=user_id,
        version_number=next_version_number,
        source='ai_generated',
        generation_status='processing',
        model_used=model_name,
    )
    db.session.add(version)
    db.session.flush()
    generated_doc.current_version_id = version.id
    db.session.commit()

    try:
        # Rebuild agent_selections from persisted selections
        sel_benefit_ids = {s.benefit_id for s in generated_doc.selections}
        sel_thesis_ids = {s.legal_thesis_id for s in generated_doc.selections if s.legal_thesis_id}
        benefits_by_id = {
            b.id: b for b in JudicialProcessBenefit.query.filter(
                JudicialProcessBenefit.id.in_(sel_benefit_ids)
            ).all()
        }
        contestations_by_key = {}
        if sel_thesis_ids:
            for row in JudicialProcessBenefitThesisContestation.query.filter(
                JudicialProcessBenefitThesisContestation.process_benefit_id.in_(sel_benefit_ids),
                JudicialProcessBenefitThesisContestation.legal_thesis_id.in_(sel_thesis_ids),
            ).all():
                contestations_by_key[(row.process_benefit_id, row.legal_thesis_id)] = row

        theses_by_id = {}
        if sel_thesis_ids:
            theses_by_id = {
                t.id: t for t in JudicialLegalThesis.query.filter(
                    JudicialLegalThesis.id.in_(sel_thesis_ids)
                ).all()
            }

        agent_selections = []
        for sel in generated_doc.selections:
            benefit = benefits_by_id.get(sel.benefit_id)
            if not benefit:
                continue
            contestation = contestations_by_key.get((sel.benefit_id, sel.legal_thesis_id))
            thesis = (
                contestation.legal_thesis
                if contestation and contestation.legal_thesis
                else theses_by_id.get(sel.legal_thesis_id) if sel.legal_thesis_id else None
            )
            agent_selections.append({
                'benefit': benefit,
                'thesis': thesis,
                'contestation': contestation,
            })

        contestation_file_path = None
        contestation_summary_payload = None
        if generated_doc.document_type == 'impugnacao_contestacao':
            contestation_file_path = _resolve_latest_contestation_pdf_path(process)
            contestation_summary_payload = _resolve_latest_contestation_summary_payload(
                process,
                law_firm_id,
            )

        agent = AgentGeneratedDocument(model_name=model_name)
        result_dict, full_text = agent.dispatch(
            generated_doc.document_type,
            process,
            agent_selections,
            instructions,
            contestation_file_path=contestation_file_path,
            contestation_summary_payload=contestation_summary_payload,
            law_firm_id=law_firm_id,
        )

        # Enriquecimento jurisprudencial (apenas para impugnação)
        if generated_doc.document_type == 'impugnacao_contestacao':
            try:
                trf_region = getattr(process, 'trf_region', None) or ''
                full_text = ImpugnacaoEnrichmentAgent().enrich(
                    document_text=full_text,
                    selections=agent_selections,
                    law_firm_id=law_firm_id,
                    trf_region=trf_region,
                )
            except Exception as enrich_err:
                print(f'[EnrichmentAgent] Falha silenciosa: {enrich_err}')

        internal_notes = None
        if isinstance(result_dict, dict):
            internal_notes = (result_dict.get('internal_review_notes') or '').strip() or None

        version.content = full_text
        version.internal_notes = internal_notes
        version.generation_status = 'completed'
        db.session.commit()
        flash('Documento regerado com sucesso!', 'success')
    except Exception as e:
        version.generation_status = 'failed'
        version.error_message = str(e)
        db.session.commit()
        flash(f'Erro ao regerar o documento: {str(e)}', 'danger')

    return redirect(url_for(
        'process_panel.generated_document_detail',
        process_id=process_id, doc_id=doc_id,
    ))


@process_panel_bp.route('/<int:process_id>/documentos-gerados/<int:doc_id>/versoes/<int:version_id>/restaurar', methods=['POST'])
@require_law_firm
def generated_document_restore_version(process_id, doc_id, version_id):
    law_firm_id = get_current_law_firm_id()

    process = JudicialProcess.query.filter_by(
        id=process_id, law_firm_id=law_firm_id
    ).first_or_404()
    generated_doc = JudicialProcessGeneratedDocument.query.filter_by(
        id=doc_id, process_id=process.id, law_firm_id=law_firm_id
    ).first_or_404()
    version = JudicialProcessGeneratedDocumentVersion.query.filter_by(
        id=version_id, generated_document_id=generated_doc.id
    ).first_or_404()

    generated_doc.current_version_id = version.id
    db.session.commit()

    flash(f'Versão {version.version_number} restaurada.', 'success')
    return redirect(url_for(
        'process_panel.generated_document_detail',
        process_id=process_id, doc_id=doc_id,
    ))


@process_panel_bp.route('/<int:process_id>/documentos-gerados/<int:doc_id>/download', methods=['GET', 'POST'])
@require_law_firm
def generated_document_download(process_id, doc_id):
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')
    process = JudicialProcess.query.filter_by(
        id=process_id, law_firm_id=law_firm_id
    ).first_or_404()
    generated_doc = JudicialProcessGeneratedDocument.query.filter_by(
        id=doc_id, process_id=process.id, law_firm_id=law_firm_id
    ).first_or_404()

    version = generated_doc.current_version
    if not version or not version.content:
        flash('Não há conteúdo disponível para download.', 'warning')
        return redirect(url_for(
            'process_panel.generated_document_detail',
            process_id=process_id, doc_id=doc_id,
        ))

    posted_content = request.form.get('content') if request.method == 'POST' else None
    content_to_export = posted_content if posted_content is not None else version.content
    if not str(content_to_export or '').strip():
        flash('O conteúdo para download está vazio.', 'warning')
        return redirect(url_for(
            'process_panel.generated_document_detail',
            process_id=process_id, doc_id=doc_id,
        ))

    # A cada download, cria uma nova versão com snapshot do conteúdo atual.
    last_version = (
        JudicialProcessGeneratedDocumentVersion.query
        .filter_by(generated_document_id=generated_doc.id)
        .order_by(JudicialProcessGeneratedDocumentVersion.version_number.desc())
        .first()
    )
    next_version_number = (last_version.version_number + 1) if last_version else 1

    new_version = JudicialProcessGeneratedDocumentVersion(
        generated_document_id=generated_doc.id,
        created_by_id=user_id,
        version_number=next_version_number,
        content=content_to_export,
        internal_notes=version.internal_notes,
        source='manually_edited' if request.method == 'POST' else (version.source or 'manually_edited'),
        generation_status='completed',
        model_used=version.model_used,
        token_usage_json=version.token_usage_json,
        prompt_used=version.prompt_used,
    )
    db.session.add(new_version)
    db.session.flush()
    generated_doc.current_version_id = new_version.id
    db.session.commit()

    try:
        export_agent = OfficeDocxExportAgent()
        buf = export_agent.export_generated_document(
            document_title=generated_doc.title or 'DOCUMENTO GERADO',
            document_text=new_version.content,
            run_ai_normalization=False,
            law_firm_id=law_firm_id,
            include_document_title=(generated_doc.document_type != 'impugnacao_contestacao'),
        )
    except Exception as error:
        flash(f'Erro ao gerar DOCX para download: {str(error)}', 'danger')
        return redirect(url_for(
            'process_panel.generated_document_detail',
            process_id=process_id, doc_id=doc_id,
        ))

    safe_title = re.sub(r'[^\w\s-]', '', generated_doc.title).strip().replace(' ', '_')
    filename = f"{safe_title}_v{new_version.version_number}.docx"

    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True,
        download_name=filename,
    )


@process_panel_bp.route('/<int:process_id>/documentos-gerados/<int:doc_id>/excluir', methods=['POST'])
@require_law_firm
def generated_document_delete(process_id, doc_id):
    law_firm_id = get_current_law_firm_id()

    process = JudicialProcess.query.filter_by(
        id=process_id, law_firm_id=law_firm_id
    ).first_or_404()
    generated_doc = JudicialProcessGeneratedDocument.query.filter_by(
        id=doc_id, process_id=process.id, law_firm_id=law_firm_id
    ).first_or_404()

    try:
        generated_doc.current_version_id = None
        db.session.flush()
        db.session.delete(generated_doc)
        db.session.commit()
        flash('Documento removido com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao remover o documento: {str(e)}', 'danger')

    return redirect(url_for('process_panel.detail', process_id=process_id) + '#generated-docs')


# ── Status do processo ─────────────────────────────────────────────────────

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
