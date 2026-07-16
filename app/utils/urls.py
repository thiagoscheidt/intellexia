"""
URLs públicas do sistema.

Fonte única para "qual é o endereço deste IntellexIA" — usado no modal do
conector MCP, no manual e nos links dos e-mails. Cada instalação (dev, produção)
responde por um domínio diferente, então **nada de URL fixa no código ou na
documentação**: resolve-se aqui.

``app_public_url()`` resolve nesta ordem:

1. O domínio da requisição atual (respeita ``X-Forwarded-Proto``/``X-Forwarded-Host``
   do nginx, já que a app não usa ProxyFix) — dentro de uma requisição, o endereço
   pelo qual o usuário está acessando é a verdade, e é o que faz a tela e o manual
   seguirem o domínio sozinhos ao publicar em produção;
2. ``APP_PUBLIC_URL``, para quando não há requisição (cron das notificações);
3. Como último recurso, o domínio de desenvolvimento.

``mcp_public_url()`` inverte a prioridade e olha ``MCP_PUBLIC_URL`` primeiro: é a
mesma variável que configura o servidor MCP (deploy/intellexia-mcp.service), e o
endereço mostrado ao usuário precisa bater **exatamente** com o que o servidor
anuncia — inclusive quando o MCP vive em outro subdomínio.
"""
import logging
import os

from flask import has_request_context, request

logger = logging.getLogger(__name__)

FALLBACK_BASE_URL = 'https://rs-dev.intellexia.com.br'


def _request_base_url() -> str | None:
    """Base da requisição atual, atrás do nginx (X-Forwarded-*) ou direto."""
    if not has_request_context():
        return None

    proto = (request.headers.get('X-Forwarded-Proto') or '').split(',')[0].strip()
    host = (request.headers.get('X-Forwarded-Host') or '').split(',')[0].strip()

    proto = proto or request.scheme
    host = host or request.host
    if not host:
        return None
    return f'{proto}://{host}'


def app_public_url() -> str:
    """Endereço público deste IntellexIA, sem barra final.

    Dentro de uma requisição vale o domínio acessado — assim uma instalação nova
    (ou um `.env` copiado de outro ambiente) nunca mostra o endereço errado.
    """
    from_request = _request_base_url()
    if from_request:
        return from_request.rstrip('/')

    env = (os.environ.get('APP_PUBLIC_URL') or '').strip()
    if env:
        return env.rstrip('/')

    # Fora de requisição e sem APP_PUBLIC_URL: os links sairão com o domínio de
    # desenvolvimento. Em produção isso é erro de configuração — avise alto.
    logger.warning(
        'APP_PUBLIC_URL não definido e sem requisição em curso: usando %s nos links. '
        'Defina APP_PUBLIC_URL no .env com o domínio desta instalação.', FALLBACK_BASE_URL
    )
    return FALLBACK_BASE_URL


def mcp_public_url() -> str:
    """Endereço público do conector MCP, sem barra final.

    A barra final importa: o cliente compara o *resource* exatamente, e uma
    barra sobrando faz o Claude recusar a conexão.
    """
    env = (os.environ.get('MCP_PUBLIC_URL') or '').strip()
    if env:
        return env.rstrip('/')
    return f'{app_public_url()}/mcp'
