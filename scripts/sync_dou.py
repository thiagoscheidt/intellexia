#!/usr/bin/env python3
"""
Captura do Diário Oficial da União (INLABS) — cron.

Baixa os ZIPs de XML das seções configuradas (padrão: DO1 DO2 DO3 DO1E DO2E
DO3E) e os PDFs assinados, quebra o XML matéria a matéria e persiste.

Regras (ver app/services/dou_ingestion_service.py):
  - HTTP 404 é estado normal ("não publicado"), não erro;
  - o INLABS reescreve datas passadas, então toda execução reconfere a janela
    dos últimos DOU_RECHECK_DAYS dias (padrão 7) comparando o SHA-256 do ZIP;
  - falha de uma (data, seção) marca a edição como 'error' e a próxima execução
    tenta de novo — falha nunca é registrada como sucesso.

Modos de execução:
  - Diário (padrão): hoje + janela de reverificação. É o modo do cron.
  - Data única (--data): reprocessa uma data específica.
  - BACKFILL (--backfill --desde): resgate histórico. O INLABS mantém uma janela
    móvel de ~4 meses; o que não for capturado agora se perde. Commit por dia,
    interrompível e retomável (dedup por chave da matéria).
  - Poda (--purge-pdfs): remove PDFs além da retenção. XML e texto nunca são
    podados.

Execução manual:
  uv run python scripts/sync_dou.py
  uv run python scripts/sync_dou.py --dry-run
  uv run python scripts/sync_dou.py --data 2026-08-10
  uv run python scripts/sync_dou.py --secoes DO1,DO3
  uv run python scripts/sync_dou.py --sem-pdf
  uv run python scripts/sync_dou.py --backfill --desde 2026-04-13
  uv run python scripts/sync_dou.py --purge-pdfs

Cron sugerido (3x/dia: a edição normal sai de manhã, as extras a qualquer hora):
  0 7,12,19 * * * cd /sites/intellexia && flock -n /tmp/intellexia_dou.lock \
      uv run python scripts/sync_dou.py >> /var/log/intellexia/sync_dou.log 2>&1
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # type: ignore[import]
load_dotenv(project_root / '.env')


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _parse_data(valor: str) -> date:
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        raise argparse.ArgumentTypeError(f'data inválida: {valor} (use YYYY-MM-DD)')


def _resumir(run) -> None:
    _log(
        f"📊 {run.modo}: {run.edicoes_baixadas} edição(ões) baixada(s), "
        f"{run.materias_inseridas} matéria(s) nova(s), "
        f"{run.materias_atualizadas} atualizada(s), "
        f"{run.nao_publicados} não publicada(s), {run.erros} erro(s) "
        f"— status {run.status}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Captura do Diário Oficial da União (INLABS)')
    parser.add_argument('--data', type=_parse_data, help='reprocessa uma data específica (YYYY-MM-DD)')
    parser.add_argument('--backfill', action='store_true', help='resgate histórico (exige --desde)')
    parser.add_argument('--desde', type=_parse_data, help='data inicial do backfill (YYYY-MM-DD)')
    parser.add_argument('--ate', type=_parse_data, help='data final do backfill (padrão: hoje)')
    parser.add_argument('--secoes', help='subconjunto de seções, ex.: DO1,DO3')
    parser.add_argument('--sem-pdf', action='store_true', help='baixa só o XML')
    parser.add_argument('--purge-pdfs', action='store_true', help='poda PDFs além da retenção e sai')
    parser.add_argument('--dry-run', action='store_true', help='não grava nada')
    args = parser.parse_args()

    # Erro de argumento é reportado antes de qualquer checagem de ambiente:
    # quem digitou o comando errado precisa ver o erro real, não "credenciais
    # ausentes".
    if args.backfill and not args.desde:
        _log('❌ --backfill exige --desde YYYY-MM-DD')
        return 2

    if args.secoes:
        os.environ['DOU_SECOES'] = args.secoes

    from main import app
    from app.services import dou_ingestion_service as ingestion
    from app.services import inlabs_client

    with app.app_context():
        if args.purge_pdfs:
            podados = ingestion.purge_old_pdfs()
            _log(f'🗑️  {podados} PDF(s) podado(s)')
            return 0

        if not inlabs_client.is_configured():
            _log('⚠️  INLABS_EMAIL/INLABS_PASSWORD ausentes no .env — nada a fazer')
            return 0

        with_pdf = not args.sem_pdf

        if args.backfill:
            _log(f'⏳ Backfill de {args.desde} até {args.ate or date.today()}...')
            run = ingestion.backfill(args.desde, args.ate, with_pdf=with_pdf, dry_run=args.dry_run)
        elif args.data:
            _log(f'⏳ Reprocessando {args.data}...')
            run = ingestion.ingest_single_date(args.data, with_pdf=with_pdf, dry_run=args.dry_run)
        else:
            _log('⏳ Captura diária (hoje + janela de reverificação)...')
            run = ingestion.sync_recent(with_pdf=with_pdf, dry_run=args.dry_run)

        _resumir(run)
        return 0 if run.status != 'error' else 1


if __name__ == '__main__':
    sys.exit(main())
