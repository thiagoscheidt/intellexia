from __future__ import annotations

from datetime import datetime

from app.models import (
    db,
    JudicialDocument,
    JudicialDocumentType,
    JudicialEvent,
    JudicialPhase,
)


class JudicialDocumentService:
    """Serviço para organização de operações de vínculo documental no painel judicial."""

    @staticmethod
    def get_link_by_knowledge_base_id(knowledge_base_id: int) -> JudicialDocument | None:
        return JudicialDocument.query.filter_by(knowledge_base_id=knowledge_base_id).first()

    @staticmethod
    def resolve_type_and_phase(law_firm_id: int, extraction_payload: dict) -> tuple[str, str, str]:
        extracted_type_key = str(extraction_payload.get("suggested_document_type_key", "") or "").strip()
        extracted_type_name = str(extraction_payload.get("suggested_document_type_name", "") or "").strip()

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
            return document_type.key, document_type.phase.key, document_type.name

        default_phase = JudicialPhase.query.filter_by(
            law_firm_id=law_firm_id,
            is_active=True,
        ).order_by(JudicialPhase.display_order.asc(), JudicialPhase.name.asc()).first()

        fallback_type = extracted_type_key or "documento_juntado"
        fallback_phase = default_phase.key if default_phase else "inicio_processo"
        fallback_name = extracted_type_name or fallback_type
        return fallback_type, fallback_phase, fallback_name

    @staticmethod
    def link_knowledge_base_document(process, knowledge_item, extraction_payload: dict) -> bool:
        event_type, event_phase, event_type_name = JudicialDocumentService.resolve_type_and_phase(
            process.law_firm_id,
            extraction_payload,
        )

        file_hash = str(getattr(knowledge_item, "file_hash", "") or "").strip()
        if file_hash:
            duplicate_in_process = JudicialDocument.query.filter_by(
                process_id=process.id,
                file_hash=file_hash,
            ).first()
            if duplicate_in_process:
                return False

        event = JudicialEvent(
            process_id=process.id,
            type=event_type,
            phase=event_phase,
            description=f"Documento da KnowledgeBase vinculado automaticamente ({event_type_name}).",
            event_date=datetime.utcnow(),
        )
        db.session.add(event)
        db.session.flush()

        db.session.add(
            JudicialDocument(
                process_id=process.id,
                event_id=event.id,
                knowledge_base_id=knowledge_item.id,
                type=event_type,
                file_name=knowledge_item.original_filename,
                file_path=knowledge_item.file_path,
                file_hash=file_hash or None,
                uploaded_by=knowledge_item.user_id,
            )
        )
        return True
