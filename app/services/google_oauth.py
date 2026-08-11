"""
Login com Google (OpenID Connect) — configuração isolada do Authlib.

O Google só *autentica* (prova que a pessoa é dona do e-mail); quem *autoriza* é o
IntellexIA: o e-mail precisa existir em ``users``. Ver
``app/blueprints/auth.py`` para as regras de decisão.

Sem ``GOOGLE_CLIENT_ID``/``GOOGLE_CLIENT_SECRET`` no ``.env`` o recurso
simplesmente não existe — ``google_login_enabled()`` devolve ``False``, o botão
some da tela de login e as rotas respondem com erro amigável.
"""
import logging
import os
from urllib.parse import urlparse

from flask import url_for

from app.utils.urls import app_public_url

logger = logging.getLogger(__name__)

GOOGLE_METADATA_URL = 'https://accounts.google.com/.well-known/openid-configuration'

# Host do CDN onde o Google serve as fotos de perfil (lh3, lh5, ... .googleusercontent.com).
PICTURE_HOST = 'googleusercontent.com'

_oauth = None


def _client_credentials():
    client_id = (os.environ.get('GOOGLE_CLIENT_ID') or '').strip()
    client_secret = (os.environ.get('GOOGLE_CLIENT_SECRET') or '').strip()
    return client_id, client_secret


def google_login_enabled() -> bool:
    """True quando o login com Google está configurado e pronto para uso."""
    client_id, client_secret = _client_credentials()
    return bool(client_id and client_secret and _oauth is not None)


def init_google_oauth(app) -> bool:
    """Registra o cliente OAuth do Google na aplicação Flask.

    Retorna ``False`` (sem levantar exceção) quando não há credenciais no
    ambiente: a aplicação sobe normalmente, só sem o botão do Google.
    """
    global _oauth

    client_id, client_secret = _client_credentials()
    if not client_id or not client_secret:
        logger.info(
            'Login com Google desativado: defina GOOGLE_CLIENT_ID e '
            'GOOGLE_CLIENT_SECRET no .env para habilitar.'
        )
        return False

    from authlib.integrations.flask_client import OAuth

    oauth = OAuth()
    oauth.init_app(app)
    oauth.register(
        name='google',
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=GOOGLE_METADATA_URL,
        client_kwargs={'scope': 'openid email profile'},
    )
    _oauth = oauth
    logger.info('Login com Google habilitado.')
    return True


def sanitize_picture_url(raw):
    """URL da foto de perfil vinda da claim ``picture``, ou ``None``.

    O valor termina num ``src`` de ``<img>`` renderizado para o usuário. O
    ``id_token`` é assinado pelo Google, então isso é cinto e suspensório — mas
    custa três linhas e fecha a porta para qualquer coisa que não seja ``https``
    no CDN dele. O host tem de *ser* ``googleusercontent.com`` ou terminar em
    ``.googleusercontent.com``: comparar só o final deixaria passar
    ``malgoogleusercontent.com``.
    """
    if not raw:
        return None

    url = str(raw).strip()
    try:
        partes = urlparse(url)
    except ValueError:
        return None

    host = (partes.hostname or '').lower()
    if partes.scheme != 'https':
        return None
    if host != PICTURE_HOST and not host.endswith('.' + PICTURE_HOST):
        return None

    return url


def google_client():
    """Cliente Authlib do Google, ou None quando não configurado."""
    if not google_login_enabled():
        return None
    return _oauth.create_client('google')


def google_redirect_uri() -> str:
    """URI de retorno registrada no Google Cloud Console.

    Montada com ``app_public_url()`` e não com ``_external=True``: a app não usa
    ProxyFix, então atrás do nginx o Flask geraria ``http://`` com host errado e o
    Google recusaria o ``redirect_uri``.
    """
    return f"{app_public_url()}{url_for('auth.google_callback')}"
