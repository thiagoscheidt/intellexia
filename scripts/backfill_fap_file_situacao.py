#!/usr/bin/env python3
"""
Backfill de `fap_web_contestacoes.file_situacao_codigo`.

A coluna diz a que situação o PDF em disco corresponde, e é o que faz a fila de
download reconhecer um arquivo defasado. Os arquivos baixados antes dela nascem
com NULL — e NULL é tratado como "origem desconhecida", que a fila ignora de
propósito (senão o acervo inteiro seria rebaixado de uma vez).

Este script preenche lendo a PRIMEIRA PÁGINA de cada PDF, onde o relatório da
DATAPREV se autodeclara:

    Situação do Processo    Transmitida
    Situação do Processo    Resultado divulgado no D.O.U

A descrição lida é convertida em código usando os pares (codigo, descricao) que
já existem na própria tabela — sem tabela fixa no código, então acompanha
qualquer situação nova que o portal passe a devolver.

Depois de rodar, o PDF defasado passa a ter `file_situacao_codigo` diferente de
`situacao_codigo` e entra sozinho na fila do cron.

Quando a descrição do PDF não casa com nenhuma conhecida, a linha é deixada como
está (NULL) e listada no fim: chutar um código faria a fila rebaixar — ou deixar
de rebaixar — pelo motivo errado.

Uso:
  uv run python scripts/backfill_fap_file_situacao.py                      # dry-run
  uv run python scripts/backfill_fap_file_situacao.py --apply
  uv run python scripts/backfill_fap_file_situacao.py --ano-vigencia 2026 --apply
  uv run python scripts/backfill_fap_file_situacao.py --workers 8 --apply
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from rich import print

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.models import FapWebContestacao, db


def parse_args():
    p = argparse.ArgumentParser(description='Preenche file_situacao_codigo lendo a 1ª página do PDF')
    p.add_argument('--apply', action='store_true', help='Grava (padrão: só relata)')
    p.add_argument('--law-firm-id', type=int, help='Restringe a um escritório')
    p.add_argument('--ano-vigencia', type=int, nargs='+', help='Restringe a vigências')
    p.add_argument('--workers', type=int, default=4, help='Processos paralelos (padrão: 4)')
    return p.parse_args()


def _normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem espaço duplicado — para casar descrições."""
    sem_acento = unicodedata.normalize('NFKD', str(texto or ''))
    sem_acento = ''.join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', sem_acento).strip().lower().rstrip('.')


def _situacao_declarada(file_path: str) -> str | None:
    """A situação que o PDF declara na primeira página, ou None."""
    import pdfplumber

    with pdfplumber.open(file_path) as pdf:
        if not pdf.pages:
            return None
        page = pdf.pages[0]
        texto = page.extract_text(x_tolerance=2, y_tolerance=3, layout=False, use_text_flow=True) or ''
        page.close()

    m = re.search(r'Situa[cç][aã]o\s+do\s+Processo\s+([^\n\r]+)', texto, re.IGNORECASE)
    return re.sub(r'\s+', ' ', m.group(1)).strip() if m else None


def _worker(payload):
    rec_id, file_path = payload
    try:
        return rec_id, _situacao_declarada(file_path), None
    except Exception as exc:
        return rec_id, None, str(exc)


def main() -> int:
    args = parse_args()

    with app.app_context():
        # Mapa descrição → código, montado da própria tabela.
        pares = (
            db.session.query(FapWebContestacao.situacao_codigo, FapWebContestacao.situacao_descricao)
            .filter(FapWebContestacao.situacao_codigo.isnot(None),
                    FapWebContestacao.situacao_descricao.isnot(None))
            .distinct()
            .all()
        )
        por_descricao = {_normalizar(desc): cod for cod, desc in pares}
        print(f'{len(por_descricao)} situação(ões) conhecidas: '
              + ', '.join(f'{d!r}→{c}' for d, c in sorted(por_descricao.items())))

        query = FapWebContestacao.query.filter(
            FapWebContestacao.file_path.isnot(None),
            FapWebContestacao.file_situacao_codigo.is_(None),
        )
        if args.law_firm_id:
            query = query.filter(FapWebContestacao.law_firm_id == args.law_firm_id)
        if args.ano_vigencia:
            query = query.filter(FapWebContestacao.ano_vigencia.in_(args.ano_vigencia))

        registros = query.with_entities(
            FapWebContestacao.id, FapWebContestacao.file_path
        ).all()

        payloads, sem_arquivo = [], 0
        for rec in registros:
            if not rec.file_path or not Path(rec.file_path).exists():
                sem_arquivo += 1
                continue
            payloads.append((rec.id, rec.file_path))

        print(f'\n{len(registros)} linha(s) sem file_situacao_codigo; {len(payloads)} com arquivo em disco.')
        if sem_arquivo:
            print(f'[yellow]{sem_arquivo} com file_path apontando para arquivo inexistente — ignoradas.[/yellow]')
        if not payloads:
            print('[green]Nada a preencher.[/green]')
            return 0

        print(f'Lendo a 1ª página de {len(payloads)} PDF(s) com {args.workers} processo(s)...\n')

        resolvidos: dict[int, str] = {}
        desconhecidas, erros = Counter(), []
        por_codigo = Counter()
        done = 0
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
            for rec_id, declarada, erro in pool.map(_worker, payloads):
                done += 1
                if done % 200 == 0:
                    print(f'  ... {done}/{len(payloads)}')
                if erro:
                    erros.append((rec_id, erro))
                    continue
                if not declarada:
                    desconhecidas['(sem "Situação do Processo" na 1ª página)'] += 1
                    continue
                codigo = por_descricao.get(_normalizar(declarada))
                if codigo is None:
                    desconhecidas[declarada] += 1
                    continue
                resolvidos[rec_id] = codigo
                por_codigo[codigo] += 1

        print(f'\n=== {len(payloads)} PDF(s) lidos ===')
        for codigo, n in por_codigo.most_common():
            print(f'  {n:>6}  {codigo}')
        if desconhecidas:
            print('\n[yellow]Deixadas como NULL (descrição não reconhecida):[/yellow]')
            for desc, n in desconhecidas.most_common(10):
                print(f'  {n:>6}  {desc!r}')
        if erros:
            print(f'\n[red]{len(erros)} erro(s) de leitura[/red]; primeiros: {erros[:3]}')

        if not args.apply:
            print('\n[cyan]Dry-run. Rode com --apply para gravar.[/cyan]')
            return 0

        for rec_id, codigo in resolvidos.items():
            rec = db.session.get(FapWebContestacao, rec_id)
            if rec is not None:
                rec.file_situacao_codigo = codigo
        db.session.commit()
        print(f'\n[green]{len(resolvidos)} linha(s) preenchida(s).[/green]')

        defasados = FapWebContestacao.query.filter(
            FapWebContestacao.filtro_arquivo_defasado()
        ).count()
        print(f'[cyan]{defasados} contestação(ões) ficaram marcadas como defasadas — '
              f'o próximo cron (ou fap_download_pendentes.py) as rebaixa.[/cyan]')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
