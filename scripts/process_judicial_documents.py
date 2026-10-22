"""
Processador de documentos judiciais pendentes.

Uso:
  uv run python scripts/process_judicial_documents.py
  uv run python scripts/process_judicial_documents.py --batch-size 20
  uv run python scripts/process_judicial_documents.py --document-id 123
  uv run python scripts/process_judicial_documents.py --include-errors
"""

import argparse
import os
import sys

from rich import print

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.utils.database_config import existe_na_fila, load_env_file


MAX_DOCUMENTS_PER_EXECUTION = 5

# Mesma condição de JudicialDocumentService._build_query, em SQL puro, para
# saber se há o que fazer antes de carregar a aplicação (ver
# app/utils/database_config.py). Mudou lá, muda aqui.
SQL_HA_PENDENTES = """
    SELECT 1 FROM judicial_documents WHERE status IN :statuses LIMIT 1
"""


def parse_args():
    parser = argparse.ArgumentParser(description="Processa documentos judiciais pendentes")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=MAX_DOCUMENTS_PER_EXECUTION,
        help=f"Quantidade máxima de itens por execução (máximo {MAX_DOCUMENTS_PER_EXECUTION})",
    )
    parser.add_argument("--document-id", type=int, help="Processa apenas o documento com esse ID")
    parser.add_argument(
        "--include-errors",
        action="store_true",
        help="Inclui também documentos com status error (além de pending)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if not args.document_id:
        load_env_file(os.path.join(PROJECT_ROOT, ".env"))
        statuses = ["pending", "error"] if args.include_errors else ["pending"]
        if not existe_na_fila(SQL_HA_PENDENTES, statuses=statuses):
            print("Nenhum documento pendente encontrado.")
            print("Total processado: 0")
            sys.exit(0)

    from main import app
    from app.services.judicial_document_service import JudicialDocumentService

    service = JudicialDocumentService(
        flask_app=app,
        max_documents_per_execution=MAX_DOCUMENTS_PER_EXECUTION,
    )
    total = service.process_pending_documents(
        batch_size=args.batch_size,
        document_id=args.document_id,
        include_errors=args.include_errors,
    )
    print(f"Total processado: {total}")