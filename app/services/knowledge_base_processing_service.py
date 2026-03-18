from __future__ import annotations

import re
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path

from rich import print

from app.models import (
    Client,
    db,
    JudicialDocument,
    JudicialDefendant,
    JudicialDocumentType,
    JudicialEvent,
    JudicialLegalThesis,
    JudicialPhase,
    JudicialProcess,
    JudicialProcessBenefit,
    JudicialSentenceAnalysis,
    KnowledgeBase,
    KnowledgeSummary,
)
from app.agents.document_processing.agent_document_extractor import AgentDocumentExtractor
from app.agents.knowledge_base.knowledge_ingestion_agent import KnowledgeIngestionAgent
from app.services.document_processor_service import DocumentProcessorService


class KnowledgeBaseProcessingService:
    def __init__(self, flask_app, max_files_per_execution: int = 5):
        self.app = flask_app
        self.max_files_per_execution = max_files_per_execution

    def _build_query(self, file_id: int | None = None, include_errors: bool = False):
        """Monta a query base para itens pendentes (ou um item específico)."""
        statuses = ["pending"]
        if include_errors:
            statuses.append("error")

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

    @staticmethod
    def _normalize_process_number(value: str | None) -> str:
        if not value:
            return ""
        return "".join(char for char in str(value) if char.isdigit())

    def _extract_primary_process_number(self, value: str | None) -> str:
        if not value:
            return ""

        text_value = str(value).strip()
        cnj_pattern = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
        match = cnj_pattern.search(text_value)
        if match:
            return match.group(0)

        normalized_digits = self._normalize_process_number(text_value)
        if len(normalized_digits) == 20:
            return normalized_digits

        return text_value[:25]

    def _find_process_by_number(self, law_firm_id: int, process_number: str) -> JudicialProcess | None:
        if not process_number:
            return None

        exact_match = JudicialProcess.query.filter_by(
            law_firm_id=law_firm_id,
            process_number=process_number,
        ).first()
        if exact_match:
            return exact_match

        normalized_target = self._normalize_process_number(process_number)
        if not normalized_target:
            return None

        candidates = JudicialProcess.query.filter_by(law_firm_id=law_firm_id).all()
        for candidate in candidates:
            if self._normalize_process_number(candidate.process_number) == normalized_target:
                return candidate

        return None

    def _propagate_process_number_update(
        self,
        law_firm_id: int,
        process_id: int,
        old_number: str,
        new_number: str,
        ingestion_agent: KnowledgeIngestionAgent | None = None,
    ) -> None:
        """Propaga a troca de número de processo para registros relacionados."""
        old_number = str(old_number or "").strip()
        new_number = str(new_number or "").strip()
        if not old_number or not new_number or old_number == new_number:
            return

        now = datetime.utcnow()
        updated_kb_ids: set[int] = set()

        kb_updated = 0
        kb_same_temp = KnowledgeBase.query.filter_by(
            law_firm_id=law_firm_id,
            lawsuit_number=old_number,
            is_active=True,
        ).all()
        for kb_item in kb_same_temp:
            kb_item.lawsuit_number = new_number
            kb_item.updated_at = now
            updated_kb_ids.add(kb_item.id)
            kb_updated += 1

        doc_links = JudicialDocument.query.filter_by(process_id=process_id).all()
        for doc_link in doc_links:
            if not doc_link.knowledge_base_id:
                continue
            kb_item = KnowledgeBase.query.filter_by(
                id=doc_link.knowledge_base_id,
                law_firm_id=law_firm_id,
                is_active=True,
            ).first()
            if not kb_item:
                continue
            if str(kb_item.lawsuit_number or "").strip() != new_number:
                kb_item.lawsuit_number = new_number
                kb_item.updated_at = now
                updated_kb_ids.add(kb_item.id)
                kb_updated += 1

        sentence_updated = 0
        sentence_items = JudicialSentenceAnalysis.query.filter_by(
            law_firm_id=law_firm_id,
            process_number=old_number,
        ).all()
        for sentence in sentence_items:
            sentence.process_number = new_number
            sentence.updated_at = now
            sentence_updated += 1

        if ingestion_agent:
            for kb_id in sorted(updated_kb_ids):
                try:
                    ingestion_agent.update_lawsuit_number_by_file_id(
                        file_id=kb_id,
                        lawsuit_number=new_number,
                    )
                except Exception as error:
                    print(
                        f"Falha ao sincronizar arquivo {kb_id} no Qdrant/Meilisearch: {error}"
                    )

        print(
            f"Propagação do número do processo: KB atualizados={kb_updated}, "
            f"análises atualizadas={sentence_updated}."
        )

    def _resolve_type_and_phase(self, law_firm_id: int, extraction_payload: dict) -> tuple[str, str, str]:
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
            type_key = document_type.key
            phase_key = document_type.phase.key
            type_name = document_type.name
            return type_key, phase_key, type_name

        default_phase = JudicialPhase.query.filter_by(
            law_firm_id=law_firm_id,
            is_active=True,
        ).order_by(JudicialPhase.display_order.asc(), JudicialPhase.name.asc()).first()

        fallback_type = extracted_type_key or "documento_juntado"
        fallback_phase = default_phase.key if default_phase else "inicio_processo"
        fallback_name = extracted_type_name or fallback_type
        return fallback_type, fallback_phase, fallback_name

    def _is_initial_petition_document(self, extraction_payload: dict) -> bool:
        doc_type_key = str(extraction_payload.get("suggested_document_type_key", "") or "").strip().lower()
        doc_type_name = str(extraction_payload.get("suggested_document_type_name", "") or "").strip().lower()

        key_match = "peticao" in doc_type_key and "inicial" in doc_type_key
        name_match = "petição inicial" in doc_type_name or (
            "peticao" in doc_type_name and "inicial" in doc_type_name
        )
        return key_match or name_match

    @staticmethod
    def _normalize_party_name(value: str | None) -> str:
        if not value:
            return ""

        text = str(value).strip().lower()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(
            r"^(autor(?:a)?|requerente|impetrante|exequente|reclamante|réu|reu|demandado|requerido|impetrado|executado|reclamado)\s*[:\-]\s*",
            "",
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
        clean_name = str(party_name or "").strip()
        if not clean_name:
            return None

        client = self._find_similar_client(law_firm_id, clean_name)
        if client:
            return client

        client = Client(
            law_firm_id=law_firm_id,
            name=clean_name,
            cnpj="00000000000000",
        )
        db.session.add(client)
        db.session.flush()
        return client

    def _resolve_or_create_defendant(self, law_firm_id: int, party_name: str) -> JudicialDefendant | None:
        clean_name = str(party_name or "").strip()
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
        law_firm_id: int,
        extraction_payload: dict,
        force_update: bool = False,
    ) -> None:
        active_pole = str(extraction_payload.get("active_pole", "") or "").strip()
        passive_pole = str(extraction_payload.get("passive_pole", "") or "").strip()

        if (force_update or not process.plaintiff_client_id) and active_pole:
            client = self._resolve_or_create_client(law_firm_id=law_firm_id, party_name=active_pole)
            if client:
                process.plaintiff_client_id = client.id

        if (force_update or not process.defendant_id) and passive_pole:
            defendant = self._resolve_or_create_defendant(law_firm_id=law_firm_id, party_name=passive_pole)
            if defendant:
                process.defendant_id = defendant.id

    def _apply_extra_info_from_extraction(
        self,
        process: JudicialProcess,
        extraction_payload: dict,
        force_update: bool = False,
    ) -> None:
        """Salva classe, valor da causa, assuntos e flags booleanas extraídos pela IA."""
        classe = extraction_payload.get("classe")
        valor_causa = extraction_payload.get("valor_causa")
        assuntos = extraction_payload.get("assuntos")
        segredo_justica = extraction_payload.get("segredo_justica")
        justica_gratuita = extraction_payload.get("justica_gratuita")
        liminar_tutela = extraction_payload.get("liminar_tutela")

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

    def _link_knowledge_to_process_if_needed(self, item: KnowledgeBase, extraction_payload: dict) -> None:
        existing_link = JudicialDocument.query.filter_by(knowledge_base_id=item.id).first()
        if existing_link:
            process = JudicialProcess.query.filter_by(id=existing_link.process_id).first()
            if process:
                self._apply_parties_from_extraction(
                    process=process,
                    law_firm_id=item.law_firm_id,
                    extraction_payload=extraction_payload,
                    force_update=False,
                )
                self._apply_extra_info_from_extraction(
                    process=process,
                    extraction_payload=extraction_payload,
                    force_update=False,
                )
                process.updated_at = datetime.utcnow()
            return

        user_provided_number = str(item.lawsuit_number or "").strip()
        extracted_number = str(extraction_payload.get("process_number", "") or "").strip()
        is_petition = self._is_initial_petition_document(extraction_payload)

        if is_petition and not user_provided_number:
            process_number_for_create = f"TEMP-{item.id}"
            process = JudicialProcess(
                law_firm_id=item.law_firm_id,
                user_id=item.user_id,
                process_number=process_number_for_create,
                title=f"Processo {process_number_for_create}",
                description=(
                    "Processo criado automaticamente a partir do arquivo da KnowledgeBase "
                    f"ID {item.id} ({item.original_filename})."
                ),
                status="ativo",
                origin_unit=str(extraction_payload.get("judicial_court", "") or "").strip() or None,
            )
            db.session.add(process)
            db.session.flush()
            self._apply_parties_from_extraction(
                process=process,
                law_firm_id=item.law_firm_id,
                extraction_payload=extraction_payload,
                force_update=True,
            )
            self._apply_extra_info_from_extraction(
                process=process,
                extraction_payload=extraction_payload,
                force_update=True,
            )
            item.lawsuit_number = process_number_for_create
        else:
            candidate_process_number = user_provided_number or extracted_number
            if not candidate_process_number:
                return

            process = self._find_process_by_number(item.law_firm_id, candidate_process_number)
            if not process:
                process_number_for_create = self._extract_primary_process_number(candidate_process_number)
                if not process_number_for_create:
                    return

                process = JudicialProcess(
                    law_firm_id=item.law_firm_id,
                    user_id=item.user_id,
                    process_number=process_number_for_create,
                    title=f"Processo {process_number_for_create}",
                    description=(
                        "Processo criado automaticamente a partir do arquivo da KnowledgeBase "
                        f"ID {item.id} ({item.original_filename})."
                    ),
                    status="ativo",
                    origin_unit=str(extraction_payload.get("judicial_court", "") or "").strip() or None,
                )
                db.session.add(process)
                db.session.flush()
                self._apply_parties_from_extraction(
                    process=process,
                    law_firm_id=item.law_firm_id,
                    extraction_payload=extraction_payload,
                    force_update=True,
                )
                self._apply_extra_info_from_extraction(
                    process=process,
                    extraction_payload=extraction_payload,
                    force_update=True,
                )

                if not item.lawsuit_number or not item.lawsuit_number.strip():
                    item.lawsuit_number = process_number_for_create
            else:
                self._apply_parties_from_extraction(
                    process=process,
                    law_firm_id=item.law_firm_id,
                    extraction_payload=extraction_payload,
                    force_update=False,
                )
                self._apply_extra_info_from_extraction(
                    process=process,
                    extraction_payload=extraction_payload,
                    force_update=False,
                )

        event_type, event_phase, event_type_name = self._resolve_type_and_phase(item.law_firm_id, extraction_payload)

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
                knowledge_base_id=item.id,
                type=event_type,
                file_name=item.original_filename,
                file_path=item.file_path,
                uploaded_by=item.user_id,
            )
        )

        process.updated_at = datetime.utcnow()

    def _resolve_target_process(self, item: KnowledgeBase, extraction_payload: dict) -> JudicialProcess | None:
        existing_link = JudicialDocument.query.filter_by(knowledge_base_id=item.id).first()
        if existing_link:
            return JudicialProcess.query.filter_by(id=existing_link.process_id).first()

        current_lawsuit = str(item.lawsuit_number or "").strip()
        extracted_lawsuit = str(extraction_payload.get("process_number", "") or "").strip()
        candidate_process_number = current_lawsuit or extracted_lawsuit
        if not candidate_process_number:
            return None

        return self._find_process_by_number(item.law_firm_id, candidate_process_number)

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

        extracted_benefits = benefits_payload.get("benefits", [])
        if not isinstance(extracted_benefits, list):
            return 0

        upserted = 0

        for benefit in extracted_benefits:
            if not isinstance(benefit, dict):
                continue

            benefit_number = str(benefit.get("benefit_number", "") or "").strip()
            if not benefit_number:
                continue

            nit_number = str(benefit.get("nit_number", "") or "").strip()
            insured_name = str(benefit.get("insured_name", "") or "").strip()
            benefit_type = str(benefit.get("benefit_type", "") or "").strip()
            fap_vigencia_year = str(benefit.get("fap_vigencia_year", "") or "").strip()
            request_type = str(benefit.get("request_type", "") or "").strip() or None
            legal_thesis_id_raw = benefit.get("legal_thesis_id")
            legal_thesis_id = None
            try:
                if legal_thesis_id_raw not in (None, ""):
                    legal_thesis_id = int(legal_thesis_id_raw)
            except (TypeError, ValueError):
                legal_thesis_id = None

            theses = self._load_valid_legal_theses_for_process(
                process,
                [legal_thesis_id] if legal_thesis_id else [],
            )
            resolved_legal_thesis_id = theses[0].id if theses else None

            existing_benefit = JudicialProcessBenefit.query.filter_by(
                process_id=process.id,
                benefit_number=benefit_number,
            ).first()

            if existing_benefit:
                if nit_number and not str(existing_benefit.nit_number or "").strip():
                    existing_benefit.nit_number = nit_number
                if insured_name and not str(existing_benefit.insured_name or "").strip():
                    existing_benefit.insured_name = insured_name
                if benefit_type and not str(existing_benefit.benefit_type or "").strip():
                    existing_benefit.benefit_type = benefit_type
                if fap_vigencia_year and not str(existing_benefit.fap_vigencia_year or "").strip():
                    existing_benefit.fap_vigencia_year = fap_vigencia_year
                if request_type and not str(existing_benefit.request_type or "").strip():
                    existing_benefit.request_type = request_type
                if theses:
                    existing_benefit.legal_theses = theses
                    existing_benefit.legal_thesis_id = resolved_legal_thesis_id
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
                legal_thesis="",
                pfn_technical_note="",
                first_instance_decision="",
                second_instance_decision="",
                third_instance_decision="",
            )
            if theses:
                new_benefit.legal_theses = theses
            db.session.add(new_benefit)
            upserted += 1

        return upserted

    def _apply_benefit_request_types(
        self,
        process: JudicialProcess,
        classification_payload: dict,
    ) -> int:
        """Aplica o request_type classificado a cada benefício do processo."""
        classified = classification_payload.get("benefits", [])
        if not isinstance(classified, list):
            return 0

        updated = 0
        for item in classified:
            if not isinstance(item, dict):
                continue

            benefit_number = str(item.get("benefit_number", "") or "").strip()
            request_type = str(item.get("request_type", "") or "").strip()
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

    def process_single_knowledge_file(self, item_id: int) -> bool:
        """Processa um único arquivo da base de conhecimento."""
        with self.app.app_context():
            item = None
            try:
                item = KnowledgeBase.query.filter_by(id=item_id, is_active=True).first()
                if not item:
                    print(f"Arquivo ID {item_id} não encontrado ou inativo.")
                    return False

                print(f"Iniciando processamento: {item.id} - {item.original_filename}")

                item.processing_status = "processing"
                item.processing_error_message = None
                db.session.commit()

                file_path = Path(item.file_path)
                if not file_path.exists():
                    raise FileNotFoundError(f"Arquivo não encontrado no caminho: {item.file_path}")

                document_processor = DocumentProcessorService()
                ingestion_agent = KnowledgeIngestionAgent()
                document_data = document_processor.process_document(file_path=str(file_path))
                if isinstance(document_data, dict):
                    document_full_text = str(document_data.get("full_text", "") or "")
                else:
                    document_full_text = str(getattr(document_data, "full_text", "") or "")

                document_faiss_vector = document_processor.build_faiss_index(document_full_text)

                extractor_agent = AgentDocumentExtractor(
                    file_id=item.id,
                    file_path=item.file_path,
                    law_firm_id=item.law_firm_id,
                    document_data=document_data,
                    document_faiss_vector=document_faiss_vector,
                )

                markdown_content = ingestion_agent.process_file(
                    processed_document=document_data,
                    source_name=item.original_filename,
                    category=item.category,
                    description=item.description,
                    tags=item.tags,
                    lawsuit_number=item.lawsuit_number,
                    file_id=item.id,
                )

                if not markdown_content:
                    raise RuntimeError("Processamento não retornou conteúdo.")

                extraction_payload = extractor_agent.extract_document_data()
                if not extraction_payload:
                    raise RuntimeError("Extração estruturada não retornou conteúdo.")

                if isinstance(extraction_payload, dict):
                    extracted_process_number = str(extraction_payload.get("process_number", "") or "").strip()
                    extracted_category = str(extraction_payload.get("suggested_category", "") or "").strip()
                    extracted_doc_type_name = str(
                        extraction_payload.get("suggested_document_type_name", "") or ""
                    ).strip()
                    extracted_doc_type_key = str(
                        extraction_payload.get("suggested_document_type_key", "") or ""
                    ).strip()

                    if extracted_process_number and (not item.lawsuit_number or item.lawsuit_number.strip() == ""):
                        item.lawsuit_number = extracted_process_number

                    if extracted_category and (not item.category or item.category.strip() == ""):
                        item.category = extracted_category

                    if (not item.tags or item.tags.strip() == "") and (
                        extracted_doc_type_name or extracted_doc_type_key
                    ):
                        item.tags = extracted_doc_type_name or extracted_doc_type_key

                    self._link_knowledge_to_process_if_needed(item, extraction_payload)

                    if extracted_process_number:
                        linked_doc = JudicialDocument.query.filter_by(knowledge_base_id=item.id).first()
                        if linked_doc:
                            linked_process = JudicialProcess.query.filter_by(id=linked_doc.process_id).first()
                            if linked_process and str(linked_process.process_number or "").startswith("TEMP-"):
                                real_number = self._extract_primary_process_number(extracted_process_number)
                                if real_number:
                                    duplicate = JudicialProcess.query.filter(
                                        JudicialProcess.id != linked_process.id,
                                        JudicialProcess.law_firm_id == linked_process.law_firm_id,
                                        JudicialProcess.process_number == real_number,
                                    ).first()
                                    if not duplicate:
                                        old_temp_number = str(linked_process.process_number or "").strip()
                                        print(
                                            f"Atualizando número temporário {linked_process.process_number} -> {real_number}"
                                        )
                                        linked_process.process_number = real_number
                                        linked_process.updated_at = datetime.utcnow()
                                        item.lawsuit_number = real_number
                                        self._propagate_process_number_update(
                                            law_firm_id=linked_process.law_firm_id,
                                            process_id=linked_process.id,
                                            old_number=old_temp_number,
                                            new_number=real_number,
                                            ingestion_agent=ingestion_agent,
                                        )
                                    else:
                                        print(
                                            f"Número {real_number} já pertence a outro processo (ID {duplicate.id}). "
                                            "Número temporário mantido."
                                        )

                    if self._is_initial_petition_document(extraction_payload):
                        target_process = self._resolve_target_process(item, extraction_payload)
                        if target_process:
                            benefits_payload = extractor_agent.extract_benefits_from_petition(
                                file_path=item.file_path,
                            )
                            inserted_or_updated = self._upsert_process_benefits(target_process, benefits_payload)
                            if inserted_or_updated > 0:
                                print(
                                    f"Benefícios vinculados ao processo {target_process.process_number}: "
                                    f"{inserted_or_updated} registro(s)."
                                )

                            extracted_benefits = benefits_payload.get("benefits", [])
                            if extracted_benefits:
                                classification = extractor_agent.classify_benefit_request_types(
                                    extracted_benefits,
                                )
                                classified_count = self._apply_benefit_request_types(target_process, classification)
                                if classified_count > 0:
                                    print(
                                        f"Tipos de pedido classificados no processo {target_process.process_number}: "
                                        f"{classified_count} benefício(s)."
                                    )

                summary_payload = extraction_payload if isinstance(extraction_payload, dict) else {}

                existing_summary = KnowledgeSummary.query.filter_by(knowledge_base_id=item.id).first()
                if existing_summary:
                    existing_payload = (
                        existing_summary.payload if isinstance(existing_summary.payload, dict) else {}
                    )

                    merged_payload = dict(existing_payload)
                    for key in [
                        "process_number",
                        "suggested_category",
                        "suggested_document_type_key",
                        "suggested_document_type_name",
                        "judicial_court",
                        "active_pole",
                        "passive_pole",
                    ]:
                        current_value = str(merged_payload.get(key, "") or "").strip()
                        new_value = str(summary_payload.get(key, "") or "").strip()
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

                item.processing_status = "completed"
                item.processed_at = datetime.utcnow()
                item.processing_error_message = None
                db.session.commit()

                print(f"Processado com sucesso: {item.id} - {item.original_filename}")
                return True

            except Exception as error:
                db.session.rollback()

                if item is not None:
                    try:
                        item.processing_status = "error"
                        item.processing_error_message = str(error)
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

                print(f"Erro ao processar ID {item_id}: {error}")
                return False
            finally:
                db.session.remove()

    def process_pending_knowledge_files(
        self,
        batch_size: int | None = None,
        file_id: int | None = None,
        include_errors: bool = False,
    ) -> int:
        """Processa arquivos pendentes da base de conhecimento."""
        with self.app.app_context():
            query = self._build_query(file_id=file_id, include_errors=include_errors)

            if file_id:
                items = query.all()
            else:
                batch_size = batch_size or self.max_files_per_execution
                effective_batch_size = max(1, min(batch_size, self.max_files_per_execution))
                items = query.limit(effective_batch_size).all()

            print(f"Itens elegíveis para processamento: {len(items)}")

            if not items:
                if file_id:
                    print(f"Nenhum arquivo elegível encontrado para o ID {file_id}.")
                else:
                    print("Nenhum arquivo pendente encontrado.")
                return 0

            item_ids = [item.id for item in items]

        print("Processando em modo sequencial...")
        return sum(1 for item_id in item_ids if self.process_single_knowledge_file(item_id))
