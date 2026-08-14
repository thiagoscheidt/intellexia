#!/usr/bin/env python3
"""
Varredura retroativa dos alertas do Diário Oficial.

A captura corrente já gera os alertas de cada edição que baixa. Este script
existe para o acervo que foi capturado **antes** de o recurso existir, e para
depois de corrigir o CNPJ de um cliente ou mexer numa regra — o alerta de ontem
não reaparece sozinho.

Cobre as duas origens do alerta: o CNPJ da carteira e as regras de
palavra-chave.

    # tudo o que já está no acervo, pelas duas origens
    uv run python scripts/gerar_alertas_dou.py --tudo

    # um intervalo
    uv run python scripts/gerar_alertas_dou.py --de 2026-08-01 --ate 2026-08-11

    # os últimos N dias com edição capturada
    uv run python scripts/gerar_alertas_dou.py --dias 30

    # só as regras de palavra-chave, sem refazer os casamentos de CNPJ
    uv run python scripts/gerar_alertas_dou.py --tudo --regras

Reprocessar não duplica: a chave é (law_firm_id, article_id) e o alerta já lido
continua lido.
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, DouEdition, DouClientAlert
from app.services import dou_alert_service as alertas
from app.services import dou_rule_service as rule_service


def _data(valor: str) -> date:
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        raise argparse.ArgumentTypeError(f'data inválida: {valor} (use AAAA-MM-DD)')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument('--tudo', action='store_true',
                       help='todas as datas com edição no acervo')
    grupo.add_argument('--dias', type=int, metavar='N',
                       help='as N datas mais recentes do acervo')
    grupo.add_argument('--de', type=_data, metavar='AAAA-MM-DD',
                       help='data inicial (use com --ate)')
    parser.add_argument('--ate', type=_data, metavar='AAAA-MM-DD',
                        help='data final; sem ela, vale só o dia de --de')
    parser.add_argument('--lote', type=int, default=3, metavar='N',
                        help='quantas datas por commit (padrão 3)')
    origem = parser.add_mutually_exclusive_group()
    origem.add_argument('--regras', action='store_true',
                        help='só as regras de palavra-chave')
    origem.add_argument('--clientes', action='store_true',
                        help='só o casamento por CNPJ da carteira')
    args = parser.parse_args()

    with app.app_context():
        consulta = db.session.query(DouEdition.data_publicacao).distinct()
        if args.de:
            consulta = consulta.filter(DouEdition.data_publicacao >= args.de,
                                       DouEdition.data_publicacao <= (args.ate or args.de))
        datas = [d for (d,) in consulta.order_by(DouEdition.data_publicacao.desc()).all()]
        if args.dias:
            datas = datas[:args.dias]
        datas.sort()

        if not datas:
            print('Nenhuma data no acervo para o filtro pedido.')
            return 0

        # Dicionário vazio desliga a origem; None manda carregar tudo.
        carteiras = {} if args.regras else alertas.carteiras_ativas()
        regras = {} if args.clientes else rule_service.regras_ativas()

        if not carteiras and not regras:
            print('✗ Nenhuma origem para vigiar: nem cliente com CNPJ válido, '
                  'nem regra de palavra-chave ativa.')
            return 1

        for law_firm_id, carteira in carteiras.items():
            print(f'escritório {law_firm_id}: {len(carteira.por_cnpj)} CNPJs vigiados, '
                  f'{len(carteira.por_raiz)} raízes'
                  + (f', {len(carteira.invalidos)} cadastro(s) com CNPJ inválido'
                     if carteira.invalidos else ''))
            for cliente in carteira.invalidos:
                print(f'    ⚠ fora da vigilância: {cliente.cnpj!r}  {cliente.name}')

        for law_firm_id, lista in regras.items():
            print(f'escritório {law_firm_id}: {len(lista)} regra(s) ativa(s) — '
                  + ', '.join(r.nome for r in lista))

        # Varredura parcial só acrescenta: com uma origem desligada ela não
        # enxerga o motivo que sobrou e não pode remover nada.
        podar = bool(carteiras) and not args.regras and not args.clientes

        print(f'\nVarrendo {len(datas)} data(s): {datas[0]} a {datas[-1]}'
              + ('' if podar else '  (parcial — só acrescenta)'))
        total = 0
        for inicio in range(0, len(datas), max(args.lote, 1)):
            lote = datas[inicio:inicio + max(args.lote, 1)]
            try:
                novos = alertas.gerar_para_datas(lote, carteiras, regras, podar)
                db.session.commit()
                total += novos
                print(f'  {lote[0]} a {lote[-1]}: {novos} alerta(s) novo(s)')
            except Exception as exc:  # noqa: BLE001 — um lote ruim não para o resto
                db.session.rollback()
                print(f'  ✗ {lote[0]} a {lote[-1]}: {exc}')

        for law_firm_id in sorted(set(carteiras) | set(regras)):
            resumo = alertas.resumo(law_firm_id)
            print(f'\n✓ escritório {law_firm_id}: {resumo["total"]} alerta(s) no total — '
                  f'{resumo["exatos"]} de cliente cadastrado, '
                  f'{resumo["raiz"]} de outra filial, '
                  f'{resumo["por_regra"]} por palavra-chave, '
                  f'{resumo["nao_lidos"]} não lido(s)')
        print(f'\n{total} alerta(s) criado(s) nesta execução.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
