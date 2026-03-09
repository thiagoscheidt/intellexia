"""
Processador de arquivos da Base de Conhecimento (pendentes).

Uso:
  python scripts/process_knowledge_base.py
  python scripts/process_knowledge_base.py --batch-size 20
  python scripts/process_knowledge_base.py --file-id 123
  python scripts/process_knowledge_base.py --include-errors
"""

import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from rich import print

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.models import (
    db,
    KnowledgeBase,
    KnowledgeSummary,
    JudicialProcess,
    JudicialProcessBenefit,
    JudicialEvent,
    JudicialDocument,
    JudicialDocumentType,
    JudicialPhase,
)
from app.agents.knowledge_base.knowledge_ingestion_agent import KnowledgeIngestionAgent
from app.agents.document_processing.agent_document_extractor import AgentDocumentExtractor


def _build_query(file_id: int | None = None, include_errors: bool = False):
    """Monta a query base para itens pendentes (ou um item específico)."""
    statuses = ['pending']
    if include_errors:
        statuses.append('error')

    if file_id:
        return KnowledgeBase.query.filter(
            KnowledgeBase.id == file_id,
            KnowledgeBase.is_active.is_(True),
            KnowledgeBase.processing_status.in_(statuses),
        )

    return KnowledgeBase.query.filter(
        KnowledgeBase.is_active.is_(True),
        KnowledgeBase.processing_status.in_(statuses),
    ).order_by(KnowledgeBase.uploaded_at.desc())


def _normalize_process_number(value: str | None) -> str:
    if not value:
        return ''
    return ''.join(char for char in str(value) if char.isdigit())


def _extract_primary_process_number(value: str | None) -> str:
    if not value:
        return ''

    text_value = str(value).strip()
    cnj_pattern = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
    match = cnj_pattern.search(text_value)
    if match:
        return match.group(0)

    normalized_digits = _normalize_process_number(text_value)
    if len(normalized_digits) == 20:
        return normalized_digits

    return text_value[:25]


def _find_process_by_number(law_firm_id: int, process_number: str) -> JudicialProcess | None:
    if not process_number:
        return None

    exact_match = JudicialProcess.query.filter_by(
        law_firm_id=law_firm_id,
        process_number=process_number,
    ).first()
    if exact_match:
        return exact_match

    normalized_target = _normalize_process_number(process_number)
    if not normalized_target:
        return None

    candidates = JudicialProcess.query.filter_by(law_firm_id=law_firm_id).all()
    for candidate in candidates:
        if _normalize_process_number(candidate.process_number) == normalized_target:
            return candidate

    return None


def _resolve_type_and_phase(
    law_firm_id: int,
    extraction_payload: dict,
) -> tuple[str, str, str]:
    extracted_type_key = str(extraction_payload.get('suggested_document_type_key', '') or '').strip()
    extracted_type_name = str(extraction_payload.get('suggested_document_type_name', '') or '').strip()

    document_type = None
    if extracted_type_key:
        document_type = JudicialDocumentType.query.filter_by(
            law_firm_id=law_firm_id,
            key=extracted_type_key,
            is_active=True,
        ).first()

    if not document_type and extracted_type_name:
        document_type = JudicialDocumentType.query.filter_by(
            law_firm_id=law_firm_id,
            name=extracted_type_name,
            is_active=True,
        ).first()

    if document_type and document_type.phase:
        type_key = document_type.key
        phase_key = document_type.phase.key
        type_name = document_type.name
        return type_key, phase_key, type_name

    default_phase = JudicialPhase.query.filter_by(
        law_firm_id=law_firm_id,
        is_active=True,
    ).order_by(JudicialPhase.display_order.asc(), JudicialPhase.name.asc()).first()

    fallback_type = extracted_type_key or 'documento_juntado'
    fallback_phase = default_phase.key if default_phase else 'inicio_processo'
    fallback_name = extracted_type_name or fallback_type
    return fallback_type, fallback_phase, fallback_name


