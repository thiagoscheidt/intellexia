"""
Notificações por e-mail — agendamento e envio.

Hoje há um tipo: ``fap_digest`` (Resumo FAP). Novos tipos entram como um novo
``NotificationSetting.notification_type`` + uma função ``send_<tipo>``.

Regras do Resumo FAP:

- a janela do "o que mudou" vai de ``last_sent_at`` até agora (no primeiro envio,
  usa o fallback da frequência: 24 h no diário, 7 dias no semanal);
- **sem novidades no período, não envia e-mail** — só avança a janela;
- falha de envio **não** avança a janela, então a próxima execução tenta de novo.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from app.models import db, LawFirm, NotificationSetting
from app.services import email_service
from app.services.fap_digest_service import build_fap_digest
from app.utils.timezone import SP_TZ

logger = logging.getLogger(__name__)

DIGEST_LIMIT = 10

# Fallback da janela no primeiro envio (sem last_sent_at).
_FIRST_WINDOW = {
    NotificationSetting.FREQUENCY_DAILY: timedelta(days=1),
    NotificationSetting.FREQUENCY_WEEKLY: timedelta(days=7),
}

WEEKDAY_LABELS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']


def app_public_url() -> str:
    """URL pública do sistema, para os links do e-mail (sem barra final)."""
    return (os.environ.get('APP_PUBLIC_URL') or 'https://rs-dev.intellexia.com.br').rstrip('/')


def get_or_create_setting(law_firm_id: int, notification_type: str) -> NotificationSetting:
    """Config do escritório para o tipo; cria desligada na primeira vez."""
    setting = NotificationSetting.query.filter_by(
        law_firm_id=law_firm_id, notification_type=notification_type
    ).first()
    if setting is None:
        setting = NotificationSetting(law_firm_id=law_firm_id, notification_type=notification_type)
        db.session.add(setting)
        db.session.commit()
    return setting


def _utcnow() -> datetime:
    """Agora em UTC, naive — as colunas DateTime do projeto são UTC sem tzinfo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def is_due(setting: NotificationSetting, now_sp: datetime | None = None) -> bool:
    """A config está no horário de envio agora?

    O cron roda de hora em hora: dispara quando a hora local bate com
    ``send_hour`` (e o dia com ``send_weekday``, no semanal) e ainda não houve
    envio nesse mesmo slot.
    """
    if not setting.is_enabled or not setting.get_recipients():
        return False

    now_sp = now_sp or datetime.now(SP_TZ)

    if now_sp.hour != setting.send_hour:
        return False

    if setting.frequency == NotificationSetting.FREQUENCY_WEEKLY:
        if now_sp.weekday() != setting.send_weekday:
            return False

    if setting.last_sent_at is not None:
        # Já enviou dentro da última hora? Então este slot já foi atendido.
        last_sent_sp = setting.last_sent_at.replace(tzinfo=timezone.utc).astimezone(SP_TZ)
        if (now_sp - last_sent_sp) < timedelta(hours=1):
            return False

    return True


def due_settings(now_sp: datetime | None = None, notification_type: str | None = None):
    """Configs que devem ser enviadas agora (todos os escritórios)."""
    query = NotificationSetting.query.filter_by(is_enabled=True)
    if notification_type:
        query = query.filter_by(notification_type=notification_type)
    return [s for s in query.all() if is_due(s, now_sp=now_sp)]


def _digest_window_start(setting: NotificationSetting, now_utc: datetime) -> datetime:
    if setting.last_sent_at:
        return _as_utc_naive(setting.last_sent_at)
    return now_utc - _FIRST_WINDOW.get(setting.frequency, timedelta(days=1))


def _logo_bytes() -> dict:
    """Logo do IntellexIA para embutir no e-mail (CID). Ausente = e-mail sem logo."""
    from flask import current_app
    path = os.path.join(current_app.static_folder, 'assets', 'img', 'logo_maior.png')
    try:
        with open(path, 'rb') as f:
            return {'logo': f.read()}
    except OSError:
        logger.warning('Logo não encontrado para o e-mail (%s)', path)
        return {}


