"""
Diagnóstico (somente leitura): PDF local que não corresponde à situação atual.

Cada relatório da DATAPREV declara na primeira página a que estágio pertence:

    Situação do Processo    Transmitida
    Situação do Processo    Resultado divulgado no D.O.U

As três filas de download baixam apenas contestação com `file_path IS NULL`
(fap_sync_cron.py, fap_panel.py, fap_download_pendentes.py), então o arquivo
capturado enquanto a contestação estava em voo nunca é rebaixado depois do
julgamento. O banco passa a dizer PUBLICADA/Indeferimento Total enquanto o PDF
em disco continua a petição transmitida — sem Status, sem Parecer, sem Sumário.
Reparsear não resolve: não há resultado no arquivo.

Este script NÃO baixa nem escreve nada. Só lê a primeira página de cada PDF e
compara com `situacao_descricao` do banco.

Uso:
  uv run python scripts/diag_fap_pdf_desatualizado.py
  uv run python scripts/diag_fap_pdf_desatualizado.py --ano-vigencia 2026
  uv run python scripts/diag_fap_pdf_desatualizado.py --law-firm-id 1 --workers 8
  uv run python scripts/diag_fap_pdf_desatualizado.py --csv desatualizados.csv
"""

import argparse
import csv
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
from app.models import FapWebContestacao, db

# Marcadores que só existem no relatório de julgamento, nunca na petição
# transmitida. Basta um para o arquivo ser da versão publicada.
MARCADORES_DE_RESULTADO = re.compile(
    r'\bParecer\b|Sum[aá]rio\s+dos\s+Elementos\s+Contestados|Data\s+Publica[cç][aã]o'
    r'|Analista\s+Respons[aá]vel',
    re.IGNORECASE,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Diagnostica PDF local defasado em relação à situação da contestação (somente leitura)'
    )
    parser.add_argument('--law-firm-id', type=int, help='Restringe a um escritório')
    parser.add_argument('--ano-vigencia', type=int, nargs='+', help='Restringe a vigências')
    parser.add_argument('--workers', type=int, default=4, help='Processos paralelos (padrão: 4)')
    parser.add_argument('--csv', type=str, help='Grava os desatualizados num CSV para conferência')
    return parser.parse_args()


def _situacao_do_pdf(file_path: str) -> tuple[str | None, bool]:
    """(situação declarada na 1ª página, tem marcador de resultado)."""
    import pdfplumber

    with pdfplumber.open(file_path) as pdf:
        if not pdf.pages:
            return None, False
        page = pdf.pages[0]
        texto = page.extract_text(x_tolerance=2, y_tolerance=3, layout=False, use_text_flow=True) or ''
        page.close()

    declarada = None
    m = re.search(r'Situa[cç][aã]o\s+do\s+Processo\s+([^\n\r]+)', texto, re.IGNORECASE)
    if m:
        declarada = re.sub(r'\s+', ' ', m.group(1)).strip()

    return declarada, bool(MARCADORES_DE_RESULTADO.search(texto))


def _worker(payload):
    rec_id, protocolo, file_path, situacao_db, deferimento = payload
    try:
        declarada, tem_resultado = _situacao_do_pdf(file_path)
    except Exception as exc:
        return {'id': rec_id, 'erro': str(exc)}
    return {
        'id': rec_id,
        'protocolo': protocolo,
        'file_path': file_path,
        'situacao_db': situacao_db,
        'deferimento': deferimento,
        'situacao_pdf': declarada,
        'tem_resultado': tem_resultado,
        'erro': None,
    }


def main() -> int:
    args = parse_args()

    with app.app_context():
        query = FapWebContestacao.query.filter(FapWebContestacao.file_path.isnot(None))
        if args.law_firm_id:
            query = query.filter(FapWebContestacao.law_firm_id == args.law_firm_id)
        if args.ano_vigencia:
            query = query.filter(FapWebContestacao.ano_vigencia.in_(args.ano_vigencia))

        registros = query.with_entities(
            FapWebContestacao.id,
            FapWebContestacao.protocolo,
            FapWebContestacao.file_path,
            FapWebContestacao.situacao_descricao,
            FapWebContestacao.deferimento_descricao,
        ).all()

        payloads = []
        sem_arquivo = 0
        for rec in registros:
            if not rec.file_path or not Path(rec.file_path).exists():
                sem_arquivo += 1
                continue
            payloads.append((rec.id, rec.protocolo, rec.file_path,
                             rec.situacao_descricao, rec.deferimento_descricao))

        print(f'{len(registros)} contestação(ões) com file_path; {len(payloads)} com arquivo em disco.')
        if sem_arquivo:
            print(f'[yellow]{sem_arquivo} com file_path apontando para arquivo inexistente.[/yellow]')
        print(f'Lendo a 1ª página de {len(payloads)} PDF(s) com {args.workers} processo(s)...\n')

        desatualizados, erros, ok = [], [], 0
        done = 0
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for r in pool.map(_worker, payloads):
                done += 1
                if done % 200 == 0:
                    print(f'  ... {done}/{len(payloads)}')
                if r.get('erro'):
                    erros.append(r)
                    continue
                # Desatualizado: o banco já tem resultado do julgamento, mas o
                # arquivo não carrega nenhum marcador de relatório publicado.
                julgado_no_banco = bool(r['deferimento']) or (
                    r['situacao_db'] or ''
                ).strip().lower().startswith('resultado divulgado')
                if julgado_no_banco and not r['tem_resultado']:
                    desatualizados.append(r)
                else:
                    ok += 1

        print(f'\n=== {len(payloads)} PDF(s) analisados ===')
        print(f'  em dia                        : {ok}')
        print(f'  [red]DESATUALIZADOS (precisam rebaixar): {len(desatualizados)}[/red]')
        print(f'  erro de leitura               : {len(erros)}')

        for r in desatualizados[:30]:
            print(
                f"    protocolo {r['protocolo']} | banco: {r['situacao_db']!r} / {r['deferimento']!r} "
                f"| PDF diz: {r['situacao_pdf']!r}"
            )
        if len(desatualizados) > 30:
            print(f'    ... e mais {len(desatualizados) - 30}')

        if args.csv and desatualizados:
            with open(args.csv, 'w', newline='', encoding='utf-8') as fh:
                writer = csv.DictWriter(
                    fh, fieldnames=['id', 'protocolo', 'situacao_db', 'deferimento',
                                    'situacao_pdf', 'file_path'], extrasaction='ignore')
                writer.writeheader()
                writer.writerows(desatualizados)
            print(f'\nCSV gravado em {args.csv}')

        return 0


if __name__ == '__main__':
    raise SystemExit(main())
