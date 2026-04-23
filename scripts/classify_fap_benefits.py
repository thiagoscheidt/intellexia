"""
Classifica tópicos de contestação FAP para benefícios da tabela central.

Uso:
  uv run python scripts/classify_fap_benefits.py
  uv run python scripts/classify_fap_benefits.py --batch-size 100
  uv run python scripts/classify_fap_benefits.py --law-firm-id 1
  uv run python scripts/classify_fap_benefits.py --benefit-id 123
  uv run python scripts/classify_fap_benefits.py --force-reclassify
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
        description='Classifica tópicos de contestação FAP para benefícios'
    )
    parser.add_argument('--batch-size', type=int, default=200, help='Quantidade para commit por lote')
    parser.add_argument('--law-firm-id', type=int, help='Filtra por escritório específico')
    parser.add_argument('--benefit-id', type=int, help='Classifica apenas um benefício específico')
    parser.add_argument(
        '--force-reclassify',
        action='store_true',
        help='Reclassifica também benefícios que já possuem tópico salvo',
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    service = FapContestationJudgmentReportService(flask_app=app)

    result = service.classify_benefits_contestation_topics(
        batch_size=args.batch_size,
        benefit_id=args.benefit_id,
        law_firm_id=args.law_firm_id,
        force_reclassify=args.force_reclassify,
    )

    print(
        'Resultado: '
        f"total={result['total']} "
        f"classificados={result['classified']} "
        f"atualizados={result['updated']} "
        f"erros={result['errors']}"
    )
