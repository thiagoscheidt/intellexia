from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from rich import print

from app.agents.document_processing.agent_document_extractor import AgentDocumentExtractor
from app.agents.processes.judicial_contestation_analysis_agent import JudicialContestationAnalysisAgent
from app.agents.processes.judicial_document_summary_agent import JudicialDocumentSummaryAgent
from app.services import ai_model_settings_service
from sqlalchemy import and_

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
    JudicialProcessBenefitThesisContestation,
    JudicialProcessCitedBenefit,
    JudicialSentenceAnalysis,
    db,
    judicial_process_benefit_legal_theses,
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
            document.processed_at = datetime.now()
        document.updated_at = datetime.now()

    @staticmethod
    def _normalize_process_number(value: str | None) -> str:
        if not value:
            return ''
        return ''.join(char for char in str(value) if char.isdigit())

    @staticmethod
    def _normalize_event_identifier(value: str | None) -> str:
        if not value:
            return ''
        digits = ''.join(char for char in str(value) if char.isdigit())
        if len(digits) < 6:
            return ''
        return digits[:50]

    def _extract_event_identifier(self, extraction_payload: dict, document_text: str = '') -> str:
        candidates = [
            extraction_payload.get('event_identifier'),
            extraction_payload.get('event_id'),
            extraction_payload.get('id_evento'),
            extraction_payload.get('document_event_id'),
        ]

        for candidate in candidates:
            normalized = self._normalize_event_identifier(candidate)
            if normalized:
                return normalized

        header_slice = str(document_text or '')[:12000]
        if not header_slice:
            return ''

        patterns = [
            r'(?im)\bid\.?\s*(?:do\s+evento|evento)?\s*[:\-]?\s*(\d{6,20})\b',
            r'(?im)^\s*(\d{6,20})\s+\d{2}/\d{2}/\d{4}',
        ]

        for pattern in patterns:
            match = re.search(pattern, header_slice)
            if not match:
                continue
            normalized = self._normalize_event_identifier(match.group(1))
            if normalized:
                return normalized

        return ''

    @staticmethod
    def _is_placeholder_process_title(title: str | None, previous_process_number: str = '') -> bool:
        normalized_title = str(title or '').strip()
        if not normalized_title:
            return True

        lowered = normalized_title.lower()
        if lowered in {'(sem número)', '(sem numero)', 'sem número', 'sem numero'}:
            return True

        if normalized_title.startswith('TEMP-'):
            return True

        previous_number = str(previous_process_number or '').strip()
        if previous_number.startswith('TEMP-') and normalized_title == previous_number:
            return True

        return False

    def _build_auto_process_title(self, process: JudicialProcess, extraction_payload: dict) -> str:
        active_pole = str(extraction_payload.get('active_pole', '') or '').strip()
        passive_pole = str(extraction_payload.get('passive_pole', '') or '').strip()

        plaintiff_name = ''
        if process.plaintiff_client:
            plaintiff_name = str(process.plaintiff_client.name or '').strip()

        defendant_name = ''
        if process.defendant:
            defendant_name = str(process.defendant.name or '').strip()

        author_label = active_pole or plaintiff_name
        defendant_label = passive_pole or defendant_name
        process_class = str(extraction_payload.get('classe') or process.process_class or '').strip()

        if author_label and defendant_label:
            title = f'{author_label} x {defendant_label}'
        elif author_label:
            title = author_label
        elif defendant_label:
            title = defendant_label
        elif process.process_number:
            title = f'Processo {process.process_number}'
        else:
            title = 'Processo Judicial'

        if process_class and process_class.lower() not in title.lower():
            title = f'{title} - {process_class}'

        return title[:255]

    @staticmethod
    def _clean_judge_name(value: str | None) -> str:
        text = str(value or '').strip()
        if not text:
            return ''

        text = re.sub(r'\s+', ' ', text)
        text = re.sub(
            r'^(?:mm\.?\s*)?(?:ju[ií]z(?:a)?(?:\s+federal)?(?:\s+substituto(?:a)?)?)\s*[:\-]?\s*',
            '',
            text,
            flags=re.IGNORECASE,
        )
        text = text.strip(' ,.;:-')
        return text[:255]

    def _extract_judge_name(self, extraction_payload: dict, document_text: str = '') -> str:
        candidate_fields = [
            extraction_payload.get('judge_name'),
            extraction_payload.get('juiz_nome'),
            extraction_payload.get('nome_juiz'),
            extraction_payload.get('magistrate_name'),
        ]

        for candidate in candidate_fields:
            cleaned = self._clean_judge_name(candidate)
            if cleaned:
                return cleaned

        header_slice = str(document_text or '')[:9000]
        if not header_slice:
            return ''

        patterns = [
            r'(?im)ju[ií]z(?:a)?(?:\s+federal)?(?:\s+substituto(?:a)?)?\s*[:\-]\s*([^\n\r,;]{4,120})',
            r'(?im)(?:mm\.?\s*)?ju[ií]z(?:a)?(?:\s+federal)?(?:\s+substituto(?:a)?)?\s+([^\n\r,;]{4,120})',
            r'(?im)assinado\s+por\s*[:\-]?\s*([^\n\r,;]{4,120})',
        ]

        for pattern in patterns:
            match = re.search(pattern, header_slice)
            if not match:
                continue
            cleaned = self._clean_judge_name(match.group(1))
            if cleaned:
                return cleaned

        return ''

    @staticmethod
    def _normalize_cnpj(value: str | None) -> str:
        digits = re.sub(r'\D', '', str(value or ''))
        return digits if len(digits) == 14 else ''

    @staticmethod
    def _is_placeholder_cnpj(value: str | None) -> bool:
        return JudicialDocumentService._normalize_cnpj(value) == '00000000000000'

    @staticmethod
    def _extract_cnpjs_from_text(text: str | None) -> list[str]:
        if not text:
            return []
        pattern = re.compile(r'\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b')
        found: list[str] = []
        for raw in pattern.findall(str(text)):
            normalized = JudicialDocumentService._normalize_cnpj(raw)
            if normalized and normalized not in found:
                found.append(normalized)
        return found

    def _extract_plaintiff_cnpj(self, extraction_payload: dict, document_text: str = '') -> str:
        """Resolve CNPJ da autora usando payload estruturado e fallback no texto."""
        candidate_fields = [
            extraction_payload.get('active_pole_cnpj'),
            extraction_payload.get('plaintiff_cnpj'),
            extraction_payload.get('author_cnpj'),
            extraction_payload.get('company_cnpj'),
            extraction_payload.get('cnpj'),
        ]

        active_pole = str(extraction_payload.get('active_pole', '') or '').strip()
        if active_pole:
            candidate_fields.extend(self._extract_cnpjs_from_text(active_pole))

        for candidate in candidate_fields:
            normalized = self._normalize_cnpj(str(candidate or ''))
            if normalized:
                return normalized

        header_slice = str(document_text or '')[:7000]
        header_cnpjs = self._extract_cnpjs_from_text(header_slice)
        if len(header_cnpjs) == 1:
            return header_cnpjs[0]

        return ''

    def _apply_plaintiff_cnpj_to_client(self, process: JudicialProcess, plaintiff_cnpj: str) -> None:
        normalized_cnpj = self._normalize_cnpj(plaintiff_cnpj)
        if not normalized_cnpj:
            return

        client = process.plaintiff_client
        if not client and process.plaintiff_client_id:
            client = Client.query.filter_by(id=process.plaintiff_client_id).first()
        if not client:
            return

        current_cnpj = self._normalize_cnpj(client.cnpj)
        if current_cnpj == normalized_cnpj:
            return

        # Evita sobrescrever CNPJ já definido com outro valor sem intervenção humana.
        if current_cnpj and not self._is_placeholder_cnpj(current_cnpj):
            return

        client.cnpj = normalized_cnpj
        client.updated_at = datetime.now()

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

    def _generate_temp_process_number(
        self,
        law_firm_id: int,
        excluded_process_ids: set[int] | None = None,
    ) -> str:
        excluded_ids = {pid for pid in (excluded_process_ids or set()) if pid}

        for _ in range(30):
            candidate = f'TEMP-{uuid.uuid4().hex[:8].upper()}'
            query = JudicialProcess.query.filter(
                JudicialProcess.law_firm_id == law_firm_id,
                JudicialProcess.process_number == candidate,
            )
            if excluded_ids:
                query = query.filter(~JudicialProcess.id.in_(excluded_ids))
            if not query.first():
                return candidate

        return f'TEMP-{uuid.uuid4().hex[:8].upper()}'

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

        now = datetime.now()
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

    def _is_contestation_document(self, extraction_payload: dict) -> bool:
        doc_type_key = str(extraction_payload.get('suggested_document_type_key', '') or '').strip().lower()
        doc_type_name = str(extraction_payload.get('suggested_document_type_name', '') or '').strip().lower()

        key_match = doc_type_key == 'contestacao' or 'contestacao' in doc_type_key
        name_match = 'contestação' in doc_type_name or 'contestacao' in doc_type_name
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

    def _resolve_or_create_client(
        self,
        law_firm_id: int,
        party_name: str,
        cnpj: str | None = None,
    ) -> Client | None:
        clean_name = str(party_name or '').strip()
        if not clean_name:
            return None

        normalized_cnpj = self._normalize_cnpj(cnpj)

        client = self._find_similar_client(law_firm_id, clean_name)
        if client:
            if normalized_cnpj:
                current_cnpj = self._normalize_cnpj(client.cnpj)
                if (not current_cnpj or self._is_placeholder_cnpj(current_cnpj)) and current_cnpj != normalized_cnpj:
                    client.cnpj = normalized_cnpj
                    client.updated_at = datetime.now()
            return client

        client = Client(
            law_firm_id=law_firm_id,
            name=clean_name,
            cnpj=normalized_cnpj or '00000000000000',
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
        document_text: str = '',
        force_update: bool = False,
    ) -> None:
        active_pole = str(extraction_payload.get('active_pole', '') or '').strip()
        passive_pole = str(extraction_payload.get('passive_pole', '') or '').strip()
        plaintiff_cnpj = self._extract_plaintiff_cnpj(extraction_payload, document_text=document_text)

        if (force_update or not process.plaintiff_client_id) and active_pole:
            client = self._resolve_or_create_client(
                law_firm_id=process.law_firm_id,
                party_name=active_pole,
                cnpj=plaintiff_cnpj,
            )
            if client:
                process.plaintiff_client_id = client.id

        if plaintiff_cnpj:
            self._apply_plaintiff_cnpj_to_client(process, plaintiff_cnpj)

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
                existing_benefit.updated_at = datetime.now()
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
                existing.updated_at = datetime.now()
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
            source_section = str(item.get('source_section', '') or '').strip()
            raw_legal_thesis_id = item.get('legal_thesis_id')
            legal_thesis_id: int | None = None
            try:
                if raw_legal_thesis_id not in (None, ''):
                    legal_thesis_id = int(raw_legal_thesis_id)
            except (TypeError, ValueError):
                legal_thesis_id = None
            if not benefit_number or not request_type:
                continue

            benefit = JudicialProcessBenefit.query.filter_by(
                process_id=process.id,
                benefit_number=benefit_number,
            ).first()
            if benefit:
                # 'nao_solicitado': o NB aparece na petição só como contexto (ex.:
                # benefício anterior de um par de restabelecimento) — sem pedido.
                benefit.request_type = None if request_type == 'nao_solicitado' else request_type
                if source_section:
                    target_thesis_id = legal_thesis_id
                    linked_thesis_ids = {
                        thesis.id for thesis in (benefit.legal_theses or []) if thesis and thesis.id
                    }

                    # Se o classificador retornar um ID que não pertence ao benefício,
                    # ignoramos esse ID e recalculamos pela seção para evitar gravar no vínculo errado.
                    if (
                        target_thesis_id is not None
                        and linked_thesis_ids
                        and target_thesis_id not in linked_thesis_ids
                    ):
                        target_thesis_id = None

                    if target_thesis_id is None:
                        target_thesis_id = self._resolve_thesis_id_from_source_section(
                            benefit=benefit,
                            source_section=source_section,
                        )
                    if target_thesis_id is None and len(benefit.legal_theses or []) == 1:
                        target_thesis_id = benefit.legal_theses[0].id

                    if target_thesis_id is not None:
                        db.session.execute(
                            judicial_process_benefit_legal_theses.update()
                            .where(
                                and_(
                                    judicial_process_benefit_legal_theses.c.benefit_id == benefit.id,
                                    judicial_process_benefit_legal_theses.c.legal_thesis_id == target_thesis_id,
                                )
                            )
                            .values(source_section=source_section)
                        )
                benefit.updated_at = datetime.now()
                updated += 1

        return updated

    @staticmethod
    def _normalize_section_match_text(value: str | None) -> str:
        text = str(value or '').strip().lower()
        if not text:
            return ''
        text = unicodedata.normalize('NFKD', text)
        text = ''.join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r'\s+', ' ', text)
        return text

    def _resolve_thesis_id_from_source_section(
        self,
        benefit: JudicialProcessBenefit,
        source_section: str,
    ) -> int | None:
        """Resolve tese do benefício com base no texto da seção quando o agente não retorna o ID."""
        theses = list(benefit.legal_theses or [])
        if not theses:
            return None

        normalized_section = self._normalize_section_match_text(source_section)
        if not normalized_section:
            return None

        # Heurística 1: número de tópico inicial (ex.: "6.") contra a key da tese.
        section_topic_match = re.match(r'^\s*(\d{1,2})(?:\.\d+)?\b', str(source_section or '').strip())
        section_topic = section_topic_match.group(1) if section_topic_match else ''
        if section_topic:
            for thesis in theses:
                thesis_key = str(getattr(thesis, 'key', '') or '').strip()
                if not thesis_key:
                    continue
                if thesis_key.startswith(f'{section_topic}.'):
                    return thesis.id

        # Heurística 2: similaridade textual com nome/descrição da tese.
        best_id: int | None = None
        best_score = 0.0
        for thesis in theses:
            thesis_text = ' '.join(
                [
                    str(getattr(thesis, 'key', '') or ''),
                    str(getattr(thesis, 'name', '') or ''),
                    str(getattr(thesis, 'description', '') or ''),
                ]
            )
            normalized_thesis = self._normalize_section_match_text(thesis_text)
            if not normalized_thesis:
                continue

            if normalized_section == normalized_thesis:
                return thesis.id

            score = 0.0
            if normalized_section in normalized_thesis or normalized_thesis in normalized_section:
                score = 0.95
            else:
                score = SequenceMatcher(None, normalized_section, normalized_thesis).ratio()

            if score > best_score:
                best_score = score
                best_id = thesis.id

        return best_id if best_score >= 0.45 else None

    def _process_initial_petition_flow(
        self,
        process: JudicialProcess,
        extractor_agent: AgentDocumentExtractor,
        file_path: Path,
    ) -> None:
        """Executa o fluxo específico da petição inicial em uma única função."""
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

        impugned_numbers = [
            str(item.get('benefit_number') or '').strip()
            for item in extracted_benefits if isinstance(item, dict)
        ]
        insured_names = [
            str(item.get('insured_name') or '').strip()
            for item in extracted_benefits if isinstance(item, dict)
        ]
        cited = extractor_agent.extract_cited_benefits(
            exclude_numbers=impugned_numbers,
            known_insured_names=[n for n in insured_names if n],
        )
        if cited:
            cited_count = self._upsert_cited_benefits(process, cited)
            print(
                f'Benefícios citados vinculados ao processo {process.process_number}: '
                f'{cited_count} novo(s) / {len(cited)} extraído(s).'
            )

    def _process_contestation_flow(
        self,
        process: JudicialProcess,
        file_path: Path,
    ) -> None:
        """Executa o fluxo específico da contestação em uma única função."""
        print(
            f'Iniciando fluxo de contestação para o processo {process.process_number} '
            f'(arquivo: {file_path.name}).'
        )

        process_benefits = JudicialProcessBenefit.query.filter_by(process_id=process.id).all()
        if not process_benefits:
            print(
                f'Fluxo de contestação sem benefícios prévios no processo {process.process_number}. '
                'Análise por benefício não executada.'
            )
            return

        benefits_payload: list[dict] = []
        benefits_by_id: dict[int, JudicialProcessBenefit] = {benefit.id: benefit for benefit in process_benefits}
        for benefit in process_benefits:
            legal_thesis_names = [
                str(thesis.name or '').strip()
                for thesis in (benefit.legal_theses or [])
                if thesis and str(thesis.name or '').strip()
            ]

            if benefit.legal_theses:
                for thesis in benefit.legal_theses:
                    thesis_name = str(thesis.name or '').strip()
                    if not thesis_name:
                        continue
                    benefits_payload.append(
                        {
                            'benefit_ref': f'{benefit.id}:{thesis.id}',
                            'benefit_number': str(benefit.benefit_number or '').strip(),
                            'thesis': thesis_name,
                        }
                    )
                continue

            fallback_thesis = ''
            if legal_thesis_names:
                fallback_thesis = '; '.join(sorted(set(legal_thesis_names)))
            elif str(benefit.legal_thesis or '').strip():
                fallback_thesis = str(benefit.legal_thesis or '').strip()

            benefits_payload.append(
                {
                    'benefit_ref': f'{benefit.id}:0',
                    'benefit_number': str(benefit.benefit_number or '').strip(),
                    'thesis': fallback_thesis,
                }
            )

        analysis_agent = JudicialContestationAnalysisAgent(
            model_name=ai_model_settings_service.get_model(
                process.law_firm_id, 'judicial_contestation_analysis'))
        analysis_payload = analysis_agent.analyze_contestation(
            file_path=str(file_path),
            benefits=benefits_payload,
            user_id=process.user_id,
            law_firm_id=process.law_firm_id,
        )

        analyses = analysis_payload.get('analises', []) if isinstance(analysis_payload, dict) else []
        if not isinstance(analyses, list):
            analyses = []

        grouped_by_benefit_id: dict[int, list[dict]] = {}
        grouped_by_benefit_thesis: dict[tuple[int, int | None], dict] = {}
        for item in analyses:
            if not isinstance(item, dict):
                continue

            benefit_ref = str(item.get('benefit_ref', '') or '').strip()
            benefit_id = None
            legal_thesis_id: int | None = None
            if ':' in benefit_ref:
                raw_benefit_id, raw_legal_thesis_id = benefit_ref.split(':', 1)
                try:
                    benefit_id = int(raw_benefit_id)
                except (TypeError, ValueError):
                    benefit_id = None
                try:
                    parsed_legal_thesis_id = int(raw_legal_thesis_id)
                    legal_thesis_id = parsed_legal_thesis_id if parsed_legal_thesis_id > 0 else None
                except (TypeError, ValueError):
                    legal_thesis_id = None

            if benefit_id is None:
                benefit_number = str(item.get('beneficio', '') or '').strip()
                if not benefit_number:
                    continue
                benefit = JudicialProcessBenefit.query.filter_by(
                    process_id=process.id,
                    benefit_number=benefit_number,
                ).first()
                if not benefit:
                    continue
                benefit_id = benefit.id

            if benefit_id not in grouped_by_benefit_id:
                grouped_by_benefit_id[benefit_id] = []
            grouped_by_benefit_id[benefit_id].append(item)

            grouped_by_benefit_thesis[(benefit_id, legal_thesis_id)] = item

        thesis_rows_updated = 0
        for (benefit_id, legal_thesis_id), thesis_item in grouped_by_benefit_thesis.items():
            benefit = benefits_by_id.get(benefit_id)
            if not benefit:
                continue

            thesis_row = JudicialProcessBenefitThesisContestation.query.filter_by(
                process_benefit_id=benefit.id,
                legal_thesis_id=legal_thesis_id,
            ).first()

            if thesis_row is None:
                thesis_row = JudicialProcessBenefitThesisContestation(
                    law_firm_id=process.law_firm_id,
                    process_id=process.id,
                    process_benefit_id=benefit.id,
                    legal_thesis_id=legal_thesis_id,
                )
                db.session.add(thesis_row)

            thesis_status = str(thesis_item.get('status', '') or '').strip()
            thesis_status_label = str(thesis_item.get('status_label', '') or '').strip()
            thesis_fundamento_uniao = str(thesis_item.get('fundamento_uniao', '') or '').strip()
            thesis_efeito_fap = str(thesis_item.get('efeito_fap', '') or '').strip()
            thesis_trecho_detectado = str(thesis_item.get('trecho_detectado', '') or '').strip()
            thesis_trecho_completo = str(
                thesis_item.get('trecho_completo_contestacao', '') or ''
            ).strip()
            thesis_resultado_tecnico = thesis_item.get('resultado_tecnico') or {}
            if not isinstance(thesis_resultado_tecnico, dict):
                thesis_resultado_tecnico = {}

            thesis_row.contestation_decision = thesis_status_label or thesis_status or ''
            thesis_row.contestation_status = thesis_status or None
            thesis_row.contestation_status_label = thesis_status_label or None
            thesis_row.contestation_fundamento_uniao = thesis_fundamento_uniao or None
            thesis_row.contestation_efeito_fap = thesis_efeito_fap or None
            thesis_row.contestation_trecho_detectado = thesis_trecho_detectado or None
            thesis_row.contestation_trecho_completo = thesis_trecho_completo or None
            thesis_row.contestation_resultado_tecnico_json = json.dumps(
                {
                    'recalcula_fap': bool(thesis_resultado_tecnico.get('recalcula_fap', False)),
                    'mantem_no_fap': bool(thesis_resultado_tecnico.get('mantem_no_fap', False)),
                    'depende_inss': bool(thesis_resultado_tecnico.get('depende_inss', False)),
                    'depende_decisao_judicial': bool(
                        thesis_resultado_tecnico.get('depende_decisao_judicial', False)
                    ),
                },
                ensure_ascii=False,
            )
            thesis_row.updated_at = datetime.now()
            thesis_rows_updated += 1

        updated = 0
        for benefit_id, thesis_items in grouped_by_benefit_id.items():
            benefit = benefits_by_id.get(benefit_id)
            if not benefit:
                continue

            # Escolhe um item principal para manter compatibilidade dos campos legados por benefício.
            principal_item = None
            for candidate in thesis_items:
                candidate_status = str(candidate.get('status', '') or '').strip().lower()
                if candidate_status not in ('nao_localizado', 'nao_analisado'):
                    principal_item = candidate
                    break
            if principal_item is None and thesis_items:
                principal_item = thesis_items[0]
            if principal_item is None:
                continue

            status = str(principal_item.get('status', '') or '').strip()
            status_label = str(principal_item.get('status_label', '') or '').strip()
            fundamento_uniao = str(principal_item.get('fundamento_uniao', '') or '').strip()
            efeito_fap = str(principal_item.get('efeito_fap', '') or '').strip()
            trecho_detectado = str(principal_item.get('trecho_detectado', '') or '').strip()
            trecho_completo = str(principal_item.get('trecho_completo_contestacao', '') or '').strip()
            resultado_tecnico = principal_item.get('resultado_tecnico') or {}
            if not isinstance(resultado_tecnico, dict):
                resultado_tecnico = {}

            per_thesis_analyses: list[dict] = []
            for thesis_item in thesis_items:
                thesis_result = thesis_item.get('resultado_tecnico') or {}
                if not isinstance(thesis_result, dict):
                    thesis_result = {}
                per_thesis_analyses.append(
                    {
                        'benefit_ref': str(thesis_item.get('benefit_ref', '') or '').strip(),
                        'beneficio': str(thesis_item.get('beneficio', '') or '').strip(),
                        'tese': str(thesis_item.get('tese', '') or '').strip(),
                        'status': str(thesis_item.get('status', '') or '').strip(),
                        'status_label': str(thesis_item.get('status_label', '') or '').strip(),
                        'fundamento_uniao': str(thesis_item.get('fundamento_uniao', '') or '').strip(),
                        'efeito_fap': str(thesis_item.get('efeito_fap', '') or '').strip(),
                        'trecho_detectado': str(thesis_item.get('trecho_detectado', '') or '').strip(),
                        'trecho_completo_contestacao': str(
                            thesis_item.get('trecho_completo_contestacao', '') or ''
                        ).strip(),
                        'resultado_tecnico': {
                            'recalcula_fap': bool(thesis_result.get('recalcula_fap', False)),
                            'mantem_no_fap': bool(thesis_result.get('mantem_no_fap', False)),
                            'depende_inss': bool(thesis_result.get('depende_inss', False)),
                            'depende_decisao_judicial': bool(thesis_result.get('depende_decisao_judicial', False)),
                        },
                    }
                )

            benefit.contestation_decision = status_label or status or ''
            benefit.contestation_status = status or None
            benefit.contestation_status_label = status_label or None
            benefit.contestation_fundamento_uniao = fundamento_uniao or None
            benefit.contestation_efeito_fap = efeito_fap or None
            benefit.contestation_trecho_detectado = trecho_detectado or None
            benefit.contestation_trecho_completo = trecho_completo or None
            benefit.contestation_resultado_tecnico_json = json.dumps(
                {
                    'recalcula_fap': bool(resultado_tecnico.get('recalcula_fap', False)),
                    'mantem_no_fap': bool(resultado_tecnico.get('mantem_no_fap', False)),
                    'depende_inss': bool(resultado_tecnico.get('depende_inss', False)),
                    'depende_decisao_judicial': bool(resultado_tecnico.get('depende_decisao_judicial', False)),
                    'analises_por_tese': per_thesis_analyses,
                },
                ensure_ascii=False,
            )
            benefit.updated_at = datetime.now()
            updated += 1

        print(
            f'Fluxo de contestação concluído para o processo {process.process_number}: '
            f'{updated} benefício(s) atualizado(s) com análise da União; '
            f'{thesis_rows_updated} vínculo(s) benefício+tese persistido(s).'
        )

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
            model_name=ai_model_settings_service.get_model(
                process.law_firm_id, 'judicial_document_extractor'),
        )

        extraction_payload = extractor_agent.extract_document_data()
        if not extraction_payload or not isinstance(extraction_payload, dict):
            raise RuntimeError('Extração estruturada não retornou conteúdo.')

        sections_overview = extractor_agent.extract_sections_overview(max_sections=12)
        pedidos_excerpt = extractor_agent.extract_pedidos_section_text()

        self._apply_parties_from_extraction(
            process=process,
            extraction_payload=extraction_payload,
            document_text=document_full_text,
            force_update=False,
        )
        self._apply_extra_info_from_extraction(
            process=process,
            extraction_payload=extraction_payload,
            force_update=False,
        )

        previous_process_number = str(process.process_number or '').strip()
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
                    process.updated_at = datetime.now()
                    self._propagate_process_number_update(
                        law_firm_id=process.law_firm_id,
                        old_number=old_temp_number,
                        new_number=real_number,
                    )
                else:
                    old_temp_number = str(process.process_number or '').strip()
                    duplicate_old_number = str(duplicate.process_number or '').strip()
                    duplicate_new_temp = self._generate_temp_process_number(
                        law_firm_id=process.law_firm_id,
                        excluded_process_ids={process.id, duplicate.id},
                    )

                    print(
                        f'Número {real_number} já pertence ao processo ID {duplicate.id}. '
                        f'Realocando processo antigo para {duplicate_new_temp} e '
                        f'atribuindo {real_number} ao processo ID {process.id}.'
                    )

                    duplicate.process_number = duplicate_new_temp
                    duplicate.updated_at = datetime.now()
                    self._propagate_process_number_update(
                        law_firm_id=process.law_firm_id,
                        old_number=duplicate_old_number,
                        new_number=duplicate_new_temp,
                    )

                    process.process_number = real_number
                    process.updated_at = datetime.now()
                    self._propagate_process_number_update(
                        law_firm_id=process.law_firm_id,
                        old_number=old_temp_number,
                        new_number=real_number,
                    )

                    print(
                        f'Swap de número concluído: processo atual={real_number}; '
                        f'processo ID {duplicate.id}={duplicate_new_temp}.'
                    )

        is_initial_document = self._is_initial_petition_document(extraction_payload)

        extracted_event_identifier = self._extract_event_identifier(
            extraction_payload,
            document_text=document_full_text,
        )
        if extracted_event_identifier and extracted_event_identifier != str(document.event_identifier or '').strip():
            document.event_identifier = extracted_event_identifier

        if is_initial_document and self._is_placeholder_process_title(process.title, previous_process_number):
            process.title = self._build_auto_process_title(process, extraction_payload)

        event_type, _, _ = self.resolve_type_and_phase(process.law_firm_id, extraction_payload)
        if event_type and not str(document.type or '').strip():
            document.type = event_type

        if not is_initial_document:
            extracted_judge_name = self._extract_judge_name(
                extraction_payload,
                document_text=document_full_text,
            )
            if extracted_judge_name and not str(process.judge_name or '').strip():
                process.judge_name = extracted_judge_name

        if is_initial_document:
            self._process_initial_petition_flow(
                process=process,
                extractor_agent=extractor_agent,
                file_path=file_path,
            )
        elif self._is_contestation_document(extraction_payload):
            self._process_contestation_flow(
                process=process,
                file_path=file_path,
            )

        process.updated_at = datetime.now()

        return {
            'sections_overview': sections_overview if isinstance(sections_overview, list) else [],
            'pedidos_excerpt': str(pedidos_excerpt or '').strip(),
            'document_event_identifier': str(document.event_identifier or '').strip(),
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
            document_event_identifier = str(document.event_identifier or '').strip()
            if isinstance(context_payload, dict):
                pedidos_excerpt = str(context_payload.get('pedidos_excerpt', '') or '').strip()
                context_event_identifier = str(context_payload.get('document_event_identifier', '') or '').strip()
                if context_event_identifier:
                    document_event_identifier = context_event_identifier

            summary_agent = JudicialDocumentSummaryAgent(
                model_name=ai_model_settings_service.get_model(
                    process.law_firm_id, 'judicial_document_summary'))
            summary_result = summary_agent.summarize_document(
                file_path=str(document.file_path),
                document_type_name=doc_type_name,
                document_type_key=doc_type_key,
                file_type='',
                sections_overview=sections_overview,
                pedidos_excerpt=pedidos_excerpt,
                document_event_identifier=document_event_identifier,
                user_id=document.uploaded_by,
                law_firm_id=process.law_firm_id,
            )

            if isinstance(summary_result, dict) and document_event_identifier:
                summary_result['document_event_identifier'] = document_event_identifier

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
                existing.processed_at = datetime.now()
                existing.updated_at = datetime.now()
            else:
                db.session.add(
                    JudicialDocumentSummary(
                        judicial_document_id=document.id,
                        law_firm_id=process.law_firm_id,
                        summary_text=summary_text,
                        summary_payload=summary_result,
                        status='completed',
                        processed_at=datetime.now(),
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
                    existing.updated_at = datetime.now()
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
