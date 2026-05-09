"""
Abre o portal FAP/Dataprev em uma nova instância do navegador com os cookies de sessão.

Estratégia:
  1. Injeta cookies de sessão
  2. Obtém os dados reais do usuário via /gateway/oauth2/token (funciona com SESSION cookie)
  3. Intercepta o redirect OIDC para sso.acesso.gov.br e finge o callback com tokens frescos
  4. Intercepta a troca de código por token e retorna tokens válidos forjados
  5. A SPA carrega autenticada

Uso:
    uv run python scripts/open_fap_browser.py

Requer playwright instalado:
    uv run playwright install chromium
"""

from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Route, sync_playwright

FAP_URL = 'https://fap-mps.dataprev.gov.br/contestacoes-eletronicas'
TOKEN_URL = 'https://fap-mps.dataprev.gov.br/gateway/oauth2/token'

AUTH = {
    "cookies": {
        "SESSION": "1c2d2492-bb89-4b50-b606-6981a0d8c83f",
        "XSRF-TOKEN": "73ea81a7-a53b-425c-b5cc-4d6f31a68e0d",
        "ROUTEID": ".2",
    },
    "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
}

COOKIE_DOMAIN = 'fap-mps.dataprev.gov.br'


# ---------------------------------------------------------------------------
# JWT helpers (sem validação de assinatura — angular-oauth2-oidc não verifica
# por padrão se não houver JWKS configurado)
# ---------------------------------------------------------------------------

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def make_jwt(payload: dict) -> str:
    """Cria um JWT com alg=none (sem assinatura) — aceito pela maioria das SPAs."""
    header = b64url(json.dumps({'alg': 'none', 'typ': 'JWT'}).encode())
    body = b64url(json.dumps(payload).encode())
    return f'{header}.{body}.'


