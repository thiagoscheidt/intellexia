#!/usr/bin/env python3
"""
Smoke test do ComunicaPjeClient contra a API real do Comunica PJe (DJEN).

Valida na prática os parâmetros aceitos pelo endpoint /comunicacao e o parse
dos itens. Rode manualmente (faz requisições reais, sujeitas a rate limit):

    uv run python scripts/tests/test_comunica_pje_client.py
    uv run python scripts/tests/test_comunica_pje_client.py --oab 53004 --uf SC
    uv run python scripts/tests/test_comunica_pje_client.py --processo 50011815620234036100
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from app.services.comunica_pje_client import ComunicaPjeClient, ComunicaPjeError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--oab', default='53004')
    parser.add_argument('--uf', default='SC')
    parser.add_argument('--processo', default=None)
    args = parser.parse_args()

    client = ComunicaPjeClient()

    try:
        if args.processo:
            print(f'🔎 Consultando processo {args.processo}...')
            items = client.get_comunicacoes_processo(args.processo)
            print(f'✅ {len(items)} comunicação(ões) no histórico do processo.')
        else:
            hoje = date.today()
            print(f'🔎 Consultando OAB {args.oab}/{args.uf} '
                  f'({hoje - timedelta(days=30)} a {hoje})...')
            payload = client.get_comunicacoes(
                numero_oab=args.oab, uf_oab=args.uf,
                data_inicio=hoje - timedelta(days=30), data_fim=hoje,
                itens_por_pagina=5,
            )
            items = client._extract_items(payload)
            if isinstance(payload, dict) and 'count' in payload:
                print(f"ℹ️  count informado pela API: {payload['count']}")
            print(f'✅ {len(items)} item(ns) na primeira página.')
    except ComunicaPjeError as exc:
        print(f'❌ Erro na API: {exc}')
        return 1

    if not items:
        print('⚠️  Nenhum item retornado — teste inconclusivo (OAB sem comunicações no período?).')
        return 0

    parsed = client.parse_comunicacao(items[0])
    print('\n📋 Primeiro item parseado:')
    for key, value in parsed.items():
        display = str(value)
        if len(display) > 100:
            display = display[:100] + '…'
        print(f'  {key}: {display}')

    obrigatorios = ['hash', 'sigla_tribunal', 'data_disponibilizacao']
    faltando = [k for k in obrigatorios if not parsed.get(k)]
    if faltando:
        print(f'\n❌ Campos essenciais ausentes no parse: {faltando}')
        return 1

    print('\n✅ Parse OK — campos essenciais presentes.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
