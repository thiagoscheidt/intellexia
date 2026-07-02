#!/usr/bin/env python3
"""Baixa apenas os PDFs pendentes das contestações FAP já sincronizadas.

Reaproveita ``download_pending_files`` do ``fap_sync_cron`` — NÃO re-sincroniza
nada (não busca contestações no portal), apenas baixa os PDFs que faltam
(registros com ``file_path`` nulo). Útil para completar o acervo após a correção
do formato de CNPJ do download (vigências antigas usam a raiz em 8 dígitos).

Uso:
  # Todos os anos que tenham contestações sem PDF:
  uv run python scripts/fap_download_pendentes.py

  # Apenas alguns anos:
  uv run python scripts/fap_download_pendentes.py --anos 2016 2015 2014 2013

  # Ajustar paralelismo / escritório:
  uv run python scripts/fap_download_pendentes.py --workers 4 --law_firm_id 1

Variáveis de ambiente (.env):
  FAP_AUTH_JSON        — JSON de autenticação (obrigatório)
  FAP_SYNC_LAW_FIRM_ID — ID do escritório (padrão: 1 ou primeiro ativo)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
scripts_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(scripts_dir))

from dotenv import load_dotenv  # type: ignore[import]
load_dotenv(project_root / '.env')

# Captura o FAP_AUTH_JSON antes de main.py sobrescrever (loader manual do .env).
_FAP_AUTH_RAW = (os.environ.get('FAP_AUTH_JSON') or '').strip()

# Reaproveita a lógica de download e o logger do cron.
from fap_sync_cron import download_pending_files, _get_law_firm_id, _log


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Baixa PDFs pendentes das contestações FAP (sem re-sincronizar).')
    p.add_argument('--anos', type=int, nargs='+', default=None,
                   help='Ano(s) de vigência a baixar. Padrão: todos com pendências.')
    p.add_argument('--law_firm_id', type=int, default=None, help='ID do escritório (padrão: env/primeiro ativo).')
    p.add_argument('--workers', type=int, default=8, help='Downloads em paralelo (padrão: 8).')
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # 1. Autenticação (mesmo caminho do cron)
    raw = _FAP_AUTH_RAW
    if raw and len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        raw = raw[1:-1].strip()
    if not raw:
        _log("ERRO: FAP_AUTH_JSON não encontrado no .env. Abortando.")
        sys.exit(1)

    from app.services.fap_web_service import FapWebAuthPayload, FapWebService
    try:
        auth = FapWebAuthPayload.from_json(raw)
    except Exception as e:
        _log(f"ERRO: FAP_AUTH_JSON inválido: {e}. Abortando.")
        sys.exit(1)

    # 2. Verifica sessão
    svc = FapWebService(auth)
    _log("Verificando sessão FAP...")
    chk = svc.check_session()
    if not chk.ok:
        _log(f"ERRO: sessão FAP inválida/expirada ({chk.message}). Atualize FAP_AUTH_JSON e tente de novo.")
        sys.exit(1)
    _log("✓ Sessão FAP ativa")

    # 3. App + download
    from main import app
    from app.models import db, LawFirm, FapWebContestacao

    with app.app_context():
        law_firm_id = args.law_firm_id or _get_law_firm_id(db, LawFirm)
        _log(f"Escritório: ID {law_firm_id}")

        # Anos: os informados, ou todos que tenham contestações sem PDF.
        if args.anos:
            years = sorted(set(int(a) for a in args.anos), reverse=True)
        else:
            rows = (
                db.session.query(FapWebContestacao.ano_vigencia)
                .filter(
                    FapWebContestacao.law_firm_id == law_firm_id,
                    FapWebContestacao.file_path.is_(None),
                )
                .distinct()
                .all()
            )
            years = sorted({int(r[0]) for r in rows if r[0] is not None}, reverse=True)

        if not years:
            _log("Nenhum ano com contestações pendentes de PDF. Nada a baixar.")
            return

        workers = max(1, min(int(args.workers), 30))
        _log(f"Anos com pendências: {years}")
        _log(f"Baixando PDFs pendentes em paralelo ({workers} workers)...")

        result = download_pending_files(
            auth, db, FapWebContestacao,
            law_firm_id, years, max_workers=workers,
        )

        _log(
            f"✓ Download concluído: {result['downloaded']} baixado(s), "
            f"{result['linked']} já em disco, "
            f"{result['failed']} sem PDF/falha (de {result['pending']} pendente(s))."
        )
        if result.get('expired'):
            chk2 = svc.check_session()
            if not chk2.ok and getattr(chk2, 'expired', False):
                _log("  ✗ Sessão expirou durante o download. Atualize FAP_AUTH_JSON e rode novamente.")
            else:
                _log("  ! Alguns documentos retornaram acesso negado, mas a sessão segue ativa "
                     "(provável contestação sem PDF, ex.: 'não transmitida').")


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        _log(f"ERRO FATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
