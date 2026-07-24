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

Modos de execução:
  - Diário (padrão): incremental pela marca d'água de cada advogado — pega as
    comunicações do dia e reprocessa uma margem de segurança. É o modo do cron.
  - FULL (--full): ignora a marca d'água e busca o histórico completo de todos
    os advogados desde o início do DJEN (2023; customizável com --desde).
    Percorre o período em janelas de 90 dias com commit por janela — pode ser
    interrompido e rodado de novo (dedup por hash), inclusive para repopular a
    base do zero.

Explicação IA: nos modos incremental e --caderno, cada comunicação nova com
teor ganha automaticamente a explicação da IA (a mesma do botão "Explicar com
IA" da tela), até 100 por escritório por execução; use --sem-ia para desligar.
O modo --full nunca explica (carga histórica = custo alto); o backlog fica
para o botão da tela.

Execução manual:
  uv run python scripts/sync_process_communications.py
  uv run python scripts/sync_process_communications.py --dry-run
  uv run python scripts/sync_process_communications.py --law-firm-id 1
  uv run python scripts/sync_process_communications.py --full
  uv run python scripts/sync_process_communications.py --full --desde 2024-01-01

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
import logging
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # type: ignore[import]
load_dotenv(project_root / '.env')


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _explain_new(monitor, firm_id, since) -> None:
    """Explicação IA das comunicações criadas na rodada (pós-commit do sync)."""
    try:
        stats = monitor.explain_new_communications(firm_id, since=since)
    except Exception as exc:  # IA nunca derruba o sync
        _log(f"🤖 escritório {firm_id} · explicação IA falhou: {exc}")
        return
    if stats['explained'] or stats['failed'] or stats['pending']:
        msg = (f"🤖 escritório {firm_id} · {stats['explained']} explicada(s), "
               f"{stats['failed']} falha(s)")
        if stats['pending']:
            msg += (f" · {stats['pending']} além do teto ficaram para o botão "
                    f"\"Explicar com IA\" da tela")
        _log(msg)


def _run_caderno(monitor, args, run_start) -> int:
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
        if not (args.dry_run or args.sem_ia):
            _explain_new(monitor, firm_id, run_start)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Sincroniza comunicações do Comunica PJe (DJEN).')
    parser.add_argument('--dry-run', action='store_true',
                        help='consulta a API e mostra o que seria salvo, sem persistir')
    parser.add_argument('--law-firm-id', type=int, default=None,
                        help='restringe a um escritório')
    parser.add_argument('--full', action='store_true',
                        help='histórico completo (ignora a marca d\'água); '
                             'padrão: incremental diário')
    parser.add_argument('--desde', type=str, default=None,
                        help='data inicial do modo FULL (YYYY-MM-DD; '
                             'padrão: 2023-01-01, início do DJEN)')
    parser.add_argument('--caderno', action='store_true',
                        help='sincroniza via cadernos diários (1 download por tribunal)')
    parser.add_argument('--data', type=str, default=None,
                        help='data do caderno (YYYY-MM-DD; padrão: hoje) — só com --caderno')
    parser.add_argument('--tribunais', type=str, default=None,
                        help='siglas separadas por vírgula (padrão: tribunais do histórico) — só com --caderno')
    parser.add_argument('--sem-ia', dest='sem_ia', action='store_true',
                        help='não gera a explicação IA das comunicações novas '
                             '(padrão: gera nos modos incremental e --caderno)')
    args = parser.parse_args()

    # Execução manual (terminal): mostra em tempo real o que o serviço e o
    # client estão fazendo (processos descobertos, pausas de rate limit,
    # retries). No cron (sem TTY) nada muda — o log continua só com o resumo.
    if sys.stdout.isatty():
        logging.basicConfig(
            level=logging.INFO,
            format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S')

    from main import app
    from app.services import communication_monitor_service as monitor

    if args.caderno and args.full:
        _log('❌ --full não se aplica ao modo --caderno (cadernos são diários).')
        return 1
    if args.desde and not args.full:
        _log('❌ --desde só faz sentido com --full.')
        return 1

    full_from = None
    if args.full:
        from datetime import date as date_cls
        if args.desde:
            try:
                full_from = date_cls.fromisoformat(args.desde)
            except ValueError:
                _log(f'❌ Data inválida: {args.desde} (use YYYY-MM-DD)')
                return 1
        else:
            full_from = monitor.FULL_SYNC_START

    with app.app_context():
        run_start = datetime.now()
        if args.caderno:
            return _run_caderno(monitor, args, run_start)
        modo = f'FULL desde {full_from.isoformat()}' if full_from else 'incremental diário'
        _log(f'🔎 Iniciando sincronização de comunicações (Comunica PJe/DJEN) — modo {modo}...')
        summaries = monitor.sync_all(law_firm_id=args.law_firm_id,
                                     dry_run=args.dry_run, full_from=full_from)

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

        if not (args.dry_run or full_from or args.sem_ia):
            for summary in summaries:
                _explain_new(monitor, summary['law_firm_id'], run_start)

        return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
