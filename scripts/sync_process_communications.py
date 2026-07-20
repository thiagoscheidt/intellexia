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


def main() -> int:
    parser = argparse.ArgumentParser(description='Sincroniza comunicações do Comunica PJe (DJEN).')
    parser.add_argument('--dry-run', action='store_true',
                        help='consulta a API e mostra o que seria salvo, sem persistir')
    parser.add_argument('--law-firm-id', type=int, default=None,
                        help='restringe a um escritório')
    args = parser.parse_args()

    from main import app
    from app.services import communication_monitor_service as monitor

    with app.app_context():
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