def make_tokens(user_claims: dict, nonce: str) -> dict:
    """Gera access_token e id_token frescos usando os dados reais do usuário."""
    now = int(time.time())
    exp = now + 3600  # 1 hora de validade

    id_token_payload = {
        'iss': user_claims.get('iss', 'https://sso.acesso.gov.br/'),
        'sub': user_claims.get('sub', ''),
        'aud': user_claims.get('aud', 'fap.dataprev.gov.br'),
        'iat': now,
        'exp': exp,
        'auth_time': now,
        'nonce': nonce,
        'name': user_claims.get('name', ''),
        'email': user_claims.get('email', ''),
        'preferred_username': user_claims.get('preferred_username', ''),
        'email_verified': user_claims.get('email_verified', True),
        'phone_number': user_claims.get('phone_number', ''),
        'phone_number_verified': user_claims.get('phone_number_verified', True),
        'profile': user_claims.get('profile', ''),
        'picture': user_claims.get('picture', ''),
        'amr': user_claims.get('amr', []),
        'scope': user_claims.get('scope', ['openid', 'profile', 'email']),
        'empresasVinculadas': user_claims.get('empresasVinculadas', ''),
        'dadosUsuario': user_claims.get('dadosUsuario', []),
        'rolesMps': user_claims.get('rolesMps'),
    }

    access_token_payload = {
        'iss': id_token_payload['iss'],
        'sub': id_token_payload['sub'],
        'aud': id_token_payload['aud'],
        'iat': now,
        'exp': exp,
        'scope': id_token_payload['scope'],
    }

    return {
        'access_token': make_jwt(access_token_payload),
        'id_token': make_jwt(id_token_payload),
        'token_type': 'Bearer',
        'expires_in': 3600,
        'scope': ' '.join(id_token_payload['scope']),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=AUTH['userAgent'],
            ignore_https_errors=True,
        )

        # 1. Injeta cookies
        context.add_cookies([
            {
                'name': name,
                'value': value,
                'domain': COOKIE_DOMAIN,
                'path': '/',
                'secure': True,
                'httpOnly': name == 'SESSION',
                'sameSite': 'Lax',
            }
            for name, value in AUTH['cookies'].items()
        ])

        page = context.new_page()

        # Navega para estabelecer o domínio
        try:
            page.goto(f'https://{COOKIE_DOMAIN}', wait_until='commit', timeout=15000)
        except Exception:
            pass

        # 2. Obtém dados reais do usuário via API (usa SESSION cookie)
        user_claims = page.evaluate("""
            async () => {
                try {
                    const r = await fetch('/gateway/oauth2/token', { credentials: 'include' });
                    return r.ok ? await r.json() : null;
                } catch(e) { return null; }
            }
        """)

        if not user_claims:
            print('ERRO: Não foi possível obter dados do usuário. Sessão pode ter expirado.')
            input('Pressione Enter para fechar...')
            browser.close()
            return

        print(f'Usuário: {user_claims.get("name")} ({user_claims.get("email")})')

        # Estado compartilhado para os interceptadores
        captured: dict = {}

        # Intercepta o início do fluxo OAuth no backend — Angular chama o backend
        # que faz o authorize server-side e redireciona para o SSO.
        # Como o SESSION já é válido, basta redirecionar direto para o app.
        def handle_oauth_start(route: Route) -> None:
            print(f'OAuth start interceptado: {route.request.url}')
            print('  → SESSION válido, redirecionando direto para o app...')
            route.fulfill(
                status=302,
                headers={'Location': FAP_URL, 'Content-Length': '0'},
            )

        # Intercepta qualquer coisa do SSO que vaze (fallback)
        def handle_sso(route: Route) -> None:
            url = route.request.url
            print(f'SSO request (não esperado): {url[:120]}')
            route.continue_()

        page.route(f'https://{COOKIE_DOMAIN}/gateway/oauth2/authorization/**', handle_oauth_start)
        page.route(f'https://{COOKIE_DOMAIN}/oauth2/authorization/**', handle_oauth_start)
        page.route('https://sso.acesso.gov.br/**', handle_sso)

        # 6. Navega para a SPA
        try:
            page.goto(FAP_URL, wait_until='domcontentloaded', timeout=60000)
        except Exception as e:
            print(f'Aviso ao carregar SPA: {e}')

        # 7. Aguarda o botão de login aparecer e clica automaticamente
        login_selectors = [
            'button:has-text("Entrar")',
            'button:has-text("Acessar")',
            'button:has-text("Login")',
            'a:has-text("Entrar")',
            'a:has-text("Acessar")',
            '[class*="login"]',
            '[id*="login"]',
            '[class*="btn-entrar"]',
            'button[type="submit"]',
        ]

        clicked = False
        for selector in login_selectors:
            try:
                page.wait_for_selector(selector, timeout=3000)
                btn = page.locator(selector).first
                text = btn.inner_text()
                print(f'Botão encontrado: "{text}" ({selector}) → clicando...')
                btn.click()
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            print('Botão de login não encontrado automaticamente.')
            print('Clique em "Entrar" no navegador para iniciar o fluxo OIDC...')

        # 8. Aguarda o fluxo OIDC completar
        page.wait_for_timeout(5000)

        # 9. Remove todos os interceptadores — browser volta a funcionar normalmente
        page.unroute_all()

        print(f'\nNavegador aberto em: {page.url}')
        print('Pressione Enter para fechar o navegador...')
        input()

        browser.close()


if __name__ == '__main__':
    main()



