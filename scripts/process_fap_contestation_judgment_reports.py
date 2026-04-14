"""
Processador de Relatórios de Julgamento de Contestação do FAP (pendentes).

Uso:
  uv run python scripts/process_fap_contestation_judgment_reports.py
  uv run python scripts/process_fap_contestation_judgment_reports.py --batch-size 20
  uv run python scripts/process_fap_contestation_judgment_reports.py --report-id 123
  uv run python scripts/process_fap_contestation_judgment_reports.py --include-errors

Nota: processamento real ainda não implementado; este script chama o service placeholder.
"""

import argparse
import os
import sys

from rich import print

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.services.fap_contestation_judgment_report_service import FapContestationJudgmentReportService


def parse_args():
    parser = argparse.ArgumentParser(
        description='Processa relatórios pendentes de julgamento de contestação do FAP'
    )
    parser.add_argument('--batch-size', type=int, default=100, help='Quantidade máxima por execução')
    parser.add_argument('--report-id', type=int, help='ID específico do relatório para processar')
    parser.add_argument(
        '--include-errors',
        action='store_true',
        help='Inclui também relatórios com status error (além de pending)'
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    service = FapContestationJudgmentReportService(flask_app=app)
    total = service.process_pending_reports(
        batch_size=args.batch_size,
        report_id=args.report_id,
        include_errors=args.include_errors,
    )
    print(f'Total processado: {total}')
