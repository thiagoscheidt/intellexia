#!/usr/bin/env python3
"""
Sincronização das comunicações processuais (Comunica PJe / DJEN) — cron diário.

Para cada escritório, busca as comunicações de todos os advogados com OAB + UF
cadastradas, deduplica pelo hash da API e cria automaticamente (flagado como
"descoberto") todo processo ainda não cadastrado no Painel de Processos.

Regras (ver app/services/communication_monitor_service.py):
  - falha de um advogado não avança a marca d'água dele; a próxima execução
    tenta o mesmo período de novo;
  - o DJEN publica uma vez por dia (dias úteis) — rodar mais de 1x/dia não
    traz dado novo.

Execução manual:
  uv run python scripts/sync_process_communications.py
  uv run python scripts/sync_process_communications.py --dry-run
  uv run python scripts/sync_process_communications.py --law-firm-id 1

Modo caderno (alternativo): baixa o caderno diário compactado de cada tribunal
e filtra localmente pelas OABs do escritório — 1 download por tribunal em vez
de 1 consulta por advogado. Tribunais padrão: os do histórico do escritório.
  uv run python scripts/sync_process_communications.py --caderno --law-firm-id 1
  uv run python scripts/sync_process_communications.py --caderno --data 2026-07-17 --tribunais TRF4,TRF3

Cron sugerido (diário, cedo):
  30 6 * * * cd /opt/intellexia && flock -n /tmp/intellexia_comunicacoes.lock \
      uv run python scripts/sync_process_communications.py >> /var/log/intellexia/sync_process_communications.log 2>&1
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


def _run_caderno(monitor, args) -> int:
    """Sincronização via cadernos diários do DJEN."""
    from datetime import date as date_cls

    from app.models import LawFirm

    data = None
    if args.data:
        try:
            data = date_cls.fromisoformat(args.data)
        except ValueError:
            _log(f"❌ Data inválida: {args.data} (use YYYY-MM-DD)")
            return 1
    siglas = [s.strip().upper() for s in (args.tribunais or '').split(',') if s.strip()] or None

    firm_ids = [args.law_firm_id] if args.law_firm_id else [f.id for f in LawFirm.query.order_by(LawFirm.id)]
    _log('📦 Iniciando sincronização por caderno (DJEN)...')
    failures = 0
    for firm_id in firm_ids:
        summary = monitor.sync_law_firm_from_cadernos(
            firm_id, data=data, siglas=siglas, dry_run=args.dry_run)
        if summary.get('status') in ('no_tribunals', 'no_lawyers'):
            _log(f"⏭️  escritório {firm_id}: {summary['status']} — nada a fazer")
            continue
        for r in summary['results']:
            icon = {'ok': '✅', 'dry_run': '🔍', 'failed': '❌', 'skipped': '⏭️ '}.get(r['status'], '•')
            _log(f"{icon} escritório {firm_id} · caderno {r['sigla']} {summary['data']} · "
                 f"{r['scanned']} varrida(s), {r['matched']} do escritório, "
                 f"{r['created']} nova(s), {r['updated']} atualizada(s), "
                 f"{r['processes_created']} processo(s) descoberto(s)"
                 + (f" · {r['error']}" if r['error'] else ''))
            if r['status'] == 'failed':
                failures += 1
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Sincroniza comunicações do Comunica PJe (DJEN).')
    parser.add_argument('--dry-run', action='store_true',
                        help='consulta a API e mostra o que seria salvo, sem persistir')
    parser.add_argument('--law-firm-id', type=int, default=None,
                        help='restringe a um escritório')
    parser.add_argument('--caderno', action='store_true',
                        help='sincroniza via cadernos diários (1 download por tribunal)')
    parser.add_argument('--data', type=str, default=None,
                        help='data do caderno (YYYY-MM-DD; padrão: hoje) — só com --caderno')
    parser.add_argument('--tribunais', type=str, default=None,
                        help='siglas separadas por vírgula (padrão: tribunais do histórico) — só com --caderno')
    args = parser.parse_args()

    from main import app
    from app.services import communication_monitor_service as monitor

    with app.app_context():
        if args.caderno:
            return _run_caderno(monitor, args)
        _log('🔎 Iniciando sincronização de comunicações (Comunica PJe/DJEN)...')
        summaries = monitor.sync_all(law_firm_id=args.law_firm_id, dry_run=args.dry_run)

        if not summaries:
            _log('Nenhum escritório para sincronizar.')
            return 0

        failures = 0
        for summary in summaries:
            firm = summary['law_firm_id']
            for skipped_name in summary['lawyers_skipped']:
                _log(f"⏭️  escritório {firm} · advogado '{skipped_name}' pulado (OAB/UF incompleta)")
            for r in summary['results']:
                icon = {'ok': '✅', 'dry_run': '🔍', 'failed': '❌'}.get(r['status'], '•')
                _log(f"{icon} escritório {firm} · {r['lawyer_name']} · "
                     f"{r['created']} nova(s), {r['updated']} atualizada(s), "
                     f"{r['processes_created']} processo(s) descoberto(s)"
                     + (f" · ERRO: {r['error']}" if r['error'] else ''))
                if r['status'] == 'failed':
                    failures += 1

        return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
