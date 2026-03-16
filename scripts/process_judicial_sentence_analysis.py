"""
Processador de análises de sentenças judiciais (pendentes).

Uso:
  python scripts/process_judicial_sentence_analysis.py

Observação:
- Este script ainda NÃO implementa a IA.
- Basta implementar a função `analyze_sentence_with_ai`.
"""

import os
import sys
import json
import argparse
import unicodedata
import re
from datetime import datetime
from rich import print

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.models import db, JudicialSentenceAnalysis, JudicialProcess, JudicialDocument, JudicialProcessBenefit
from app.agents.document_processing.agent_sentence_summary import AgentSentenceSummary
from app.agents.document_processing.agent_initial_petition_analysis import AgentInitialPetitionAnalysis


def _normalize_doc_type(value: str | None) -> str:
    normalized = unicodedata.normalize('NFKD', str(value or '').strip().lower())
    return ''.join(ch for ch in normalized if not unicodedata.combining(ch))


def _is_sentence_document(doc_type: str | None) -> bool:
    normalized = _normalize_doc_type(doc_type)
    return 'sentenca' in normalized


def _is_initial_petition_document(doc_type: str | None) -> bool:
    normalized = _normalize_doc_type(doc_type)
    return 'peticao' in normalized and 'inicial' in normalized


def _resolve_existing_file_path(doc: JudicialDocument) -> str | None:
    """Retorna um caminho de arquivo válido para o documento, se existir."""
    current_path = str(doc.file_path or '').strip()
    if current_path and os.path.exists(current_path):
        return current_path

    if doc.knowledge_base and doc.knowledge_base.file_path:
        kb_path = str(doc.knowledge_base.file_path).strip()
        if kb_path and os.path.exists(kb_path):
            doc.file_path = kb_path
            return kb_path

    return None


def _queue_process_sentences(process: JudicialProcess) -> int:
    """Cria registros pendentes de análise para as sentenças vinculadas ao processo."""
    process_documents = JudicialDocument.query.filter_by(process_id=process.id).order_by(
        JudicialDocument.created_at.desc()
    ).all()

    sentence_docs = [doc for doc in process_documents if _is_sentence_document(doc.type)]
    petition_doc = next((doc for doc in process_documents if _is_initial_petition_document(doc.type)), None)

    queued = 0
    for sentence_doc in sentence_docs:
        sentence_path = _resolve_existing_file_path(sentence_doc)
        if not sentence_path:
            continue

        existing = JudicialSentenceAnalysis.query.filter_by(
            law_firm_id=process.law_firm_id,
            file_path=sentence_path,
        ).first()
        if existing:
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


def _normalize_benefit_number(value: str | None) -> str:
    if not value:
        return ''
    return ''.join(ch for ch in str(value) if ch.isdigit())


def _normalize_benefit_decision(value: str | None) -> str:
    normalized = _normalize_doc_type(value)
    if not normalized:
        return 'Não mencionado na sentença'

    if 'nao mencionado' in normalized:
        return 'Não mencionado na sentença'
    if 'aceito' in normalized or 'defer' in normalized or 'procedente' in normalized:
        return 'Procedente'
    if 'rejeitado' in normalized or 'indefer' in normalized or 'improcedente' in normalized:
        return 'Improcedente'

    return 'Não mencionado na sentença'


def _normalize_for_match(value: str | None) -> str:
    normalized = _normalize_doc_type(value)
    return re.sub(r'\s+', ' ', normalized).strip()


def _extract_thesis_terms(value: str | None) -> list[str]:
    text = _normalize_for_match(value)
    if not text:
        return []

    terms: list[str] = []
    stopwords = {
        'beneficio', 'beneficios', 'revisao', 'fap', 'motivo', 'legal', 'tese', 'teses',
        'de', 'da', 'do', 'dos', 'das', 'e', 'em', 'para', 'por', 'com', 'sem'
    }
    for token in re.split(r'[^a-z0-9]+', text):
        if not token or token in stopwords:
            continue
        if len(token) >= 3 or re.fullmatch(r'b\d{2}', token):
            terms.append(token)

    seen = set()
    unique_terms = []
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        unique_terms.append(term)
    return unique_terms