def _link_knowledge_to_process_if_needed(item: KnowledgeBase, extraction_payload: dict) -> None:
    existing_link = JudicialDocument.query.filter_by(knowledge_base_id=item.id).first()
    if existing_link:
        return

    current_lawsuit = str(item.lawsuit_number or '').strip()
    extracted_lawsuit = str(extraction_payload.get('process_number', '') or '').strip()
    candidate_process_number = current_lawsuit or extracted_lawsuit
    if not candidate_process_number:
        return

    process = _find_process_by_number(item.law_firm_id, candidate_process_number)
    if not process:
        process_number_for_create = _extract_primary_process_number(candidate_process_number)
        if not process_number_for_create:
            return

        process = JudicialProcess(
            law_firm_id=item.law_firm_id,
            user_id=item.user_id,
            process_number=process_number_for_create,
            title=f'Processo {process_number_for_create}',
            description=(
                f'Processo criado automaticamente a partir do arquivo da KnowledgeBase '
                f'ID {item.id} ({item.original_filename}).'
            ),
            status='ativo',
            origin_unit=str(extraction_payload.get('judicial_court', '') or '').strip() or None,
        )
        db.session.add(process)
        db.session.flush()

        if not item.lawsuit_number or not item.lawsuit_number.strip():
            item.lawsuit_number = process_number_for_create

    event_type, event_phase, event_type_name = _resolve_type_and_phase(item.law_firm_id, extraction_payload)

    event = JudicialEvent(
        process_id=process.id,
        type=event_type,
        phase=event_phase,
        description=f'Documento da KnowledgeBase vinculado automaticamente ({event_type_name}).',
        event_date=datetime.utcnow(),
    )
    db.session.add(event)
    db.session.flush()

    db.session.add(
        JudicialDocument(
            process_id=process.id,
            event_id=event.id,
            knowledge_base_id=item.id,
            type=event_type,
            file_name=item.original_filename,
            file_path=item.file_path,
            uploaded_by=item.user_id,
        )
    )

    process.updated_at = datetime.utcnow()


def _is_initial_petition_document(extraction_payload: dict) -> bool:
    doc_type_key = str(extraction_payload.get('suggested_document_type_key', '') or '').strip().lower()
    doc_type_name = str(extraction_payload.get('suggested_document_type_name', '') or '').strip().lower()

    key_match = 'peticao' in doc_type_key and 'inicial' in doc_type_key
    name_match = 'petição inicial' in doc_type_name or ('peticao' in doc_type_name and 'inicial' in doc_type_name)
    return key_match or name_match


def _resolve_target_process(item: KnowledgeBase, extraction_payload: dict) -> JudicialProcess | None:
    existing_link = JudicialDocument.query.filter_by(knowledge_base_id=item.id).first()
    if existing_link:
        return JudicialProcess.query.filter_by(id=existing_link.process_id).first()

    current_lawsuit = str(item.lawsuit_number or '').strip()
    extracted_lawsuit = str(extraction_payload.get('process_number', '') or '').strip()
    candidate_process_number = current_lawsuit or extracted_lawsuit
    if not candidate_process_number:
        return None

    return _find_process_by_number(item.law_firm_id, candidate_process_number)


