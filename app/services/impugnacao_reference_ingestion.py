"""Ingestão de peças-modelo de impugnação: Docling -> metadados IA -> Qdrant/Meili.

Extraído do worker de thread do blueprint `impugnacao_references` para ser
reutilizado também pelo worker da fila de importação em lote (planilha).

`ingest_reference` exige contexto de aplicação Flask ativo (app context) e
NÃO chama `db.session.remove()` — quem chama esta função é responsável por
gerenciar o ciclo de vida da sessão (ex.: remover a sessão só no `finally` do
job inteiro, para não fechar a sessão no meio de um laço que processa vários
itens).
"""
from __future__ import annotations

from flask import current_app

from app.models import (
    db,
    ImpugnacaoReferenceModel,
    ImpugnacaoReferenceChunk,
    JudicialLegalThesis,
)
from app.services import impugnacao_reference_search


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


def ingest_reference(
    law_firm_id: int,
    ref_id: int,
    *,
    is_new: bool,
    preserve_curated_fields: bool = False,
) -> None:
    """Processa e indexa uma peça-modelo: Docling -> metadados IA -> Qdrant -> Meili.

    Exige app context ativo. Atualiza `ingestion_status`/`ingestion_error` da
    peça. NÃO chama `db.session.remove()` — quem chama gerencia o ciclo da
    sessão.

    No upload manual (is_new=True) os metadados são sempre extraídos; na
    reindexação só há backfill quando os campos de contexto estão vazios.

    `preserve_curated_fields`: quando True, os campos vindos de fonte curada
    (title, case_name, trf_region, generation_mode, quality_score) só são
    sobrescritos pela IA se estiverem vazios (usado pela importação em lote,
    cujos metadados da planilha são fato curado). Com o flag em False
    (padrão — caminho do upload manual), o comportamento é o mesmo de sempre:
    a IA sempre define esses 5 campos quando is_new=True.
    """
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
                    if preserve_curated_fields:
                        if not reference.title:
                            reference.title = (meta.title or reference.title)[:250]
                        if not reference.case_name:
                            reference.case_name = meta.case_name
                        if not reference.trf_region:
                            reference.trf_region = meta.trf_region
                        if not reference.generation_mode:
                            reference.generation_mode = meta.generation_mode
                        if not reference.quality_score:
                            reference.quality_score = meta.quality_score
                    else:
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
        current_app.logger.error(f'[impugnacao_references.worker] falha na ingestão de {ref_id}: {error}')
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
