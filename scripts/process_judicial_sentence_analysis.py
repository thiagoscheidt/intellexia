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

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.models import db, JudicialSentenceAnalysis
from app.agents.agent_sentence_summary import AgentSentenceSummary


def analyze_sentence_with_ai(sentence_path: str, petition_path: str | None = None) -> str | None:
    """
    Analisa a sentença judicial usando IA e retorna o resultado em JSON.

    Args:
        sentence_path: caminho do arquivo da sentença
        petition_path: caminho da petição inicial (opcional, não usado por enquanto)

    Returns:
        str: JSON com o resultado da análise ou None em caso de erro
    """
    try:
        print(f"Analisando sentença: {sentence_path}")
        sentence_agent = AgentSentenceSummary()
        
        # Analisa a sentença
        sentence_analysis = sentence_agent.summarizeSentence(file_path=sentence_path)
        
        # Converte para JSON
        result_json = json.dumps(sentence_analysis, ensure_ascii=False, indent=2)
        
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
