#!/usr/bin/env python3
"""
Vigência do ano seguinte no portal FAP — FAP-34 da Remessa R09.

A vigência N é divulgada no ano N-1 (o índice sai até 30/09 e as contestações
são feitas em novembro), mas cron, Painel FAP e importação automática só iam
até o ano do calendário: a vigência 2027 chegaria ao sistema em janeiro de
2027. E o portal responde a vigência ainda não publicada com 403
{"mensagem": "Vigência informada ainda não publicada: 2028"} — que o código
lia como sessão expirada / sem procuração.

Sem rede: o GET do portal é trocado por um dublê.

    uv run python tests/test_fap_vigencia_seguinte.py
"""

import io
import sys
import urllib.error
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.services import fap_vigencia_service as vig
from app.services.fap_web_service import FapWebAuthPayload, FapWebService

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def test_anos_portal():
    print('\n1. Até que vigência consultar')
    check('em setembro de 2026, até 2026', vig.anos_portal(hoje=date(2026, 9, 30))[0] == 2026)
    check('a partir de outubro de 2026, até 2027', vig.anos_portal(hoje=date(2026, 10, 1))[0] == 2027)
    check('em dezembro de 2026, até 2027', vig.anos_portal(hoje=date(2026, 12, 31))[0] == 2027)
    check('em janeiro de 2027, até 2027', vig.anos_portal(hoje=date(2027, 1, 2))[0] == 2027)
    anos = vig.anos_portal(hoje=date(2026, 10, 20))
    check('da mais nova para a mais antiga, até 2010', anos[0] == 2027 and anos[-1] == 2010
          and anos == sorted(anos, reverse=True), str(anos[:3]))
    check('início configurável', vig.anos_portal(inicio=2024, hoje=date(2026, 10, 20)) == [2027, 2026, 2025, 2024])


def _http_error(code, corpo):
    return urllib.error.HTTPError('https://fap', code, 'x', {}, io.BytesIO(corpo.encode()))


def test_portal_vigencia_nao_publicada():
    print('\n2. Vigência ainda não publicada não é sessão expirada')
    svc = FapWebService(FapWebAuthPayload.from_json('{"cookies": {"SESSION": "x"}}'))

    svc._raw_get = lambda *a, **k: (_ for _ in ()).throw(_http_error(
        403, '{"status":403,"mensagem":"Vigência informada ainda não publicada: 2028","erros":[]}'))
    r = svc.fetch_contestacoes('07718633', 2028)
    check('403 "ainda não publicada" volta ok, sem contestações', r.ok and r.data == [], str(r))
    check('… e não marca expirada', not r.expired)

    svc._raw_get = lambda *a, **k: (_ for _ in ()).throw(_http_error(403, '{"mensagem":"Acesso negado"}'))
    r = svc.fetch_contestacoes('07718633', 2026)
    check('outro 403 continua sendo acesso negado', not r.ok and r.expired)

    svc._raw_get = lambda *a, **k: (b'[]', 200)
    r = svc.fetch_contestacoes('07718633', 2027)
    check('vigência publicada sem contestação volta lista vazia', r.ok and r.data == [])


def test_telas_e_cron():
    print('\n3. Telas e cron usam a mesma regra')
    import importlib.util

    raiz = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('fap_sync_cron', raiz / 'scripts' / 'fap_sync_cron.py')
    cron = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cron)
    import os
    antigos = {k: os.environ.pop(k, None) for k in ('FAP_SYNC_YEARS', 'FAP_SYNC_START_YEAR')}
    try:
        check('cron vai até a vigência mais nova', cron._get_sync_years() == vig.anos_portal(),
              str(cron._get_sync_years()[:3]))
    finally:
        for k, v in antigos.items():
            if v is not None:
                os.environ[k] = v

    from app.blueprints import disputes_center, fap_panel
    import inspect
    check('Painel FAP não tem mais a lista fixa do arranque', not hasattr(fap_panel, 'FAP_AVAILABLE_YEARS'))
    check('importação automática usa anos_portal',
          'fap_vigencia_service.anos_portal()' in inspect.getsource(disputes_center.fap_auto_import))


def main() -> int:
    with app.app_context():
        test_anos_portal()
        test_portal_vigencia_nao_publicada()
        test_telas_e_cron()

    print('\n' + '=' * 62)
    if _falhas:
        print(f'❌ {len(_falhas)} verificação(ões) falharam:')
        for nome in _falhas:
            print(f'   - {nome}')
        return 1
    print('✅ Tudo verde')
    return 0


if __name__ == '__main__':
    sys.exit(main())
