#!/usr/bin/env python3
"""
Carga do catálogo de teses do escritório (PRC-23) — `catalogo_teses_service`.

Lê a planilha "Catálogo de teses" (abas CATÁLOGO e EQUIVALÊNCIAS) e:

1. cria no catálogo do Painel as teses que faltam e grava código, área e
   descrição nas que já existem (descrição só onde está vazia, salvo
   `--descricoes`);
2. liga cada grafia da EQUIVALÊNCIAS à tese do catálogo, na Jurisprudência;
3. com `--juntar`, junta cada tese inativa na indicada em "Juntar com":
   benefícios do Painel, análises da contestação, peças-modelo (banco, Qdrant
   e Meilisearch) e ligações da Jurisprudência vão para o destino, e a origem
   fica inativa. Mexe no Painel de Processos, por isso é opcional.

**Simula por padrão** (mostra tudo o que faria). Grava com `--aplicar`.
Rodar de novo é seguro: o que já está igual é pulado.

    uv run python scripts/importar_catalogo_teses.py PLANILHA.xlsx --escritorio 1
    uv run python scripts/importar_catalogo_teses.py PLANILHA.xlsx --escritorio 1 --aplicar
    uv run python scripts/importar_catalogo_teses.py PLANILHA.xlsx --escritorio 1 --aplicar --juntar
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, LawFirm
from app.services import catalogo_teses_service as svc
from app.services import jurisprudence_index_service as indice_juris


def _lista(titulo: str, itens: list, formato, limite: int = 40) -> None:
    if not itens:
        return
    print(f'\n{titulo} ({len(itens)})')
    for item in itens[:limite]:
        print(f'  - {formato(item)}')
    if len(itens) > limite:
        print(f'  … e mais {len(itens) - limite}')


def _uso(uso: dict) -> str:
    partes = [f'{n} {nome}' for nome, n in (
        ('benefício(s) do Painel', uso.get('beneficios', 0)),
        ('análise(s) de contestação', uso.get('contestacoes', 0)),
        ('peça(s)-modelo', uso.get('pecas', 0)),
        ('trecho(s) de peça', uso.get('trechos', 0)),
        ('tese(s) da Jurisprudência', uso.get('teses_da_base', 0))) if n]
    return ', '.join(partes) or 'sem uso'


def relatorio(plano: dict, juntar: bool) -> None:
    print('\n=== Catálogo ===')
    print(f"  criar: {len(plano['criar'])} · atualizar: {len(plano['atualizar'])} · "
          f"já iguais: {plano['sem_mudanca']}")
    _lista('Teses novas', plano['criar'],
           lambda c: f"{c['codigo']} {c['nome']} ({c['area']})"
                     + ('' if c['ativa'] else f" — inativa, juntada em {c.get('juntar_em')}"))
    _lista('Teses atualizadas', plano['atualizar'],
           lambda a: f"{a['nome']}: " + ', '.join(
               f"{k}={'(texto da planilha)' if k == 'description' else v}" for k, v in a['mudancas'].items()))
    _lista('Teses do sistema que não estão na planilha (ficam como estão)', plano['fora_da_planilha'],
           lambda t: t['nome'] + ('' if t['ativa'] else ' (inativa)'))

    print('\n=== Junção das teses inativas ===' + ('' if juntar else '  (só com --juntar)'))
    _lista('Juntar', plano['juntar'], lambda j: f"{j['origem']} → {j['destino']}: {_uso(j['uso'])}")
    if not plano['juntar']:
        print('  nada a juntar')

    print('\n=== Equivalências → Jurisprudência ===')
    print(f"  ligar: {len(plano['ligar'])} · trocar ligação: {len(plano['trocar_ligacao'])} · "
          f"já ligadas igual: {plano['ligacao_igual']}")
    _lista('Ligação trocada', plano['trocar_ligacao'],
           lambda i: f"{i['grafia']}: {', '.join(i['antes'])} → {i['tese']}")
    _lista('Grafias da planilha que não estão na base (ignoradas)', plano['grafia_fora_da_base'],
           lambda g: f"{g['grafia']} → {g['tese']}")
    _lista('Teses da base pendentes que a planilha não cobre (seguem para a tela/IA)',
           plano['teses_da_base_sem_equivalencia'], lambda t: f"{t['nome']} ({t['decisoes']} decisão(ões))")
    _lista('Benefícios ligados a teses fora da área FAP (o vínculo fica; a tese some do seletor do benefício)',
           plano['beneficios_fora_da_area'], lambda b: f"{b['nome']} ({b['area']}): {b['beneficios']}")

    if plano['erros']:
        _lista('ERROS — nada será gravado', plano['erros'], str, limite=100)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('planilha')
    parser.add_argument('--escritorio', type=int, required=True, help='law_firm_id')
    parser.add_argument('--aplicar', action='store_true', help='grava (sem isso, só simula)')
    parser.add_argument('--juntar', action='store_true', help='junta as teses inativas (mexe no Painel)')
    parser.add_argument('--descricoes', action='store_true',
                        help='sobrescreve a descrição das teses existentes com a da planilha')
    args = parser.parse_args()

    # No script a atualização do índice da Jurisprudência roda aqui mesmo: em
    # thread de fundo ela morreria junto com o processo, deixando as decisões
    # com a tese do catálogo antiga no índice.
    indice_juris.SINCRONO = True

    with app.app_context():
        if db.session.get(LawFirm, args.escritorio) is None:
            print(f'✗ Escritório {args.escritorio} não existe.')
            return 1
        planilha = svc.ler_planilha(args.planilha)
        print(f'Planilha: {len(planilha.teses)} teses, {len(planilha.equivalencias)} equivalências.')
        plano = svc.planejar(args.escritorio, planilha, descricoes=args.descricoes)
        relatorio(plano, args.juntar)
        if plano['erros']:
            return 1
        if not args.aplicar:
            print('\nSimulação: nada foi gravado. Rode com --aplicar para gravar'
                  + ('.' if args.juntar else ' (e --juntar para juntar as inativas).'))
            return 0

        resultado = svc.executar(plano, juntar=args.juntar)
        print(f"\n✓ Gravado: {resultado['criadas']} tese(s) criada(s), {resultado['atualizadas']} atualizada(s), "
              f"{resultado['ligadas']} grafia(s) ligada(s).")
        for j in resultado['juntadas']:
            print(f"✓ Juntada: {j['origem']} → {j['destino']}: {_uso(j)}")
        for aviso in resultado['avisos']:
            print(f'⚠ {aviso}')
        return 2 if resultado['avisos'] else 0


if __name__ == '__main__':
    sys.exit(main())
