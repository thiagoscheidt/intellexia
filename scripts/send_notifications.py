#!/usr/bin/env python3
"""
Envio das notificações por e-mail agendadas — script para rodar via cron.

Roda de hora em hora e envia o que está no horário configurado em
Configurações → Notificações (por escritório). Hoje há um tipo: Resumo FAP.

Regras (ver app/services/notification_service.py):
  - sem novidades no período → não envia e-mail, apenas avança a janela;
  - falha de envio → não avança a janela; a próxima execução tenta de novo.

Variáveis de ambiente (.env):
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL, SMTP_FROM_NAME
  APP_PUBLIC_URL — base dos links do e-mail (padrão: https://rs-dev.intellexia.com.br)

Execução manual:
  uv run python scripts/send_notifications.py
  uv run python scripts/send_notifications.py --dry-run
  uv run python scripts/send_notifications.py --law-firm-id 1 --force

Cron sugerido (de hora em hora):
  0 * * * * cd /sites/intellexia && flock -n /tmp/intellexia_notifications.lock \
      uv run python scripts/send_notifications.py >> /var/log/intellexia/send_notifications.log 2>&1
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Garante que o projeto raiz esteja no path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Carrega .env antes de importar o app
from dotenv import load_dotenv  # type: ignore[import]
load_dotenv(project_root / '.env')


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description='Envia as notificações agendadas por e-mail.')
    parser.add_argument('--dry-run', action='store_true',
                        help='monta os e-mails e mostra o que seria enviado, sem enviar')
    parser.add_argument('--law-firm-id', type=int, default=None,
                        help='restringe a um escritório')
    parser.add_argument('--force', action='store_true',
                        help='ignora o horário e envia o Resumo FAP agora (exige --law-firm-id)')
    args = parser.parse_args()

    from main import app
    from app.services import email_service, notification_service

    with app.app_context():
        # O dry-run só monta os e-mails, então roda mesmo sem SMTP.
        if not email_service.is_configured() and not args.dry_run:
            _log('⚠️  SMTP não configurado (SMTP_HOST/SMTP_FROM_EMAIL no .env). Nada a fazer.')
            return 1

        if args.force:
            if not args.law_firm_id:
                _log('❌ --force exige --law-firm-id.')
                return 2
            _log(f'🚀 Envio forçado do Resumo FAP — escritório {args.law_firm_id}')
            results = [notification_service.send_fap_digest(
                args.law_firm_id, force=True, dry_run=args.dry_run
            )]
        else:
            results = notification_service.send_due_notifications(
                law_firm_id=args.law_firm_id, dry_run=args.dry_run
            )

        if not results:
            _log('Nenhuma notificação no horário.')
            return 0

        failures = 0
        for r in results:
            icon = {'sent': '✅', 'skipped': '⏭️ ', 'dry_run': '🔍', 'failed': '❌'}.get(r['status'], '•')
            firm = r.get('law_firm_id', args.law_firm_id)
            _log(f"{icon} escritório {firm} · {r['status']} · {r['message']}")
            if r['status'] == 'failed':
                failures += 1

        return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
