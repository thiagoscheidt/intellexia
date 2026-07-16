#!/usr/bin/env python3
"""
Teste das URLs públicas (app/utils/urls.py).

Cada instalação responde por um domínio diferente (dev, produção), então o
endereço mostrado ao usuário — modal do conector MCP, manual, links dos e-mails —
não pode ser fixo. Este teste trava esse comportamento:

    uv run python tests/test_public_urls.py

Cobre:
  1. Dentro de requisição, vale o domínio acessado (mesmo com .env de outro ambiente)
  2. Atrás do nginx, respeita X-Forwarded-Proto/Host (a app não usa ProxyFix)
  3. Fora de requisição (cron), usa APP_PUBLIC_URL
  4. MCP_PUBLIC_URL explícito vence (MCP em subdomínio próprio)
  5. O manual renderiza :url_mcp: com o domínio certo e o cache não mistura domínios
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.services.manual_renderer import render_modules
from app.utils.urls import FALLBACK_BASE_URL, app_public_url, mcp_public_url

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _limpa_env():
    os.environ.pop('APP_PUBLIC_URL', None)
    os.environ.pop('MCP_PUBLIC_URL', None)


def test_dominio_da_requisicao():
    print('\n1) Dentro de requisição vale o domínio acessado')
    _limpa_env()
    with app.test_request_context(base_url='http://localhost:5051'):
        check('dev direto', mcp_public_url() == 'http://localhost:5051/mcp', mcp_public_url())

    # O cenário do bug: .env copiado de outro ambiente não pode vencer o domínio real.
    os.environ['APP_PUBLIC_URL'] = 'https://ambiente-errado.example.com'
    with app.test_request_context(base_url='https://app.intellexia.com.br'):
        check('.env de outro ambiente não sobrepõe o domínio acessado',
              mcp_public_url() == 'https://app.intellexia.com.br/mcp', mcp_public_url())
    _limpa_env()


def test_atras_do_nginx():
    print('\n2) Atrás do nginx (sem ProxyFix, lendo X-Forwarded-*)')
    _limpa_env()
    with app.test_request_context(base_url='http://app.intellexia.com.br',
                                  headers={'X-Forwarded-Proto': 'https'}):
        check('X-Forwarded-Proto vira https',
              mcp_public_url() == 'https://app.intellexia.com.br/mcp', mcp_public_url())

    with app.test_request_context(base_url='http://127.0.0.1:8000',
                                  headers={'X-Forwarded-Proto': 'https',
                                           'X-Forwarded-Host': 'app.intellexia.com.br'}):
        check('X-Forwarded-Host vence o Host interno',
              mcp_public_url() == 'https://app.intellexia.com.br/mcp', mcp_public_url())


def test_sem_requisicao():
    print('\n3) Fora de requisição (cron das notificações)')
    _limpa_env()
    os.environ['APP_PUBLIC_URL'] = 'https://app.intellexia.com.br'
    check('usa APP_PUBLIC_URL', app_public_url() == 'https://app.intellexia.com.br', app_public_url())
    check('MCP derivado dele', mcp_public_url() == 'https://app.intellexia.com.br/mcp', mcp_public_url())

    _limpa_env()
    check('sem env algum, cai no fallback (e loga aviso)',
          app_public_url() == FALLBACK_BASE_URL, app_public_url())


def test_mcp_em_subdominio():
    print('\n4) MCP em subdomínio próprio')
    _limpa_env()
    os.environ['MCP_PUBLIC_URL'] = 'https://mcp.intellexia.com.br/mcp'
    with app.test_request_context(base_url='https://app.intellexia.com.br'):
        check('MCP_PUBLIC_URL explícito vence',
              mcp_public_url() == 'https://mcp.intellexia.com.br/mcp', mcp_public_url())
        check('app_public_url segue o domínio da requisição',
              app_public_url() == 'https://app.intellexia.com.br', app_public_url())

    os.environ['MCP_PUBLIC_URL'] = 'https://mcp.intellexia.com.br/mcp/'
    check('barra final removida (o cliente compara o resource exato)',
          mcp_public_url() == 'https://mcp.intellexia.com.br/mcp', mcp_public_url())
    _limpa_env()


def test_manual():
    print('\n5) Manual segue o domínio (marcador :url_mcp:)')
    _limpa_env()

    def html_do_manual():
        return [m for m in render_modules() if m['id'] == 'conectar-ia'][0]['html']

    with app.test_request_context(base_url='https://app.intellexia.com.br'):
        html = html_do_manual()
        check('mostra a URL desta instalação', 'https://app.intellexia.com.br/mcp' in html)
        check('não vaza domínio fixo de outro ambiente', 'rs-dev' not in html)
        check('não vaza o marcador cru', ':url_mcp:' not in html and ':url_app:' not in html)

    # O cache é por mtime + domínio: outro domínio não pode receber o HTML anterior.
    with app.test_request_context(base_url='https://outro.exemplo.com.br'):
        html = html_do_manual()
        check('cache não serve o domínio anterior',
              'https://outro.exemplo.com.br/mcp' in html and 'app.intellexia.com.br' not in html)


def main():
    test_dominio_da_requisicao()
    test_atras_do_nginx()
    test_sem_requisicao()
    test_mcp_em_subdominio()
    test_manual()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} verificação(ões) falharam:')
        for f in _falhas:
            print(f'   · {f}')
        return 1
    print('✅ Todas as verificações passaram.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
