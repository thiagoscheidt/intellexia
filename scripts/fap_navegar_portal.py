#!/usr/bin/env python3
"""
Navega pelo portal FAP como um usuário, com a sessão do ``FAP_AUTH_JSON`` — experimento.

A lista de procurações só vem completa enquanto a sessão tem as **empresas
vinculadas** do gov.br. Sem elas o portal devolve só as procurações outorgadas ao
CPF do login e esconde as do CNPJ do escritório (foi o que atrasou o alerta da
SMARTFIT em 09/09/2026). O keep-alive por ``curl`` mantém a sessão viva, mas não
as empresas.

Em 10/09 abrir o portal não recuperou uma sessão que já estava parcial. Este
script testa outra coisa: se navegar a cada poucos minutos, desde o login,
**impede** a perda. Cada execução grava uma linha com o estado lido do tráfego da
própria página — é esse log que diz se funciona.

Sequência:
  1. Abre ``/`` com os cookies e o sessionStorage mínimo (``idp``, ``sessionId``)
     que o frontend exige para se considerar logado
  2. Pelo menu principal: Procurações Eletrônicas → Contestação Eletrônica →
     Consulta do FAP
  3. Lê das respostas que a página recebeu: ``/gateway/oauth2/token``
     (``empresasVinculadas``) e ``/gateway/fap/v1/procuracoes`` (total e quantas
     outorgadas a CNPJ)

Playwright não está no pyproject: rode com ``uv run --with playwright``.
Instale o Chromium uma vez no servidor:
  uv run --with playwright playwright install --with-deps chromium

Execução manual:
  uv run --with playwright python scripts/fap_navegar_portal.py
  uv run --with playwright python scripts/fap_navegar_portal.py --screenshot /tmp/fap_navegar.png

Cron sugerido (a cada 10 minutos, com lock):
  */10 * * * * cd /sites/intellexia && flock -n /tmp/intellexia_fap_navegar.lock \
      uv run --with playwright python scripts/fap_navegar_portal.py >> /var/log/intellexia/fap_navegar.log 2>&1

Códigos de saída:
  0 — navegou (a linha do log diz se a sessão está completa ou parcial)
  1 — erro (configuração ausente, portal fora, menu não encontrado)
  2 — sessão FAP expirada (atualize FAP_AUTH_JSON no .env)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # type: ignore[import]
load_dotenv(project_root / '.env')

BASE = 'https://fap-mps.dataprev.gov.br'
DOMINIO = 'fap-mps.dataprev.gov.br'
TIMEOUT_MS = 60_000

EXIT_OK = 0
EXIT_ERRO = 1
EXIT_SESSAO_EXPIRADA = 2

MENU_PRINCIPAL = 'button[aria-label="Abrir Menu Principal"]'
# (rótulo no log, href do item do menu) — na ordem em que a pessoa navegaria.
ROTAS = (
    ('Procurações', '/procuracoes'),
    ('Contestação', '/contestacoes-eletronicas'),
    ('Consulta FAP', '/consultar-fap'),
)

# O frontend só se considera logado com idp + sessionId no storage. O sessionId
# é usado apenas no navegador, então vai um valor fictício.
STORAGE_MINIMO = """
for (const st of [window.sessionStorage, window.localStorage]) {
  try {
    if (!st.getItem('idp')) st.setItem('idp', 'fapgovbridp');
    if (!st.getItem('sessionId')) st.setItem('sessionId', 'intellexia-navegador');
  } catch (e) {}
}
"""


class SessaoExpirada(Exception):
    pass


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _eh_token(resp) -> bool:
    return resp.request.method == 'GET' and resp.url.split('?')[0].endswith('/gateway/oauth2/token')


def _eh_lista_procuracoes(resp) -> bool:
    return resp.request.method == 'GET' and resp.url.split('?')[0].endswith('/gateway/fap/v1/procuracoes')


def _resumo_vinculadas(token: dict) -> tuple[bool, str]:
    """(completa?, texto) a partir do campo empresasVinculadas do token."""
    bruto = token.get('empresasVinculadas')
    try:
        dado = json.loads(bruto) if isinstance(bruto, str) else bruto
    except ValueError:
        return False, 'formato inesperado'
    if isinstance(dado, dict) and dado.get('errors'):
        codigos = ','.join(str(e.get('code', '?')) for e in dado['errors'])
        return False, f'erro {codigos}'
    if isinstance(dado, list):
        return len(dado) > 0, f'{len(dado)} empresa(s)'
    return False, 'ausente'


def _resumo_lista(itens) -> str:
    if not isinstance(itens, list):
        return 'resposta inesperada'
    a_cnpj = sum(1 for i in itens if isinstance(i, dict) and i.get('cnpjRaizOutorgado'))
    return f'{len(itens)} ({a_cnpj} outorgadas a CNPJ)'


def navegar(auth, screenshot: str | None) -> tuple[bool, str, str, list[str]]:
    from playwright.sync_api import sync_playwright

    visitadas: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(
                user_agent=auth.effective_user_agent,
                locale='pt-BR',
                viewport={'width': 1366, 'height': 900},
            )
            ctx.add_cookies([
                {'name': k, 'value': v, 'domain': DOMINIO, 'path': '/', 'secure': True}
                for k, v in auth.cookies.items() if k and v
            ])
            ctx.add_init_script(STORAGE_MINIMO)
            page = ctx.new_page()
            page.set_default_timeout(TIMEOUT_MS)

            try:
                with page.expect_response(_eh_token) as info_token:
                    page.goto(BASE + '/', wait_until='domcontentloaded')
                resp_token = info_token.value
                if resp_token.status in (401, 403):
                    raise SessaoExpirada(f'HTTP {resp_token.status} em /oauth2/token')
                completa, vinculadas = _resumo_vinculadas(resp_token.json())

                lista = 'não carregou'
                for rotulo, href in ROTAS:
                    page.locator(MENU_PRINCIPAL).click()
                    item = page.locator(f'a[href="{href}"]:visible').first
                    if href == '/procuracoes':
                        with page.expect_response(_eh_lista_procuracoes) as info_lista:
                            item.click()
                        resp_lista = info_lista.value
                        if resp_lista.status in (401, 403):
                            raise SessaoExpirada(f'HTTP {resp_lista.status} em /procuracoes')
                        lista = _resumo_lista(resp_lista.json())
                    else:
                        item.click()
                    page.wait_for_load_state('networkidle')
                    visitadas.append(rotulo)
            finally:
                if screenshot:
                    try:
                        page.screenshot(path=screenshot)
                    except Exception:
                        pass
        finally:
            browser.close()

    return completa, vinculadas, lista, visitadas


def main() -> int:
    parser = argparse.ArgumentParser(description='Navega pelo portal FAP com a sessão do FAP_AUTH_JSON.')
    parser.add_argument('--screenshot', default=None,
                        help='grava um print da última tela neste caminho (contém dados de clientes)')
    args = parser.parse_args()

    if not os.environ.get('FAP_AUTH_JSON', '').strip():
        _log('ERRO: FAP_AUTH_JSON não encontrado no .env. Abortando.')
        return EXIT_ERRO

    from app.services.fap_web_service import FapWebAuthPayload
    try:
        auth = FapWebAuthPayload.from_env()
    except Exception as e:
        _log(f'ERRO: FAP_AUTH_JSON inválido: {e}. Abortando.')
        return EXIT_ERRO
    if auth is None or not auth.cookies:
        _log('ERRO: FAP_AUTH_JSON sem cookies. Abortando.')
        return EXIT_ERRO

    try:
        completa, vinculadas, lista, visitadas = navegar(auth, args.screenshot)
    except SessaoExpirada as e:
        _log(f'ERRO: sessão FAP expirada ({e}). Atualize FAP_AUTH_JSON no .env.')
        return EXIT_SESSAO_EXPIRADA
    except Exception as e:
        _log(f'ERRO ao navegar no portal: {type(e).__name__}: {str(e).splitlines()[0][:200]}')
        return EXIT_ERRO

    estado = 'completa' if completa else 'PARCIAL'
    _log(f"Sessão {estado} · empresas vinculadas: {vinculadas} · procurações: {lista} · "
         f"navegou: {' → '.join(visitadas)}")
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
