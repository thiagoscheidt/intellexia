#!/usr/bin/env python3
"""
Reindexa o acervo do DOU no Meilisearch.

O índice é descartável: o MySQL é a fonte da verdade. Use este script na carga
inicial, depois de um backfill, ou se o índice for perdido.

    uv run python scripts/reindex_dou.py
    uv run python scripts/reindex_dou.py --desde 2026-08-01
    uv run python scripts/reindex_dou.py --recriar     # apaga o índice antes
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # type: ignore[import]
load_dotenv(project_root / '.env')


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _parse_data(valor: str):
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        raise argparse.ArgumentTypeError(f'data inválida: {valor} (use YYYY-MM-DD)')


def main() -> int:
    parser = argparse.ArgumentParser(description='Reindexa o acervo do DOU')
    parser.add_argument('--desde', type=_parse_data, help='só a partir desta data')
    parser.add_argument('--recriar', action='store_true',
                        help='apaga o índice antes de reconstruir')
    args = parser.parse_args()

    from main import app
    from app.services import dou_search_service as busca

    if not busca.is_available():
        _log('⚠️  Meilisearch não responde — nada a fazer')
        return 1

    if args.recriar:
        _log(f'🗑️  removendo o índice {busca.MEILI_INDEX}...')
        busca.drop_index(busca.MEILI_INDEX)

    with app.app_context():
        _log('⏳ reindexando...')
        total = busca.reindex_all(desde=args.desde)

    _log('⏳ aguardando o Meilisearch processar a fila...')
    busca.aguardar_indexacao()
    _log(f'✅ {total} matéria(s) indexada(s)')

    return 0


if __name__ == '__main__':
    sys.exit(main())
