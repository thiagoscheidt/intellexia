"""
Processador de arquivos da Base de Conhecimento (pendentes).

Uso:
  python scripts/process_knowledge_base.py
  python scripts/process_knowledge_base.py --batch-size 20
  python scripts/process_knowledge_base.py --file-id 123
  python scripts/process_knowledge_base.py --include-errors
"""

import argparse
import os
import sys

from rich import print

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.services.knowledge_base_processing_service import KnowledgeBaseProcessingService


MAX_FILES_PER_EXECUTION = 5


def parse_args():
    parser = argparse.ArgumentParser(description="Processa arquivos pendentes da base de conhecimento")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=MAX_FILES_PER_EXECUTION,
        help=f"Quantidade máxima de itens por execução (máximo {MAX_FILES_PER_EXECUTION})",
    )
    parser.add_argument("--file-id", type=int, help="Processa apenas o arquivo com esse ID")
    parser.add_argument(
        "--include-errors",
        action="store_true",
        help="Inclui também arquivos com status error (além de pending)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    service = KnowledgeBaseProcessingService(
        flask_app=app,
        max_files_per_execution=MAX_FILES_PER_EXECUTION,
    )
    total = service.process_pending_knowledge_files(
        batch_size=args.batch_size,
        file_id=args.file_id,
        include_errors=args.include_errors,
    )
    print(f"Total processado: {total}")
