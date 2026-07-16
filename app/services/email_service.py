"""
Envio de e-mails por SMTP.

Base reutilizável para qualquer e-mail do sistema (notificações, avisos, etc.).
Usa apenas a biblioteca padrão (``smtplib``) — sem dependência nova.

Configuração via ``.env`` (o servidor é global da plataforma; a senha nunca é
gravada no banco nem exibida em tela):

    SMTP_HOST=smtp.exemplo.com.br
    SMTP_PORT=587              # 465 usa SSL direto; demais usam STARTTLS
    SMTP_USER=usuario
    SMTP_PASSWORD=senha
    SMTP_FROM_EMAIL=nao-responda@exemplo.com.br
    SMTP_FROM_NAME=IntellexIA
    SMTP_USE_TLS=1             # '0' desativa o STARTTLS (relay interno sem TLS)
    SMTP_TIMEOUT=30

Degradação graciosa (convenção do projeto): sem configuração, ``send_email``
apenas registra um aviso e retorna ``False`` — nunca lança para o chamador.
"""
import logging
import os
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

DEFAULT_PORT = 587
SSL_PORT = 465
DEFAULT_TIMEOUT = 30


def _env(name: str, default: str = '') -> str:
    return (os.environ.get(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = True) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in ('1', 'true', 'yes', 'on', 'sim')


def get_config() -> dict:
    """Configuração SMTP atual (sem expor a senha)."""
    host = _env('SMTP_HOST')
    port = _env_int('SMTP_PORT', DEFAULT_PORT)
    from_email = _env('SMTP_FROM_EMAIL') or _env('SMTP_USER')
    return {
        'host': host,
        'port': port,
        'user': _env('SMTP_USER'),
        'has_password': bool(_env('SMTP_PASSWORD')),
        'from_email': from_email,
        'from_name': _env('SMTP_FROM_NAME', 'IntellexIA'),
        'use_tls': _env_bool('SMTP_USE_TLS', True),
        'timeout': _env_int('SMTP_TIMEOUT', DEFAULT_TIMEOUT),
    }


def is_configured() -> bool:
    """True quando há o mínimo para enviar: servidor e remetente."""
    cfg = get_config()
    return bool(cfg['host'] and cfg['from_email'])


def is_valid_email(address: str) -> bool:
    return bool(EMAIL_PATTERN.match((address or '').strip()))


def normalize_recipients(recipients) -> list[str]:
    """Lista de e-mails válidos, sem repetição e preservando a ordem."""
    if isinstance(recipients, str):
        recipients = re.split(r'[,;\s]+', recipients)

    cleaned: list[str] = []
    for item in recipients or []:
        address = (item or '').strip()
        if address and is_valid_email(address) and address.lower() not in [c.lower() for c in cleaned]:
            cleaned.append(address)
    return cleaned


def _html_to_text(html: str) -> str:
    """Alternativa em texto puro — simples, só para clientes sem HTML."""
    text = re.sub(r'(?is)<(script|style).*?</\1>', '', html or '')
    text = re.sub(r'(?i)<br\s*/?>', '\n', text)
    text = re.sub(r'(?i)</(p|div|tr|h[1-6]|li)>', '\n', text)
    text = re.sub(r'(?i)</td>', ' ', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = (text.replace('&nbsp;', ' ').replace('&amp;', '&')
                .replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"'))
    text = re.sub(r'\n{3,}', '\n\n', text)
    return '\n'.join(line.strip() for line in text.splitlines()).strip()


def build_message(to: list[str], subject: str, html: str, text: str | None = None,
                  inline_images: dict | None = None, reply_to: str | None = None) -> EmailMessage:
    """Monta a mensagem multipart (texto + HTML + imagens embutidas por CID).

    ``inline_images``: ``{"logo": b"...bytes..."}`` — a chave é referenciada no
    HTML como ``<img src="cid:logo">``.
    """
    cfg = get_config()

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = formataddr((cfg['from_name'], cfg['from_email']))
    msg['To'] = ', '.join(to)
    if reply_to:
        msg['Reply-To'] = reply_to
    msg['Auto-Submitted'] = 'auto-generated'  # evita autorresposta de férias/ausência

    msg.set_content(text or _html_to_text(html))

    # Os CIDs precisam existir no HTML antes de anexar as imagens.
    html_final = html
    cid_by_key = {}
    for key in (inline_images or {}):
        cid = make_msgid(domain='intellexia.local')
        cid_by_key[key] = cid
        html_final = html_final.replace(f'cid:{key}', f'cid:{cid[1:-1]}')

    msg.add_alternative(html_final, subtype='html')

    if inline_images:
        html_part = msg.get_payload()[-1]
        for key, data in inline_images.items():
            html_part.add_related(
                data, maintype='image', subtype='png', cid=cid_by_key[key], filename=f'{key}.png'
            )

    return msg


def send_email(to, subject: str, html: str, text: str | None = None,
               inline_images: dict | None = None, reply_to: str | None = None) -> bool:
    """Envia um e-mail. Retorna True em sucesso, False em qualquer falha.

    Nunca lança: falhas de SMTP viram log. O chamador decide o que fazer com o
    ``False`` (ex.: não avançar a janela do resumo, para tentar de novo depois).
    """
    recipients = normalize_recipients(to)
    if not recipients:
        logger.warning('E-mail não enviado: nenhum destinatário válido (assunto=%r)', subject)
        return False

    if not is_configured():
        logger.warning(
            'E-mail não enviado: SMTP não configurado (defina SMTP_HOST e SMTP_FROM_EMAIL no .env). '
            'Assunto=%r, destinatários=%d', subject, len(recipients)
        )
        return False

    cfg = get_config()
    msg = build_message(recipients, subject, html, text=text,
                        inline_images=inline_images, reply_to=reply_to)

    try:
        if cfg['port'] == SSL_PORT:
            server = smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=cfg['timeout'])
        else:
            server = smtplib.SMTP(cfg['host'], cfg['port'], timeout=cfg['timeout'])

        with server:
            server.ehlo()
            if cfg['port'] != SSL_PORT and cfg['use_tls']:
                server.starttls()
                server.ehlo()
            if cfg['user'] and _env('SMTP_PASSWORD'):
                server.login(cfg['user'], _env('SMTP_PASSWORD'))
            server.send_message(msg)

        logger.info('E-mail enviado para %d destinatário(s): %r', len(recipients), subject)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.exception('Falha de autenticação SMTP — verifique SMTP_USER/SMTP_PASSWORD')
    except smtplib.SMTPException:
        logger.exception('Falha SMTP ao enviar %r', subject)
    except OSError:
        logger.exception('Falha de conexão com %s:%s ao enviar %r', cfg['host'], cfg['port'], subject)

    return False