def _build_analysis_text_blob(analysis: dict) -> str:
    if not isinstance(analysis, dict):
        return ''

    sentence_info = analysis.get('sentence_info', {}) if isinstance(analysis.get('sentence_info', {}), dict) else {}
    parts: list[str] = []

    for key in ('summary', 'summary_short', 'summary_long', 'notes'):
        value = analysis.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)

    for key in ('operative_part', 'overall_result'):
        value = sentence_info.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)

    for item in sentence_info.get('key_points', []) if isinstance(sentence_info.get('key_points'), list) else []:
        if isinstance(item, str) and item.strip():
            parts.append(item)

    for decision in sentence_info.get('decisions', []) if isinstance(sentence_info.get('decisions'), list) else []:
        if not isinstance(decision, dict):
            continue
        for key in ('subject', 'result', 'reasoning'):
            value = decision.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)

    for benefit_item in sentence_info.get('fap_benefits_analysis', []) if isinstance(sentence_info.get('fap_benefits_analysis'), list) else []:
        if not isinstance(benefit_item, dict):
            continue
        for key in ('benefit_number', 'insured_name', 'accident_type', 'result', 'reasoning'):
            value = benefit_item.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)

    return _normalize_for_match(' '.join(parts))


def _load_process_benefits_payload(process_number: str | None, law_firm_id: int | None) -> dict | None:
    """Carrega benefícios já cadastrados no processo para usar como contexto da análise de sentença."""
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
            thesis_names = [thesis.name for thesis in benefit.legal_theses if thesis and thesis.name]
            revision_reason = ', '.join(thesis_names)
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


def _build_benefits_markdown_context(petition_benefits_data: dict | None) -> str | None:
    """Converte benefícios estruturados em texto tabular para contexto forte no prompt."""
    if not petition_benefits_data or not isinstance(petition_benefits_data, dict):
        return None

    benefits = petition_benefits_data.get('benefits', [])
    if not isinstance(benefits, list) or not benefits:
        return None

    header = [
        'INSTRUCOES DE VINCULACAO:',
        '- Considere TODOS os beneficios da tabela para preencher fap_benefits_analysis.',
        '- Se a sentenca decidir em BLOCO por grupo (ex.: "14 B91 de trajeto"), propague a mesma decisao para todos os beneficios desse grupo (mesmo tipo/tese).',
        '- Marque "Nao mencionado na sentenca" apenas quando realmente nao houver criterio para vincular o beneficio.',
        '',
        '| NB | NIT | Segurado | Tipo | Vigência FAP | Motivo/Tese |',
        '|---|---|---|---|---|---|',
    ]

    rows = []
    for benefit in benefits:
        if not isinstance(benefit, dict):
            continue

        benefit_number = str(benefit.get('benefit_number') or '').strip() or '-'
        nit_number = str(benefit.get('nit_number') or '').strip() or '-'
        insured_name = str(benefit.get('insured_name') or '').strip() or '-'
        benefit_type = str(benefit.get('benefit_type') or '').strip() or '-'
        fap_vigencia = str(benefit.get('fap_vigencia_year') or '').strip() or '-'
        revision_reason = str(benefit.get('revision_reason') or '').strip() or '-'

        rows.append(
            f"| {benefit_number} | {nit_number} | {insured_name} | {benefit_type} | {fap_vigencia} | {revision_reason} |"
        )

    if not rows:
        return None

    return '\n'.join(header + rows)


