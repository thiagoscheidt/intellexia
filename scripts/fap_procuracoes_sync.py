#!/usr/bin/env python3
"""
Sincronização das procurações eletrônicas do FAP Web — script para rodar via cron.

Só procurações: sem empresas, sem contestações, sem download de PDF. É por isso
que ele existe separado de ``fap_sync_cron.py`` — dá para rodar de poucos em
poucos minutos sem arrastar junto a sincronização pesada das contestações.

Sequência:
  1. Verifica a sessão FAP (expirada → sai com código 2)
  2. Sincroniza as procurações com detecção de mudança campo a campo
  3. Dispara o alerta de procurações (se houver novidade e a notificação estiver ativa)

Variáveis de ambiente (.env):
  FAP_AUTH_JSON        — JSON de autenticação (obrigatório)
                         Formato: { "cookies": { "SESSION": "...", "XSRF-TOKEN": "...", "ROUTEID": "..." },
                                    "userAgent": "Mozilla/5.0 ..." }
  FAP_SYNC_LAW_FIRM_ID — ID do escritório a sincronizar (padrão: primeiro ativo)

Códigos de saída:
  0 — sucesso
  1 — erro (configuração ausente, falha na busca, exceção)
  2 — sessão FAP expirada (atualize FAP_AUTH_JSON no .env)

Execução manual:
  uv run python scripts/fap_procuracoes_sync.py
  uv run python scripts/fap_procuracoes_sync.py --dry-run
  uv run python scripts/fap_procuracoes_sync.py --law-firm-id 1 --no-notify

Cron sugerido (a cada 10 minutos). O flock é obrigatório: em intervalo curto,
duas execuções simultâneas se atropelariam no upsert.
  */10 * * * * cd /sites/intellexia && flock -n /tmp/intellexia_fap_procuracoes.lock \
      uv run python scripts/fap_procuracoes_sync.py >> /var/log/intellexia/fap_procuracoes.log 2>&1
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Garante que o projeto raiz esteja no path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Carrega .env antes de importar o app
from dotenv import load_dotenv  # type: ignore[import]
load_dotenv(project_root / '.env')

EXIT_OK = 0
EXIT_ERRO = 1
EXIT_SESSAO_EXPIRADA = 2


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _resolve_law_firm_id(arg_id: int | None) -> int:
    from app.models import LawFirm

    if arg_id:
        return arg_id

    raw = os.environ.get('FAP_SYNC_LAW_FIRM_ID', '').strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            _log(f"AVISO: FAP_SYNC_LAW_FIRM_ID inválido ('{raw}'). Usando o primeiro escritório ativo.")

    firm = LawFirm.query.filter_by(is_active=True).order_by(LawFirm.id).first()
    if not firm:
        raise RuntimeError('Nenhum escritório ativo encontrado no banco.')
    return firm.id


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Sincroniza as procurações eletrônicas do FAP Web.'
    )
    parser.add_argument('--law-firm-id', type=int, default=None,
                        help='escritório a sincronizar (padrão: FAP_SYNC_LAW_FIRM_ID ou o primeiro ativo)')
    parser.add_argument('--dry-run', action='store_true',
                        help='mostra o que seria enviado por e-mail, sem enviar (a sincronização é feita)')
    parser.add_argument('--no-notify', action='store_true',
                        help='sincroniza sem disparar o alerta por e-mail')
    args = parser.parse_args()

    auth_json = os.environ.get('FAP_AUTH_JSON', '').strip()
    if not auth_json:
        _log('ERRO: FAP_AUTH_JSON não encontrado no .env. Abortando.')
        return EXIT_ERRO

    from app.services.fap_web_service import FapWebAuthPayload, FapWebService
    try:
        auth = FapWebAuthPayload.from_json(auth_json)
    except Exception as e:
        _log(f'ERRO: FAP_AUTH_JSON inválido: {e}. Abortando.')
        return EXIT_ERRO

    svc = FapWebService(auth)

    check = svc.check_session()
    if not check.ok:
        if getattr(check, 'expired', False):
            _log('ERRO: sessão FAP expirada. Atualize FAP_AUTH_JSON no .env.')
            return EXIT_SESSAO_EXPIRADA
        _log(f'ERRO: sessão FAP inválida: {check.message}')
        return EXIT_ERRO

    from main import app
    from app.models import db
    from app.services import notification_service
    from app.services.fap_procuracoes_service import sync_procuracoes

    with app.app_context():
        try:
            law_firm_id = _resolve_law_firm_id(args.law_firm_id)
        except RuntimeError as e:
            _log(f'ERRO: {e}')
            return EXIT_ERRO

        try:
            stats = sync_procuracoes(svc, law_firm_id)
        except Exception as e:
            db.session.rollback()
            _log(f'ERRO ao sincronizar procurações: {e}')
            return EXIT_ERRO

        if not stats['ok']:
            if stats['expired']:
                _log('ERRO: sessão FAP expirou durante a busca. Atualize FAP_AUTH_JSON no .env.')
                return EXIT_SESSAO_EXPIRADA
            _log(f"ERRO ao buscar procurações: {stats['message']}")
            return EXIT_ERRO

        _log(
            f"Escritório {law_firm_id} · {stats['total']} procuração(ões) no portal — "
            f"{stats['created']} nova(s), {stats['updated']} alterada(s), "
            f"{stats['unchanged']} sem mudança"
        )

        if not stats['alertaveis']:
            _log('Nenhuma mudança que gere alerta.')

        if args.no_notify:
            _log('Notificação desativada por --no-notify.')
            return EXIT_OK

        try:
            result = notification_service.send_procuracoes_alert(
                law_firm_id, dry_run=args.dry_run
            )
        except Exception as e:
            db.session.rollback()
            _log(f'ERRO ao enviar o alerta: {e}')
            return EXIT_ERRO

        icon = {'sent': '✅', 'skipped': '⏭️ ', 'dry_run': '🔍', 'failed': '❌'}.get(result['status'], '•')
        _log(f"{icon} alerta · {result['status']} · {result['message']}")

        return EXIT_ERRO if result['status'] == 'failed' else EXIT_OK


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        _log(f'ERRO FATAL: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(EXIT_ERRO)
