"""Blueprint: Base de Peças-Modelo de Impugnação.

CRUD da base de referências de estilo do escritório usada pelo agente
gerador de impugnação à contestação. Multi-tenant (sempre filtra por
law_firm_id).

Rotas:
    GET  /referencias-impugnacao/
    GET  /referencias-impugnacao/novo
    POST /referencias-impugnacao/novo
    GET  /referencias-impugnacao/<id>
    GET  /referencias-impugnacao/<id>/status
    GET  /referencias-impugnacao/<id>/arquivo
    POST /referencias-impugnacao/<id>/metadados
    POST /referencias-impugnacao/<id>/arquivar
    POST /referencias-impugnacao/<id>/reativar
    POST /referencias-impugnacao/<id>/excluir
    POST /referencias-impugnacao/<id>/reindexar

A ingestão (Docling + agentes + embeddings + Qdrant + Meilisearch) roda em
thread de segundo plano — mesmo padrão do gerador de documentos do Painel de
Processos — com status em ImpugnacaoReferenceModel.ingestion_status e polling
pela rota /status.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, abort, current_app, jsonify, send_file,
)
from werkzeug.utils import secure_filename

from app.models import (
    db,
    ImpugnacaoReferenceModel,
    ImpugnacaoReferenceChunk,
    JudicialLegalThesis,
)
from app.services import impugnacao_reference_search


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


# ── Ingestão em segundo plano ─────────────────────────────────────────

def _run_reference_ingestion(app_obj, law_firm_id, ref_id, is_new):
    """Worker de ingestão (thread): Docling → metadados IA → Qdrant → Meili.

    No upload (is_new=True) os metadados são sempre extraídos; na reindexação
    só há backfill quando os campos de contexto estão vazios.
    """
    with app_obj.app_context():
        reference = None
        try:
            from app.agents.legal_drafting.impugnacao_reference_ingestor import (
                ImpugnacaoReferenceIngestor,
            )
            from app.agents.legal_drafting.impugnacao_reference_metadata_agent import (
                ImpugnacaoReferenceMetadataAgent,
            )

            reference = ImpugnacaoReferenceModel.query.filter_by(
                id=ref_id, law_firm_id=law_firm_id
            ).first()
            if reference is None or not reference.file_path:
                return

            ingestor = ImpugnacaoReferenceIngestor()
            processed_document = ingestor._process_document(reference.file_path)
            extracted_text = str(getattr(processed_document, 'full_text', '') or '').strip()

            needs_backfill = not any([
                reference.process_number, reference.orgao_julgador, reference.judge_name,
            ])
            if extracted_text and (is_new or needs_backfill):
                try:
                    meta = ImpugnacaoReferenceMetadataAgent().extract(
                        extracted_text, original_filename=reference.original_filename,
                    )
                    if is_new:
                        reference.title = (meta.title or reference.title)[:250]
                        reference.case_name = meta.case_name
                        reference.trf_region = meta.trf_region
                        reference.generation_mode = meta.generation_mode
                        reference.quality_score = meta.quality_score
                    reference.process_number = meta.process_number
                    reference.orgao_julgador = meta.orgao_julgador
                    reference.judge_name = meta.judge_name
                    if not is_new and not reference.trf_region and meta.trf_region:
                        reference.trf_region = meta.trf_region
                    db.session.commit()
                except Exception as error:
                    db.session.rollback()
                    print(f'[impugnacao_references.worker] metadados falharam: {error}')

            thesis_catalog = _load_thesis_catalog(law_firm_id)

            # Limpa índice antigo antes de reingerir.
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
                process_number=reference.process_number,
                orgao_julgador=reference.orgao_julgador,
                judge_name=reference.judge_name,
                thesis_catalog=thesis_catalog,
                text=extracted_text or None,
                processed_document=processed_document,
            )

            reference.qdrant_collection = ingestor.collection
            reference.chunks_count = len(chunks_meta)
            reference.thesis_catalog_ids = ingestor.last_document_thesis_catalog_ids or []
            reference.sections_json = ingestor.last_sections_summary or []
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
            reference.ingestion_status = 'completed'
            reference.ingestion_error = None
            db.session.commit()

            impugnacao_reference_search.index_reference_chunks(reference, chunks_meta)
        except Exception as error:
            app_obj.logger.error(f'[impugnacao_references.worker] falha na ingestão de {ref_id}: {error}')
            try:
                db.session.rollback()
                reference = ImpugnacaoReferenceModel.query.filter_by(
                    id=ref_id, law_firm_id=law_firm_id
                ).first()
                if reference is not None:
                    reference.ingestion_status = 'failed'
                    reference.ingestion_error = str(error)[:2000]
                    db.session.commit()
            except Exception:
                db.session.rollback()
        finally:
            db.session.remove()


def _spawn_reference_ingestion(law_firm_id, ref_id, is_new):
    threading.Thread(
        target=_run_reference_ingestion,
        args=(current_app._get_current_object(), law_firm_id, ref_id, is_new),
        daemon=True,
        name=f'impugnacao-ref-ingest-{ref_id}',
    ).start()


# ── Listagem ──────────────────────────────────────────────────────────

@impugnacao_references_bp.route('/')
@require_law_firm
def list_references():
    law_firm_id = get_current_law_firm_id()
    status_filter = (request.args.get('status') or 'active').strip()
    trf_filter = (request.args.get('trf') or '').strip().upper()
    vara_filter = (request.args.get('vara') or '').strip()
    search_query = (request.args.get('q') or '').strip()

    thesis_options = _load_thesis_catalog(law_firm_id)
    valid_thesis_keys = {t['key'] for t in thesis_options}
    tese_filter = (request.args.get('tese') or '').strip()
    if tese_filter not in valid_thesis_keys:
        tese_filter = ''

    query = ImpugnacaoReferenceModel.query.filter_by(law_firm_id=law_firm_id)
    if status_filter in ('active', 'archived'):
        query = query.filter_by(status=status_filter)
    if trf_filter:
        query = query.filter_by(trf_region=trf_filter)
    if vara_filter:
        query = query.filter(ImpugnacaoReferenceModel.orgao_julgador.ilike(f'%{vara_filter}%'))

    references = query.order_by(ImpugnacaoReferenceModel.created_at.desc()).all()

    if tese_filter:
        references = [
            ref for ref in references
            if tese_filter in (ref.thesis_catalog_ids or [])
        ]

    # Busca textual: Meilisearch com fallback SQL LIKE nos chunks.
    search_hits_by_ref: dict[int, list[dict]] = {}
    search_error = False
    if search_query:
        hits = impugnacao_reference_search.search_chunks(
            law_firm_id, search_query,
            status=status_filter if status_filter in ('active', 'archived') else 'active',
            trf_region=trf_filter or None,
            thesis_catalog_id=tese_filter or None,
        )
        if hits is None:
            # Meilisearch fora do ar: aviso na tela + fallback SQL LIKE.
            search_error = True
            like = f'%{search_query}%'
            rows = (
                ImpugnacaoReferenceChunk.query
                .filter_by(law_firm_id=law_firm_id)
                .filter(ImpugnacaoReferenceChunk.full_text.ilike(like))
                .limit(30)
                .all()
            )
            for row in rows:
                search_hits_by_ref.setdefault(row.reference_id, []).append({
                    'section': row.secao_origem or '',
                    'section_kind': row.section_kind,
                    'text': (row.preview_text or '')[:200],
                })
        else:
            for hit in hits:
                ref_id = hit.get('reference_id')
                if ref_id is not None:
                    search_hits_by_ref.setdefault(int(ref_id), []).append(hit)
        references = [ref for ref in references if ref.id in search_hits_by_ref]

    trf_options = ['TRF1', 'TRF2', 'TRF3', 'TRF4', 'TRF5', 'TRF6']
    total = len(references)
    total_chunks = sum(ref.chunks_count or 0 for ref in references)

    return render_template(
        'impugnacao_references/list.html',
        references=references,
        status_filter=status_filter,
        trf_filter=trf_filter,
        vara_filter=vara_filter,
        search_query=search_query,
        search_hits_by_ref=search_hits_by_ref,
        search_error=search_error,
        trf_options=trf_options,
        thesis_options=thesis_options,
        tese_filter=tese_filter,
        total=total,
        total_chunks=total_chunks,
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

    # Título provisório (nome do arquivo); a IA substitui no worker.
    stem = os.path.splitext(upload.filename)[0]
    provisional_title = (stem.replace('_', ' ').replace('-', ' ').strip() or 'Peça-Modelo')[:250]

    reference = ImpugnacaoReferenceModel(
        law_firm_id=law_firm_id,
        user_id=user_id,
        title=provisional_title,
        original_filename=upload.filename,
        file_path=file_path,
        file_size=file_size,
        file_type=file_ext,
        notes=notes,
        status='active',
        ingestion_status='processing',
    )
    db.session.add(reference)
    db.session.commit()

    _spawn_reference_ingestion(law_firm_id, reference.id, is_new=True)
    flash(
        'Peça enviada. A extração de metadados e a indexação rodam em segundo '
        'plano — a página atualiza sozinha quando concluir.',
        'info',
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


@impugnacao_references_bp.route('/<int:ref_id>/arquivo')
@require_law_firm
def view_reference_file(ref_id):
    """Serve o arquivo original inline (PDF abre no navegador; demais baixam)."""
    law_firm_id = get_current_law_firm_id()
    reference = ImpugnacaoReferenceModel.query.filter_by(
        id=ref_id, law_firm_id=law_firm_id
    ).first_or_404()

    file_path = str(reference.file_path or '').strip()
    if not file_path or not os.path.exists(file_path):
        flash('Arquivo original não encontrado no servidor.', 'warning')
        return redirect(url_for('impugnacao_references.reference_detail', ref_id=ref_id))

    return send_file(
        os.path.abspath(file_path),
        as_attachment=False,
        download_name=reference.original_filename,
    )


@impugnacao_references_bp.route('/<int:ref_id>/status')
@require_law_firm
def reference_status(ref_id):
    """Status da ingestão — consumido pelo polling da tela de detalhe."""
    law_firm_id = get_current_law_firm_id()
    reference = ImpugnacaoReferenceModel.query.filter_by(
        id=ref_id, law_firm_id=law_firm_id
    ).first_or_404()
    return jsonify({
        'status': reference.ingestion_status or 'completed',
        'chunks_count': reference.chunks_count or 0,
    })


@impugnacao_references_bp.route('/<int:ref_id>/metadados', methods=['POST'])
@require_law_firm
def update_metadata(ref_id):
    from app.utils.cnj import cnj_digits, tribunal_sigla_from_cnj

    law_firm_id = get_current_law_firm_id()
    reference = ImpugnacaoReferenceModel.query.filter_by(
        id=ref_id, law_firm_id=law_firm_id
    ).first_or_404()

    def _clean(name, max_len):
        value = (request.form.get(name) or '').strip()
        return value[:max_len] or None

    reference.title = _clean('title', 250) or reference.title
    reference.case_name = _clean('case_name', 250)
    reference.orgao_julgador = _clean('orgao_julgador', 250)
    reference.judge_name = _clean('judge_name', 250)

    process_number = _clean('process_number', 30)
    if process_number and len(cnj_digits(process_number)) != 20:
        flash('Número CNJ inválido — os demais campos foram salvos.', 'warning')
        process_number = reference.process_number
    reference.process_number = process_number

    trf_region = (request.form.get('trf_region') or '').strip().upper() or None
    cnj_sigla = tribunal_sigla_from_cnj(reference.process_number)
    if cnj_sigla and cnj_sigla.startswith('TRF'):
        trf_region = cnj_sigla  # CNJ válido manda no TRF
    reference.trf_region = trf_region if trf_region in (
        'TRF1', 'TRF2', 'TRF3', 'TRF4', 'TRF5', 'TRF6') else None

    db.session.commit()

    # Reflete os metadados no índice de busca da tela (partial update —
    # preserva texto/heading/section já indexados).
    impugnacao_reference_search.update_reference_metadata(reference)

    flash('Metadados atualizados. Reindexe a peça para propagar ao Qdrant.', 'success')
    return redirect(url_for('impugnacao_references.reference_detail', ref_id=ref_id))


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

    impugnacao_reference_search.update_reference_status(reference)

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

    impugnacao_reference_search.update_reference_status(reference)

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

    impugnacao_reference_search.delete_reference(ref_id)

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

    if reference.ingestion_status == 'processing':
        flash('Esta peça já está sendo indexada — aguarde a conclusão.', 'warning')
        return redirect(url_for('impugnacao_references.reference_detail', ref_id=ref_id))

    reference.ingestion_status = 'processing'
    reference.ingestion_error = None
    db.session.commit()

    _spawn_reference_ingestion(law_firm_id, ref_id, is_new=False)
    flash(
        'Reindexação iniciada em segundo plano — a página atualiza sozinha '
        'quando concluir.',
        'info',
    )
    return redirect(url_for('impugnacao_references.reference_detail', ref_id=ref_id))
