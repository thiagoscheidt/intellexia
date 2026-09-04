#!/usr/bin/env python3
"""
RPI-10 — acrescenta ao manual de revisão FAP a regra de contagem do intervalo
entre a DCB de um benefício e a DIB do seguinte.

O manual definia restabelecimento como "intervalo inferior a 60 dias", mas
nunca dizia como contar o intervalo — e é justamente aí que o erro aparece,
somando um dia a mais por contar o próprio dia da cessação.

Não sobrescreve nada: cria uma versão NOVA do manual ativo de cada escritório,
com o bloco inserido logo após a definição do tópico 3.3, e a ativa. A versão
anterior continua no histórico e pode ser reativada pela tela de configurações.

Idempotente — escritório cujo manual ativo já traz a regra é pulado.

Uso:
  uv run python database/add_regra_60_dias_manual_fap.py [--law-firm-id 1] [--dry-run]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from app.models import db, FapReviewReferenceVersion

ANCORA = (
    '**Definição:** dois benefícios de incapacidade temporária consecutivos '
    'decorrentes da mesma incapacidade, com intervalo inferior a 60 dias entre '
    'a DCB do primeiro e a DIB do segundo.'
)

MARCA = '**Como contar o intervalo:**'

REGRA = """

**Como contar o intervalo:** o dia da cessação **não** entra na conta — conta-se do dia seguinte à DCB até o dia anterior à DIB. Em fórmula: `(DIB − DCB) − 1`.

| DCB | DIB | Intervalo |
|---|---|---|
| 22/12/2017 | 22/01/2018 | **30 dias** |
| 01/01/2020 | 02/01/2020 | **0 dias** (benefícios consecutivos, sem intervalo) |
| 01/01/2020 | 02/03/2020 | **60 dias** — não é restabelecimento, porque a regra exige intervalo *inferior* a 60 |

Conferir o número escrito na peça contra essa conta. É erro frequente somar um dia a mais, contando o próprio dia da cessação."""


def aplicar(law_firm_id: int | None, dry_run: bool) -> int:
    query = FapReviewReferenceVersion.query.filter_by(
        reference_type='manual_fap', is_active=True)
    if law_firm_id is not None:
        query = query.filter_by(law_firm_id=law_firm_id)

    ativos = query.all()
    if not ativos:
        alvo = f'do escritório {law_firm_id}' if law_firm_id else 'de nenhum escritório'
        print(f'! Nenhum manual_fap ativo {alvo}. Nada a fazer.')
        return 0

    alterados = 0
    for ativo in ativos:
        conteudo = ativo.content or ''
        etiqueta = f'escritório {ativo.law_firm_id} (ativa v{ativo.version_number})'

        if MARCA in conteudo:
            print(f'  = {etiqueta}: já traz a regra de contagem — pulado')
            continue

        if ANCORA not in conteudo:
            print(f'  ! {etiqueta}: não encontrei a definição do tópico 3.3 para ancorar. '
                  f'Acrescente a regra manualmente pela tela de configurações.')
            continue

        novo_conteudo = conteudo.replace(ANCORA, ANCORA + REGRA, 1)

        if dry_run:
            print(f'  ~ {etiqueta}: criaria v{ativo.version_number + 1} '
                  f'(+{len(novo_conteudo) - len(conteudo)} chars)')
            alterados += 1
            continue

        maior = max(
            (v.version_number for v in FapReviewReferenceVersion.query.filter_by(
                law_firm_id=ativo.law_firm_id, reference_type='manual_fap').all()),
            default=ativo.version_number,
        )
        ativo.is_active = False
        db.session.add(FapReviewReferenceVersion(
            law_firm_id=ativo.law_firm_id,
            reference_type='manual_fap',
            version_number=maior + 1,
            content=novo_conteudo,
            change_note='RPI-10: regra de contagem do intervalo entre DCB e DIB',
            is_active=True,
        ))
        print(f'  ✓ {etiqueta}: criada v{maior + 1} com a regra, e ativada')
        alterados += 1

    return alterados


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--law-firm-id', type=int, default=None,
                        help='só este escritório (padrão: todos)')
    parser.add_argument('--dry-run', action='store_true',
                        help='mostra o que faria, sem gravar')
    args = parser.parse_args()

    with app.app_context():
        try:
            print('RPI-10 — regra de contagem dos 60 dias no manual_fap')
            alterados = aplicar(args.law_firm_id, args.dry_run)
            if args.dry_run:
                db.session.rollback()
                print(f'\n✓ Simulação: {alterados} manual(is) seriam atualizados.')
            else:
                db.session.commit()
                print(f'\n✓ Concluído: {alterados} manual(is) atualizado(s).')
        except Exception as e:
            db.session.rollback()
            print(f'\n✗ Erro: {e}')
            sys.exit(1)