def _sync_benefit_decisions_from_analysis(item: JudicialSentenceAnalysis, analysis: dict) -> int:
    process_number = str(item.process_number or '').strip()
    if not process_number:
        return 0

    process = JudicialProcess.query.filter_by(
        law_firm_id=item.law_firm_id,
        process_number=process_number,
    ).first()
    if not process:
        return 0

    sentence_info = analysis.get('sentence_info', {}) if isinstance(analysis, dict) else {}
    benefits_analysis = sentence_info.get('fap_benefits_analysis', []) if isinstance(sentence_info, dict) else []
    if not isinstance(benefits_analysis, list) or not benefits_analysis:
        return 0

    updated = 0
    process_benefits = JudicialProcessBenefit.query.filter_by(process_id=process.id).all()
    analysis_text_blob = _build_analysis_text_blob(analysis)

    positive_markers = ('aceito', 'aceitos', 'procedente', 'procedentes', 'defer', 'reconhecid')
    negative_markers = ('rejeitado', 'rejeitados', 'improcedente', 'indefer')

    benefits_by_number = {
        _normalize_benefit_number(benefit.benefit_number): benefit
        for benefit in process_benefits
        if _normalize_benefit_number(benefit.benefit_number)
    }

    for benefit_item in benefits_analysis:
        if not isinstance(benefit_item, dict):
            continue

        raw_number = benefit_item.get('benefit_number', '')
        normalized_number = _normalize_benefit_number(raw_number)
        if not normalized_number:
            continue

        target_benefit = benefits_by_number.get(normalized_number)
        if not target_benefit:
            continue

        decision = _normalize_benefit_decision(benefit_item.get('result', ''))
        if target_benefit.first_instance_decision != decision:
            target_benefit.first_instance_decision = decision
            target_benefit.updated_at = datetime.utcnow()
            updated += 1

    # Fallback: quando a sentença decide por grupo (tipo/tese) e não por NB individual.
    for benefit in process_benefits:
        if benefit.first_instance_decision and benefit.first_instance_decision != 'Não mencionado na sentença':
            continue

        benefit_type_norm = _normalize_for_match(benefit.benefit_type)
        if not benefit_type_norm or benefit_type_norm not in analysis_text_blob:
            continue

        thesis_text = ''
        if getattr(benefit, 'legal_theses', None):
            thesis_text = ' '.join([th.name for th in benefit.legal_theses if th and th.name])
        elif getattr(benefit, 'legal_thesis', None):
            thesis_text = str(benefit.legal_thesis)

        thesis_terms = _extract_thesis_terms(thesis_text)
        if not thesis_terms:
            continue
        if not any(term in analysis_text_blob for term in thesis_terms):
            continue

        has_positive = any(marker in analysis_text_blob for marker in positive_markers)
        has_negative = any(marker in analysis_text_blob for marker in negative_markers)

        inferred_decision = None
        if has_positive and not has_negative:
            inferred_decision = 'Procedente'
        elif has_negative and not has_positive:
            inferred_decision = 'Improcedente'

        if inferred_decision and benefit.first_instance_decision != inferred_decision:
            benefit.first_instance_decision = inferred_decision
            benefit.updated_at = datetime.utcnow()
            updated += 1

    return updated


def analyze_sentence_with_ai(
    sentence_path: str,
    petition_path: str | None = None,
    process_number: str | None = None,
    user_id: int | None = None,
    law_firm_id: int | None = None,
) -> str | None:
    """
    Analisa a sentença judicial usando IA e, se disponível, extrai os pedidos da petição inicial.

    Args:
        sentence_path: caminho do arquivo da sentença
        petition_path: caminho da petição inicial (opcional) - pedidos serão extraídos e usados como contexto

    Returns:
        str: JSON com o resultado da análise ou None em caso de erro
    """
    try:
        # PASSO 1: Extrair pedidos e benefícios da petição ANTES de analisar a sentença (se houver)
        petition_requests_list = None
        petition_requests_data = None
        petition_benefits_data = _load_process_benefits_payload(
            process_number=process_number,
            law_firm_id=law_firm_id,
        )
        petition_benefits_context = _build_benefits_markdown_context(petition_benefits_data)

        if petition_benefits_data and petition_benefits_data.get('benefits'):
            print(f"✓ {len(petition_benefits_data.get('benefits', []))} benefícios carregados da tabela do processo")
        else:
            print("⚠ Nenhum benefício encontrado na tabela do processo")
        
        if petition_path and os.path.exists(petition_path):
            petition_agent = AgentInitialPetitionAnalysis(model_name="gpt-5-nano")
            
            # 1.1 Extrair pedidos
            # print(f"Extraindo pedidos da petição inicial: {petition_path}")
            # try:
            #     petition_requests_data = petition_agent.extract_petition_requests(file_path=petition_path)
            #     # Extrai a lista simples de pedidos para usar como contexto
            #     petition_requests_list = petition_requests_data.get('all_requests', [])
            #     print(f"✓ {len(petition_requests_list)} pedidos extraídos da petição")
            # except Exception as petition_error:
            #     print(f"Erro ao extrair pedidos da petição inicial: {petition_error}")
            #     import traceback
            #     traceback.print_exc()
            
            # 1.2 Benefícios agora vêm da base do processo (JudicialProcessBenefit), não da petição.
        elif petition_path:
            print(f"Petição inicial informada, mas arquivo não encontrado: {petition_path}")
        
        # PASSO 2: Analisar a sentença (com pedidos e benefícios da petição como contexto, se disponíveis)
        print(f"Analisando sentença: {sentence_path}")
        sentence_agent = AgentSentenceSummary()
        
        sentence_analysis = sentence_agent.summarizeSentence(
            file_path=sentence_path,
            petition_requests=petition_requests_list,
            petition_benefits=petition_benefits_context or petition_benefits_data,
            user_id=user_id,
            law_firm_id=law_firm_id,
        )

        # PASSO 3: Montar resultado final
        combined_analysis = sentence_analysis
        
        # Incluir dados completos dos pedidos da petição (com detalhamento) se foram extraídos
        if petition_requests_data:
            combined_analysis["petition_requests"] = petition_requests_data
        
        # Incluir dados dos benefícios da petição se foram extraídos
        if petition_benefits_data:
            combined_analysis["petition_benefits"] = petition_benefits_data
        
        # Converte para JSON
        result_json = json.dumps(combined_analysis, ensure_ascii=False, indent=2)
        
        print("Análise concluída com sucesso!")
        return result_json
        
    except Exception as e:
        print(f"Erro ao analisar sentença: {e}")
        import traceback
        traceback.print_exc()
        return None


