#!/usr/bin/env python3
"""
Testa o controle de rate limit do ComunicaPjeClient:
- intervalo mínimo entre requisições consecutivas (pacing global, não só entre páginas)
- respeito ao header Retry-After em respostas 429

Uso: uv run python tests/test_comunica_pje_rate_limit.py
Não faz nenhuma chamada de rede (HTTP e sleep são simulados).
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services import comunica_pje_client as cpc

failures = []


def check(name, cond, detail=''):
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f' — {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(name)


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {'items': []}
        self.headers = headers or {}
        self.text = ''

    def json(self):
        return self._payload


def run_scenario(responses):
    """Executa _get com respostas simuladas; retorna (resultado/erro, sleeps)."""
    sleeps = []
    clock = {'now': 1000.0}

    def fake_sleep(seconds):
        sleeps.append(round(seconds, 2))
        clock['now'] += seconds

    def fake_monotonic():
        return clock['now']

    client = cpc.ComunicaPjeClient()
    responses_iter = iter(responses)

    def fake_get(url, params=None, timeout=None):
        clock['now'] += 0.01  # tempo da própria requisição
        return next(responses_iter)

    with patch.object(client.session, 'get', side_effect=fake_get), \
         patch.object(cpc.time, 'sleep', side_effect=fake_sleep), \
         patch.object(cpc.time, 'monotonic', side_effect=fake_monotonic):
        try:
            result = client._get('/comunicacao', {'pagina': 1})
        except cpc.ComunicaPjeError as exc:
            result = exc
        # segunda chamada logo em seguida — deve esperar o intervalo mínimo
        try:
            client._get('/comunicacao', {'pagina': 2})
        except (cpc.ComunicaPjeError, StopIteration):
            pass
    return result, sleeps


# 1) Duas requisições OK em sequência → pacing entre elas
result, sleeps = run_scenario([FakeResponse(200), FakeResponse(200)])
check('resposta 200 retorna payload', isinstance(result, dict))
pacing = [s for s in sleeps if 0 < s <= cpc.MIN_REQUEST_INTERVAL_SECONDS]
check('há pausa de pacing entre requisições consecutivas', len(pacing) >= 1, f'sleeps={sleeps}')

# 2) 429 → espera a orientação oficial do DJEN (1 minuto), mesmo sem Retry-After
result, sleeps = run_scenario([
    FakeResponse(429),
    FakeResponse(200),
    FakeResponse(200),
])
check('429 espera >= 60s (orientação oficial do DJEN)',
      any(s >= cpc.RATE_LIMIT_WAIT_SECONDS for s in sleeps), f'sleeps={sleeps}')
check('após a espera a requisição é refeita e retorna 200', isinstance(result, dict))

# 3) 429 com Retry-After maior que 60s → respeita o maior valor
result, sleeps = run_scenario([
    FakeResponse(429, headers={'Retry-After': '90'}),
    FakeResponse(200),
    FakeResponse(200),
])
check('429 com Retry-After 90 espera >= 90s', any(s >= 90 for s in sleeps), f'sleeps={sleeps}')

# 4) 5xx → backoff exponencial curto (não os 60s do rate limit)
result, sleeps = run_scenario([
    FakeResponse(500),
    FakeResponse(200),
    FakeResponse(200),
])
check('500 usa backoff exponencial', any(cpc.BACKOFF_BASE_SECONDS <= s < 60 for s in sleeps),
      f'sleeps={sleeps}')

# 5) x-ratelimit-remaining baixo em resposta 200 → pausa preventiva antes da próxima
result, sleeps = run_scenario([
    FakeResponse(200, headers={'x-ratelimit-remaining': '0', 'x-ratelimit-limit': '60'}),
    FakeResponse(200),
])
check('janela esgotada (remaining=0) gera pausa preventiva >= 60s',
      any(s >= cpc.RATE_LIMIT_WAIT_SECONDS for s in sleeps), f'sleeps={sleeps}')

# 6) 429 persistente → esgota tentativas com erro claro
result, sleeps = run_scenario([FakeResponse(429)] * (cpc.MAX_RETRIES + 1))
check('429 persistente levanta ComunicaPjeError', isinstance(result, cpc.ComunicaPjeError),
      str(type(result)))

if failures:
    print(f'\n❌ {len(failures)} falha(s): {failures}')
    sys.exit(1)
print('\n✅ Todos os testes passaram!')
