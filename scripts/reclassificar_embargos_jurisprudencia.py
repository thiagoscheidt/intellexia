#!/usr/bin/env python3
"""Embargos de declaração parados em "Revisar" como se fossem sentença.

O ED julgado na vara vem sob o cabeçalho "SENTENÇA", e a leitura o registrava
como sentença — duplicata da sentença do processo, parada em "Revisar". A
leitura agora corrige o tipo pelo nome do arquivo ("Decisão ED",
"SENTENÇAED1") e pela classe processual; este script reaplica a regra no que
já estava parado, **sem reler o PDF** (a leitura está guardada) e sem IA.

Só mexe em quem o tipo muda. O que continua parecendo duplicata (o mesmo ED
compartilhado de novo) fica em "Revisar", agora contra a decisão certa.

Simula por padrão; grava com --gravar.

    uv run python scripts/reclassificar_embargos_jurisprudencia.py --escritorio 1
    uv run python scripts/reclassificar_embargos_jurisprudencia.py --escritorio 1 --gravar
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402
from app.services import jurisprudence_upload_service as envios  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--escritorio', type=int, required=True, help='law_firm_id')
    parser.add_argument('--gravar', action='store_true', help='grava (sem ele, só simula)')
    args = parser.parse_args()

    with app.app_context():
        itens = envios.reclassificar_embargos_em_revisao(args.escritorio, gravar=args.gravar)

    para_base = [i for i in itens if i['destino'] == 'base']
    for item in itens:
        destino = 'vira decisão' if item['destino'] == 'base' else f"continua em Revisar (decisão {item['parecida_id']})"
        print(f"  #{item['upload_id']} {item['arquivo'][:70]} — {item['de']} → embargos "
              f"({item['motivo']}): {destino}")
    print(f"\n{len(itens)} embargos reclassificados: {len(para_base)} viram decisão, "
          f"{len(itens) - len(para_base)} continuam em Revisar."
          + ('' if args.gravar else ' Simulação — nada gravado; rode com --gravar.'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