def _upsert_process_benefits(
    process: JudicialProcess,
    benefits_payload: dict,
) -> int:
    if not isinstance(benefits_payload, dict):
        return 0

    extracted_benefits = benefits_payload.get('benefits', [])
    if not isinstance(extracted_benefits, list):
        return 0

    general_context = str(benefits_payload.get('general_revision_context', '') or '').strip()
    upserted = 0

    for benefit in extracted_benefits:
        if not isinstance(benefit, dict):
            continue

        benefit_number = str(benefit.get('benefit_number', '') or '').strip()
        if not benefit_number:
            continue

        nit_number = str(benefit.get('nit_number', '') or '').strip()
        insured_name = str(benefit.get('insured_name', '') or '').strip()
        benefit_type = str(benefit.get('benefit_type', '') or '').strip()
        fap_vigencia_year = str(benefit.get('fap_vigencia_year', '') or '').strip()

        existing_benefit = JudicialProcessBenefit.query.filter_by(
            process_id=process.id,
            benefit_number=benefit_number,
        ).first()

        if existing_benefit:
            if nit_number and not str(existing_benefit.nit_number or '').strip():
                existing_benefit.nit_number = nit_number
            if insured_name and not str(existing_benefit.insured_name or '').strip():
                existing_benefit.insured_name = insured_name
            if benefit_type and not str(existing_benefit.benefit_type or '').strip():
                existing_benefit.benefit_type = benefit_type
            if fap_vigencia_year and not str(existing_benefit.fap_vigencia_year or '').strip():
                existing_benefit.fap_vigencia_year = fap_vigencia_year
            if general_context and not str(existing_benefit.legal_thesis or '').strip():
                existing_benefit.legal_thesis = general_context
            existing_benefit.updated_at = datetime.utcnow()
            upserted += 1
            continue

        db.session.add(
            JudicialProcessBenefit(
                process_id=process.id,
                benefit_number=benefit_number,
                nit_number=nit_number,
                insured_name=insured_name,
                benefit_type=benefit_type,
                fap_vigencia_year=fap_vigencia_year,
                legal_thesis=general_context,
                pfn_technical_note='',
                first_instance_decision='',
                second_instance_decision='',
                third_instance_decision='',
            )
        )
        upserted += 1

    return upserted


def _process_single_knowledge_file(item_id: int) -> bool:
    """Processa um único arquivo da base de conhecimento."""
    with app.app_context():
        item = None
        try:
            item = KnowledgeBase.query.filter_by(id=item_id, is_active=True).first()
            if not item:
                print(f"Arquivo ID {item_id} não encontrado ou inativo.")
                return False

            print(f"Iniciando processamento: {item.id} - {item.original_filename}")

            item.processing_status = 'processing'
            item.processing_error_message = None
            db.session.commit()

            file_path = Path(item.file_path)
            if not file_path.exists():
                raise FileNotFoundError(f"Arquivo não encontrado no caminho: {item.file_path}")

            ingestion_agent = KnowledgeIngestionAgent()
            # summary_agent = AgentDocumentSummary()
            extractor_agent = AgentDocumentExtractor()

            markdown_content = ingestion_agent.process_file(
                file_path=file_path,
                source_name=item.original_filename,
                category=item.category,
                description=item.description,
                tags=item.tags,
                lawsuit_number=item.lawsuit_number,
                file_id=item.id,
            )

            if not markdown_content:
                raise RuntimeError("Processamento não retornou conteúdo.")

            # summary_payload = summary_agent.summarizeDocument(file_path=item.file_path)
            extraction_payload = extractor_agent.extract_document_data(
                file_path=item.file_path,
                law_firm_id=item.law_firm_id,
            )
            if not extraction_payload:
                raise RuntimeError("Extração estruturada não retornou conteúdo.")

            if isinstance(extraction_payload, dict):
                extracted_process_number = str(extraction_payload.get('process_number', '') or '').strip()
                extracted_category = str(extraction_payload.get('suggested_category', '') or '').strip()
                extracted_doc_type_name = str(extraction_payload.get('suggested_document_type_name', '') or '').strip()
                extracted_doc_type_key = str(extraction_payload.get('suggested_document_type_key', '') or '').strip()

                if extracted_process_number and (not item.lawsuit_number or item.lawsuit_number.strip() == ''):
                    item.lawsuit_number = extracted_process_number

                if extracted_category and (not item.category or item.category.strip() == ''):
                    item.category = extracted_category

                if (not item.tags or item.tags.strip() == '') and (extracted_doc_type_name or extracted_doc_type_key):
                    item.tags = extracted_doc_type_name or extracted_doc_type_key

                _link_knowledge_to_process_if_needed(item, extraction_payload)

                if _is_initial_petition_document(extraction_payload):
                    target_process = _resolve_target_process(item, extraction_payload)
                    if target_process:
                        benefits_payload = extractor_agent.extract_benefits_from_petition(
                            file_path=item.file_path,
                        )
                        inserted_or_updated = _upsert_process_benefits(target_process, benefits_payload)
                        if inserted_or_updated > 0:
                            print(
                                f"Benefícios vinculados ao processo {target_process.process_number}: "
                                f"{inserted_or_updated} registro(s)."
                            )

            summary_payload = extraction_payload if isinstance(extraction_payload, dict) else {}

            existing_summary = KnowledgeSummary.query.filter_by(knowledge_base_id=item.id).first()
            if existing_summary:
                existing_payload = existing_summary.payload if isinstance(existing_summary.payload, dict) else {}

                merged_payload = dict(existing_payload)
                for key in [
                    'process_number',
                    'suggested_category',
                    'suggested_document_type_key',
                    'suggested_document_type_name',
                    'judicial_court',
                    'active_pole',
                    'passive_pole',
                ]:
                    current_value = str(merged_payload.get(key, '') or '').strip()
                    new_value = str(summary_payload.get(key, '') or '').strip()
                    if not current_value and new_value:
                        merged_payload[key] = new_value

                existing_summary.payload = merged_payload
                existing_summary.updated_at = datetime.utcnow()
            else:
                db.session.add(
                    KnowledgeSummary(
                        knowledge_base_id=item.id,
                        payload=summary_payload,
                    )
                )

            item.processing_status = 'completed'
            item.processed_at = datetime.utcnow()
            item.processing_error_message = None
            db.session.commit()

            print(f"Processado com sucesso: {item.id} - {item.original_filename}")
            return True

        except Exception as error:
            db.session.rollback()

            if item is not None:
                try:
                    item.processing_status = 'error'
                    item.processing_error_message = str(error)
                    db.session.commit()
                except Exception:
                    db.session.rollback()

            print(f"Erro ao processar ID {item_id}: {error}")
            return False
        finally:
            db.session.remove()


