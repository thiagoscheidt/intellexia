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

from app.utils.database_config import existe_na_fila, load_env_file


DEFAULT_BATCH_SIZE = 5

# Mesma condição de KnowledgeBaseProcessingService._build_query, em SQL puro,
# para saber se há o que fazer antes de carregar a aplicação (ver
# app/utils/database_config.py). Mudou lá, muda aqui.
SQL_HA_PENDENTES = """
    SELECT 1 FROM knowledge_base kb
    WHERE kb.is_active = :ativo
      AND kb.processing_status IN :statuses
      AND kb.id NOT IN (
          SELECT jd.knowledge_base_id FROM judicial_documents jd
          WHERE jd.knowledge_base_id IS NOT NULL
      )
    LIMIT 1
"""


def parse_args():
    parser = argparse.ArgumentParser(description="Processa arquivos pendentes da base de conhecimento")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Quantidade de itens por execução (padrão: {DEFAULT_BATCH_SIZE})",
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

    if not args.file_id:
        load_env_file(os.path.join(PROJECT_ROOT, ".env"))
        statuses = ["pending", "error"] if args.include_errors else ["pending"]
        if not existe_na_fila(SQL_HA_PENDENTES, ativo=True, statuses=statuses):
            print("Nenhum arquivo pendente encontrado.")
            print("Total processado: 0")
            sys.exit(0)

    from main import app
    from app.services.knowledge_base_processing_service import KnowledgeBaseProcessingService

    service = KnowledgeBaseProcessingService(
        flask_app=app,
        max_files_per_execution=max(1, args.batch_size),
    )
    total = service.process_pending_knowledge_files(
        batch_size=args.batch_size,
        file_id=args.file_id,
        include_errors=args.include_errors,
    )
    print(f"Total processado: {total}")
