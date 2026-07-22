"""
Detecta e corrige benefícios truncados pelo bug da menção inline a "Número do Benefício".

Bug: relatórios de julgamento em que a justificativa/parecer cita
"(Número do benefício NNN)" no meio do texto faziam o split de blocos cortar
o benefício naquele ponto — a justificativa da 2ª instância ficava truncada
(ex.: terminando em "NIT ... ("), o status virava "Em análise" e o parecer se
perdia, além de criar uma "ocorrência" espúria de decisão.

O parser já foi corrigido; este script encontra os arquivos/benefícios afetados
e refaz a importação:

  1. Varre os PDFs dos relatórios e localiza menções inline (mesma heurística
     do parser corrigido). O NB afetado é o do cabeçalho de bloco anterior.
  2. --apply: para cada benefício afetado, apaga as decisões
     (benefit_contestation_decisions) e o histórico de fonte
     (benefit_fap_source_history) dos relatórios envolvidos — o histórico
     precisa sair porque o upsert só sobrescreve com data estritamente mais
     nova — e reprocessa os relatórios na ordem de upload.

A classificação de tópicos FAP NÃO é refeita aqui: benefícios afetados são
listados no final para reclassificação (a justificativa usada antes estava
truncada).

O reprocessamento usa o mesmo `service.process_single_report` da fase 2 do
`scripts/processar_beneficios_contestacoes.py` — não é preciso (nem adianta)
rodar aquele script com --force_reimport para corrigir dados truncados.

Uso:
  uv run python scripts/fix_fap_reports_inline_benefit_number.py               # dry-run
  uv run python scripts/fix_fap_reports_inline_benefit_number.py --apply
  uv run python scripts/fix_fap_reports_inline_benefit_number.py --ano-vigencia 2022
  uv run python scripts/fix_fap_reports_inline_benefit_number.py --report-ids 12,34
  uv run python scripts/fix_fap_reports_inline_benefit_number.py --law-firm-id 1
"""

import argparse
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from rich import print

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.models import (
    Benefit,
    BenefitContestationDecision,
    BenefitFapSourceHistory,
    FapContestationJudgmentReport,
    FapWebContestacao,
    db,
)
from app.services.fap_contestation_judgment_report_service import (
    FapContestationJudgmentReportService,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Detecta e corrige benefícios truncados por menção inline a "Número do Benefício"'
    )
    parser.add_argument('--apply', action='store_true', help='Executa limpeza e reprocessamento (padrão: só listar)')
    parser.add_argument('--report-ids', type=str, help='IDs de relatórios separados por vírgula (padrão: todos)')
    parser.add_argument('--law-firm-id', type=int, help='Restringe a um escritório')
    parser.add_argument(
        '--ano-vigencia', type=int, nargs='+',
        help='Restringe aos relatórios de contestações dessas vigências (via fap_web_contestacoes)',
    )
    parser.add_argument(
        '--scan-workers', type=int, default=4,
        help='Processos paralelos para varrer os PDFs (padrão: 4; a varredura não usa o banco)',
    )
    return parser.parse_args()


def _scan_worker(payload: tuple[int, str]) -> tuple[int, list[str], str | None]:
    """Varre um PDF em processo separado (sem tocar no banco)."""
    report_id, file_path = payload
    service = object.__new__(FapContestationJudgmentReportService)
    try:
        return report_id, find_inline_mentions(service, file_path), None
    except Exception as exc:
        return report_id, [], str(exc)


def find_inline_mentions(service: FapContestationJudgmentReportService, file_path: str) -> list[str]:
    """Retorna os NBs dos blocos que continham menção inline (bloco que era truncado)."""
    text = service._read_pdf_as_markdown(file_path)
    if not text:
        return []

    markers = FapContestationJudgmentReportService._classify_benefit_number_markers(text)
    if not any(is_header for _, is_header in markers):
        # Sem cabeçalho validável o parser mantém o comportamento antigo — nada a corrigir.
        return []

    affected: list[str] = []
    last_header_nb: str | None = None
    for match, is_header in markers:
        window = text[match.end():match.end() + 60]
        nb_match = re.match(r'\s*[:\-]?\s*(\d{8,})', window)
        if is_header:
            last_header_nb = nb_match.group(1) if nb_match else None
        elif last_header_nb and last_header_nb not in affected:
            # A menção inline cortava o bloco do cabeçalho anterior.
            affected.append(last_header_nb)
    return affected


