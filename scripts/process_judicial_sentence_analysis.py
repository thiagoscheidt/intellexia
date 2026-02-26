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
from datetime import datetime
from rich import print

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.models import db, JudicialSentenceAnalysis
from app.agents.agent_sentence_summary import AgentSentenceSummary
from app.agents.agent_initial_petition_analysis import AgentInitialPetitionAnalysis


def analyze_sentence_with_ai(sentence_path: str, petition_path: str | None = None) -> str | None:
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
        petition_benefits_data = None
        
        if petition_path and os.path.exists(petition_path):
            petition_agent = AgentInitialPetitionAnalysis(model_name="gpt-5-nano")
            
            # 1.1 Extrair pedidos
            print(f"Extraindo pedidos da petição inicial: {petition_path}")
            try:
                petition_requests_data = petition_agent.extract_petition_requests(file_path=petition_path)
                # Extrai a lista simples de pedidos para usar como contexto
                petition_requests_list = petition_requests_data.get('all_requests', [])
                print(f"✓ {len(petition_requests_list)} pedidos extraídos da petição")
            except Exception as petition_error:
                print(f"Erro ao extrair pedidos da petição inicial: {petition_error}")
                import traceback
                traceback.print_exc()
            
            # 1.2 Extrair benefícios (especialmente importante para processos FAP)
            print(f"Extraindo benefícios da petição inicial: {petition_path}")
            try:
                #petition_benefits_data = petition_agent.extract_benefits_and_reasons(file_path=petition_path)
                petition_benefits_data = petition_agent.extract_benefits_and_reasons_from_requests(file_path=petition_path)
                benefits_count = len(petition_benefits_data.get('benefits', []))
                print(f"✓ {benefits_count} benefícios extraídos da petição")
            except Exception as benefits_error:
                print(f"Erro ao extrair benefícios da petição inicial: {benefits_error}")
                import traceback
                traceback.print_exc()
        elif petition_path:
            print(f"Petição inicial informada, mas arquivo não encontrado: {petition_path}")
        
        # PASSO 2: Analisar a sentença (com pedidos e benefícios da petição como contexto, se disponíveis)
        print(f"Analisando sentença: {sentence_path}")
        sentence_agent = AgentSentenceSummary()
        
        sentence_analysis = sentence_agent.summarizeSentence(
            file_path=sentence_path,
            petition_requests=petition_requests_list,
            petition_benefits=petition_benefits_data
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


def process_pending_sentences(batch_size: int = 10) -> int:
    """Processa um lote de análises pendentes. Retorna quantidade processada."""
    pending_items = (
        JudicialSentenceAnalysis.query
        .filter(JudicialSentenceAnalysis.status == 'pending')
        .order_by(JudicialSentenceAnalysis.uploaded_at.asc())
        .limit(batch_size)
        .all()
    )

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
                petition_path=item.petition_file_path
            )

            if not analysis:
                raise Exception("Falha ao gerar análise pela IA")

            item.analysis_result = analysis
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


if __name__ == '__main__':
    with app.app_context():
        total = process_pending_sentences(batch_size=10)
        print(f"Total processado: {total}")
