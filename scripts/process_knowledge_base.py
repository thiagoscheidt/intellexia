"""
Processador de arquivos da Base de Conhecimento (pendentes).

Uso:
  python scripts/process_knowledge_base.py
  python scripts/process_knowledge_base.py --batch-size 20
  python scripts/process_knowledge_base.py --file-id 123
  python scripts/process_knowledge_base.py --include-errors
"""

import argparse
import builtins
import os
import sys
from datetime import datetime
from pathlib import Path

from rich import print

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.models import db, KnowledgeBase, KnowledgeSummary
from app.agents.knowledge_ingestion_agent import KnowledgeIngestionAgent
from app.agents.agent_document_summary import AgentDocumentSummary


def _build_query(file_id: int | None = None, include_errors: bool = False):
    """Monta a query base para itens pendentes (ou um item específico)."""
    statuses = ['pending']
    if include_errors:
        statuses.append('error')

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


def process_pending_knowledge_files(
    batch_size: int = 10,
    file_id: int | None = None,
    include_errors: bool = False,
) -> int:
    """Processa arquivos pendentes da base de conhecimento."""
    query = _build_query(file_id=file_id, include_errors=include_errors)

    if file_id:
        items = query.all()
    else:
        items = query.limit(batch_size).all()

    print(f"Itens elegíveis para processamento: {len(items)}")

    if not items:
        if file_id:
            print(f"Nenhum arquivo elegível encontrado para o ID {file_id}.")
        else:
            print("Nenhum arquivo pendente encontrado.")
        return 0

    ingestion_agent = KnowledgeIngestionAgent()
    summary_agent = AgentDocumentSummary()
    processed = 0

    for item in items:
        try:
            print(f"Iniciando processamento: {item.id} - {item.original_filename}")

            item.processing_status = 'processing'
            item.processing_error_message = None
            db.session.commit()

            file_path = Path(item.file_path)
            if not file_path.exists():
                raise FileNotFoundError(f"Arquivo não encontrado no caminho: {item.file_path}")

            markdown_content = ingestion_agent.process_file(
                file_path=file_path,
                source_name=item.original_filename,
                category=item.category,
                description=item.description,
                tags=item.tags,
                lawsuit_number=item.lawsuit_number,
                file_id=item.id,
            )

            if not markdown_content:
                raise RuntimeError("Processamento não retornou conteúdo.")

            summary_payload = summary_agent.summarizeDocument(file_path=item.file_path)

            if not summary_payload:
                raise RuntimeError("Geração de resumo não retornou conteúdo.")

            lawsuit_numbers = []
            if isinstance(summary_payload, dict):
                lawsuit_numbers_raw = summary_payload.get('lawsuit_numbers', [])
                if lawsuit_numbers_raw:
                    if isinstance(lawsuit_numbers_raw, builtins.list):
                        lawsuit_numbers = [
                            str(num).strip()
                            for num in lawsuit_numbers_raw
                            if num and str(num).strip()
                        ]
                    elif isinstance(lawsuit_numbers_raw, str) and lawsuit_numbers_raw.strip():
                        lawsuit_numbers = [lawsuit_numbers_raw.strip()]

                if lawsuit_numbers and (not item.lawsuit_number or item.lawsuit_number.strip() == ''):
                    item.lawsuit_number = ', '.join(lawsuit_numbers)

            existing_summary = KnowledgeSummary.query.filter_by(knowledge_base_id=item.id).first()
            if existing_summary:
                existing_summary.payload = summary_payload
                existing_summary.updated_at = datetime.utcnow()
            else:
                db.session.add(
                    KnowledgeSummary(
                        knowledge_base_id=item.id,
                        payload=summary_payload,
                    )
                )

            item.processing_status = 'completed'
            item.processed_at = datetime.utcnow()
            item.processing_error_message = None
            db.session.commit()

            processed += 1
            print(f"Processado com sucesso: {item.id} - {item.original_filename}")

        except Exception as error:
            db.session.rollback()

            item.processing_status = 'error'
            item.processing_error_message = str(error)
            db.session.commit()

            print(f"Erro ao processar {item.id} - {item.original_filename}: {error}")

    return processed


def parse_args():
    parser = argparse.ArgumentParser(description='Processa arquivos pendentes da base de conhecimento')
    parser.add_argument('--batch-size', type=int, default=10, help='Quantidade máxima de itens por execução')
    parser.add_argument('--file-id', type=int, help='Processa apenas o arquivo com esse ID')
    parser.add_argument(
        '--include-errors',
        action='store_true',
        help='Inclui também arquivos com status error (além de pending)',
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()

    with app.app_context():
        total = process_pending_knowledge_files(
            batch_size=args.batch_size,
            file_id=args.file_id,
            include_errors=args.include_errors,
        )
        print(f"Total processado: {total}")
