#!/usr/bin/env python3
"""
DIAGNÓSTICO (somente leitura): estado no portal FAP × estado no banco × PDF em disco.

Responde, contestação a contestação, três perguntas que hoje se confundem:

  1. A SITUAÇÃO sincronizou?  Compara `situacao`/`deferimento`/`dataDOU` que o
     portal devolve AGORA com o que está em `fap_web_contestacoes`.
  2. O ARQUIVO está atualizado?  Lê a 1ª página do PDF local ("Situação do
     Processo") e compara com a situação atual. As três filas de download só
     pegam `file_path IS NULL`, então o arquivo capturado enquanto a
     contestação estava em voo nunca é rebaixado depois do julgamento.
  3. Os BENEFÍCIOS foram processados?  Mostra o relatório vinculado e quantos
     benefícios ele gerou.

NÃO baixa PDF, NÃO grava nada. Precisa de FAP_AUTH_JSON no .env (mesma sessão
usada pelo cron); sem ele, roda só as partes 2 e 3, com aviso.

Uso:
  uv run python scripts/diag_fap_estado_vs_portal.py --cnpj-raiz 83647917 --ano 2026
  uv run python scripts/diag_fap_estado_vs_portal.py --cnpj-raiz 83647917 --ano 2026 --protocolo 10128056943202571
  uv run python scripts/diag_fap_estado_vs_portal.py --cnpj-raiz 14309992 --ano 2026
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv  # type: ignore[import]
    load_dotenv(project_root / '.env')
except Exception:
    pass

# Captura ANTES de importar main.py, cujo loader manual de .env pode
# sobrescrever a variável (mesmo cuidado de diag_fap_contestacao_cnpj.py).
_FAP_AUTH_RAW = (os.environ.get('FAP_AUTH_JSON') or '').strip()

from rich import print  # noqa: E402

from main import app  # noqa: E402
from app.models import (  # noqa: E402
    Benefit,
    BenefitFapSourceHistory,
    FapContestationJudgmentReport,
    FapWebContestacao,
    db,
)

MARCADORES_DE_RESULTADO = re.compile(
    r'\bParecer\b|Sum[aá]rio\s+dos\s+Elementos\s+Contestados|Data\s+Publica[cç][aã]o'
    r'|Analista\s+Respons[aá]vel',
    re.IGNORECASE,
)


def parse_args():
    p = argparse.ArgumentParser(description='Compara portal FAP × banco × PDF em disco (read-only)')
    p.add_argument('--cnpj-raiz', required=True, help='CNPJ raiz (8 dígitos)')
    p.add_argument('--ano', type=int, required=True, help='Ano de vigência')
    p.add_argument('--law-firm-id', type=int, default=1, help='ID do escritório (padrão: 1)')
    p.add_argument('--protocolo', help='Restringe a um protocolo (com ou sem pontuação)')
    return p.parse_args()


def _situacao_do_pdf(file_path: str) -> tuple[str | None, bool]:
    """(situação declarada na 1ª página, tem marcador de relatório publicado)."""
    import pdfplumber

    with pdfplumber.open(file_path) as pdf:
        if not pdf.pages:
            return None, False
        page = pdf.pages[0]
        texto = page.extract_text(x_tolerance=2, y_tolerance=3, layout=False, use_text_flow=True) or ''
        page.close()

    m = re.search(r'Situa[cç][aã]o\s+do\s+Processo\s+([^\n\r]+)', texto, re.IGNORECASE)
    declarada = re.sub(r'\s+', ' ', m.group(1)).strip() if m else None
    return declarada, bool(MARCADORES_DE_RESULTADO.search(texto))


def _so_digitos(v) -> str:
    return ''.join(c for c in str(v or '') if c.isdigit())


def _buscar_no_portal(cnpj_raiz: str, ano: int) -> dict[int, dict] | None:
    """{contestacao_id: item} conforme o portal responde AGORA, ou None."""
    if not _FAP_AUTH_RAW:
        print('[yellow]FAP_AUTH_JSON ausente — pulando a comparação com o portal.[/yellow]')
        return None

    from app.services.fap_web_service import FapWebAuthPayload, FapWebService

    try:
        auth = FapWebAuthPayload.from_json(_FAP_AUTH_RAW)
    except Exception as exc:
        print(f'[red]FAP_AUTH_JSON inválido: {exc}[/red]')
        return None

    result = FapWebService(auth).fetch_contestacoes(cnpj=cnpj_raiz, year=ano)
    if not result.ok:
        marca = ' (sessão expirada — atualize FAP_AUTH_JSON)' if getattr(result, 'expired', False) else ''
        print(f'[red]Portal recusou a consulta: {result.message}{marca}[/red]')
        return None

    return {int(item['id']): item for item in (result.data or []) if item.get('id') is not None}


def main() -> int:
    args = parse_args()
    cnpj_raiz = _so_digitos(args.cnpj_raiz)[:8]

    portal = _buscar_no_portal(cnpj_raiz, args.ano)
    if portal is not None:
        print(f'Portal devolveu {len(portal)} contestação(ões) para {cnpj_raiz}/{args.ano}.\n')

    with app.app_context():
        query = FapWebContestacao.query.filter(
            FapWebContestacao.law_firm_id == args.law_firm_id,
            FapWebContestacao.cnpj_raiz == cnpj_raiz,
            FapWebContestacao.ano_vigencia == args.ano,
        )
        if args.protocolo:
            query = query.filter(FapWebContestacao.protocolo == _so_digitos(args.protocolo))

        registros = query.order_by(FapWebContestacao.protocolo).all()
        print(f'Banco tem {len(registros)} contestação(ões) para o mesmo filtro.\n')

        vistos = set()
        for rec in registros:
            vistos.add(rec.contestacao_id)
            print(f'[bold]── contestação {rec.contestacao_id} | protocolo {rec.protocolo} | CNPJ {rec.cnpj}[/bold]')
            print(f'   banco   : situação {rec.situacao_descricao!r} | deferimento {rec.deferimento_descricao!r} '
                  f'| DOU {rec.data_dou} | sync {rec.last_synced_at}')

            # ── 1) situação sincronizou? ──────────────────────────────
            if portal is not None:
                item = portal.get(rec.contestacao_id)
                if item is None:
                    print('   [yellow]portal  : contestação NÃO retornada agora (verifique procuração/vigência)[/yellow]')
                else:
                    p_sit = (item.get('situacao') or {}).get('descricao')
                    p_def = (item.get('deferimento') or {}).get('descricao')
                    p_dou = (item.get('dataDOU') or '')[:10]
                    print(f'   portal  : situação {p_sit!r} | deferimento {p_def!r} | DOU {p_dou or None}')
                    if (p_sit or None) != (rec.situacao_descricao or None) or \
                       (p_def or None) != (rec.deferimento_descricao or None):
                        print('   [red]>>> SITUAÇÃO DESSINCRONIZADA — o cron não atualizou este registro[/red]')

            # ── 2) arquivo em dia? ────────────────────────────────────
            if not rec.file_path:
                print('   [yellow]arquivo : nenhum PDF baixado[/yellow]')
            elif not Path(rec.file_path).exists():
                print(f'   [red]arquivo : file_path aponta para arquivo inexistente ({rec.file_path})[/red]')
            else:
                try:
                    declarada, tem_resultado = _situacao_do_pdf(rec.file_path)
                except Exception as exc:
                    print(f'   [red]arquivo : erro ao ler PDF ({exc})[/red]')
                else:
                    print(f'   arquivo : PDF declara {declarada!r} | tem resultado: {tem_resultado}')
                    julgado = bool(rec.deferimento_descricao) or (
                        rec.situacao_descricao or ''
                    ).strip().lower().startswith('resultado divulgado')
                    if julgado and not tem_resultado:
                        print('   [red]>>> PDF DESATUALIZADO — é a versão transmitida; precisa rebaixar[/red]')

            # ── 3) benefícios processados? ────────────────────────────
            if rec.report_id:
                report = db.session.get(FapContestationJudgmentReport, rec.report_id)
                n = (db.session.query(db.func.count(db.distinct(BenefitFapSourceHistory.benefit_id)))
                     .filter(BenefitFapSourceHistory.report_id == rec.report_id).scalar() or 0)
                em_analise = (db.session.query(db.func.count(Benefit.id))
                              .join(BenefitFapSourceHistory, BenefitFapSourceHistory.benefit_id == Benefit.id)
                              .filter(BenefitFapSourceHistory.report_id == rec.report_id,
                                      Benefit.first_instance_status == 'Em análise').scalar() or 0)
                print(f"   relatório #{rec.report_id} status {getattr(report, 'status', '?')!r} "
                      f"| {n} benefício(s), {em_analise} em análise | needs_reprocess={rec.needs_reprocess}")
            else:
                print(f'   [yellow]relatório: nenhum vinculado (benefícios não processados) '
                      f'| needs_reprocess={rec.needs_reprocess}[/yellow]')
            print()

        if portal:
            faltando = sorted(set(portal) - vistos)
            if faltando:
                print(f'[red]{len(faltando)} contestação(ões) no portal e AUSENTES do banco: {faltando}[/red]')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