def process_pending_knowledge_files(
    batch_size: int = 10,
    file_id: int | None = None,
    include_errors: bool = False,
    max_workers: int = 3,
) -> int:
    """Processa arquivos pendentes da base de conhecimento."""
    query = _build_query(file_id=file_id, include_errors=include_errors)

    if file_id:
        items = query.all()
    else:
        items = query.limit(batch_size).all()

    print(f"Itens elegíveis para processamento: {len(items)}")

    if not items:
        if file_id:
            print(f"Nenhum arquivo elegível encontrado para o ID {file_id}.")
        else:
            print("Nenhum arquivo pendente encontrado.")
        return 0

    item_ids = [item.id for item in items]
    workers = max(1, min(max_workers, len(item_ids)))
    print(f"Processando em paralelo com {workers} thread(s)...")

    if workers == 1:
        return sum(1 for item_id in item_ids if _process_single_knowledge_file(item_id))

    processed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_process_single_knowledge_file, item_id) for item_id in item_ids]
        for future in as_completed(futures):
            if future.result():
                processed += 1

    return processed


def parse_args():
    parser = argparse.ArgumentParser(description='Processa arquivos pendentes da base de conhecimento')
    parser.add_argument('--batch-size', type=int, default=10, help='Quantidade máxima de itens por execução')
    parser.add_argument('--file-id', type=int, help='Processa apenas o arquivo com esse ID')
    parser.add_argument('--max-workers', type=int, default=3, help='Quantidade de threads paralelas para processamento')
    parser.add_argument(
        '--include-errors',
        action='store_true',
        help='Inclui também arquivos com status error (além de pending)',
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()

    with app.app_context():
        total = process_pending_knowledge_files(
            batch_size=args.batch_size,
            file_id=args.file_id,
            include_errors=args.include_errors,
            max_workers=args.max_workers,
        )
        print(f"Total processado: {total}")