def render_fap_digest(law_firm_id: int, since: datetime, is_test: bool = False) -> tuple[str, dict]:
    """Renderiza o HTML do Resumo FAP. Retorna (html, digest)."""
    from flask import current_app, render_template

    digest = build_fap_digest(law_firm_id, since=since, limit=DIGEST_LIMIT)
    law_firm = LawFirm.query.get(law_firm_id)

    # O cron não tem request context; com base_url=APP_PUBLIC_URL o url_for(_external=True)
    # do template gera links absolutos para o sistema (mesmo padrão dos exports do MCP).
    with current_app.test_request_context(base_url=app_public_url()):
        html = render_template(
            'emails/fap_digest.html',
            digest=digest,
            law_firm=law_firm,
            periodo_inicio=since,
            gerado_em=datetime.now(SP_TZ),
            is_test=is_test,
        )
    return html, digest


def send_fap_digest(law_firm_id: int, force: bool = False,
                    override_recipients: list[str] | None = None,
                    dry_run: bool = False) -> dict:
    """Envia o Resumo FAP de um escritório.

    - ``force``: envia mesmo sem novidades (usado pelo botão "Enviar agora").
    - ``override_recipients``: destinatários alternativos (teste vai só para o admin).
    - ``dry_run``: monta tudo e não envia.

    Retorna ``{"status": "sent"|"skipped"|"failed"|"dry_run", "message": str, ...}``.
    """
    setting = get_or_create_setting(law_firm_id, NotificationSetting.TYPE_FAP_DIGEST)
    is_test = override_recipients is not None

    recipients = email_service.normalize_recipients(
        override_recipients if is_test else setting.get_recipients()
    )
    if not recipients:
        return {'status': 'skipped', 'message': 'Nenhum destinatário válido configurado.'}

    now_utc = _utcnow()
    since = _digest_window_start(setting, now_utc)

    html, digest = render_fap_digest(law_firm_id, since=since, is_test=is_test)
    totais = digest['totais']

    if not digest['has_novidades'] and not force:
        # Nada novo: não envia e-mail vazio, mas avança a janela.
        setting.last_sent_at = now_utc
        db.session.commit()
        return {'status': 'skipped', 'message': 'Sem novidades no período — nenhum e-mail enviado.',
                'totais': totais}

    subject = _digest_subject(totais, is_test=is_test)

    if dry_run:
        return {'status': 'dry_run', 'message': f'(dry-run) enviaria para {len(recipients)} destinatário(s).',
                'subject': subject, 'totais': totais, 'recipients': recipients}

    sent = email_service.send_email(recipients, subject, html, inline_images=_logo_bytes())
    if not sent:
        # Não avança a janela: a próxima execução tenta de novo com o mesmo período.
        return {'status': 'failed',
                'message': 'Falha no envio (verifique a configuração SMTP e os logs).',
                'totais': totais}

    if not is_test:
        setting.last_sent_at = now_utc
        db.session.commit()

    return {'status': 'sent', 'message': f'Resumo enviado para {len(recipients)} destinatário(s).',
            'totais': totais, 'recipients': recipients}


def _digest_subject(totais: dict, is_test: bool = False) -> str:
    total = totais.get('total', 0)
    if total:
        resumo = f'{total} novidade' + ('s' if total > 1 else '')
    else:
        resumo = 'sem novidades'
    hoje = datetime.now(SP_TZ).strftime('%d/%m/%Y')
    prefix = '[TESTE] ' if is_test else ''
    return f'{prefix}Resumo FAP — {resumo} ({hoje})'


# Tipo → função de envio. Novos tipos entram aqui.
SENDERS = {
    NotificationSetting.TYPE_FAP_DIGEST: send_fap_digest,
}


def send_due_notifications(now_sp: datetime | None = None, law_firm_id: int | None = None,
                           dry_run: bool = False) -> list[dict]:
    """Envia todas as notificações no horário. Usado pelo cron."""
    results = []
    for setting in due_settings(now_sp=now_sp):
        if law_firm_id and setting.law_firm_id != law_firm_id:
            continue
        sender = SENDERS.get(setting.notification_type)
        if not sender:
            logger.warning('Tipo de notificação sem enviador: %s', setting.notification_type)
            continue
        try:
            result = sender(setting.law_firm_id, dry_run=dry_run)
        except Exception as e:  # uma falha não pode derrubar os demais escritórios
            db.session.rollback()
            logger.exception('Erro ao enviar %s do escritório %s',
                             setting.notification_type, setting.law_firm_id)
            result = {'status': 'failed', 'message': str(e)}
        result.update({'law_firm_id': setting.law_firm_id,
                       'notification_type': setting.notification_type})
        results.append(result)
    return results
