"""
Detecta e corrige benefícios truncados por terminador de seção casando em prosa.

São dois bugs da mesma família — uma frase que também é cabeçalho em algum
layout de relatório era usada como terminador sem exigir que fosse cabeçalho:

  1. "Dados do Benefício" encerrava a seção da instância. A justificativa
     "...é indevida a utilização dos dados do benefício B91 para composição do
     FAP da empresa." casava, e o corte caía ANTES de "Status" e "Parecer": o
     benefício era gravado como "Em análise", sem status e sem parecer.
     Caso de origem: protocolo 10128.053135/2025-51 (WEG DRIVES & CONTROLS,
     vigência 2026), 2 dos 4 benefícios.

  2. "Não deve ser considerado" encerrava o Parecer. O analista narra o pedido
     da empresa com essa frase ("...que o respectivo insumo não deve ser
     considerado no cálculo do FAP"), e o parecer era cortado no meio dela.
     Caso de origem: 207878_relatorioContestacao.pdf (vigência 2025), NBs
     6415794306 e 6437742520 — 243 caracteres gravados, 1.985 perdidos.
     Esse não muda o status, então não aparece em tela.

Os dois terminadores agora só valem ocupando a linha inteira. O parser já foi
corrigido; este script encontra os benefícios afetados e refaz a importação:

  1. Detecção: reparsa os PDFs com os regex ANTIGOS e com os atuais e marca os
     blocos cujo status ou parecer muda. É ground truth — não depende de
     heurística sobre o texto já gravado.
  2. --apply: para cada benefício afetado, apaga as decisões
     (benefit_contestation_decisions) e o histórico de fonte
     (benefit_fap_source_history) dos relatórios envolvidos — o histórico precisa
     sair porque o upsert só sobrescreve com data estritamente mais nova — e
     reprocessa os relatórios na ordem de upload.

`--from-db` é um pré-filtro barato, não a checagem. Ele reconhece as assinaturas
dos dois danos (1ª instância sem status e sem parecer; parecer terminando sem
pontuação, isto é, no meio da frase), mas um parecer cortado que por acaso
termine em ponto escapa dele. A varredura completa dos PDFs continua sendo a
checagem exaustiva — rode-a ao menos uma vez.

A classificação de tópicos FAP NÃO é refeita aqui: os benefícios afetados são
listados no final para reclassificação (o texto usado antes estava truncado).

Uso:
  uv run python scripts/fix_fap_reports_terminadores_em_prosa.py --from-db            # dry-run rápido
  uv run python scripts/fix_fap_reports_terminadores_em_prosa.py --from-db --apply
  uv run python scripts/fix_fap_reports_terminadores_em_prosa.py                      # dry-run exaustivo
  uv run python scripts/fix_fap_reports_terminadores_em_prosa.py --ano-vigencia 2026
  uv run python scripts/fix_fap_reports_terminadores_em_prosa.py --report-ids 12,34 --apply
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

# Regex de terminação anteriores à correção — usados só para reconhecer o dano.
LEGACY_END_PATTERN = (
    r'(?:^|\n)\s*NB\s*:'
    r'|Informa[cç][oõ]es\s+de\s+Revis[aã]o\s+de\s+Benef[ií]cio'
    r'|Dados\s+do\s+Benef[ií]cio'
    r'|Sum[aá]rio\s+dos\s+Elementos\s+Contestados'
)
LEGACY_OPINION_ENDS = [
    r'\bSum[aá]rio\s+dos\s+Elementos\s+Contestados\b',
    r'\bN[aã]o\s+deve\s+ser\s+considerado\b',
]


def parse_args():
    parser = argparse.ArgumentParser(
        description='Detecta e corrige benefícios truncados por terminador casando em prosa'
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
    parser.add_argument(
        '--from-db', action='store_true',
        help='Pré-filtra pelos relatórios com assinatura de dano antes de abrir os PDFs. Muito mais '
             'rápido, mas é só um pré-filtro: a varredura completa continua sendo a checagem exaustiva.',
    )
    return parser.parse_args()


def _legacy_sections(service, block: str) -> tuple[str | None, str | None]:
    """As seções de 1ª e 2ª instância como o parser as recortava ANTES da correção."""
    first_match = re.search(r'Administrativo\s*1\s*[ªa]\s*inst[âa]ncia', block, flags=re.IGNORECASE)
    second_match = re.search(r'Administrativo\s*2\s*[ªa]\s*inst[âa]ncia', block, flags=re.IGNORECASE)
    end_match = re.search(LEGACY_END_PATTERN, block, flags=re.IGNORECASE | re.MULTILINE)

    first_section = None
    if first_match:
        first_end = second_match.start() if second_match else (end_match.start() if end_match else len(block))
        first_section = block[first_match.end():first_end].strip() or None

    second_section = None
    if second_match:
        second_start = second_match.end()
        second_end = end_match.start() if end_match and end_match.start() > second_start else len(block)
        second_section = block[second_start:second_end].strip() or None

    return first_section, second_section


def _legacy_opinion(service, section: str) -> str:
    """O Parecer como era extraído ANTES da correção (terminador solto)."""
    opinion = service._extract_text_between_keywords(section, r'\bParecer\b', LEGACY_OPINION_ENDS)
    if opinion:
        opinion = re.sub(
            r'^(Status\s*)?(Deferido|Indeferido)\b\s*', '', opinion, flags=re.IGNORECASE
        ).strip()
    return opinion or ''


def find_truncated_benefits(service, file_path: str) -> list[tuple[str, int, str]]:
    """Blocos cujo status ou parecer muda ao trocar os regex antigos pelos corrigidos.

    Retorna [(nb, instancia, motivo), ...]. Cobre as duas instâncias: o corte
    atinge sempre a ÚLTIMA instância do bloco (quando há 2ª, o recorte da 1ª
    termina no título dela, que tem prioridade sobre o terminador).
    """
    text = service._read_pdf_as_markdown(file_path)
    if not text:
        return []

    affected: list[tuple[str, int, str]] = []
    for kind, block in FapContestationJudgmentReportService._split_all_blocks(text):
        if kind != 'benefit':
            continue

        nb_match = re.match(r'\s*(\d{8,})', block)
        nb = nb_match.group(1) if nb_match else '?'

        legacy = _legacy_sections(service, block)
        current = service._extract_instance_sections(block)

        for instancia, (old_section, new_section) in enumerate(zip(legacy, current), start=1):
            if not new_section:
                continue

            old_decision = service._extract_instance_decision(old_section) if old_section else {}
            new_decision = service._extract_instance_decision(new_section)

            # Dano 1: a seção era cortada antes do Status/Parecer.
            if old_decision.get('status') != new_decision.get('status'):
                affected.append((
                    nb, instancia,
                    f'status {old_decision.get("status")!r} -> {new_decision.get("status")!r}',
                ))
                continue

            # Dano 2: o Parecer era cortado no meio da frase.
            old_opinion = _legacy_opinion(service, old_section) if old_section else ''
            new_opinion = new_decision.get('opinion') or ''
            if len(new_opinion) > len(old_opinion):
                affected.append((
                    nb, instancia,
                    f'parecer +{len(new_opinion) - len(old_opinion)} caracteres '
                    f'({len(old_opinion)} -> {len(new_opinion)})',
                ))

    return affected


def _scan_worker(payload: tuple[int, str]):
    """Varre um PDF em processo separado (sem tocar no banco)."""
    report_id, file_path = payload
    service = object.__new__(FapContestationJudgmentReportService)
    try:
        return report_id, find_truncated_benefits(service, file_path), None
    except Exception as exc:
        return report_id, [], str(exc)


def prefilter_report_ids() -> set[int]:
    """Relatórios com assinatura de algum dos dois danos. PRÉ-FILTRO, não checagem.

    Assinatura do dano 1 (corte antes de Status/Parecer): instância sem status e
    sem parecer — a regra de negócio do parser grava "Em análise". Superconjunto
    seguro: os "Não Analisados" legítimos também entram e caem na varredura.

    Assinatura do dano 2 (corte no meio do Parecer): o parecer termina sem
    pontuação final, isto é, no meio da frase ("...que o respectivo insumo").
    Medido no acervo local: 0,3% dos pareceres — filtro apertado e barato. Mas um
    parecer cortado que por acaso termine em ponto passa batido, e por isso a
    varredura completa dos PDFs continua sendo a checagem exaustiva.

    Olha as DUAS origens do mesmo dado: `benefit_contestation_decisions` (uma
    linha por análise) e as colunas planas de `benefits`, ligadas ao relatório
    pelo histórico de fonte. A tabela de decisões é recente — uma instalação que
    importou antes dela tem só as colunas planas, e um pré-filtro que olhasse
    apenas as decisões devolveria "nada a corrigir" em silêncio.
    """
    # Fecho de frase: o parecer íntegro termina em ponto, aspas, parêntese ou
    # dois-pontos. `LIKE` com esses sufixos vale igual no SQLite e no MySQL.
    FECHOS = ('.', '"', '”', ')', ':')

    def _termina_no_meio(column):
        return db.and_(
            column.isnot(None),
            column != '',
            *[db.not_(column.like(f'%{fecho}')) for fecho in FECHOS],
        )

    def _sem_analise(status_col, opinion_col):
        return db.and_(
            db.or_(status_col.is_(None), status_col == 'Em análise'),
            db.or_(opinion_col.is_(None), opinion_col == ''),
        )

    flat_rows = (
        db.session.query(BenefitFapSourceHistory.report_id)
        .join(Benefit, Benefit.id == BenefitFapSourceHistory.benefit_id)
        .filter(
            BenefitFapSourceHistory.report_id.isnot(None),
            db.or_(
                db.and_(
                    Benefit.first_instance_justification.isnot(None),
                    _sem_analise(Benefit.first_instance_status, Benefit.first_instance_opinion),
                ),
                db.and_(
                    Benefit.second_instance_justification.isnot(None),
                    _sem_analise(Benefit.second_instance_status, Benefit.second_instance_opinion),
                ),
                _termina_no_meio(Benefit.first_instance_opinion),
                _termina_no_meio(Benefit.second_instance_opinion),
            ),
        )
        .distinct()
        .all()
    )

    decision_rows = (
        db.session.query(BenefitContestationDecision.report_id)
        .filter(
            BenefitContestationDecision.report_id.isnot(None),
            db.or_(
                _sem_analise(
                    BenefitContestationDecision.status,
                    BenefitContestationDecision.opinion,
                ),
                _termina_no_meio(BenefitContestationDecision.opinion),
            ),
        )
        .distinct()
        .all()
    )

    return {row[0] for row in flat_rows} | {row[0] for row in decision_rows}


def main() -> int:
    args = parse_args()
    service = FapContestationJudgmentReportService(flask_app=app)

    with app.app_context():
        query = FapContestationJudgmentReport.query.filter(
            FapContestationJudgmentReport.status.in_(['completed', 'error'])
        )
        if args.report_ids:
            report_ids = [int(x) for x in args.report_ids.split(',') if x.strip()]
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
        if args.from_db and not args.report_ids:
            candidate_ids = prefilter_report_ids()
            print(f'Pré-filtro pelo banco: {len(candidate_ids)} relatório(s) candidato(s).')
            if not candidate_ids:
                print('[green]Nenhum relatório candidato.[/green]')
                return 0
            query = query.filter(FapContestationJudgmentReport.id.in_(candidate_ids))

        reports = query.order_by(FapContestationJudgmentReport.uploaded_at.asc()).all()
        report_by_id = {r.id: r for r in reports}

        scan_payloads: list[tuple[int, str]] = []
        missing_files: list[int] = []
        for report in reports:
            if not report.file_path or not Path(report.file_path).exists():
                missing_files.append(report.id)
                continue
            scan_payloads.append((report.id, report.file_path))

        scan_workers = max(1, args.scan_workers)
        print(f'Varrendo {len(scan_payloads)} PDF(s) com {scan_workers} processo(s)...')

        affected_by_report: dict[int, list[tuple[str, int, str]]] = {}
        done = 0
        with ProcessPoolExecutor(max_workers=scan_workers) as pool:
            for report_id, hits, error in pool.map(_scan_worker, scan_payloads):
                done += 1
                if done % 50 == 0:
                    print(f'  ... {done}/{len(scan_payloads)} PDFs varridos')
                if error:
                    print(f'[red]Relatório #{report_id}: erro ao ler PDF ({error})[/red]')
                    continue
                if not hits:
                    continue
                report = report_by_id[report_id]
                affected_by_report[report_id] = hits
                resumo = ', '.join(f'NB {nb} {instancia}ª inst.: {motivo}' for nb, instancia, motivo in hits)
                print(
                    f'[yellow]Relatório #{report_id}[/yellow] ({report.original_filename}, '
                    f'escritório {report.law_firm_id}): {resumo}'
                )

        if missing_files:
            print(f'[red]Arquivo não encontrado para os relatórios: {missing_files} — ignorados.[/red]')

        if not affected_by_report:
            print('[green]Nenhum benefício afetado encontrado.[/green]')
            return 0

        affected_benefits: dict[int, Benefit] = {}
        for report_id, hits in affected_by_report.items():
            report = report_by_id[report_id]
            for nb, _, _motivo in hits:
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
            opinion_tail = (benefit.first_instance_opinion or '')[-60:]
            print(
                f'  Benefit #{benefit.id} NB {benefit.benefit_number} '
                f'(escritório {benefit.law_firm_id}) | status 1ª: '
                f'{benefit.first_instance_status!r} | decisões: {decision_count} | '
                f'fim do parecer 1ª inst.: ...{opinion_tail!r}'
            )

        # Relatórios a reprocessar: os afetados + todos que já alimentaram esses
        # benefícios (o histórico inteiro é refeito para reconstruir decisões e
        # campos por data).
        reprocess_ids: set[int] = set(affected_by_report.keys())
        for benefit in affected_benefits.values():
            history_rows = BenefitFapSourceHistory.query.filter_by(benefit_id=benefit.id).all()
            reprocess_ids.update({row.report_id for row in history_rows if row.report_id})

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
