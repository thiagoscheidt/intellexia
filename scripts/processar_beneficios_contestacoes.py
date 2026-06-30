#!/usr/bin/env python3
"""
Processa os benefícios de contestações FAP já sincronizadas (com arquivo local),
equivalente ao botão "Processar Benefícios" da página de contestações.

Uso:
  uv run python scripts/processar_beneficios_contestacoes.py --ano_vigencia 2026
  uv run python scripts/processar_beneficios_contestacoes.py --ano_vigencia 2026 --workers 4
  uv run python scripts/processar_beneficios_contestacoes.py --ano_vigencia 2026 --law_firm_id 2
  uv run python scripts/processar_beneficios_contestacoes.py --ano_vigencia 2026 --cnpj_raiz 12345678
  uv run python scripts/processar_beneficios_contestacoes.py --ano_vigencia 2026 --dry_run
  uv run python scripts/processar_beneficios_contestacoes.py --ano_vigencia 2026 --force_reimport

Filtros equivalentes à URL:
  /fap-panel/contestacoes?ano_vigencia=2026&cnpj_raiz=&instancia=&situacao=&protocolo=

Restrições:
  - Só processa contestações com arquivo PDF já baixado localmente (file_path preenchido).
  - Contestações sem arquivo local são puladas (exigiriam sessão ativa do portal FAP).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # type: ignore[import]
load_dotenv(project_root / '.env')


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Processa benefícios de contestações FAP já sincronizadas'
    )
    parser.add_argument('--ano_vigencia', type=int, required=True, help='Ano de vigência (ex: 2026)')
    parser.add_argument('--law_firm_id', type=int, default=1, help='ID do escritório (padrão: 1)')
    parser.add_argument('--cnpj_raiz', default='', help='Filtro por CNPJ raiz (8 dígitos)')
    parser.add_argument('--instancia', default='', help='Filtro por código de instância')
    parser.add_argument('--situacao', default='', help='Filtro por código de situação')
    parser.add_argument('--protocolo', default='', help='Filtro por protocolo (busca parcial)')
    parser.add_argument('--batch_size', type=int, default=0, help='Limite de contestações a processar (0 = sem limite)')
    parser.add_argument('--workers', type=int, default=1, help='Workers paralelos para processar PDFs (padrão: 1)')
    parser.add_argument('--force_reimport', action='store_true', help='Reimporta mesmo que já exista registro anterior')
    parser.add_argument('--dry_run', action='store_true', help='Apenas lista o que seria processado, sem gravar')
    return parser.parse_args()


def _compute_file_hash(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _ensure_knowledge_base(db, KnowledgeBase, law_firm_id, user_id, filename, file_path, file_size, file_type):
    file_hash = _compute_file_hash(file_path)

    duplicate = KnowledgeBase.query.filter_by(
        law_firm_id=law_firm_id,
        file_hash=file_hash,
        is_active=True,
    ).first()

    if duplicate:
        if (not duplicate.file_path or not os.path.exists(duplicate.file_path)) and os.path.exists(file_path):
            duplicate.file_path = file_path
            duplicate.file_size = file_size
            duplicate.updated_at = datetime.now()
        return duplicate

    knowledge_file = KnowledgeBase(
        user_id=user_id,
        law_firm_id=law_firm_id,
        original_filename=filename,
        file_path=file_path,
        file_size=file_size,
        file_type=file_type,
        file_hash=file_hash,
        description='Relatório de julgamento de contestação do FAP importado pelo painel de benefícios.',
        category='Relatórios FAP',
        tags='fap,contestacao,julgamento',
        lawsuit_number=None,
        processing_status='pending',
        is_active=True,
    )
    db.session.add(knowledge_file)
    db.session.flush()
    return knowledge_file


def main() -> None:
    args = parse_args()

    from main import app
    from app.models import db
    from app.models import (
        FapWebContestacao,
        FapAutoImportedContestacao,
        FapContestationJudgmentReport,
        FapVigenciaCnpj,
        KnowledgeBase,
        User,
    )
    from app.services.fap_contestation_judgment_report_service import FapContestationJudgmentReportService
    from sqlalchemy import and_, exists

    service = FapContestationJudgmentReportService(flask_app=app)

    with app.app_context():
        law_firm_id = args.law_firm_id

        # Usa o primeiro usuário admin/ativo do escritório para gravar os registros
        admin_user = (
            User.query
            .filter_by(law_firm_id=law_firm_id, is_active=True)
            .order_by(User.id.asc())
            .first()
        )
        if not admin_user:
            _log(f'ERRO: Nenhum usuário ativo encontrado para law_firm_id={law_firm_id}.')
            sys.exit(1)
        user_id = admin_user.id
        _log(f'Usuário de referência: {admin_user.email} (id={user_id})')

        # Monta filtros
        conds = [
            FapWebContestacao.law_firm_id == law_firm_id,
            FapWebContestacao.ano_vigencia == args.ano_vigencia,
        ]
        if args.cnpj_raiz:
            conds.append(FapWebContestacao.cnpj_raiz == args.cnpj_raiz)
        if args.instancia:
            conds.append(FapWebContestacao.instancia_codigo == args.instancia)
        if args.situacao:
            conds.append(FapWebContestacao.situacao_codigo == args.situacao)
        if args.protocolo:
            conds.append(FapWebContestacao.protocolo.ilike(f'%{args.protocolo}%'))

        # Apenas registros com arquivo local
        conds.append(FapWebContestacao.file_path.isnot(None))
        conds.append(FapWebContestacao.file_path != '')

        # Exclui já importadas (a menos que force_reimport)
        if not args.force_reimport:
            already_imported = exists().where(and_(
                FapAutoImportedContestacao.law_firm_id == law_firm_id,
                FapAutoImportedContestacao.contestacao_id == FapWebContestacao.contestacao_id,
            ))
            conds.append(~already_imported)

        query = (
            FapWebContestacao.query
            .filter(*conds)
            .order_by(FapWebContestacao.cnpj.asc(), FapWebContestacao.contestacao_id.asc())
        )

        if args.batch_size > 0:
            query = query.limit(args.batch_size)

        contestacoes = query.all()
        total = len(contestacoes)

        _log(f'Vigência: {args.ano_vigencia} | law_firm_id: {law_firm_id}')
        _log(f'Contestações a processar: {total}')

        if total == 0:
            _log('Nada a processar. Verifique os filtros ou se os PDFs foram baixados.')
            return

        if args.dry_run:
            _log('[DRY RUN] Listagem sem gravação:')
            for c in contestacoes:
                _log(f'  contestacao_id={c.contestacao_id} cnpj={c.cnpj} protocolo={c.protocolo} file={c.file_path}')
            return

        app_root = app.root_path  # = project root (main.py está na raiz)
        skip_count = 0
        report_ids: list[int] = []  # IDs registrados aguardando processamento
        # Mapa report_id → fap_web_contestacao.id para reset em caso de erro
        report_to_fap_rec: dict[int, int] = {}

        # ── Fase 1: Registro (single-thread) ─────────────────────────────
        _log('Fase 1/2 — Registrando relatórios...')
        for idx, fap_rec in enumerate(contestacoes, start=1):
            if os.path.isabs(fap_rec.file_path):
                abs_path = fap_rec.file_path
            else:
                abs_path = os.path.abspath(os.path.join(app_root, fap_rec.file_path))

            if not os.path.isfile(abs_path):
                _log(f'  [{idx}/{total}] PULADO — arquivo não encontrado: {fap_rec.file_path}')
                skip_count += 1
                continue

            cnpj14 = (fap_rec.cnpj or '').zfill(14)
            filename = f'FAP_{fap_rec.protocolo}.pdf' if fap_rec.protocolo else f'FAP_{fap_rec.contestacao_id}.pdf'
            file_size = os.path.getsize(abs_path)

            try:
                existing = FapAutoImportedContestacao.query.filter_by(
                    law_firm_id=law_firm_id,
                    contestacao_id=fap_rec.contestacao_id,
                    cnpj=cnpj14,
                ).first()

                report = FapContestationJudgmentReport(
                    user_id=user_id,
                    law_firm_id=law_firm_id,
                    original_filename=filename,
                    file_path=abs_path,
                    file_size=file_size,
                    file_type='PDF',
                    status='pending',
                )
                db.session.add(report)
                db.session.flush()

                knowledge_file = _ensure_knowledge_base(
                    db=db,
                    KnowledgeBase=KnowledgeBase,
                    law_firm_id=law_firm_id,
                    user_id=user_id,
                    filename=filename,
                    file_path=abs_path,
                    file_size=file_size,
                    file_type='PDF',
                )
                report.knowledge_base_id = knowledge_file.id
                db.session.flush()

                if existing and args.force_reimport:
                    existing.report_id = report.id
                    existing.year = fap_rec.ano_vigencia
                    existing.original_filename = filename
                    existing.imported_at = datetime.now()
                else:
                    imported = FapAutoImportedContestacao(
                        law_firm_id=law_firm_id,
                        report_id=report.id,
                        contestacao_id=fap_rec.contestacao_id,
                        cnpj=cnpj14,
                        year=fap_rec.ano_vigencia,
                        original_filename=filename,
                    )
                    db.session.add(imported)

                fap_rec.needs_reprocess = False
                fap_rec.report_id = report.id

                db.session.commit()
                report_ids.append(report.id)
                report_to_fap_rec[report.id] = fap_rec.id
                _log(f'  [{idx}/{total}] Registrado report_id={report.id} | contestacao={fap_rec.contestacao_id} | {cnpj14}')

            except Exception as exc:
                db.session.rollback()
                _log(f'  [{idx}/{total}] ERRO no registro (contestacao={fap_rec.contestacao_id}): {exc}')
                skip_count += 1

        _log(f'Fase 1 concluída: {len(report_ids)} relatório(s) registrado(s), {skip_count} pulado(s).')

        if not report_ids:
            return

        # ── Fase 1b: Pre-seed fap_vigencia_cnpjs (single-thread) ────────
        # Garante que as linhas já existam antes das threads paralelas.
        # Sem isso, múltiplas threads tentam INSERT na mesma chave e
        # causam deadlock de índice no MySQL.
        _log('Fase 1b — Pre-seed fap_vigencia_cnpjs...')
        try:
            from sqlalchemy.dialects.mysql import insert as mysql_insert
            unique_vigencias = {
                (str(c.cnpj or '').zfill(14).replace('.', '').replace('/', '').replace('-', ''),
                 str(c.ano_vigencia))
                for c in contestacoes
                if c.cnpj and c.ano_vigencia
            }
            seeded = 0
            for cnpj_digits, vigencia_year in sorted(unique_vigencias):
                if len(cnpj_digits) != 14:
                    continue
                now_dt = datetime.now()
                stmt = mysql_insert(FapVigenciaCnpj.__table__).values(
                    law_firm_id=law_firm_id,
                    employer_cnpj=cnpj_digits,
                    vigencia_year=vigencia_year,
                    created_at=now_dt,
                    updated_at=now_dt,
                ).on_duplicate_key_update(updated_at=now_dt)
                db.session.execute(stmt)
                seeded += 1
            db.session.commit()
            _log(f'  {seeded} combinação(ões) CNPJ/vigência garantidas.')
        except Exception as exc:
            db.session.rollback()
            _log(f'  AVISO: pre-seed falhou ({exc}) — prosseguindo sem garantia.')

        # ── Fase 2: Processamento (multi-thread) ─────────────────────────
        workers = max(1, args.workers)
        _log(f'Fase 2/2 — Processando PDFs com {workers} worker(s)...')

        success_count = 0
        error_count = 0

        # 1213 = deadlock, 1205 = lock wait timeout
        _RETRYABLE_CODES = {1213, 1205}
        _MAX_RETRIES = 5

        def _process_one(report_id: int) -> tuple[int, bool, int, str | None]:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    with app.app_context():
                        ok, cnt, err = service.process_single_report(report_id)
                    return report_id, ok, cnt, err
                except Exception as exc:
                    cause = getattr(exc, 'orig', None) or exc
                    code = getattr(cause, 'args', (None,))[0]
                    if code in _RETRYABLE_CODES and attempt < _MAX_RETRIES:
                        wait = attempt * 2.0  # backoff mais longo para lock timeout
                        _log(f'  [retry {attempt}/{_MAX_RETRIES}] Erro {code} em report_id={report_id}, aguardando {wait:.0f}s...')
                        time.sleep(wait)
                        continue
                    return report_id, False, 0, str(exc)

        def _reset_failed(report_id: int) -> None:
            """Remove o registro de importação e reseta o FapWebContestacao para pendente."""
            try:
                with app.app_context():
                    FapAutoImportedContestacao.query.filter_by(report_id=report_id).delete()
                    fap_rec_id = report_to_fap_rec.get(report_id)
                    if fap_rec_id:
                        fap_rec = FapWebContestacao.query.get(fap_rec_id)
                        if fap_rec:
                            fap_rec.needs_reprocess = True
                            fap_rec.report_id = None
                    db.session.commit()
            except Exception as exc:
                db.session.rollback()
                _log(f'  AVISO: não foi possível resetar report_id={report_id}: {exc}')

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_process_one, rid): rid for rid in report_ids}
            done = 0
            for future in as_completed(futures):
                done += 1
                report_id, ok, cnt, err = future.result()
                if ok:
                    _log(f'  [{done}/{len(report_ids)}] ✓ report_id={report_id} — {cnt} benefício(s)')
                    success_count += 1
                else:
                    _log(f'  [{done}/{len(report_ids)}] ✗ report_id={report_id} — {err}')
                    _reset_failed(report_id)
                    error_count += 1

        _log('─' * 60)
        _log(f'Concluído: {success_count} OK | {skip_count} pulados/erros registro | {error_count} erros processamento')


if __name__ == '__main__':
    main()
