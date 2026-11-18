#!/usr/bin/env python3
"""Placar de teses das decisões que já estão na base (PRC-24 e PRC-25).

Lê cada decisão sem `tipo_julgamento` e grava o tipo de julgamento (mérito,
homologação do reconhecimento, sem resolução de mérito) e o resultado de cada
tese, sem mexer no resto da decisão. O texto vem do inteiro teor, do arquivo
anexado ou do lote de Markdown do escritório (instance/importacao/lote_md).

Simula por padrão (só conta de onde viria o texto, sem IA); grava com --gravar.

    uv run python scripts/preencher_placar_jurisprudencia.py --escritorio 1
    uv run python scripts/preencher_placar_jurisprudencia.py --escritorio 1 --gravar
    uv run python scripts/preencher_placar_jurisprudencia.py --escritorio 1 --gravar --limite 20
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402
from app.services import jurisprudence_placar_service as placar  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--escritorio', type=int, required=True, help='law_firm_id')
    parser.add_argument('--gravar', action='store_true', help='lê com a IA e grava (sem ele, só simula)')
    parser.add_argument('--limite', type=int, help='no máximo N decisões (para conferir uma amostra)')
    parser.add_argument('--refazer', action='store_true', help='relê também as que já têm placar')
    parser.add_argument('--pasta', action='append', type=Path,
                        help='pasta do lote de decisões em .md (padrão: instance/importacao/lote_md/decisoes)')
    parser.add_argument('--workers', type=int, default=placar.WORKERS_PADRAO)
    args = parser.parse_args()

    def progresso(r):
        if r['gravadas'] % 25 == 0:
            print(f"  … {r['gravadas']} gravadas", flush=True)

    with app.app_context():
        r = placar.preencher(args.escritorio, gravar=args.gravar, limite=args.limite, refazer=args.refazer,
                             pastas=args.pasta, workers=args.workers, ao_progredir=progresso)

    print(f"\n{r['decisoes']} decisões sem placar.")
    for origem, n in sorted(r['por_origem'].items()):
        print(f'  texto pelo {origem}: {n}')
    if r['sem_texto']:
        print(f"  sem texto em lugar nenhum: {len(r['sem_texto'])}")
        for item in r['sem_texto'][:15]:
            print(f"    decisão {item['id']}: {item['arquivo'] or '(sem nome de arquivo)'}")
    if not args.gravar:
        print('\nSimulação — nada lido nem gravado; rode com --gravar.')
        return 0
    print(f"\n{r['gravadas']} gravadas, {r['teses_com_resultado']} teses com resultado.")
    for julgamento, n in sorted(r['julgamento'].items()):
        print(f'  {julgamento}: {n}')
    if r['falhas']:
        print(f"\n{len(r['falhas'])} falhas (rode de novo para tentar só elas):")
        for f in r['falhas'][:20]:
            print(f"  decisão {f['id']}: {f['motivo']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
