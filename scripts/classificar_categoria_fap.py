#!/usr/bin/env python3
"""
Classifica a Categoria FAP dos benefícios pela justificativa da empresa (E04 da R09).

Uma chamada ao classificador por **justificativa distinta**, não por decisão:
na homologação são 30.905 textos para 64.628 benefícios (~US$ 84 com
gpt-5.4-mini), contra 119.906 decisões (~US$ 326) do caminho antigo
(scripts/classify_fap_benefits.py). O texto é a justificativa da 1ª instância,
a da 2ª só se não houver a da 1ª; o parecer do analista nunca é usado. Mesmo
classificador, prompt e referência do escritório.

**Só simula por padrão** — classifica e mostra, sem gravar. Para conferir antes:
  uv run python scripts/classificar_categoria_fap.py --limite 50

Para gravar (pula quem já tem categoria; rodar de novo só faz o que faltou):
  uv run python scripts/classificar_categoria_fap.py --aplicar --workers 5

Opções: --forcar (reclassifica quem já tem categoria), --escritorio N
(padrão FAP_SYNC_LAW_FIRM_ID). A amostra dos resultados (texto + categoria) vai
para instance/categoria_fap_amostra.json — dado de cliente, não compartilhe.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # carrega o .env


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Classifica a Categoria FAP pela justificativa (simula por padrão).')
    ap.add_argument('--aplicar', action='store_true', help='grava a categoria nos benefícios')
    ap.add_argument('--forcar', action='store_true', help='inclui benefícios que já têm categoria')
    ap.add_argument('--limite', type=int, default=None, help='classifica só os N primeiros textos distintos')
    ap.add_argument('--workers', type=int, default=5, help='chamadas em paralelo (padrão 5)')
    ap.add_argument('--escritorio', type=int, default=None, help='law_firm_id (padrão: FAP_SYNC_LAW_FIRM_ID)')
    args = ap.parse_args(argv)

    law_firm_id = args.escritorio or int(os.environ.get('FAP_SYNC_LAW_FIRM_ID') or 0)
    if not law_firm_id:
        print('ERRO: informe --escritorio ou FAP_SYNC_LAW_FIRM_ID no .env.')
        return 1

    from app.services.fap_contestation_judgment_report_service import FapContestationJudgmentReportService

    t0 = time.time()
    r = FapContestationJudgmentReportService(app).classify_benefits_by_justification(
        law_firm_id, aplicar=args.aplicar, forcar=args.forcar,
        parallel_workers=max(1, min(args.workers, 20)), limite_textos=args.limite)

    print(f"\nTextos classificados: {r['classificados']}/{r['textos']} (de {r['textos_total']} distintos) · "
          f"erros: {r['erros']} · {time.time() - t0:.0f}s")
    print('Categoria principal, por benefício:')
    for categoria, n in r['por_categoria'].items():
        print(f'  {n:>7}  {categoria}')
    if args.aplicar:
        print(f"Benefícios gravados: {r['gravados']}")
    else:
        print('SIMULAÇÃO — nada foi gravado. Use --aplicar para gravar.')

    destino = Path(app.root_path) / 'instance' / 'categoria_fap_amostra.json'
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(r['amostra'], ensure_ascii=False, indent=1))
    print(f'Amostra (texto + categoria) em {destino}')
    return 1 if r['erros'] and not r['classificados'] else 0


if __name__ == '__main__':
    sys.exit(main())
