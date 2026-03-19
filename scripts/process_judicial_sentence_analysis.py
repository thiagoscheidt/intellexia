"""
Processador de análises de sentenças judiciais (pendentes).

Uso:
  python scripts/process_judicial_sentence_analysis.py
  python scripts/process_judicial_sentence_analysis.py --batch-size 20
  python scripts/process_judicial_sentence_analysis.py --process-id 123
  python scripts/process_judicial_sentence_analysis.py --include-errors
"""

import argparse
import os
import sys

from rich import print

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.services.judicial_sentence_analysis_service import JudicialSentenceAnalysisService


def parse_args():
    parser = argparse.ArgumentParser(description="Processa análises pendentes de sentença judicial")
    parser.add_argument("--batch-size", type=int, default=10, help="Quantidade máxima por execução")
    parser.add_argument("--process-id", type=int, help="ID do processo para enfileirar e processar suas sentenças")
    parser.add_argument(
        "--include-errors",
        action="store_true",
        help="Inclui também análises com status error (além de pending)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    service = JudicialSentenceAnalysisService(flask_app=app)
    total = service.process_pending_sentences(
        batch_size=args.batch_size,
        process_id=args.process_id,
        include_errors=args.include_errors,
    )
    print(f"Total processado: {total}")