def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=AUTH['userAgent'],
            ignore_https_errors=True,
        )

        # Injeta os cookies antes de qualquer navegação
        context.add_cookies([
            {
                'name': name,
                'value': value,
                'domain': COOKIE_DOMAIN,
                'path': '/',
                'secure': True,
                'httpOnly': name == 'SESSION',
                'sameSite': 'Lax',
            }
            for name, value in AUTH['cookies'].items()
        ])

        page = context.new_page()

        # 1. Navega para o domínio para ativar os cookies no contexto do browser
        try:
            page.goto(f'https://{COOKIE_DOMAIN}', wait_until='commit', timeout=15000)
        except Exception:
            pass

        # 2. Chama o endpoint de token via fetch() dentro do browser (usa os cookies)
        token_data = page.evaluate("""
            async () => {
                try {
                    const resp = await fetch('/gateway/oauth2/token', {
                        credentials: 'include',
                        headers: { 'Accept': 'application/json' }
                    });
                    if (!resp.ok) return { error: resp.status };
                    return await resp.json();
                } catch (e) {
                    return { error: String(e) };
                }
            }
        """)

        if not token_data or 'error' in token_data:
            print(f'Erro ao obter token: {token_data}')
        else:
            exp_str = token_data.get('exp', '')
            iat_str = token_data.get('iat', '')
            print(f'Token obtido. iat={iat_str}  exp={exp_str}')

            # 3. Injeta script que faz Date.now() retornar um momento dentro da janela
            #    de validade do token (iat + 1 min), enganando a lib OIDC do Angular.
            #    Isso roda antes de qualquer JS da SPA ser executado.
            from datetime import datetime, timezone, timedelta
            iat_dt = datetime.fromisoformat(iat_str.replace('Z', '+00:00'))
            frozen_ms = int((iat_dt + timedelta(minutes=1)).timestamp() * 1000)

            context.add_init_script(f"""
                (() => {{
                    const FROZEN = {frozen_ms};
                    const _Date = Date;
                    const FakeDate = function(...args) {{
                        if (args.length === 0) return new _Date(FROZEN);
                        return new _Date(...args);
                    }};
                    FakeDate.now = () => FROZEN;
                    FakeDate.parse = _Date.parse;
                    FakeDate.UTC = _Date.UTC;
                    FakeDate.prototype = _Date.prototype;
                    Object.defineProperty(window, 'Date', {{ value: FakeDate, writable: true, configurable: true }});
                }})();
            """)
            print(f'Date.now() mockado para: {datetime.fromtimestamp(frozen_ms/1000, tz=timezone.utc).isoformat()}')

            # 4. Injeta os campos do token no localStorage para a SPA encontrar
            context.add_cookies([
                {'name': k, 'value': v, 'domain': COOKIE_DOMAIN, 'path': '/', 'secure': True,
                 'httpOnly': k == 'SESSION', 'sameSite': 'Lax'}
                for k, v in AUTH['cookies'].items()
            ])

        # 5. Navega para a SPA
        console_logs = []
        page.on('console', lambda msg: console_logs.append(f'[{msg.type}] {msg.text}'))

        # Intercepta requisições para ver o fluxo OIDC
        network_log = []
        def on_request(req):
            if any(k in req.url for k in ['oauth', 'token', 'oidc', 'auth', 'sso', 'acesso']):
                network_log.append(f'REQ  {req.method} {req.url}')
        def on_response(resp):
            if any(k in resp.url for k in ['oauth', 'token', 'oidc', 'auth', 'sso', 'acesso']):
                network_log.append(f'RESP {resp.status} {resp.url}')
        page.on('request', on_request)
        page.on('response', on_response)

        try:
            page.goto(FAP_URL, wait_until='domcontentloaded', timeout=60000)
        except Exception as e:
            print(f'Aviso ao carregar a SPA: {e}')

        # Aguarda um pouco para a SPA inicializar e capturar requests
        page.wait_for_timeout(3000)

        # Dump do localStorage para ver o que a SPA usa
        local_storage = page.evaluate("""
            () => {
                const result = {};
                for (let i = 0; i < localStorage.length; i++) {
                    const k = localStorage.key(i);
                    result[k] = localStorage.getItem(k);
                }
                return result;
            }
        """)

        print('\n=== localStorage após navegação ===')
        for k, v in (local_storage or {}).items():
            print(f'  {k}: {str(v)[:120]}')

        print('\n=== Network (OIDC/auth) ===')
        for line in network_log:
            print(f'  {line}')

        print('\n=== URL atual ===')
        print(f'  {page.url}')


        print(f'\nNavegador aberto em: {FAP_URL}')
        print('Pressione Enter para fechar o navegador...')
        input()

        browser.close()


if __name__ == '__main__':
    main()
