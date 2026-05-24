from __future__ import annotations

from datetime import datetime

from rich import print

from app.models import (
    db,
    JudicialDocument,
    JudicialDocumentSummary,
    JudicialDocumentType,
    JudicialEvent,
    JudicialPhase,
    KnowledgeBase,
    KnowledgeSummary,
)
from app.agents.processes.judicial_document_summary_agent import JudicialDocumentSummaryAgent


class JudicialDocumentService:
    """Serviço para vínculo e processamento de documentos judiciais."""

    def __init__(self, flask_app=None, max_documents_per_execution: int = 5):
        self.app = flask_app
        self.max_documents_per_execution = max_documents_per_execution

    def _build_query(self, document_id: int | None = None, include_errors: bool = False):
        statuses = ['pending']
        if include_errors:
            statuses.append('error')

        base_query = JudicialDocument.query.filter(
            JudicialDocument.status.in_(statuses),
            JudicialDocument.knowledge_base_id.isnot(None),
        )

        if document_id:
            return base_query.filter(JudicialDocument.id == document_id)

        return base_query.order_by(JudicialDocument.created_at.asc())

    @staticmethod
    def get_link_by_knowledge_base_id(knowledge_base_id: int) -> JudicialDocument | None:
        return JudicialDocument.query.filter_by(knowledge_base_id=knowledge_base_id).first()

    @staticmethod
    def resolve_type_and_phase(law_firm_id: int, extraction_payload: dict) -> tuple[str, str, str]:
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
            return document_type.key, document_type.phase.key, document_type.name

        default_phase = JudicialPhase.query.filter_by(
            law_firm_id=law_firm_id,
            is_active=True,
        ).order_by(JudicialPhase.display_order.asc(), JudicialPhase.name.asc()).first()

        fallback_type = extracted_type_key or 'documento_juntado'
        fallback_phase = default_phase.key if default_phase else 'inicio_processo'
        fallback_name = extracted_type_name or fallback_type
        return fallback_type, fallback_phase, fallback_name

    @staticmethod
    def link_knowledge_base_document(process, knowledge_item, extraction_payload: dict) -> bool:
        event_type, event_phase, event_type_name = JudicialDocumentService.resolve_type_and_phase(
            process.law_firm_id,
            extraction_payload,
        )

        file_hash = str(getattr(knowledge_item, 'file_hash', '') or '').strip()
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
            description=f'Documento da KnowledgeBase vinculado automaticamente ({event_type_name}).',
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
                status='pending',
            )
        )
        return True

    @staticmethod
    def _set_document_status(document: JudicialDocument, status: str, error_message: str | None = None) -> None:
        document.status = status
        document.error_message = error_message
        if status == 'completed':
            document.processed_at = datetime.utcnow()
        document.updated_at = datetime.utcnow()

    def _process_single_document(self, document: JudicialDocument) -> bool:
        if not document.knowledge_base_id:
            self._set_document_status(document, 'error', 'Documento sem vínculo com KnowledgeBase.')
            db.session.commit()
            return False

        kb_item = KnowledgeBase.query.filter_by(id=document.knowledge_base_id).first()
        if not kb_item:
            self._set_document_status(document, 'error', 'KnowledgeBase não encontrada para este documento.')
            db.session.commit()
            return False

        try:
            self._set_document_status(document, 'processing')
            db.session.commit()

            from app.services.knowledge_base_processing_service import KnowledgeBaseProcessingService

            kb_service = KnowledgeBaseProcessingService(flask_app=self.app)
            success = kb_service.process_single_knowledge_file(
                document.knowledge_base_id,
                skip_indexing=True,
            )

            if success:
                refreshed = JudicialDocument.query.get(document.id)
                if refreshed:
                    self._set_document_status(refreshed, 'completed')
                db.session.commit()
                self._summarize_judicial_document(refreshed or document, kb_item)
                return True

            self._set_document_status(document, 'error', 'Falha no processamento da KnowledgeBase.')
            db.session.commit()
            return False
        except Exception as error:
            db.session.rollback()
            try:
                self._set_document_status(document, 'error', str(error))
                db.session.commit()
            except Exception:
                db.session.rollback()
            print(f'Erro ao processar documento judicial ID {document.id}: {error}')
            return False

    def _summarize_judicial_document(
        self,
        document: JudicialDocument,
        kb_item: KnowledgeBase,
    ) -> None:
        if not document or not kb_item:
            return

        try:
            doc_type = None
            if document.type:
                doc_type = JudicialDocumentType.query.filter_by(
                    law_firm_id=kb_item.law_firm_id,
                    key=document.type,
                    is_active=True,
                ).first()

            doc_type_name = str(getattr(doc_type, 'name', '') or '').strip()
            doc_type_key = str(document.type or '').strip()

            knowledge_summary = KnowledgeSummary.query.filter_by(knowledge_base_id=kb_item.id).first()
            summary_payload = knowledge_summary.payload if knowledge_summary and isinstance(knowledge_summary.payload, dict) else {}
            sections_overview = summary_payload.get('sections_overview', [])
            if not isinstance(sections_overview, list):
                sections_overview = []
            pedidos_excerpt = str(summary_payload.get('pedidos_excerpt', '') or '').strip()

            summary_agent = JudicialDocumentSummaryAgent()
            summary_result = summary_agent.summarize_document(
                file_path=str(kb_item.file_path),
                document_type_name=doc_type_name,
                document_type_key=doc_type_key,
                file_type=kb_item.file_type or '',
                sections_overview=sections_overview,
                pedidos_excerpt=pedidos_excerpt,
                user_id=kb_item.user_id,
                law_firm_id=kb_item.law_firm_id,
            )

            summary_text = ''
            if isinstance(summary_result, dict):
                summary_text = str(
                    summary_result.get('summary_long')
                    or summary_result.get('summary')
                    or summary_result.get('summary_short')
                    or ''
                ).strip()
            existing = JudicialDocumentSummary.query.filter_by(
                judicial_document_id=document.id,
                law_firm_id=kb_item.law_firm_id,
            ).first()

            if existing:
                existing.summary_text = summary_text
                existing.summary_payload = summary_result
                existing.status = 'completed'
                existing.error_message = None
                existing.processed_at = datetime.utcnow()
                existing.updated_at = datetime.utcnow()
            else:
                db.session.add(
                    JudicialDocumentSummary(
                        judicial_document_id=document.id,
                        law_firm_id=kb_item.law_firm_id,
                        summary_text=summary_text,
                        summary_payload=summary_result,
                        status='completed',
                        processed_at=datetime.utcnow(),
                    )
                )
            db.session.commit()
        except Exception as error:
            db.session.rollback()
            try:
                existing = JudicialDocumentSummary.query.filter_by(
                    judicial_document_id=document.id,
                    law_firm_id=kb_item.law_firm_id,
                ).first()
                if existing:
                    existing.status = 'error'
                    existing.error_message = str(error)
                    existing.updated_at = datetime.utcnow()
                    db.session.commit()
            except Exception:
                db.session.rollback()
            print(f'Erro ao resumir documento judicial ID {document.id}: {error}')

    def process_pending_documents(
        self,
        batch_size: int | None = None,
        document_id: int | None = None,
        include_errors: bool = False,
    ) -> int:
        with self.app.app_context():
            query = self._build_query(document_id=document_id, include_errors=include_errors)

            if document_id:
                items = query.all()
            else:
                batch_size = batch_size or self.max_documents_per_execution
                effective_batch_size = max(1, min(batch_size, self.max_documents_per_execution))
                items = query.limit(effective_batch_size).all()

            print(f'Itens elegíveis para processamento: {len(items)}')

            if not items:
                if document_id:
                    print(f'Nenhum documento elegível encontrado para o ID {document_id}.')
                else:
                    print('Nenhum documento pendente encontrado.')
                return 0

            document_ids = [item.id for item in items]

        print('Processando em modo sequencial...')

        processed = 0
        for item_id in document_ids:
            with self.app.app_context():
                document = JudicialDocument.query.get(item_id)
                if not document:
                    continue
                if self._process_single_document(document):
                    processed += 1

        return processed