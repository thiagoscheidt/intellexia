#!/usr/bin/env python3
"""Jurisprudência: reaplica as regras atuais ao que está em "Revisar" e aos tipos já gravados.

1. "Revisar": cada item parado passa de novo pela correção de tipo (embargos
   lidos como sentença) e pela regra de repetido — o mesmo arquivo, o nome de
   arquivo de uma decisão do mesmo processo, ou processo + instância + data.
   Outra data no mesmo processo e instância é outra decisão e entra na base
   (até 13/11/2026 ia para "Revisar"). Usa a leitura guardada: **sem reler o
   PDF** e sem IA.
2. Base: decisão com nome ou classe de embargos de declaração gravada como
   sentença ou acórdão vira embargos (tipo corrigido à mão não é tocado).

Simula por padrão; grava com --gravar.

    uv run python scripts/reavaliar_revisar_jurisprudencia.py --escritorio 1
    uv run python scripts/reavaliar_revisar_jurisprudencia.py --escritorio 1 --gravar
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
        tipos = envios.reclassificar_embargos_na_base(args.escritorio, gravar=args.gravar)
        revisar = envios.reavaliar_revisar(args.escritorio, gravar=args.gravar)

    print('Decisões da base que viram embargos:')
    for item in tipos:
        print(f"  decisão {item['decision_id']} {(item['arquivo'] or '')[:70]} — {item['de']} → embargos ({item['motivo']})")
    print(f"  {len(tipos)} no total.\n")

    print('Itens em "Revisar":')
    for item in revisar:
        tipo = f" [{item['tipo_de']} → embargos]" if item['tipo_de'] else ''
        if item['destino'] == 'base':
            destino = 'vira decisão' + (f" {item['decision_id']}" if item.get('decision_id') else '')
        else:
            destino = f"continua em Revisar, repete a decisão {item['parecida_id']} (antes: {item['antes']})"
        print(f"  #{item['upload_id']} {item['arquivo'][:70]}{tipo}: {destino}")
    na_base = sum(1 for i in revisar if i['destino'] == 'base')
    print(f"  {na_base} viram decisão, {len(revisar) - na_base} continuam em Revisar contra outra decisão; "
          f"o resto não muda.")
    if not args.gravar:
        print('\nSimulação — nada gravado; rode com --gravar.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
