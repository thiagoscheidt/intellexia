from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime

from rich import print

from app.models import db, JudicialDocument, JudicialProcess, JudicialProcessBenefit, JudicialSentenceAnalysis
from app.agents.document_processing.agent_sentence_summary import AgentSentenceSummary
from app.services.document_processor_service import DocumentProcessorService


class JudicialSentenceAnalysisService:

    def __init__(self, flask_app):
        self.app = flask_app
        self.doc_processor = DocumentProcessorService()

    # ------------------------------------------------------------------
    # Normalização
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(value: str | None) -> str:
        normalized = unicodedata.normalize('NFKD', str(value or '').strip().lower())
        return ''.join(ch for ch in normalized if not unicodedata.combining(ch))

    @staticmethod
    def _normalize_for_match(value: str | None) -> str:
        normalized = unicodedata.normalize('NFKD', str(value or '').strip().lower())
        text = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def _normalize_benefit_number(value: str | None) -> str:
        return ''.join(ch for ch in str(value or '') if ch.isdigit())

    def _normalize_benefit_decision(self, value: str | None) -> str:
        norm = self._normalize(value)
        if not norm or 'nao mencionado' in norm:
            return 'Não mencionado na sentença'
        if 'aceito' in norm or 'defer' in norm or 'procedente' in norm:
            return 'Procedente'
        if 'rejeitado' in norm or 'indefer' in norm or 'improcedente' in norm:
            return 'Improcedente'
        return 'Não mencionado na sentença'

    def _extract_thesis_terms(self, value: str | None) -> list[str]:
        text = self._normalize_for_match(value)
        if not text:
            return []
        stopwords = {
            'beneficio', 'beneficios', 'revisao', 'fap', 'motivo', 'legal', 'tese', 'teses',
            'de', 'da', 'do', 'dos', 'das', 'e', 'em', 'para', 'por', 'com', 'sem',
        }
        seen: set[str] = set()
        terms: list[str] = []
        for token in re.split(r'[^a-z0-9]+', text):
            if not token or token in stopwords or token in seen:
                continue
            if len(token) >= 3 or re.fullmatch(r'b\d{2}', token):
                terms.append(token)
                seen.add(token)
        return terms

    # ------------------------------------------------------------------
    # Helpers de documento
    # ------------------------------------------------------------------

    @staticmethod
    def _is_sentence_doc(doc_type: str | None) -> bool:
        norm = unicodedata.normalize('NFKD', str(doc_type or '').strip().lower())
        norm = ''.join(ch for ch in norm if not unicodedata.combining(ch))
        return 'sentenca' in norm

    @staticmethod
    def _is_initial_petition_doc(doc_type: str | None) -> bool:
        norm = unicodedata.normalize('NFKD', str(doc_type or '').strip().lower())
        norm = ''.join(ch for ch in norm if not unicodedata.combining(ch))
        return 'peticao' in norm and 'inicial' in norm

    @staticmethod
    def _resolve_file_path(doc: JudicialDocument) -> str | None:
        path = str(doc.file_path or '').strip()
        if path and os.path.exists(path):
            return path
        if doc.knowledge_base and doc.knowledge_base.file_path:
            kb_path = str(doc.knowledge_base.file_path).strip()
            if kb_path and os.path.exists(kb_path):
                doc.file_path = kb_path
                return kb_path
        return None

    # ------------------------------------------------------------------
    # Enfileiramento
    # ------------------------------------------------------------------

    def queue_process_sentences(self, process: JudicialProcess) -> int:
        """Cria registros pendentes de análise para as sentenças vinculadas ao processo."""
        docs = JudicialDocument.query.filter_by(process_id=process.id).order_by(
            JudicialDocument.created_at.desc()
        ).all()

        sentence_docs = [d for d in docs if self._is_sentence_doc(d.type)]
        petition_doc = next((d for d in docs if self._is_initial_petition_doc(d.type)), None)

        queued = 0
        for sentence_doc in sentence_docs:
            sentence_path = self._resolve_file_path(sentence_doc)
            if not sentence_path:
                continue

            if JudicialSentenceAnalysis.query.filter_by(
                law_firm_id=process.law_firm_id,
                file_path=sentence_path,
            ).first():
                continue

            ext = os.path.splitext(sentence_doc.file_name or '')[1].lower().replace('.', '')
            analysis = JudicialSentenceAnalysis(
                user_id=process.user_id,
                law_firm_id=process.law_firm_id,
                original_filename=sentence_doc.file_name,
                file_path=sentence_path,
                file_size=os.path.getsize(sentence_path),
                file_type=ext.upper() if ext else '',
                process_number=process.process_number,
                status='pending',
            )

            if petition_doc and petition_doc.file_path and os.path.exists(petition_doc.file_path):
                petition_ext = os.path.splitext(petition_doc.file_name or '')[1].lower().replace('.', '')
                analysis.petition_filename = petition_doc.file_name
                analysis.petition_file_path = petition_doc.file_path
                analysis.petition_file_size = os.path.getsize(petition_doc.file_path)
                analysis.petition_file_type = petition_ext.upper() if petition_ext else ''

            db.session.add(analysis)
            queued += 1

        if queued > 0:
            db.session.commit()

        return queued

    # ------------------------------------------------------------------
    # Contexto de benefícios
    # ------------------------------------------------------------------

    def _load_benefits_payload(self, process_number: str | None, law_firm_id: int | None) -> dict | None:
        process_number_clean = str(process_number or '').strip()
        if not process_number_clean or not law_firm_id:
            return None

        process = JudicialProcess.query.filter_by(
            law_firm_id=law_firm_id,
            process_number=process_number_clean,
        ).first()
        if not process:
            return None

        process_benefits = JudicialProcessBenefit.query.filter_by(process_id=process.id).all()
        if not process_benefits:
            return None

        benefits_list = []
        for benefit in process_benefits:
            revision_reason = ''
            if getattr(benefit, 'legal_theses', None):
                revision_reason = ', '.join(th.name for th in benefit.legal_theses if th and th.name)
            elif getattr(benefit, 'legal_thesis', None):
                revision_reason = str(benefit.legal_thesis)

            benefits_list.append({
                'benefit_number': str(benefit.benefit_number or '').strip(),
                'nit_number': str(benefit.nit_number or '').strip(),
                'insured_name': str(benefit.insured_name or '').strip(),
                'benefit_type': str(benefit.benefit_type or '').strip(),
                'fap_vigencia_year': str(benefit.fap_vigencia_year or '').strip(),
                'accident_date': '',
                'revision_reason': revision_reason.strip(),
            })

        return {
            'general_revision_context': 'Benefícios carregados da base do processo judicial',
            'benefits': benefits_list,
        }

    def _build_benefits_markdown(self, data: dict | None) -> str | None:
        if not data or not isinstance(data, dict):
            return None
        benefits = data.get('benefits', [])
        if not isinstance(benefits, list) or not benefits:
            return None

        lines = [
            'INSTRUCOES DE VINCULACAO:',
            '- Considere TODOS os beneficios da tabela para preencher fap_benefits_analysis.',
            '- Se a sentenca decidir em BLOCO por grupo (ex.: "14 B91 de trajeto"), propague a mesma decisao para todos os beneficios desse grupo (mesmo tipo/tese).',
            '- Marque "Nao mencionado na sentenca" apenas quando realmente nao houver criterio para vincular o beneficio.',
            '',
            '| NB | NIT | Segurado | Tipo | Vigência FAP | Motivo/Tese |',
            '|---|---|---|---|---|---|',
        ]
        for b in benefits:
            if not isinstance(b, dict):
                continue
            lines.append(
                f"| {b.get('benefit_number') or '-'} "
                f"| {b.get('nit_number') or '-'} "
                f"| {b.get('insured_name') or '-'} "
                f"| {b.get('benefit_type') or '-'} "
                f"| {b.get('fap_vigencia_year') or '-'} "
                f"| {b.get('revision_reason') or '-'} |"
            )
        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Sincronização de decisões
    # ------------------------------------------------------------------

    def _build_analysis_blob(self, analysis: dict) -> str:
        if not isinstance(analysis, dict):
            return ''
        sentence_info = analysis.get('sentence_info') or {}
        if not isinstance(sentence_info, dict):
            sentence_info = {}

        parts: list[str] = []
        for key in ('summary', 'summary_short', 'summary_long', 'notes'):
            v = analysis.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v)
        for key in ('operative_part', 'overall_result'):
            v = sentence_info.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v)
        for item in (sentence_info.get('key_points') or []):
            if isinstance(item, str) and item.strip():
                parts.append(item)
        for decision in (sentence_info.get('decisions') or []):
            if not isinstance(decision, dict):
                continue
            for key in ('subject', 'result', 'reasoning'):
                v = decision.get(key)
                if isinstance(v, str) and v.strip():
                    parts.append(v)
        for b in (sentence_info.get('fap_benefits_analysis') or []):
            if not isinstance(b, dict):
                continue
            for key in ('benefit_number', 'insured_name', 'accident_type', 'result', 'reasoning'):
                v = b.get(key)
                if isinstance(v, str) and v.strip():
                    parts.append(v)

        return self._normalize_for_match(' '.join(parts))

    def _sync_benefit_decisions(self, item: JudicialSentenceAnalysis, analysis: dict) -> int:
        process_number = str(item.process_number or '').strip()
        if not process_number:
            return 0

        process = JudicialProcess.query.filter_by(
            law_firm_id=item.law_firm_id,
            process_number=process_number,
        ).first()
        if not process:
            return 0

        sentence_info = analysis.get('sentence_info') or {} if isinstance(analysis, dict) else {}
        benefits_analysis = sentence_info.get('fap_benefits_analysis') or []
        if not isinstance(benefits_analysis, list) or not benefits_analysis:
            return 0

        process_benefits = JudicialProcessBenefit.query.filter_by(process_id=process.id).all()
        blob = self._build_analysis_blob(analysis)
        positive = ('aceito', 'aceitos', 'procedente', 'procedentes', 'defer', 'reconhecid')
        negative = ('rejeitado', 'rejeitados', 'improcedente', 'indefer')

        by_number = {
            self._normalize_benefit_number(b.benefit_number): b
            for b in process_benefits
            if self._normalize_benefit_number(b.benefit_number)
        }

        updated = 0

        for benefit_item in benefits_analysis:
            if not isinstance(benefit_item, dict):
                continue
            nb = self._normalize_benefit_number(benefit_item.get('benefit_number', ''))
            if not nb:
                continue
            target = by_number.get(nb)
            if not target:
                continue
            decision = self._normalize_benefit_decision(benefit_item.get('result', ''))
            if target.first_instance_decision != decision:
                target.first_instance_decision = decision
                target.updated_at = datetime.utcnow()
                updated += 1

        # Fallback: sentença decide por grupo (tipo/tese), não por NB individual
        for benefit in process_benefits:
            if benefit.first_instance_decision and benefit.first_instance_decision != 'Não mencionado na sentença':
                continue
            benefit_type_norm = self._normalize_for_match(benefit.benefit_type)
            if not benefit_type_norm or benefit_type_norm not in blob:
                continue

            thesis_text = ''
            if getattr(benefit, 'legal_theses', None):
                thesis_text = ' '.join(th.name for th in benefit.legal_theses if th and th.name)
            elif getattr(benefit, 'legal_thesis', None):
                thesis_text = str(benefit.legal_thesis)

            terms = self._extract_thesis_terms(thesis_text)
            if not terms or not any(t in blob for t in terms):
                continue

            has_pos = any(m in blob for m in positive)
            has_neg = any(m in blob for m in negative)
            inferred = None
            if has_pos and not has_neg:
                inferred = 'Procedente'
            elif has_neg and not has_pos:
                inferred = 'Improcedente'

            if inferred and benefit.first_instance_decision != inferred:
                benefit.first_instance_decision = inferred
                benefit.updated_at = datetime.utcnow()
                updated += 1

        return updated

    # ------------------------------------------------------------------
    # Análise individual
    # ------------------------------------------------------------------

    def analyze_sentence(
        self,
        sentence_path: str,
        process_number: str | None = None,
        user_id: int | None = None,
        law_firm_id: int | None = None,
    ) -> str | None:
        try:
            benefits_data = self._load_benefits_payload(process_number, law_firm_id)
            benefits_ctx = self._build_benefits_markdown(benefits_data)

            if benefits_data and benefits_data.get('benefits'):
                print(f"✓ {len(benefits_data['benefits'])} benefícios carregados do processo")
            else:
                print("⚠ Nenhum benefício encontrado na tabela do processo")

            print(f"Convertendo sentença: {sentence_path}")
            sentence_text = self.doc_processor.convert_with_markitdown(sentence_path)

            print(f"Analisando sentença com IA...")
            agent = AgentSentenceSummary()
            analysis = agent.summarizeSentence(
                text_content=sentence_text,
                petition_benefits=benefits_ctx or benefits_data,
                user_id=user_id,
                law_firm_id=law_firm_id,
            )

            if benefits_data:
                analysis['petition_benefits'] = benefits_data

            print("Análise concluída com sucesso!")
            return json.dumps(analysis, ensure_ascii=False, indent=2)

        except Exception as e:
            import traceback
            print(f"Erro ao analisar sentença: {e}")
            traceback.print_exc()
            return None

    # ------------------------------------------------------------------
    # Processamento em lote
    # ------------------------------------------------------------------

    def process_pending_sentences(
        self,
        batch_size: int = 10,
        process_id: int | None = None,
        include_errors: bool = False,
    ) -> int:
        with self.app.app_context():
            if process_id:
                process = JudicialProcess.query.filter_by(id=process_id).first()
                if not process:
                    print(f"Processo {process_id} não encontrado.")
                    return 0
                queued = self.queue_process_sentences(process)
                print(f"Sentenças enfileiradas para o processo {process_id}: {queued}")

            statuses = ['pending']
            if include_errors:
                statuses.append('error')

            query = JudicialSentenceAnalysis.query.filter(
                JudicialSentenceAnalysis.status.in_(statuses)
            )

            if process_id:
                process = JudicialProcess.query.filter_by(id=process_id).first()
                if process and process.process_number:
                    query = query.filter(JudicialSentenceAnalysis.process_number == process.process_number)
                else:
                    query = query.filter(JudicialSentenceAnalysis.id == -1)

            pending = query.order_by(JudicialSentenceAnalysis.uploaded_at.asc()).limit(batch_size).all()

            if not pending:
                print("Nenhuma análise pendente encontrada.")
                return 0

            processed = 0
            for item in pending:
                try:
                    print(f"Iniciando: {item.id} - {item.original_filename}")
                    item.status = 'processing'
                    item.error_message = None
                    db.session.commit()

                    result_json = self.analyze_sentence(
                        sentence_path=item.file_path,
                        process_number=item.process_number,
                        user_id=item.user_id,
                        law_firm_id=item.law_firm_id,
                    )

                    if not result_json:
                        raise Exception("Falha ao gerar análise pela IA")

                    analysis_dict = json.loads(result_json)
                    item.analysis_result = result_json

                    updated_benefits = self._sync_benefit_decisions(item, analysis_dict)
                    if updated_benefits > 0:
                        print(f"Benefícios atualizados (1ª instância): {updated_benefits}")

                    item.processed_at = datetime.utcnow()
                    item.status = 'completed'
                    db.session.commit()
                    processed += 1
                    print(f"Processado: {item.id} - {item.original_filename}")

                except Exception as e:
                    import traceback
                    db.session.rollback()
                    item.status = 'error'
                    item.error_message = str(e)
                    db.session.commit()
                    print(f"Erro ao processar {item.id}: {e}")
                    traceback.print_exc()

            return processed