def process_pending_sentences(batch_size: int = 10, process_id: int | None = None) -> int:
    """Processa análises pendentes, com opção de enfileirar e filtrar por processo."""
    if process_id:
        process = JudicialProcess.query.filter_by(id=process_id).first()
        if not process:
            print(f"Processo {process_id} não encontrado.")
            return 0

        queued = _queue_process_sentences(process)
        print(f"Sentenças enfileiradas para o processo {process_id}: {queued}")

    query = JudicialSentenceAnalysis.query.filter(JudicialSentenceAnalysis.status == 'pending')

    if process_id:
        process = JudicialProcess.query.filter_by(id=process_id).first()
        if process and process.process_number:
            query = query.filter(JudicialSentenceAnalysis.process_number == process.process_number)
        else:
            query = query.filter(JudicialSentenceAnalysis.id == -1)

    pending_items = query.order_by(JudicialSentenceAnalysis.uploaded_at.asc()).limit(batch_size).all()

    if not pending_items:
        print("Nenhuma análise pendente encontrada.")
        return 0

    processed = 0

    for item in pending_items:
        try:
            # Marcar como processando antes de iniciar
            print(f"Iniciando processamento: {item.id} - {item.original_filename}")
            item.status = 'processing'
            item.error_message = None
            db.session.commit()

            analysis = analyze_sentence_with_ai(
                sentence_path=item.file_path,
                petition_path=item.petition_file_path,
                process_number=item.process_number,
                user_id=item.user_id,
                law_firm_id=item.law_firm_id,
            )

            if not analysis:
                raise Exception("Falha ao gerar análise pela IA")

            analysis_dict = json.loads(analysis)
            item.analysis_result = analysis

            updated_benefits = _sync_benefit_decisions_from_analysis(item, analysis_dict)
            if updated_benefits > 0:
                print(
                    f"Benefícios atualizados com decisão de julgamento (1ª instância): {updated_benefits}"
                )

            item.processed_at = datetime.utcnow()
            item.status = 'completed'
            db.session.commit()

            processed += 1
            print(f"Processado: {item.id} - {item.original_filename}")
        except Exception as e:
            db.session.rollback()
            item.status = 'error'
            item.error_message = str(e)
            db.session.commit()
            import traceback
            print(f"Erro ao processar {item.id}: {e}")
            traceback.print_exc()

    return processed


def parse_args():
    parser = argparse.ArgumentParser(description='Processa análises pendentes de sentença judicial')
    parser.add_argument('--batch-size', type=int, default=10, help='Quantidade máxima por execução')
    parser.add_argument('--process-id', type=int, help='ID do processo para enfileirar e processar suas sentenças')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    with app.app_context():
        total = process_pending_sentences(batch_size=args.batch_size, process_id=args.process_id)
        print(f"Total processado: {total}")
