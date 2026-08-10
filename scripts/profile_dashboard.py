"""
Profiling do dashboard: mostra onde vai o tempo de uma requisição /dashboard.

Somente leitura — não altera nada no banco. Roda uma requisição real pelo
test_client (mesmo caminho do usuário: middleware, view, context processors e
template), captura todo SQL emitido com o tempo de cada statement e imprime o
ranking dos mais caros.

Executar (no servidor onde o dashboard está lento):
    uv run python scripts/profile_dashboard.py
    uv run python scripts/profile_dashboard.py --runs 5 --top 20
"""

import argparse
import os
import re
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import event

from main import app
from app.models import db, User


def _fmt(ms):
    return f'{ms/1000:.2f} s' if ms >= 1000 else f'{ms:.0f} ms'


def main():
    ap = argparse.ArgumentParser(description='Profiling read-only do /dashboard')
    ap.add_argument('--runs', type=int, default=3, help='requisições medidas (default: 3)')
    ap.add_argument('--top', type=int, default=12, help='quantas consultas listar (default: 12)')
    ap.add_argument('--user-id', type=int, help='usuário a simular (default: o primeiro do escritório)')
    ap.add_argument('--law-firm-id', type=int, help='escritório (default: o do usuário)')
    args = ap.parse_args()

    stmts = []
    started = {}

    def before(conn, cursor, statement, parameters, context, executemany):
        started[id(context)] = time.perf_counter()

    def after(conn, cursor, statement, parameters, context, executemany):
        t0 = started.pop(id(context), None)
        if t0 is not None:
            stmts.append(((time.perf_counter() - t0) * 1000, ' '.join(statement.split())))

    with app.app_context():
        event.listen(db.engine, 'before_cursor_execute', before)
        event.listen(db.engine, 'after_cursor_execute', after)

        q = User.query
        if args.user_id:
            q = q.filter_by(id=args.user_id)
        elif args.law_firm_id:
            q = q.filter_by(law_firm_id=args.law_firm_id)
        user = q.first()
        if not user:
            print('Nenhum usuário encontrado para simular a sessão.')
            return 1
        uid, law_firm_id, role = user.id, user.law_firm_id, user.role

    print(f'Simulando usuário id={uid} (escritório {law_firm_id}, papel {role})')

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['law_firm_id'] = law_firm_id
        sess['user_role'] = role

    # Aquecimento (conexão, cache de query plan, import tardio) — não é medido.
    client.get('/dashboard')

    piores = defaultdict(lambda: [0, 0.0])
    total_req = total_sql = 0.0
    n_stmts = 0

    for i in range(args.runs):
        stmts.clear()
        t0 = time.perf_counter()
        resp = client.get('/dashboard')
        elapsed = (time.perf_counter() - t0) * 1000
        sql_ms = sum(d for d, _ in stmts)

        total_req += elapsed
        total_sql += sql_ms
        n_stmts = len(stmts)

        print(f'  run {i+1}: requisição {_fmt(elapsed):>8}  |  SQL {_fmt(sql_ms):>8} '
              f'em {len(stmts)} statements  |  Python+template {_fmt(elapsed - sql_ms):>8}'
              f'  [HTTP {resp.status_code}]')

        for dur, sql in stmts:
            chave = re.sub(r'\d+', '?', sql)[:160]
            piores[chave][0] += 1
            piores[chave][1] += dur

    runs = args.runs
    print(f'\nMÉDIA de {runs} execuções: requisição {_fmt(total_req/runs)} | '
          f'SQL {_fmt(total_sql/runs)} ({n_stmts} statements) | '
          f'Python+template {_fmt((total_req - total_sql)/runs)}')

    if 'Erro ao carregar dashboard' in resp.get_data(as_text=True):
        print('\n  ATENÇÃO: a página caiu no fallback de erro — os números abaixo '
              'não representam o dashboard funcionando.')

    print(f'\nConsultas mais caras (tempo somado nas {runs} execuções):')
    for chave, (vezes, dur) in sorted(piores.items(), key=lambda kv: -kv[1][1])[:args.top]:
        print(f'  {_fmt(dur):>9}  x{vezes:<4} {chave}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
