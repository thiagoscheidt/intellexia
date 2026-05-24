from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from rich import print

from app.agents.document_processing.agent_document_extractor import AgentDocumentExtractor
from app.agents.processes.judicial_document_summary_agent import JudicialDocumentSummaryAgent
from app.models import (
    Client,
    JudicialDefendant,
    JudicialDocument,
    JudicialDocumentSummary,
    JudicialDocumentType,
    JudicialLegalThesis,
    JudicialPhase,
    JudicialProcess,
    JudicialProcessBenefit,
    JudicialProcessCitedBenefit,
    JudicialSentenceAnalysis,
    db,
)
from app.services.document_processor_service import DocumentProcessorService


class JudicialDocumentService:
    """Serviço para processamento de documentos judiciais."""

    def __init__(self, flask_app=None, max_documents_per_execution: int = 5):
        self.app = flask_app
        self.max_documents_per_execution = max_documents_per_execution

    def _build_query(self, document_id: int | None = None, include_errors: bool = False):
        statuses = ['pending']
        if include_errors:
            statuses.append('error')

        base_query = JudicialDocument.query.filter(JudicialDocument.status.in_(statuses))

        if document_id:
            return base_query.filter(JudicialDocument.id == document_id)

        return base_query.order_by(JudicialDocument.created_at.asc())

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
    def _set_document_status(document: JudicialDocument, status: str, error_message: str | None = None) -> None:
        document.status = status
        document.error_message = error_message
        if status == 'completed':
            document.processed_at = datetime.utcnow()
        document.updated_at = datetime.utcnow()

    @staticmethod
    def _normalize_process_number(value: str | None) -> str:
        if not value:
            return ''
        return ''.join(char for char in str(value) if char.isdigit())

    def _extract_primary_process_number(self, value: str | None) -> str:
        if not value:
            return ''

        text_value = str(value).strip()
        cnj_pattern = re.compile(r'\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b')
        match = cnj_pattern.search(text_value)
        if match:
            return match.group(0)

        normalized_digits = self._normalize_process_number(text_value)
        if len(normalized_digits) == 20:
            return normalized_digits

        return text_value[:25]

    def _propagate_process_number_update(
        self,
        law_firm_id: int,
        old_number: str,
        new_number: str,
    ) -> None:
        old_number = str(old_number or '').strip()
        new_number = str(new_number or '').strip()
        if not old_number or not new_number or old_number == new_number:
            return

        now = datetime.utcnow()
        sentence_updated = 0
        sentence_items = JudicialSentenceAnalysis.query.filter_by(
            law_firm_id=law_firm_id,
            process_number=old_number,
        ).all()
        for sentence in sentence_items:
            sentence.process_number = new_number
            sentence.updated_at = now
            sentence_updated += 1

        print(f'Propagação do número do processo: análises atualizadas={sentence_updated}.')

    def _is_initial_petition_document(self, extraction_payload: dict) -> bool:
        doc_type_key = str(extraction_payload.get('suggested_document_type_key', '') or '').strip().lower()
        doc_type_name = str(extraction_payload.get('suggested_document_type_name', '') or '').strip().lower()

        key_match = 'peticao' in doc_type_key and 'inicial' in doc_type_key
        name_match = 'petição inicial' in doc_type_name or (
            'peticao' in doc_type_name and 'inicial' in doc_type_name
        )
        return key_match or name_match

    @staticmethod
    def _normalize_party_name(value: str | None) -> str:
        if not value:
            return ''

        text = str(value).strip().lower()
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(
            r'^(autor(?:a)?|requerente|impetrante|exequente|reclamante|réu|reu|demandado|requerido|impetrado|executado|reclamado)\s*[:\-]\s*',
            '',
            text,
            flags=re.IGNORECASE,
        )
        return text.strip()

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        return SequenceMatcher(None, left, right).ratio()

    def _find_similar_client(self, law_firm_id: int, party_name: str) -> Client | None:
        if not party_name:
            return None

        normalized_target = self._normalize_party_name(party_name)
        if not normalized_target:
            return None

        clients = Client.query.filter_by(law_firm_id=law_firm_id).all()
        if not clients:
            return None

        best_client: Client | None = None
        best_score = 0.0

        for client in clients:
            normalized_name = self._normalize_party_name(client.name)
            if normalized_name == normalized_target:
                return client

            score = self._similarity(normalized_target, normalized_name)
            if score > best_score:
                best_score = score
                best_client = client

        return best_client if best_score >= 0.86 else None

    def _find_similar_defendant(self, law_firm_id: int, party_name: str) -> JudicialDefendant | None:
        if not party_name:
            return None

        normalized_target = self._normalize_party_name(party_name)
        if not normalized_target:
            return None

        defendants = JudicialDefendant.query.filter_by(
            law_firm_id=law_firm_id,
            is_active=True,
        ).all()
        if not defendants:
            return None

        best_defendant: JudicialDefendant | None = None
        best_score = 0.0

        for defendant in defendants:
            normalized_name = self._normalize_party_name(defendant.name)
            if normalized_name == normalized_target:
                return defendant

            score = self._similarity(normalized_target, normalized_name)
            if score > best_score:
                best_score = score
                best_defendant = defendant

        return best_defendant if best_score >= 0.86 else None

    def _resolve_or_create_client(self, law_firm_id: int, party_name: str) -> Client | None:
        clean_name = str(party_name or '').strip()
        if not clean_name:
            return None

        client = self._find_similar_client(law_firm_id, clean_name)
        if client:
            return client

        client = Client(
            law_firm_id=law_firm_id,
            name=clean_name,
            cnpj='00000000000000',
        )
        db.session.add(client)
        db.session.flush()
        return client

    def _resolve_or_create_defendant(self, law_firm_id: int, party_name: str) -> JudicialDefendant | None:
        clean_name = str(party_name or '').strip()
        if not clean_name:
            return None

        defendant = self._find_similar_defendant(law_firm_id, clean_name)
        if defendant:
            return defendant

        defendant = JudicialDefendant(
            law_firm_id=law_firm_id,
            name=clean_name,
            is_active=True,
        )
        db.session.add(defendant)
        db.session.flush()
        return defendant

    def _apply_parties_from_extraction(
        self,
        process: JudicialProcess,
        extraction_payload: dict,
        force_update: bool = False,
    ) -> None:
        active_pole = str(extraction_payload.get('active_pole', '') or '').strip()
        passive_pole = str(extraction_payload.get('passive_pole', '') or '').strip()

        if (force_update or not process.plaintiff_client_id) and active_pole:
            client = self._resolve_or_create_client(law_firm_id=process.law_firm_id, party_name=active_pole)
            if client:
                process.plaintiff_client_id = client.id

        if (force_update or not process.defendant_id) and passive_pole:
            defendant = self._resolve_or_create_defendant(law_firm_id=process.law_firm_id, party_name=passive_pole)
            if defendant:
                process.defendant_id = defendant.id

    def _apply_extra_info_from_extraction(
        self,
        process: JudicialProcess,
        extraction_payload: dict,
        force_update: bool = False,
    ) -> None:
        classe = extraction_payload.get('classe')
        valor_causa = extraction_payload.get('valor_causa')
        assuntos = extraction_payload.get('assuntos')
        segredo_justica = extraction_payload.get('segredo_justica')
        justica_gratuita = extraction_payload.get('justica_gratuita')
        liminar_tutela = extraction_payload.get('liminar_tutela')

        if (force_update or not process.process_class) and classe:
            process.process_class = str(classe).strip()

        if (force_update or not process.valor_causa_texto) and valor_causa:
            process.valor_causa_texto = str(valor_causa).strip()

        if (force_update or not process.assuntos) and isinstance(assuntos, list) and assuntos:
            process.assuntos = assuntos

        if (force_update or process.segredo_justica is None) and segredo_justica is not None:
            process.segredo_justica = bool(segredo_justica)

        if (force_update or process.justica_gratuita is None) and justica_gratuita is not None:
            process.justica_gratuita = bool(justica_gratuita)

        if (force_update or process.liminar_tutela is None) and liminar_tutela is not None:
            process.liminar_tutela = bool(liminar_tutela)

    def _load_valid_legal_theses_for_process(
        self,
        process: JudicialProcess,
        legal_thesis_ids: list[int],
    ) -> list[JudicialLegalThesis]:
        if not legal_thesis_ids:
            return []

        unique_ids = sorted({thesis_id for thesis_id in legal_thesis_ids if thesis_id})
        if not unique_ids:
            return []

        return JudicialLegalThesis.query.filter(
            JudicialLegalThesis.id.in_(unique_ids),
            JudicialLegalThesis.law_firm_id == process.law_firm_id,
            JudicialLegalThesis.is_active.is_(True),
        ).order_by(JudicialLegalThesis.name.asc()).all()

    def _upsert_process_benefits(self, process: JudicialProcess, benefits_payload: dict) -> int:
        if not isinstance(benefits_payload, dict):
            return 0

        extracted_benefits = benefits_payload.get('benefits', [])
        if not isinstance(extracted_benefits, list):
            return 0

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
            request_type = str(benefit.get('request_type', '') or '').strip() or None
            legal_thesis_id_raw = benefit.get('legal_thesis_id')
            legal_thesis_id = None
            try:
                if legal_thesis_id_raw not in (None, ''):
                    legal_thesis_id = int(legal_thesis_id_raw)
            except (TypeError, ValueError):
                legal_thesis_id = None

            legal_thesis_ids_raw = benefit.get('legal_thesis_ids')
            legal_thesis_ids: list[int] = []
            if isinstance(legal_thesis_ids_raw, list):
                for raw_id in legal_thesis_ids_raw:
                    try:
                        thesis_id = int(raw_id)
                    except (TypeError, ValueError):
                        continue
                    if thesis_id not in legal_thesis_ids:
                        legal_thesis_ids.append(thesis_id)
            if legal_thesis_id and legal_thesis_id not in legal_thesis_ids:
                legal_thesis_ids.append(legal_thesis_id)

            theses = self._load_valid_legal_theses_for_process(
                process,
                legal_thesis_ids,
            )
            resolved_legal_thesis_id = theses[0].id if theses else None

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
                if request_type and not str(existing_benefit.request_type or '').strip():
                    existing_benefit.request_type = request_type
                if theses:
                    current_ids = [thesis.id for thesis in existing_benefit.legal_theses]
                    merged_ids = sorted(set(current_ids + [thesis.id for thesis in theses]))
                    merged_theses = self._load_valid_legal_theses_for_process(process, merged_ids)
                    existing_benefit.legal_theses = merged_theses
                    existing_benefit.legal_thesis_id = merged_theses[0].id if merged_theses else resolved_legal_thesis_id
                elif resolved_legal_thesis_id is None and not existing_benefit.legal_theses:
                    existing_benefit.legal_thesis_id = None
                existing_benefit.updated_at = datetime.utcnow()
                upserted += 1
                continue

            new_benefit = JudicialProcessBenefit(
                process_id=process.id,
                benefit_number=benefit_number,
                nit_number=nit_number,
                insured_name=insured_name,
                benefit_type=benefit_type,
                fap_vigencia_year=fap_vigencia_year,
                request_type=request_type,
                legal_thesis_id=resolved_legal_thesis_id,
                legal_thesis='',
                pfn_technical_note='',
                first_instance_decision='',
                second_instance_decision='',
                third_instance_decision='',
            )
            if theses:
                new_benefit.legal_theses = theses
            db.session.add(new_benefit)
            upserted += 1

        return upserted

    def _upsert_cited_benefits(self, process: JudicialProcess, cited: list[dict]) -> int:
        if not cited:
            return 0

        upserted = 0
        for item in cited:
            if not isinstance(item, dict):
                continue

            benefit_number = str(item.get('benefit_number', '') or '').strip()
            if not benefit_number:
                continue

            existing = JudicialProcessCitedBenefit.query.filter_by(
                process_id=process.id,
                benefit_number=benefit_number,
            ).first()
            if existing:
                existing.nit_number = str(item.get('nit_number', '') or '').strip() or existing.nit_number
                existing.insured_name = str(item.get('insured_name', '') or '').strip() or existing.insured_name
                existing.benefit_type = str(item.get('benefit_type', '') or '').strip() or existing.benefit_type
                existing.fap_vigencia_year = (
                    str(item.get('fap_vigencia_year', '') or '').strip() or existing.fap_vigencia_year
                )
                existing.updated_at = datetime.utcnow()
            else:
                db.session.add(
                    JudicialProcessCitedBenefit(
                        process_id=process.id,
                        benefit_number=benefit_number,
                        nit_number=str(item.get('nit_number', '') or '').strip() or None,
                        insured_name=str(item.get('insured_name', '') or '').strip() or None,
                        benefit_type=str(item.get('benefit_type', '') or '').strip() or None,
                        fap_vigencia_year=str(item.get('fap_vigencia_year', '') or '').strip() or None,
                    )
                )
                upserted += 1

        return upserted

    def _apply_benefit_request_types(self, process: JudicialProcess, classification_payload: dict) -> int:
        classified = classification_payload.get('benefits', [])
        if not isinstance(classified, list):
            return 0

        updated = 0
        for item in classified:
            if not isinstance(item, dict):
                continue

            benefit_number = str(item.get('benefit_number', '') or '').strip()
            request_type = str(item.get('request_type', '') or '').strip()
            if not benefit_number or not request_type:
                continue

            benefit = JudicialProcessBenefit.query.filter_by(
                process_id=process.id,
                benefit_number=benefit_number,
            ).first()
            if benefit:
                benefit.request_type = request_type
                benefit.updated_at = datetime.utcnow()
                updated += 1

        return updated

    def _extract_context_from_document(self, document: JudicialDocument, process: JudicialProcess) -> dict:
        file_path = Path(str(document.file_path or '').strip())
        if not file_path.exists():
            raise FileNotFoundError(f'Arquivo não encontrado no caminho: {document.file_path}')

        document_processor = DocumentProcessorService()
        document_data = document_processor.process_document(file_path=str(file_path))

        if isinstance(document_data, dict):
            document_full_text = str(document_data.get('full_text', '') or '')
        else:
            document_full_text = str(getattr(document_data, 'full_text', '') or '')

        if not document_full_text:
            raise RuntimeError('Processamento não retornou conteúdo.')

        document_faiss_vector = document_processor.build_faiss_index(document_full_text)
        extractor_agent = AgentDocumentExtractor(
            file_id=document.id,
            file_path=str(file_path),
            law_firm_id=process.law_firm_id,
            document_data=document_data,
            document_faiss_vector=document_faiss_vector,
        )

        extraction_payload = extractor_agent.extract_document_data()
        if not extraction_payload or not isinstance(extraction_payload, dict):
            raise RuntimeError('Extração estruturada não retornou conteúdo.')

        sections_overview = extractor_agent.extract_sections_overview(max_sections=12)
        pedidos_excerpt = extractor_agent.extract_pedidos_section_text()

        self._apply_parties_from_extraction(
            process=process,
            extraction_payload=extraction_payload,
            force_update=False,
        )
        self._apply_extra_info_from_extraction(
            process=process,
            extraction_payload=extraction_payload,
            force_update=False,
        )

        extracted_process_number = str(extraction_payload.get('process_number', '') or '').strip()
        if extracted_process_number and str(process.process_number or '').startswith('TEMP-'):
            real_number = self._extract_primary_process_number(extracted_process_number)
            if real_number:
                duplicate = JudicialProcess.query.filter(
                    JudicialProcess.id != process.id,
                    JudicialProcess.law_firm_id == process.law_firm_id,
                    JudicialProcess.process_number == real_number,
                ).first()
                if not duplicate:
                    old_temp_number = str(process.process_number or '').strip()
                    print(f'Atualizando número temporário {process.process_number} -> {real_number}')
                    process.process_number = real_number
                    process.updated_at = datetime.utcnow()
                    self._propagate_process_number_update(
                        law_firm_id=process.law_firm_id,
                        old_number=old_temp_number,
                        new_number=real_number,
                    )
                else:
                    print(
                        f'Número {real_number} já pertence a outro processo (ID {duplicate.id}). '
                        'Número temporário mantido.'
                    )

        event_type, _, _ = self.resolve_type_and_phase(process.law_firm_id, extraction_payload)
        if event_type and not str(document.type or '').strip():
            document.type = event_type

        if self._is_initial_petition_document(extraction_payload):
            benefits_payload = extractor_agent.extract_benefits_from_petition(file_path=str(file_path))
            inserted_or_updated = self._upsert_process_benefits(process, benefits_payload)
            if inserted_or_updated > 0:
                print(
                    f'Benefícios vinculados ao processo {process.process_number}: '
                    f'{inserted_or_updated} registro(s).'
                )

            extracted_benefits = benefits_payload.get('benefits', []) if isinstance(benefits_payload, dict) else []
            if extracted_benefits:
                classification = extractor_agent.classify_benefit_request_types(extracted_benefits)
                classified_count = self._apply_benefit_request_types(process, classification)
                if classified_count > 0:
                    print(
                        f'Tipos de pedido classificados no processo {process.process_number}: '
                        f'{classified_count} benefício(s).'
                    )

            cited = extractor_agent.extract_cited_benefits()
            if cited:
                cited_count = self._upsert_cited_benefits(process, cited)
                print(
                    f'Benefícios citados vinculados ao processo {process.process_number}: '
                    f'{cited_count} novo(s) / {len(cited)} extraído(s).'
                )

        process.updated_at = datetime.utcnow()

        return {
            'sections_overview': sections_overview if isinstance(sections_overview, list) else [],
            'pedidos_excerpt': str(pedidos_excerpt or '').strip(),
        }

    def _summarize_judicial_document(
        self,
        document: JudicialDocument,
        process: JudicialProcess,
        context_payload: dict,
    ) -> None:
        if not document or not process:
            return

        try:
            doc_type = None
            if document.type:
                doc_type = JudicialDocumentType.query.filter_by(
                    law_firm_id=process.law_firm_id,
                    key=document.type,
                    is_active=True,
                ).first()

            doc_type_name = str(getattr(doc_type, 'name', '') or '').strip()
            doc_type_key = str(document.type or '').strip()
            sections_overview = context_payload.get('sections_overview', []) if isinstance(context_payload, dict) else []
            if not isinstance(sections_overview, list):
                sections_overview = []
            pedidos_excerpt = ''
            if isinstance(context_payload, dict):
                pedidos_excerpt = str(context_payload.get('pedidos_excerpt', '') or '').strip()

            summary_agent = JudicialDocumentSummaryAgent()
            summary_result = summary_agent.summarize_document(
                file_path=str(document.file_path),
                document_type_name=doc_type_name,
                document_type_key=doc_type_key,
                file_type='',
                sections_overview=sections_overview,
                pedidos_excerpt=pedidos_excerpt,
                user_id=document.uploaded_by,
                law_firm_id=process.law_firm_id,
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
                law_firm_id=process.law_firm_id,
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
                        law_firm_id=process.law_firm_id,
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
                    law_firm_id=process.law_firm_id,
                ).first()
                if existing:
                    existing.status = 'error'
                    existing.error_message = str(error)
                    existing.updated_at = datetime.utcnow()
                    db.session.commit()
            except Exception:
                db.session.rollback()
            print(f'Erro ao resumir documento judicial ID {document.id}: {error}')

    def _process_single_document(self, document: JudicialDocument) -> bool:
        if not document.process_id:
            self._set_document_status(document, 'error', 'Documento sem vínculo com processo judicial.')
            db.session.commit()
            return False

        process = JudicialProcess.query.filter_by(id=document.process_id).first()
        if not process:
            self._set_document_status(document, 'error', 'Processo judicial não encontrado para este documento.')
            db.session.commit()
            return False

        try:
            self._set_document_status(document, 'processing')
            db.session.commit()

            context_payload = self._extract_context_from_document(document, process)

            self._set_document_status(document, 'completed')
            db.session.commit()

            self._summarize_judicial_document(document, process, context_payload)
            return True
        except Exception as error:
            db.session.rollback()
            try:
                self._set_document_status(document, 'error', str(error))
                db.session.commit()
            except Exception:
                db.session.rollback()
            print(f'Erro ao processar documento judicial ID {document.id}: {error}')
            return False

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
