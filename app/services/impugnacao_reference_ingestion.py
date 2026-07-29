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


def _clip(value, max_len: int):
    """Corta um valor de texto no limite da coluna (None passa direto).

    O extrator de jurisprudência devolve listas concatenadas ("AC x; AC y; ...")
    que estouram VARCHAR e, sem isso, um único campo longo derrubava a ingestão
    inteira da peça (DataError no INSERT do lote de chunks).
    """
    if value is None:
        return None
    text = str(value)
    return text[:max_len] if len(text) > max_len else text


def apply_extracted_metadata(reference, meta, *, is_new: bool, preserve_curated_fields: bool) -> None:
    """Aplica ao `reference` os metadados extraídos pela IA (`meta`).

    Função pura (sem I/O, sem consultar `needs_backfill`) — só decide qual
    campo recebe o valor da IA. Extraída de `ingest_reference` para ser
    testável isoladamente com um objeto simples (não precisa do modelo
    SQLAlchemy nem de app context).

    Duas categorias de campo:
    - Curados (`title`, `case_name`, `trf_region`, `orgao_julgador`): quando
      `is_new=True` e `preserve_curated_fields=True` (importação em lote a
      partir da planilha, cujos metadados são fato curado), só são
      preenchidos pela IA se ainda estiverem vazios — nunca sobrescrevem o
      que veio da planilha. Com `preserve_curated_fields=False` (upload
      manual), a IA sempre define esses 4 campos quando `is_new=True`.
    - Sempre-IA (`process_number`, `judge_name`, `generation_mode`,
      `quality_score`): a planilha nunca traz esses dados, então a IA é a
      única fonte — são sempre atribuídos quando `is_new=True`,
      independente de `preserve_curated_fields` (inclusive `quality_score`,
      que tem default truthy `Decimal('3.00')` no modelo — por isso não
      pode ser tratado como "vazio == não preenchido").

    Quando `is_new=False` (reindexação), os campos curados não são tocados;
    `process_number`/`orgao_julgador`/`judge_name` são sempre atribuídos
    (o chamador só roda a extração aqui quando os três já estão vazios —
    ver `needs_backfill` em `ingest_reference`) e `trf_region` recebe
    backfill apenas se estiver vazio.
    """
    if is_new:
        if preserve_curated_fields:
            if not reference.title:
                reference.title = (meta.title or reference.title)[:250]
            if not reference.case_name:
                reference.case_name = meta.case_name
            if not reference.trf_region:
                reference.trf_region = meta.trf_region
            if not reference.orgao_julgador:
                reference.orgao_julgador = meta.orgao_julgador
        else:
            reference.title = (meta.title or reference.title)[:250]
            reference.case_name = meta.case_name
            reference.trf_region = meta.trf_region
            reference.orgao_julgador = meta.orgao_julgador
        reference.generation_mode = meta.generation_mode
        reference.quality_score = meta.quality_score
        reference.process_number = meta.process_number
        reference.judge_name = meta.judge_name
    else:
        reference.process_number = meta.process_number
        reference.orgao_julgador = meta.orgao_julgador
        reference.judge_name = meta.judge_name
        if not reference.trf_region and meta.trf_region:
            reference.trf_region = meta.trf_region


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
    (title, case_name, trf_region, orgao_julgador) só são sobrescritos pela
    IA se estiverem vazios (usado pela importação em lote, cujos metadados
    da planilha são fato curado). process_number, judge_name,
    generation_mode e quality_score são sempre definidos pela IA (a
    planilha não traz esses dados). Com o flag em False (padrão — caminho
    do upload manual), o comportamento é o mesmo de sempre: a IA sempre
    define os 4 campos curados quando is_new=True. Ver `apply_extracted_metadata`.
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
                apply_extracted_metadata(
                    reference, meta,
                    is_new=is_new, preserve_curated_fields=preserve_curated_fields,
                )
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
                section_kind=_clip(chunk.get('section_kind'), 60),
                thesis_catalog_id=_clip(chunk.get('thesis_catalog_id'), 120),
                benefit_type=_clip(chunk.get('benefit_type'), 10),
                qdrant_point_id=_clip(chunk.get('qdrant_point_id'), 64),
                chunk_chars=chunk.get('chunk_chars', 0),
                order_in_doc=chunk.get('order_in_doc', 0),
                preview_text=chunk.get('preview_text'),
                full_text=chunk.get('full_text'),
                secao_origem=_clip(chunk.get('secao_origem'), 60),
                tribunal=_clip(chunk.get('tribunal'), 120),
                processo=_clip(chunk.get('processo'), 500),
                relator=_clip(chunk.get('relator'), 500),
                tipo_juris=_clip(chunk.get('tipo_juris'), 60),
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
