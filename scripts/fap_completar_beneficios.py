#!/usr/bin/env python3
"""
Completa CPF, nascimento, RMI e total pago dos benefícios da Central de
Contestações com a Consulta do FAP do portal (E02 e E04 da Remessa R09).

Para cada vigência que tem benefício (CNPJ do estabelecimento + ano), duas
chamadas ao portal — o cálculo atual e os benefícios dele — e os benefícios
daquela vigência recebem os dados pelo NB. Regras e detalhes em
``app/services/fap_beneficio_portal_service.py``.

**Só simula por padrão.** Grava apenas com ``--aplicar``.

Só vai ao portal nas vigências que ainda têm benefício **sem CPF** — o CPF é o
que o portal sempre traz quando acha o NB, então rodar de novo só busca o que
faltou. ``--todos`` revisita a base inteira (para trocar CPF divergente pelo do
portal, por exemplo).

Uso:
  uv run python scripts/fap_completar_beneficios.py                          # simula tudo
  uv run python scripts/fap_completar_beneficios.py --empresa 07718633       # simula uma empresa
  uv run python scripts/fap_completar_beneficios.py --vigencia 2026 --aplicar
  uv run python scripts/fap_completar_beneficios.py --aplicar --workers 12
  uv run python scripts/fap_completar_beneficios.py --aplicar --todos        # base inteira

Variáveis (.env):
  FAP_AUTH_JSON           — sessão do portal (a mesma do fap_sync_cron)
  FAP_SYNC_LAW_FIRM_ID    — escritório (ou --escritorio)
  FAP_SYNC_FETCH_WORKERS  — consultas em paralelo (padrão 8, máx 20), como no fap_sync_cron

Códigos de saída:
  0 — terminou (o resumo diz o que ficou sem acesso)
  1 — erro de configuração
  2 — sessão FAP expirada no meio (o que já foi gravado fica; rode de novo depois do login)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # carrega o .env

EXIT_OK, EXIT_ERRO, EXIT_EXPIRADA = 0, 1, 2
WORKERS_PADRAO, WORKERS_MAX = 8, 20


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _workers(valor: int | None) -> int:
    if valor:
        return max(1, min(valor, WORKERS_MAX))
    bruto = os.environ.get('FAP_SYNC_FETCH_WORKERS', '').strip()
    try:
        return max(1, min(int(bruto), WORKERS_MAX)) if bruto else WORKERS_PADRAO
    except ValueError:
        _log(f"AVISO: FAP_SYNC_FETCH_WORKERS inválido ('{bruto}'). Usando {WORKERS_PADRAO}.")
        return WORKERS_PADRAO


def _vigencias(law_firm_id: int, anos: list[int], raizes: list[str], todos: bool = False):
    """[(vigencia_id, ano, cnpj14, {nb, ...})] das vigências que têm benefício.

    Sem ``todos``, só as vigências com algum benefício sem CPF.
    """
    from sqlalchemy import func, or_

    from app.models import Benefit, FapVigenciaCnpj, db
    from app.utils.cnpj import TAMANHO_CNPJ, TAMANHO_CNPJ_RAIZ, completar_zeros

    q = (db.session.query(FapVigenciaCnpj.id, FapVigenciaCnpj.vigencia_year,
                          FapVigenciaCnpj.employer_cnpj, Benefit.benefit_number)
         .join(Benefit, Benefit.fap_vigencia_cnpj_id == FapVigenciaCnpj.id)
         .filter(FapVigenciaCnpj.law_firm_id == law_firm_id, Benefit.law_firm_id == law_firm_id))
    if anos:
        q = q.filter(FapVigenciaCnpj.vigencia_year.in_([str(a) for a in anos]))
    if not todos:
        pendentes = (db.session.query(Benefit.fap_vigencia_cnpj_id)
                     .filter(Benefit.law_firm_id == law_firm_id,
                             or_(Benefit.insured_cpf.is_(None), func.trim(Benefit.insured_cpf) == ''))
                     .distinct())
        q = q.filter(FapVigenciaCnpj.id.in_(pendentes))

    raizes8 = {completar_zeros(r, TAMANHO_CNPJ_RAIZ) for r in raizes}
    por_vigencia: dict[int, tuple[int, str, set]] = {}
    for vid, ano, cnpj, nb in q.all():
        cnpj14 = completar_zeros(cnpj, TAMANHO_CNPJ)
        if not cnpj14 or len(cnpj14) != TAMANHO_CNPJ or not str(ano).isdigit():
            continue
        if raizes8 and cnpj14[:8] not in raizes8:
            continue
        por_vigencia.setdefault(vid, (int(ano), cnpj14, set()))[2].add(nb)
    return [(vid, ano, cnpj, nbs) for vid, (ano, cnpj, nbs) in sorted(por_vigencia.items(),
                                                                      key=lambda kv: (-kv[1][0], kv[1][1]))]


def executar(law_firm_id: int, svc, anos: list[int], raizes: list[str], workers: int, aplicar: bool,
             todos: bool = False) -> int:
    from app.models import db
    from app.services.fap_beneficio_portal_service import aplicar as aplicar_vigencia, buscar_vigencia

    vigencias = _vigencias(law_firm_id, anos, raizes, todos)
    total_ben = sum(len(n) for *_, n in vigencias)
    _log(f"{len(vigencias)} vigência(s) com {total_ben} benefício(s)"
         f"{'' if todos else ' (só as que têm benefício sem CPF; --todos para a base inteira)'}"
         f" — {workers} consulta(s) em paralelo"
         f" — {'GRAVANDO' if aplicar else 'SIMULAÇÃO (use --aplicar para gravar)'}")

    situacoes: dict[str, int] = {}
    campos = {'beneficios': 0, 'cpf': 0, 'nascimento': 0, 'rmi': 0, 'total_pago': 0, 'nao_encontrados': 0}
    sem_acesso: list[str] = []
    expirou = False
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(buscar_vigencia, svc, ano, cnpj, nbs): (vid, ano, cnpj)
                   for vid, ano, cnpj, nbs in vigencias}
        for n, futuro in enumerate(as_completed(futuros), 1):
            vid, ano, cnpj = futuros[futuro]
            try:
                busca = futuro.result()
            except Exception as e:  # não derruba a execução por uma vigência
                situacoes['erro'] = situacoes.get('erro', 0) + 1
                _log(f"  ERRO {ano} {cnpj}: {type(e).__name__}")
                continue
            situacoes[busca.situacao] = situacoes.get(busca.situacao, 0) + 1
            if busca.situacao == 'expirada':
                expirou = True
                for f in futuros:
                    f.cancel()
                break
            if busca.situacao == 'sem_acesso':
                sem_acesso.append(f'{ano} {cnpj}')
            if busca.situacao == 'ok':
                conta = aplicar_vigencia(law_firm_id, vid, busca)
                for k, v in conta.items():
                    campos[k] += v
                if aplicar:
                    db.session.commit()
                else:
                    db.session.rollback()
            if n % 50 == 0:
                _log(f"  {n}/{len(vigencias)} vigências ({time.time() - t0:.0f}s) — "
                     f"CPF {campos['cpf']}, RMI {campos['rmi']}, total pago {campos['total_pago']}")

    verbo = 'gravados' if aplicar else 'a gravar'
    _log('Resumo:')
    _log(f"  vigências: {situacoes}")
    _log(f"  benefícios vistos: {campos['beneficios']} — não encontrados no portal: {campos['nao_encontrados']}")
    _log(f"  campos {verbo}: CPF {campos['cpf']}, nascimento {campos['nascimento']}, "
         f"RMI {campos['rmi']}, total pago {campos['total_pago']}")
    if sem_acesso:
        _log(f"  sem acesso (403 — sessão parcial ou sem procuração): {len(sem_acesso)}, ex.: "
             f"{', '.join(sem_acesso[:5])}")
    _log(f"  tempo: {time.time() - t0:.0f}s")
    if expirou:
        _log('ERRO: sessão FAP expirada no meio. Faça login, atualize o FAP_AUTH_JSON e rode de novo '
             '(o que já foi gravado fica).')
        return EXIT_EXPIRADA
    return EXIT_OK


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Completa CPF, nascimento, RMI e total pago pela Consulta do FAP.')
    ap.add_argument('--aplicar', action='store_true', help='grava (sem isso, só simula)')
    ap.add_argument('--vigencia', type=int, action='append', default=[], help='ano (repetível)')
    ap.add_argument('--empresa', action='append', default=[], help='CNPJ raiz, 8 dígitos (repetível)')
    ap.add_argument('--escritorio', type=int, default=None, help='law_firm_id (padrão: FAP_SYNC_LAW_FIRM_ID)')
    ap.add_argument('--workers', type=int, default=None, help='consultas em paralelo (padrão 8, máx 20)')
    ap.add_argument('--todos', action='store_true', help='inclui as vigências em que todo benefício já tem CPF')
    args = ap.parse_args(argv)

    law_firm_id = args.escritorio or int(os.environ.get('FAP_SYNC_LAW_FIRM_ID') or 0)
    if not law_firm_id:
        _log('ERRO: informe --escritorio ou FAP_SYNC_LAW_FIRM_ID no .env.')
        return EXIT_ERRO

    from app.services.fap_web_service import FapWebAuthPayload, FapWebService
    try:
        auth = FapWebAuthPayload.from_env()
    except Exception as e:
        _log(f'ERRO: FAP_AUTH_JSON inválido: {e}')
        return EXIT_ERRO
    if auth is None or not auth.cookies:
        _log('ERRO: FAP_AUTH_JSON ausente ou sem cookies no .env.')
        return EXIT_ERRO

    with app.app_context():
        return executar(law_firm_id, FapWebService(auth), args.vigencia, args.empresa,
                        _workers(args.workers), args.aplicar, args.todos)


if __name__ == '__main__':
    sys.exit(main())
