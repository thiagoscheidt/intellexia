#!/usr/bin/env python3
"""Retoma a fila de PDFs da Base de Jurisprudência.

A leitura roda em thread do processo web; um restart/deploy no meio mata a
thread e deixa o arquivo "na fila" ou "lendo" para sempre. Este script lê o
que ficou para trás: tudo que está na fila e o que está "lendo" há mais de
TRAVADA_MINUTOS. Seguro para cron (não relê o que já terminou).

    uv run python scripts/process_jurisprudence_uploads.py
    uv run python scripts/process_jurisprudence_uploads.py --limite 10
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402
from app.models import db, JurisprudenceUpload  # noqa: E402
from app.services import jurisprudence_upload_service as envios  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--limite', type=int, default=30, help='máximo de arquivos por execução')
    args = parser.parse_args()

    with app.app_context():
        corte = datetime.now() - timedelta(minutes=envios.TRAVADA_MINUTOS)
        pendentes = (JurisprudenceUpload.query
                     .filter(db.or_(JurisprudenceUpload.status == JurisprudenceUpload.STATUS_QUEUED,
                                    db.and_(JurisprudenceUpload.status == JurisprudenceUpload.STATUS_PROCESSING,
                                            JurisprudenceUpload.started_at < corte)))
                     .order_by(JurisprudenceUpload.id).limit(args.limite).all())
        if not pendentes:
            print('Nada na fila.')
            return 0
        falhas = 0
        for upload in pendentes:
            law_firm_id, upload_id = upload.law_firm_id, upload.id
            if upload.status == JurisprudenceUpload.STATUS_PROCESSING:
                upload.status = JurisprudenceUpload.STATUS_QUEUED    # travada: volta para a fila
                db.session.commit()
            try:
                resultado = envios.processar(law_firm_id, upload_id)
                print(f'✓ {upload_id} {resultado.original_filename}: {resultado.status}'
                      + (f' — {resultado.error_message}' if resultado.error_message else ''))
                falhas += resultado.status == JurisprudenceUpload.STATUS_FAILED
            except Exception as erro:
                db.session.rollback()
                falhas += 1
                print(f'✗ {upload_id}: {erro}')
        print(f'\n{len(pendentes)} arquivo(s) processado(s), {falhas} com falha.')
        return 1 if falhas else 0


if __name__ == '__main__':
    sys.exit(main())
