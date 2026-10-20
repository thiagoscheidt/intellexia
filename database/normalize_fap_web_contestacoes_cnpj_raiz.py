#!/usr/bin/env python3
"""Normaliza a coluna cnpj_raiz de fap_web_contestacoes (e do histórico).

Contexto:
    O portal FAP manda ``cnpj`` e ``cnpjRaiz`` como número. Duas derivações
    erradas já passaram pela sincronização:

    - até 02/07/2026: ``cnpj.zfill(14)[:8]`` — nas vigências antigas, em que o
      item não traz ``cnpj``, a raiz da empresa virava "00000079";
    - de 02/07/2026 (commit 0357ead) até a correção do E01 da Remessa R09: os 8
      primeiros dígitos do número sem zero — 07.718.633/0081-63 chegava como
      7718633008163 e a UNIDASUL ficou com 370 contestações em "77186330".

    A sincronização agora usa ``app.utils.cnpj.raiz_contestacao_fap``; este
    script aplica a mesma função ao que já foi gravado. **Rode depois do deploy
    da correção**: o cnpj_raiz é campo rastreado do upsert, e o código antigo
    o regravaria errado na próxima sincronização.

Fonte da raiz correta:
    O JSON bruto (coluna raw_data), pelo ``raiz_contestacao_fap`` — o campo
    canônico ``cnpjRaiz`` com os zeros devolvidos. Linha sem raw_data
    aproveitável fica como está e entra na contagem.

O histórico (fap_web_contestacao_change_history) copia a raiz da contestação
a que pertence. As linhas "updated" que só mudaram cnpj_raiz são ruído das
sincronizações com a regra errada; são contadas, não apagadas.

Uso:
    uv run python database/normalize_fap_web_contestacoes_cnpj_raiz.py           # simula
    uv run python database/normalize_fap_web_contestacoes_cnpj_raiz.py --aplicar # grava

Idempotente: só atualiza registros cujo cnpj_raiz atual difere do correto.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import func

from main import app
from app.models import db, FapWebContestacao, FapWebContestacaoChangeHistory
from app.utils.cnpj import raiz_contestacao_fap

BATCH = 1000


def _raiz_from_raw(raw_data: str | None) -> str | None:
    """Raiz canônica (8 dígitos) a partir do JSON bruto da contestação."""
    if not raw_data:
        return None
    try:
        data = json.loads(raw_data)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return raiz_contestacao_fap(data) or None


def _checar_duplicatas() -> bool:
    """A chave única é (law_firm_id, contestacao_id); sem ela, trocar a raiz
    poderia juntar duas linhas que hoje só se distinguem por ela."""
    dup = (
        db.session.query(FapWebContestacao.law_firm_id, FapWebContestacao.contestacao_id)
        .group_by(FapWebContestacao.law_firm_id, FapWebContestacao.contestacao_id)
        .having(func.count(FapWebContestacao.id) > 1)
        .limit(5)
        .all()
    )
    if dup:
        print('ERRO: há contestações repetidas por (law_firm_id, contestacao_id):')
        for law_firm_id, cid in dup:
            print(f'  escritório {law_firm_id}, contestação {cid}')
        print('Resolva as duplicatas antes de normalizar a raiz. Nada foi alterado.')
        return False
    return True


def _normalizar_contestacoes(aplicar: bool) -> dict:
    total = FapWebContestacao.query.count()
    print(f'Contestações: {total}')

    updated = already_ok = skipped_no_raw = processed = 0
    trocas = Counter()
    last_id = 0
    while True:
        rows = (
            FapWebContestacao.query
            .filter(FapWebContestacao.id > last_id)
            .order_by(FapWebContestacao.id)
            .limit(BATCH)
            .all()
        )
        if not rows:
            break
        for rec in rows:
            processed += 1
            correct = _raiz_from_raw(rec.raw_data)
            if correct is None:
                skipped_no_raw += 1
                continue
            if (rec.cnpj_raiz or '') == correct:
                already_ok += 1
                continue
            trocas[(rec.cnpj_raiz, correct)] += 1
            rec.cnpj_raiz = correct
            updated += 1
        last_id = rows[-1].id
        if aplicar:
            db.session.commit()
        else:
            db.session.rollback()
        print(f'  ... {processed}/{total} (a corrigir={updated}, ok={already_ok}, '
              f'sem_raw={skipped_no_raw})')

    if trocas:
        print('\n  Raiz gravada → raiz correta (contestações):')
        for (antes, depois), n in trocas.most_common(30):
            print(f'    {antes!s:>10} → {depois}  ({n})')
        if len(trocas) > 30:
            print(f'    ... e mais {len(trocas) - 30} combinações')

    return {'corrigidas': updated, 'ok': already_ok, 'sem_raw': skipped_no_raw}


def _normalizar_historico(aplicar: bool) -> dict:
    """Histórico copia a raiz da contestação a que pertence.

    Roda depois das contestações: na simulação elas não foram gravadas, então
    a contagem daqui sai pela raiz calculada, não pela do banco.
    """
    corrigidas = 0
    last_id = 0
    while True:
        rows = (
            db.session.query(FapWebContestacaoChangeHistory, FapWebContestacao.raw_data)
            .join(FapWebContestacao,
                  FapWebContestacao.id == FapWebContestacaoChangeHistory.contestacao_db_id)
            .filter(FapWebContestacaoChangeHistory.id > last_id)
            .order_by(FapWebContestacaoChangeHistory.id)
            .limit(BATCH)
            .all()
        )
        if not rows:
            break
        for hist, raw_data in rows:
            correct = _raiz_from_raw(raw_data)
            if correct and hist.cnpj_raiz != correct:
                hist.cnpj_raiz = correct
                corrigidas += 1
        last_id = rows[-1][0].id
        if aplicar:
            db.session.commit()
        else:
            db.session.rollback()

    ruido = (
        FapWebContestacaoChangeHistory.query
        .filter(FapWebContestacaoChangeHistory.change_type == 'updated')
        .filter(FapWebContestacaoChangeHistory.changed_fields == '["cnpj_raiz"]')
        .count()
    )
    return {'corrigidas': corrigidas, 'ruido': ruido}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--aplicar', action='store_true',
                        help='grava as correções (sem isso, só simula)')
    args = parser.parse_args()

    with app.app_context():
        modo = 'APLICANDO' if args.aplicar else 'SIMULAÇÃO (nada será gravado; use --aplicar)'
        print(f'== Normalização de cnpj_raiz — {modo} ==\n')

        if not _checar_duplicatas():
            return 1

        cont = _normalizar_contestacoes(args.aplicar)
        hist = _normalizar_historico(args.aplicar)

        print('\nResumo:')
        verbo = 'Corrigidas' if args.aplicar else 'A corrigir'
        print(f'  Contestações — {verbo}: {cont["corrigidas"]}, já corretas: {cont["ok"]}, '
              f'sem raw_data/cnpjRaiz: {cont["sem_raw"]}')
        print(f'  Histórico    — {verbo}: {hist["corrigidas"]}')
        print(f'  Histórico com mudança só de cnpj_raiz (ruído das sincronizações '
              f'com a regra errada, mantido): {hist["ruido"]}')
        print('Concluído.' if args.aplicar else 'Simulação concluída. Nada foi gravado.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
