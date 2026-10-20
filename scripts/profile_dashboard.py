"""
Profiling de uma tela: mostra onde vai o tempo de uma requisição (padrão /dashboard).

Somente leitura — não altera nada no banco. Roda uma requisição real pelo
test_client (mesmo caminho do usuário: middleware, view, context processors e
template), captura todo SQL emitido com o tempo de cada statement e imprime o
ranking dos mais caros.

Executar (no servidor onde a tela está lenta):
    uv run python scripts/profile_dashboard.py
    uv run python scripts/profile_dashboard.py --runs 5 --top 20
    uv run python scripts/profile_dashboard.py --url '/disputes-center/api/list?draw=1&start=0&length=25'

``--url`` mede qualquer endereço do app (GET), inclusive APIs JSON — o nome
ficou do dashboard, que foi a primeira tela medida. ``--explain`` mostra, no
fim, o plano do MySQL (EXPLAIN) das consultas mais caras e o tamanho das
tabelas que elas leem — é o que diz se a lentidão é varredura completa.
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
    ap = argparse.ArgumentParser(description='Profiling read-only de uma tela (padrão /dashboard)')
    ap.add_argument('--url', default='/dashboard', help='endereço a medir (default: /dashboard)')
    ap.add_argument('--runs', type=int, default=3, help='requisições medidas (default: 3)')
    ap.add_argument('--top', type=int, default=12, help='quantas consultas listar (default: 12)')
    ap.add_argument('--user-id', type=int, help='usuário a simular (default: o primeiro do escritório)')
    ap.add_argument('--law-firm-id', type=int, help='escritório (default: o do usuário)')
    ap.add_argument('--explain', type=int, nargs='?', const=4, default=0, metavar='N',
                    help='mostra o EXPLAIN das N consultas mais caras (default: 4)')
    args = ap.parse_args()

    stmts = []
    started = {}

    def before(conn, cursor, statement, parameters, context, executemany):
        started[id(context)] = time.perf_counter()

    exemplos = {}

    def after(conn, cursor, statement, parameters, context, executemany):
        t0 = started.pop(id(context), None)
        if t0 is not None:
            sql = ' '.join(statement.split())
            stmts.append(((time.perf_counter() - t0) * 1000, sql))
            exemplos.setdefault(re.sub(r'\d+', '?', sql)[:160], (statement, parameters))

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

    print(f'Simulando usuário id={uid} (escritório {law_firm_id}, papel {role}) em {args.url}')

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['law_firm_id'] = law_firm_id
        sess['user_role'] = role

    # Aquecimento (conexão, cache de query plan, import tardio) — não é medido.
    client.get(args.url)

    piores = defaultdict(lambda: [0, 0.0])
    total_req = total_sql = 0.0
    n_stmts = 0

    for i in range(args.runs):
        stmts.clear()
        t0 = time.perf_counter()
        resp = client.get(args.url)
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

    if args.url == '/dashboard' and 'Erro ao carregar dashboard' in resp.get_data(as_text=True):
        print('\n  ATENÇÃO: a página caiu no fallback de erro — os números abaixo '
              'não representam o dashboard funcionando.')

    print(f'\nConsultas mais caras (tempo somado nas {runs} execuções):')
    ranking = sorted(piores.items(), key=lambda kv: -kv[1][1])
    for chave, (vezes, dur) in ranking[:args.top]:
        print(f'  {_fmt(dur):>9}  x{vezes:<4} {chave}')

    if args.explain:
        _explain(ranking[:args.explain], exemplos)
    return 0


def _explain(ranking, exemplos):
    """EXPLAIN das consultas mais caras + tamanho das tabelas envolvidas (só leitura)."""
    with app.app_context():
        conn = db.engine.raw_connection()
        try:
            cur = conn.cursor()
            tabelas = set()
            for n, (chave, (vezes, dur)) in enumerate(ranking, 1):
                statement, parameters = exemplos[chave]
                if not statement.lstrip().upper().startswith('SELECT'):
                    continue
                print(f'\n[{n}] {_fmt(dur / vezes)} por execução — {chave[:100]}')
                try:
                    cur.execute('EXPLAIN ' + statement, parameters)
                except Exception as e:
                    print(f'    EXPLAIN falhou: {e}')
                    continue
                cols = [c[0] for c in cur.description]
                for linha in cur.fetchall():
                    d = dict(zip(cols, linha))
                    tabelas.add(d.get('table'))
                    print(f"    {d.get('select_type')!s:<12} tabela={d.get('table')!s:<22} tipo={d.get('type')!s:<7} "
                          f"chave={d.get('key')!s:<38} linhas={d.get('rows')!s:<8} extra={d.get('Extra')}")
            tabelas = sorted(t for t in tabelas if t and not str(t).startswith('<'))
            if tabelas:
                cur.execute(
                    'SELECT table_name, table_rows, ROUND(data_length/1048576), ROUND(index_length/1048576), row_format '
                    'FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name IN ('
                    + ','.join(['%s'] * len(tabelas)) + ')', tabelas)
                print('\nTamanho das tabelas (MB de dados / MB de índices):')
                for nome, linhas, dados, indices, formato in cur.fetchall():
                    print(f'    {nome:<28} ~{linhas} linhas  {dados} MB dados  {indices} MB índices  ({formato})')
        finally:
            conn.close()


if __name__ == '__main__':
    sys.exit(main())