def main() -> int:
    args = parse_args()
    service = FapContestationJudgmentReportService(flask_app=app)

    report_ids = None
    if args.report_ids:
        report_ids = [int(x) for x in args.report_ids.split(',') if x.strip()]

    with app.app_context():
        query = FapContestationJudgmentReport.query.filter(
            FapContestationJudgmentReport.status.in_(['completed', 'error'])
        )
        if report_ids:
            query = FapContestationJudgmentReport.query.filter(
                FapContestationJudgmentReport.id.in_(report_ids)
            )
        if args.law_firm_id:
            query = query.filter(FapContestationJudgmentReport.law_firm_id == args.law_firm_id)
        if args.ano_vigencia:
            report_ids_for_years = db.session.query(FapWebContestacao.report_id).filter(
                FapWebContestacao.ano_vigencia.in_(args.ano_vigencia),
                FapWebContestacao.report_id.isnot(None),
            )
            query = query.filter(FapContestationJudgmentReport.id.in_(report_ids_for_years))

        reports = query.order_by(FapContestationJudgmentReport.uploaded_at.asc()).all()
        print(f'Analisando {len(reports)} relatório(s)...')

        # report -> NBs afetados
        affected_by_report: dict[int, list[str]] = {}
        missing_files: list[int] = []
        report_by_id_all = {r.id: r for r in reports}

        scan_payloads: list[tuple[int, str]] = []
        for report in reports:
            if not report.file_path or not Path(report.file_path).exists():
                missing_files.append(report.id)
                continue
            scan_payloads.append((report.id, report.file_path))

        scan_workers = max(1, args.scan_workers)
        print(f'Varrendo {len(scan_payloads)} PDF(s) com {scan_workers} processo(s)...')
        done = 0
        with ProcessPoolExecutor(max_workers=scan_workers) as pool:
            for report_id, nbs, error in pool.map(_scan_worker, scan_payloads):
                done += 1
                if done % 20 == 0:
                    print(f'  ... {done}/{len(scan_payloads)} PDFs varridos')
                if error:
                    print(f'[red]Relatório #{report_id}: erro ao ler PDF ({error})[/red]')
                    continue
                if nbs:
                    report = report_by_id_all[report_id]
                    affected_by_report[report_id] = nbs
                    print(
                        f'[yellow]Relatório #{report_id}[/yellow] ({report.original_filename}, '
                        f'escritório {report.law_firm_id}): menção inline nos blocos dos NBs {", ".join(nbs)}'
                    )

        if missing_files:
            print(f'[red]Arquivo não encontrado para os relatórios: {missing_files} — ignorados.[/red]')

        if not affected_by_report:
            print('[green]Nenhum relatório afetado encontrado.[/green]')
            return 0

        # Benefícios afetados por escritório
        report_by_id = {r.id: r for r in reports}
        affected_benefits: dict[int, Benefit] = {}
        for report_id, nbs in affected_by_report.items():
            report = report_by_id[report_id]
            for nb in nbs:
                candidates = (
                    Benefit.query
                    .filter_by(law_firm_id=report.law_firm_id, benefit_number=nb)
                    .all()
                )
                if not candidates:
                    print(f'  NB {nb} (relatório #{report_id}): nenhum benefício no banco.')
                for benefit in candidates:
                    affected_benefits[benefit.id] = benefit

        print(f'\n{len(affected_benefits)} benefício(s) afetado(s):')
        for benefit in affected_benefits.values():
            decision_count = BenefitContestationDecision.query.filter_by(benefit_id=benefit.id).count()
            just_tail = (benefit.second_instance_justification or '')[-60:]
            print(
                f'  Benefit #{benefit.id} NB {benefit.benefit_number} '
                f'(escritório {benefit.law_firm_id}) | decisões: {decision_count} | '
                f'fim da justificativa 2ª inst.: ...{just_tail!r}'
            )

        # Relatórios a reprocessar: os afetados + todos que já alimentaram esses benefícios
        # (o histórico inteiro é refeito para reconstruir decisões e campos por data).
        reprocess_ids: set[int] = set(affected_by_report.keys())
        for benefit in affected_benefits.values():
            history_rows = BenefitFapSourceHistory.query.filter_by(benefit_id=benefit.id).all()
            reprocess_ids.update(row.report_id for row in history_rows if row.report_id)

        # Só reprocessa relatórios com arquivo presente; sem o arquivo não apagamos nada dele.
        reprocess_reports = (
            FapContestationJudgmentReport.query
            .filter(FapContestationJudgmentReport.id.in_(reprocess_ids))
            .order_by(FapContestationJudgmentReport.uploaded_at.asc())
            .all()
        )
        usable_ids = {
            r.id for r in reprocess_reports
            if r.file_path and Path(r.file_path).exists()
        }
        skipped = sorted(reprocess_ids - usable_ids)
        if skipped:
            print(f'[red]Relatórios sem arquivo (não serão reprocessados nem limpos): {skipped}[/red]')

        print(f'\nRelatórios a reprocessar ({len(usable_ids)}): {sorted(usable_ids)}')

        if not args.apply:
            print('\n[cyan]Dry-run. Rode com --apply para limpar e reprocessar.[/cyan]')
            return 0

        # ── Limpeza ──────────────────────────────────────────────────────
        for benefit in affected_benefits.values():
            deleted_decisions = (
                BenefitContestationDecision.query
                .filter(
                    BenefitContestationDecision.benefit_id == benefit.id,
                    db.or_(
                        BenefitContestationDecision.report_id.in_(usable_ids),
                        BenefitContestationDecision.report_id.is_(None),
                    ),
                )
                .delete(synchronize_session=False)
            )
            deleted_history = (
                BenefitFapSourceHistory.query
                .filter(
                    BenefitFapSourceHistory.benefit_id == benefit.id,
                    BenefitFapSourceHistory.report_id.in_(usable_ids),
                )
                .delete(synchronize_session=False)
            )
            print(
                f'Benefit #{benefit.id} NB {benefit.benefit_number}: '
                f'{deleted_decisions} decisão(ões) e {deleted_history} registro(s) de histórico apagados.'
            )
        db.session.commit()

        # ── Reprocessamento (ordem de upload, como no pipeline normal) ───
        ok_count = 0
        for report in reprocess_reports:
            if report.id not in usable_ids:
                continue
            success, imported, error = service.process_single_report(report.id)
            if success:
                ok_count += 1
                print(f'[green]Relatório #{report.id} reprocessado ({imported} benefício(s)).[/green]')
            else:
                print(f'[red]Relatório #{report.id} falhou: {error}[/red]')

        print(f'\n{ok_count}/{len(usable_ids)} relatório(s) reprocessado(s).')
        print(
            '[cyan]Reclassifique os tópicos FAP dos benefícios afetados '
            '(a classificação anterior usou justificativa truncada):[/cyan]'
        )
        for benefit in affected_benefits.values():
            print(
                f'  uv run python scripts/classify_fap_benefits.py '
                f'--benefit-id {benefit.id} --force-reclassify'
            )

        return 0


if __name__ == '__main__':
    raise SystemExit(main())
