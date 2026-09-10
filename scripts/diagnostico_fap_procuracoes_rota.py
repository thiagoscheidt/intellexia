#!/usr/bin/env python3
"""
Diagnóstico (somente leitura): a lista de procurações do portal FAP muda
conforme o nó do balanceador?

Contexto: em 09/09/2026 a procuração 414660 (cadastrada às 10:34) só apareceu
na lista do cron das 17:00 às 17:50, junto com 38 procurações antigas da NORSA
e da CAF CRYSTAL, e depois sumiu de novo. O ``FAP_AUTH_JSON`` fixa o cookie
``ROUTEID`` (afinidade do balanceador), então o cron fala sempre com o mesmo nó.

O script faz só GET em ``/gateway/fap/v1/procuracoes`` — não grava no banco,
não envia e-mail, não altera o ``.env``. Compara:
  1. os cookies exatamente como estão no ``.env``;
  2. os mesmos cookies sem ``ROUTEID`` (o balanceador escolhe o nó);
  3. cada ``ROUTEID`` diferente que o portal devolver em ``Set-Cookie``.

Uso (no servidor de produção):
  uv run python scripts/diagnostico_fap_procuracoes_rota.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # type: ignore[import]
load_dotenv(project_root / '.env')

from app.services.fap_web_service import (  # noqa: E402
    FapWebAuthPayload, FapWebService, _BASE_URL,
)

URL = f'{_BASE_URL}/gateway/fap/v1/procuracoes'
REFERER = 'https://fap-mps.dataprev.gov.br/procuracoes'
REPETICOES = 3

# As 39 "novas" do alerta de 09/09 17:01 — presentes só na janela 17:00–17:50.
TESTEMUNHAS = {
    '4728', '4730', '16347', '16371', '16384', '16393', '66025', '66029',
    '198579', '203370', '203389', '203396', '203406', '234567', '234568',
    '234572', '234844', '234881', '234888', '246866', '246868', '273227',
    '273243', '300222', '340607', '340609', '350991', '351002', '351005',
    '351075', '364636', '364649', '364650', '364653', '364673', '364674',
    '364676', '364680', '414660',
}

CABECALHOS_DE_INTERESSE = ('server', 'via', 'age', 'etag', 'cache-control',
                           'last-modified', 'x-cache', 'x-served-by', 'date')


def consultar(auth: FapWebAuthPayload) -> dict:
    svc = FapWebService(auth, use_env_fallback=False)
    req = urllib.request.Request(URL, headers=svc._base_headers(referer=REFERER), method='GET')
    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=30, context=svc._ssl_ctx) as resp:
            corpo, status, headers = resp.read(), resp.status, resp.headers
    except urllib.error.HTTPError as e:
        corpo, status, headers = b'', e.code, e.headers
    except Exception as e:
        return {'erro': f'{type(e).__name__}: {e}'}
    duracao = time.monotonic() - inicio

    rotas = set()
    nomes_set_cookie = []
    for valor in headers.get_all('Set-Cookie') or []:
        cookie = SimpleCookie()
        try:
            cookie.load(valor)
        except Exception:
            continue
        for nome, morsel in cookie.items():
            nomes_set_cookie.append(nome)
            if nome == 'ROUTEID':
                rotas.add(morsel.value)

    total = presentes = None
    tem_414660 = None
    if status == 200:
        try:
            itens = json.loads(corpo.decode('utf-8'))
            protocolos = {str(i.get('protocolo')).strip() for i in itens if isinstance(i, dict)}
            total = len(itens)
            presentes = len(protocolos & TESTEMUNHAS)
            tem_414660 = '414660' in protocolos
        except Exception as e:
            return {'status': status, 'erro': f'corpo não é a lista esperada: {e}'}

    return {
        'status': status,
        'segundos': round(duracao, 1),
        'total': total,
        'tem_414660': tem_414660,
        'testemunhas': f'{presentes}/{len(TESTEMUNHAS)}' if presentes is not None else None,
        'set_cookie': nomes_set_cookie,
        'rotas_devolvidas': sorted(rotas),
        'cabecalhos': {k: headers.get(k) for k in CABECALHOS_DE_INTERESSE if headers.get(k)},
    }


def rodar(rotulo: str, auth: FapWebAuthPayload) -> set:
    print(f'\n=== {rotulo} · ROUTEID enviado: {auth.cookies.get("ROUTEID", "(nenhum)")}')
    rotas = set()
    for n in range(1, REPETICOES + 1):
        r = consultar(auth)
        print(f'  #{n} {json.dumps(r, ensure_ascii=False)}')
        rotas.update(r.get('rotas_devolvidas') or [])
        time.sleep(2)
    return rotas


def main() -> int:
    base = FapWebAuthPayload.from_env()
    if base is None or not base.cookies:
        print('FAP_AUTH_JSON ausente ou sem cookies.')
        return 1

    print(f'Cookies no .env: {sorted(base.cookies)}')
    rotas = rodar('1. como está no .env', base)

    sem_rota = {k: v for k, v in base.cookies.items() if k != 'ROUTEID'}
    rotas |= rodar('2. sem ROUTEID', FapWebAuthPayload(cookies=sem_rota, user_agent=base.user_agent))

    for rota in sorted(rotas - {base.cookies.get('ROUTEID')}):
        fixada = dict(sem_rota, ROUTEID=rota)
        rodar(f'3. fixado na rota devolvida pelo portal', FapWebAuthPayload(cookies=fixada, user_agent=base.user_agent))

    return 0


if __name__ == '__main__':
    sys.exit(main())
