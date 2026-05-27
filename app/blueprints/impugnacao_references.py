"""Blueprint: Base de Peças-Modelo de Impugnação.

CRUD da base de referências de estilo do escritório usada pelo agente
gerador de impugnação à contestação. Multi-tenant (sempre filtra por
law_firm_id).

Rotas:
    GET  /referencias-impugnacao/
    GET  /referencias-impugnacao/novo
    POST /referencias-impugnacao/novo
    GET  /referencias-impugnacao/<id>
    POST /referencias-impugnacao/<id>/arquivar
    POST /referencias-impugnacao/<id>/reativar
    POST /referencias-impugnacao/<id>/excluir
"""

from __future__ import annotations

import os
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, abort,
)
from werkzeug.utils import secure_filename

from app.models import (
    db,
    ImpugnacaoReferenceModel,
    ImpugnacaoReferenceChunk,
    JudicialLegalThesis,
)


impugnacao_references_bp = Blueprint(
    'impugnacao_references',
    __name__,
    url_prefix='/referencias-impugnacao',
)

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'txt', 'md'}
UPLOAD_BASE_DIR = os.path.join('uploads', 'impugnacao_references')


def get_current_law_firm_id():
    return session.get('law_firm_id')


def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            flash('Você precisa estar associado a um escritório.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def _allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _load_thesis_catalog(law_firm_id: int) -> list[dict]:
    theses = (
        JudicialLegalThesis.query
        .filter_by(law_firm_id=law_firm_id, is_active=True)
        .order_by(JudicialLegalThesis.name.asc())
        .all()
    )
    return [
        {
            'id': thesis.id,
            'key': thesis.key,
            'name': thesis.name,
        }
        for thesis in theses
        if thesis.key and thesis.name
    ]


# ── Listagem ──────────────────────────────────────────────────────────

@impugnacao_references_bp.route('/')
@require_law_firm
def list_references():
    law_firm_id = get_current_law_firm_id()
    status_filter = (request.args.get('status') or 'active').strip()

    query = ImpugnacaoReferenceModel.query.filter_by(law_firm_id=law_firm_id)
    if status_filter in ('active', 'archived'):
        query = query.filter_by(status=status_filter)

    references = query.order_by(ImpugnacaoReferenceModel.created_at.desc()).all()
    return render_template(
        'impugnacao_references/list.html',
        references=references,
        status_filter=status_filter,
    )


# ── Novo ──────────────────────────────────────────────────────────────

@impugnacao_references_bp.route('/novo', methods=['GET', 'POST'])
@require_law_firm
def new_reference():
    law_firm_id = get_current_law_firm_id()
    user_id = session.get('user_id')

    if request.method == 'GET':
        return render_template('impugnacao_references/new.html')

    # POST — somente arquivo (obrigatório) + notas (opcional).
    # Metadados (título, TRF, modo, qualidade) são extraídos por agente.
    notes = (request.form.get('notes') or '').strip() or None

    upload = request.files.get('file')
    if not upload or not upload.filename:
        flash('Envie um arquivo da peça-modelo (PDF, DOCX, TXT).', 'warning')
        return redirect(url_for('impugnacao_references.new_reference'))
    if not _allowed_file(upload.filename):
        flash('Formato de arquivo não suportado.', 'warning')
        return redirect(url_for('impugnacao_references.new_reference'))

    upload_dir = os.path.join(UPLOAD_BASE_DIR, str(law_firm_id))
    os.makedirs(upload_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_name = secure_filename(upload.filename)
    saved_filename = f'{timestamp}_{safe_name}'
    file_path = os.path.join(upload_dir, saved_filename)
    upload.save(file_path)

    file_size = os.path.getsize(file_path)
    file_ext = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''

    # ── Extração de texto + metadados automáticos ────────────────────
    extracted_text = ''
    title = None
    case_name = None
    trf_region = None
    generation_mode = None
    quality_score = 3.0
    processed_document = None
    ingestor = None
    thesis_catalog = _load_thesis_catalog(law_firm_id)

    try:
        from app.agents.legal_drafting.impugnacao_reference_ingestor import (
            ImpugnacaoReferenceIngestor,
        )
        from app.agents.legal_drafting.impugnacao_reference_metadata_agent import (
            ImpugnacaoReferenceMetadataAgent,
        )

        ingestor = ImpugnacaoReferenceIngestor()
        processed_document = ingestor._process_document(file_path)
        extracted_text = str(getattr(processed_document, 'full_text', '') or '').strip()

        meta = ImpugnacaoReferenceMetadataAgent().extract(
            extracted_text, original_filename=upload.filename,
        )
        title = meta.title
        case_name = meta.case_name
        trf_region = meta.trf_region
        generation_mode = meta.generation_mode
        quality_score = meta.quality_score
    except Exception as error:
        print(f'[impugnacao_references.new] falha na extração de metadados: {error}')
        # Fallback determinístico: título a partir do nome do arquivo
        stem = os.path.splitext(upload.filename)[0]
        title = (stem.replace('_', ' ').replace('-', ' ').strip() or 'Peça-Modelo')[:250]

    reference = ImpugnacaoReferenceModel(
        law_firm_id=law_firm_id,
        user_id=user_id,
        title=title,
        case_name=case_name,
        trf_region=trf_region,
        generation_mode=generation_mode,
        quality_score=quality_score,
        original_filename=upload.filename,
        file_path=file_path,
        file_size=file_size,
        file_type=file_ext,
        notes=notes,
        status='active',
    )
    db.session.add(reference)
    db.session.commit()

    # Ingestão no Qdrant (não bloquear a criação se falhar)
    try:
        if ingestor is None:
            from app.agents.legal_drafting.impugnacao_reference_ingestor import (
                ImpugnacaoReferenceIngestor,
            )
            ingestor = ImpugnacaoReferenceIngestor()

        chunks_meta = ingestor.ingest_file(
            file_path=file_path,
            reference_id=reference.id,
            law_firm_id=law_firm_id,
            title=title,
            trf_region=trf_region,
            generation_mode=generation_mode,
            quality_score=quality_score,
            thesis_catalog=thesis_catalog,
            text=extracted_text,
            processed_document=processed_document,
        )

        reference.qdrant_collection = ingestor.collection
        reference.chunks_count = len(chunks_meta)
        reference.thesis_catalog_ids = ingestor.last_document_thesis_catalog_ids or []

        for chunk in chunks_meta:
            db.session.add(ImpugnacaoReferenceChunk(
                reference_id=reference.id,
                law_firm_id=law_firm_id,
                section_kind=chunk.get('section_kind'),
                thesis_catalog_id=chunk.get('thesis_catalog_id'),
                benefit_type=chunk.get('benefit_type'),
                qdrant_point_id=chunk.get('qdrant_point_id'),
                chunk_chars=chunk.get('chunk_chars', 0),
                order_in_doc=chunk.get('order_in_doc', 0),
                preview_text=chunk.get('preview_text'),
                full_text=chunk.get('full_text'),
                secao_origem=chunk.get('secao_origem'),
                tribunal=chunk.get('tribunal'),
                processo=chunk.get('processo'),
                relator=chunk.get('relator'),
                tipo_juris=chunk.get('tipo_juris'),
                fundamento_principal=chunk.get('fundamento_principal'),
            ))
        db.session.commit()
        meta_bits = []
        if trf_region:
            meta_bits.append(trf_region)
        if generation_mode:
            meta_bits.append(f'modo {generation_mode}')
        meta_suffix = f' ({", ".join(meta_bits)})' if meta_bits else ''
        flash(
            f'Peça-modelo "{title}"{meta_suffix} cadastrada e '
            f'{len(chunks_meta)} trechos indexados.',
            'success',
        )
    except Exception as error:
        db.session.rollback()
        # Recarrega para atualizar campos básicos
        reference = ImpugnacaoReferenceModel.query.get(reference.id)
        flash(
            f'Peça cadastrada, mas houve falha na indexação: {error}. '
            'Use "Reindexar" para tentar novamente.',
            'warning',
        )

    return redirect(url_for('impugnacao_references.reference_detail', ref_id=reference.id))


# ── Detalhe ───────────────────────────────────────────────────────────

@impugnacao_references_bp.route('/<int:ref_id>')
@require_law_firm
def reference_detail(ref_id):
    law_firm_id = get_current_law_firm_id()
    reference = ImpugnacaoReferenceModel.query.filter_by(
        id=ref_id, law_firm_id=law_firm_id
    ).first_or_404()
    chunks = (
        ImpugnacaoReferenceChunk.query
        .filter_by(reference_id=ref_id, law_firm_id=law_firm_id)
        .order_by(ImpugnacaoReferenceChunk.order_in_doc.asc())
        .all()
    )
    return render_template(
        'impugnacao_references/detail.html',
        reference=reference,
        chunks=chunks,
    )


# ── Arquivar / Reativar / Reindexar / Excluir ─────────────────────────

@impugnacao_references_bp.route('/<int:ref_id>/arquivar', methods=['POST'])
@require_law_firm
def archive_reference(ref_id):
    law_firm_id = get_current_law_firm_id()
    reference = ImpugnacaoReferenceModel.query.filter_by(
        id=ref_id, law_firm_id=law_firm_id
    ).first_or_404()
    reference.status = 'archived'
    db.session.commit()

    try:
        from app.agents.legal_drafting.impugnacao_reference_ingestor import (
            ImpugnacaoReferenceIngestor,
        )
        ImpugnacaoReferenceIngestor().set_status_by_reference_id(ref_id, 'archived')
    except Exception as error:
        flash(f'Arquivada no banco, mas falhou atualizar Qdrant: {error}', 'warning')
    else:
        flash('Peça-modelo arquivada.', 'success')

    return redirect(url_for('impugnacao_references.list_references'))


@impugnacao_references_bp.route('/<int:ref_id>/reativar', methods=['POST'])
@require_law_firm
def reactivate_reference(ref_id):
    law_firm_id = get_current_law_firm_id()
    reference = ImpugnacaoReferenceModel.query.filter_by(
        id=ref_id, law_firm_id=law_firm_id
    ).first_or_404()
    reference.status = 'active'
    db.session.commit()

    try:
        from app.agents.legal_drafting.impugnacao_reference_ingestor import (
            ImpugnacaoReferenceIngestor,
        )
        ImpugnacaoReferenceIngestor().set_status_by_reference_id(ref_id, 'active')
    except Exception as error:
        flash(f'Reativada no banco, mas falhou atualizar Qdrant: {error}', 'warning')
    else:
        flash('Peça-modelo reativada.', 'success')

    return redirect(url_for('impugnacao_references.reference_detail', ref_id=ref_id))


@impugnacao_references_bp.route('/<int:ref_id>/excluir', methods=['POST'])
@require_law_firm
def delete_reference(ref_id):
    law_firm_id = get_current_law_firm_id()
    reference = ImpugnacaoReferenceModel.query.filter_by(
        id=ref_id, law_firm_id=law_firm_id
    ).first_or_404()

    # Apaga arquivo físico
    if reference.file_path and os.path.exists(reference.file_path):
        try:
            os.remove(reference.file_path)
        except Exception:
            pass

    # Apaga vetores do Qdrant
    try:
        from app.agents.legal_drafting.impugnacao_reference_ingestor import (
            ImpugnacaoReferenceIngestor,
        )
        ImpugnacaoReferenceIngestor().delete_by_reference_id(ref_id)
    except Exception as error:
        print(f'[impugnacao_references] Falha ao deletar do Qdrant: {error}')

    db.session.delete(reference)
    db.session.commit()
    flash('Peça-modelo excluída.', 'success')
    return redirect(url_for('impugnacao_references.list_references'))


@impugnacao_references_bp.route('/<int:ref_id>/reindexar', methods=['POST'])
@require_law_firm
def reindex_reference(ref_id):
    law_firm_id = get_current_law_firm_id()
    reference = ImpugnacaoReferenceModel.query.filter_by(
        id=ref_id, law_firm_id=law_firm_id
    ).first_or_404()

    if not reference.file_path or not os.path.exists(reference.file_path):
        flash('Arquivo original não encontrado. Não é possível reindexar.', 'danger')
        return redirect(url_for('impugnacao_references.reference_detail', ref_id=ref_id))

    try:
        from app.agents.legal_drafting.impugnacao_reference_ingestor import (
            ImpugnacaoReferenceIngestor,
        )
        ingestor = ImpugnacaoReferenceIngestor()
        thesis_catalog = _load_thesis_catalog(law_firm_id)

        # Limpa vetores antigos e chunks antigos
        ingestor.delete_by_reference_id(ref_id)
        ImpugnacaoReferenceChunk.query.filter_by(reference_id=ref_id).delete()
        db.session.commit()

        chunks_meta = ingestor.ingest_file(
            file_path=reference.file_path,
            reference_id=reference.id,
            law_firm_id=law_firm_id,
            title=reference.title,
            trf_region=reference.trf_region,
            generation_mode=reference.generation_mode,
            quality_score=float(reference.quality_score) if reference.quality_score is not None else None,
            thesis_catalog=thesis_catalog,
            processed_document=ingestor._process_document(reference.file_path),
        )

        reference.qdrant_collection = ingestor.collection
        reference.chunks_count = len(chunks_meta)
        reference.thesis_catalog_ids = ingestor.last_document_thesis_catalog_ids or []
        for chunk in chunks_meta:
            db.session.add(ImpugnacaoReferenceChunk(
                reference_id=reference.id,
                law_firm_id=law_firm_id,
                section_kind=chunk.get('section_kind'),
                thesis_catalog_id=chunk.get('thesis_catalog_id'),
                benefit_type=chunk.get('benefit_type'),
                qdrant_point_id=chunk.get('qdrant_point_id'),
                chunk_chars=chunk.get('chunk_chars', 0),
                order_in_doc=chunk.get('order_in_doc', 0),
                preview_text=chunk.get('preview_text'),
                full_text=chunk.get('full_text'),
                secao_origem=chunk.get('secao_origem'),
                tribunal=chunk.get('tribunal'),
                processo=chunk.get('processo'),
                relator=chunk.get('relator'),
                tipo_juris=chunk.get('tipo_juris'),
                fundamento_principal=chunk.get('fundamento_principal'),
            ))
        db.session.commit()
        flash(f'Reindexado: {len(chunks_meta)} trechos.', 'success')
    except Exception as error:
        db.session.rollback()
        flash(f'Falha ao reindexar: {error}', 'danger')

    return redirect(url_for('impugnacao_references.reference_detail', ref_id=ref_id))
