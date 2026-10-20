#!/usr/bin/env python3
"""
Sincroniza a Consulta do FAP do portal: benefícios e CATs de cada cálculo, de
todas as vigências, empresas e estabelecimentos, para ``fap_calculo_itens``.

Só leitura no portal (GETs); grava nas tabelas ``fap_calculo_*``. Retomável:
``--somente-novos`` pula o que já foi gravado. Ao fim completa a Central
(CPF, nascimento, RMI, total pago) salvo ``--sem-completar``.

Uso:
  uv run python scripts/fap_calculo_sync.py --somente-novos                 # carga inicial
  uv run python scripts/fap_calculo_sync.py --vigencia 2026 --empresa 07718633 --sem-completar
  uv run python scripts/fap_calculo_sync.py --estabelecimento 07718633008163

Variáveis (.env):
  FAP_AUTH_JSON               — sessão do portal
  FAP_SYNC_LAW_FIRM_ID        — escritório (ou --escritorio)
  FAP_CALCULO_SYNC_WORKERS    — consultas em paralelo (padrão 8, máx 20)

Códigos de saída: 0 ok, 1 erro de configuração, 2 sessão FAP expirada.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # carrega o .env

EXIT_OK, EXIT_ERRO, EXIT_EXPIRADA = 0, 1, 2
WORKERS_PADRAO, WORKERS_MAX = 8, 20


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _workers(valor: int | None) -> int:
    if valor:
        return max(1, min(valor, WORKERS_MAX))
    bruto = os.environ.get('FAP_CALCULO_SYNC_WORKERS', '').strip()
    try:
        return max(1, min(int(bruto), WORKERS_MAX)) if bruto else WORKERS_PADRAO
    except ValueError:
        _log(f"AVISO: FAP_CALCULO_SYNC_WORKERS inválido ('{bruto}'). Usando {WORKERS_PADRAO}.")
        return WORKERS_PADRAO


def main(argv=None, svc=None) -> int:
    ap = argparse.ArgumentParser(description='Sincroniza benefícios e CATs dos cálculos do FAP.')
    ap.add_argument('--vigencia', type=int, action='append', default=[], help='ano (repetível)')
    ap.add_argument('--empresa', action='append', default=[], help='CNPJ raiz, 8 dígitos (repetível)')
    ap.add_argument('--estabelecimento', action='append', default=[], help='CNPJ de 14 dígitos (repetível)')
    ap.add_argument('--somente-novos', action='store_true', help='pula estabelecimentos já gravados')
    ap.add_argument('--sem-completar', action='store_true', help='não completa a Central ao fim')
    ap.add_argument('--escritorio', type=int, default=None, help='law_firm_id (padrão: FAP_SYNC_LAW_FIRM_ID)')
    ap.add_argument('--workers', type=int, default=None, help='consultas em paralelo (padrão 8, máx 20)')
    args = ap.parse_args(argv)

    law_firm_id = args.escritorio or int(os.environ.get('FAP_SYNC_LAW_FIRM_ID') or 0)
    if not law_firm_id:
        _log('ERRO: informe --escritorio ou FAP_SYNC_LAW_FIRM_ID no .env.')
        return EXIT_ERRO

    if svc is None:
        from app.services.fap_web_service import FapWebAuthPayload, FapWebService
        try:
            auth = FapWebAuthPayload.from_env()
        except Exception as e:
            _log(f'ERRO: FAP_AUTH_JSON inválido: {e}')
            return EXIT_ERRO
        if auth is None or not auth.cookies:
            _log('ERRO: FAP_AUTH_JSON ausente ou sem cookies no .env.')
            return EXIT_ERRO
        svc = FapWebService(auth)

    from app.services.fap_calculo_sync_service import completar_central, sincronizar

    workers = _workers(args.workers)
    t0 = time.time()
    with app.app_context():
        _log(f'Sincronizando com {workers} consulta(s) em paralelo'
             f'{" (somente novos)" if args.somente_novos else ""}…')
        r = sincronizar(law_firm_id, svc, anos=args.vigencia or None, raizes=args.empresa or None,
                        cnpjs=args.estabelecimento or None, workers=workers,
                        somente_novos=args.somente_novos, log=_log)
        _log('Resumo:')
        for k in ('estabelecimentos', 'com_itens', 'itens_novos', 'itens_atualizados', 'sem_acesso', 'erros'):
            _log(f'  {k}: {r[k]}')
        _log(f'  tempo: {time.time() - t0:.0f}s')
        if r['expirada']:
            _log('ERRO: sessão FAP expirada no meio. Faça login, atualize o FAP_AUTH_JSON e rode de novo '
                 'com --somente-novos (o que já foi gravado fica).')
            return EXIT_EXPIRADA
        if not args.sem_completar:
            _log(f'Central completada: {completar_central(law_firm_id)}')
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
