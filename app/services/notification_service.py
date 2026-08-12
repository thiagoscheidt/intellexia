"""
Notificações por e-mail — agendamento e envio.

Tipos hoje: ``fap_digest`` (Resumo FAP), ``communications_digest`` (Comunicações
DJEN), ``radar_digest`` (Radar da Mesa de Trabalho), ``procuracoes_digest``
(resumo diário de procurações FAP) e ``procuracoes_alert`` (alerta de mudança em
procuração). Novos tipos entram como um novo
``NotificationSetting.notification_type`` + uma função ``send_<tipo>``.

Regras comuns a todos:

- a janela do "o que mudou" vai de ``last_sent_at`` até agora (no primeiro envio,
  usa o fallback da frequência: 24 h no diário, 7 dias no semanal);
- **sem novidades no período, não envia e-mail** — só avança a janela;
- falha de envio **não** avança a janela, então a próxima execução tenta de novo.

**Tipos de evento** (``EVENT_TYPES``) fogem do agendamento: quem dispara é o
script que produz o dado, não o cron horário. Eles são excluídos de
``due_settings`` — senão o cron horário os mandaria de novo no ``send_hour``.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from app.models import db, LawFirm, NotificationSetting
from app.services import email_service
from app.services.communication_monitor_service import build_communications_digest
from app.services.fap_digest_service import build_fap_digest
from app.services.fap_procuracoes_service import (
    build_procuracoes_alert,
    build_procuracoes_digest,
)
from app.services.process_radar_service import build_radar_digest
from app.utils.timezone import SP_TZ
from app.utils.urls import app_public_url

logger = logging.getLogger(__name__)

DIGEST_LIMIT = 10

# Notificações disparadas por evento (pelo script que gera o dado), nunca pelo
# agendamento horário. Ver docstring do módulo.
EVENT_TYPES = frozenset({NotificationSetting.TYPE_PROCURACOES_ALERT})

# Fallback da janela no primeiro envio (sem last_sent_at).
_FIRST_WINDOW = {
    NotificationSetting.FREQUENCY_DAILY: timedelta(days=1),
    NotificationSetting.FREQUENCY_WEEKLY: timedelta(days=7),
}

WEEKDAY_LABELS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']


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

    # Notificação de evento não tem horário: quem dispara é o script de origem.
    if setting.notification_type in EVENT_TYPES:
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
    """Configs que devem ser enviadas agora (todos os escritórios).

    Tipos de evento nunca entram: são disparados pelo script que gera o dado.
    """
    query = NotificationSetting.query.filter_by(is_enabled=True)
    query = query.filter(NotificationSetting.notification_type.notin_(tuple(EVENT_TYPES)))
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


def render_communications_digest(law_firm_id: int, since: datetime, is_test: bool = False) -> tuple[str, dict]:
    """Renderiza o HTML do resumo de Comunicações (DJEN). Retorna (html, digest)."""
    from flask import current_app, render_template

    digest = build_communications_digest(law_firm_id, since=since)
    law_firm = LawFirm.query.get(law_firm_id)

    with current_app.test_request_context(base_url=app_public_url()):
        html = render_template(
            'emails/communications_digest.html',
            digest=digest,
            law_firm=law_firm,
            periodo_inicio=since,
            gerado_em=datetime.now(SP_TZ),
            is_test=is_test,
        )
    return html, digest


def send_communications_digest(law_firm_id: int, force: bool = False,
                               override_recipients: list[str] | None = None,
                               dry_run: bool = False) -> dict:
    """Envia o resumo de Comunicações processuais (DJEN) de um escritório.

    Mesmo contrato do Resumo FAP: sem novidades não envia (só avança a janela);
    falha de envio não avança a janela.
    """
    setting = get_or_create_setting(law_firm_id, NotificationSetting.TYPE_COMMUNICATIONS_DIGEST)
    is_test = override_recipients is not None

    recipients = email_service.normalize_recipients(
        override_recipients if is_test else setting.get_recipients()
    )
    if not recipients:
        return {'status': 'skipped', 'message': 'Nenhum destinatário válido configurado.'}

    now_utc = _utcnow()
    since = _digest_window_start(setting, now_utc)

    html, digest = render_communications_digest(law_firm_id, since=since, is_test=is_test)
    totais = digest['totais']

    if not digest['has_novidades'] and not force:
        setting.last_sent_at = now_utc
        db.session.commit()
        return {'status': 'skipped', 'message': 'Sem novidades no período — nenhum e-mail enviado.',
                'totais': totais}

    total = totais.get('total', 0)
    resumo = (f'{total} comunicação' + ('ões' if total > 1 else '')) if total else 'sem novidades'
    hoje = datetime.now(SP_TZ).strftime('%d/%m/%Y')
    prefix = '[TESTE] ' if is_test else ''
    subject = f'{prefix}Comunicações processuais — {resumo} ({hoje})'

    if dry_run:
        return {'status': 'dry_run', 'message': f'(dry-run) enviaria para {len(recipients)} destinatário(s).',
                'subject': subject, 'totais': totais, 'recipients': recipients}

    sent = email_service.send_email(recipients, subject, html, inline_images=_logo_bytes())
    if not sent:
        return {'status': 'failed',
                'message': 'Falha no envio (verifique a configuração SMTP e os logs).',
                'totais': totais}

    if not is_test:
        setting.last_sent_at = now_utc
        db.session.commit()

    return {'status': 'sent', 'message': f'Resumo enviado para {len(recipients)} destinatário(s).',
            'totais': totais, 'recipients': recipients}


def render_radar_digest(law_firm_id: int, since: datetime, is_test: bool = False) -> tuple[str, dict]:
    """Renderiza o HTML do Resumo do Radar (Mesa de Trabalho). Retorna (html, digest)."""
    from flask import current_app, render_template

    law_firm = LawFirm.query.get(law_firm_id)

    # build_radar_digest usa url_for para montar os links dos itens — precisa do
    # request context (no cron não há request), por isso é montado aqui dentro.
    with current_app.test_request_context(base_url=app_public_url()):
        digest = build_radar_digest(law_firm_id, since=since)
        html = render_template(
            'emails/radar_digest.html',
            digest=digest,
            law_firm=law_firm,
            periodo_inicio=since,
            gerado_em=datetime.now(SP_TZ),
            is_test=is_test,
        )
    return html, digest


def send_radar_digest(law_firm_id: int, force: bool = False,
                      override_recipients: list[str] | None = None,
                      dry_run: bool = False) -> dict:
    """Envia o Resumo do Radar (Mesa de Trabalho) de um escritório.

    Mesmo contrato dos demais digests: sem item novo no período não envia (só
    avança a janela); falha de envio não avança a janela. O corpo mostra o estado
    atual do Radar, mas o gatilho é haver ao menos uma novidade desde o último envio.
    """
    setting = get_or_create_setting(law_firm_id, NotificationSetting.TYPE_RADAR_DIGEST)
    is_test = override_recipients is not None

    recipients = email_service.normalize_recipients(
        override_recipients if is_test else setting.get_recipients()
    )
    if not recipients:
        return {'status': 'skipped', 'message': 'Nenhum destinatário válido configurado.'}

    now_utc = _utcnow()
    since = _digest_window_start(setting, now_utc)

    html, digest = render_radar_digest(law_firm_id, since=since, is_test=is_test)
    totais = digest['totais']

    if not digest['has_novidades'] and not force:
        setting.last_sent_at = now_utc
        db.session.commit()
        return {'status': 'skipped', 'message': 'Sem novidades no período — nenhum e-mail enviado.',
                'totais': totais}

    novos = totais.get('novos', 0)
    decisoes = totais.get('decisoes', 0)
    if novos:
        resumo = f'{novos} novidade' + ('s' if novos > 1 else '')
        if decisoes:
            resumo += f' · {decisoes} decisão' + ('ões' if decisoes > 1 else '')
    else:
        resumo = 'sem novidades'
    hoje = datetime.now(SP_TZ).strftime('%d/%m/%Y')
    prefix = '[TESTE] ' if is_test else ''
    subject = f'{prefix}Radar · Monitoramento de Processos — {resumo} ({hoje})'

    if dry_run:
        return {'status': 'dry_run', 'message': f'(dry-run) enviaria para {len(recipients)} destinatário(s).',
                'subject': subject, 'totais': totais, 'recipients': recipients}

    sent = email_service.send_email(recipients, subject, html, inline_images=_logo_bytes())
    if not sent:
        return {'status': 'failed',
                'message': 'Falha no envio (verifique a configuração SMTP e os logs).',
                'totais': totais}

    if not is_test:
        setting.last_sent_at = now_utc
        db.session.commit()

    return {'status': 'sent', 'message': f'Resumo enviado para {len(recipients)} destinatário(s).',
            'totais': totais, 'recipients': recipients}


def render_procuracoes_alert(law_firm_id: int, since: datetime, is_test: bool = False) -> tuple[str, dict]:
    """Renderiza o HTML do alerta de procurações. Retorna (html, alerta)."""
    from flask import current_app, render_template

    alerta = build_procuracoes_alert(law_firm_id, since=since)
    law_firm = LawFirm.query.get(law_firm_id)

    with current_app.test_request_context(base_url=app_public_url()):
        html = render_template(
            'emails/procuracoes_alert.html',
            alerta=alerta,
            law_firm=law_firm,
            periodo_inicio=since,
            gerado_em=datetime.now(SP_TZ),
            is_test=is_test,
        )
    return html, alerta


def send_procuracoes_alert(law_firm_id: int, force: bool = False,
                           override_recipients: list[str] | None = None,
                           dry_run: bool = False) -> dict:
    """Envia o alerta de mudança em procuração FAP.

    Notificação **de evento**: chamada pelo script de sincronização das
    procurações ao fim de cada execução, não pelo cron horário. O contrato é o
    dos digests — janela ``last_sent_at``, sem novidade não envia, falha de envio
    não avança a janela. É essa última regra que faz o alerta sobreviver a SMTP
    fora do ar: a execução seguinte reenvia o mesmo período.
    """
    setting = get_or_create_setting(law_firm_id, NotificationSetting.TYPE_PROCURACOES_ALERT)
    is_test = override_recipients is not None

    if not setting.is_enabled and not is_test:
        return {'status': 'skipped', 'message': 'Alerta de procurações desativado nas configurações.'}

    recipients = email_service.normalize_recipients(
        override_recipients if is_test else setting.get_recipients()
    )
    if not recipients:
        return {'status': 'skipped', 'message': 'Nenhum destinatário válido configurado.'}

    now_utc = _utcnow()
    since = _digest_window_start(setting, now_utc)

    html, alerta = render_procuracoes_alert(law_firm_id, since=since, is_test=is_test)
    totais = alerta['totais']

    if not alerta['has_novidades'] and not force:
        setting.last_sent_at = now_utc
        db.session.commit()
        return {'status': 'skipped', 'message': 'Sem mudança em procurações no período.',
                'totais': totais}

    partes = []
    if totais['novas']:
        partes.append(f"{totais['novas']} nova" + ('s' if totais['novas'] > 1 else ''))
    if totais['alteradas']:
        partes.append(f"{totais['alteradas']} alterada" + ('s' if totais['alteradas'] > 1 else ''))
    resumo = ' · '.join(partes) or 'sem mudanças'
    hoje = datetime.now(SP_TZ).strftime('%d/%m/%Y')
    prefix = '[TESTE] ' if is_test else ''
    subject = f'{prefix}Procurações FAP — {resumo} ({hoje})'

    if dry_run:
        return {'status': 'dry_run', 'message': f'(dry-run) enviaria para {len(recipients)} destinatário(s).',
                'subject': subject, 'totais': totais, 'recipients': recipients}

    sent = email_service.send_email(recipients, subject, html, inline_images=_logo_bytes())
    if not sent:
        return {'status': 'failed',
                'message': 'Falha no envio (verifique a configuração SMTP e os logs).',
                'totais': totais}

    if not is_test:
        setting.last_sent_at = now_utc
        db.session.commit()

    return {'status': 'sent', 'message': f'Alerta enviado para {len(recipients)} destinatário(s).',
            'totais': totais, 'recipients': recipients}


def render_procuracoes_digest(law_firm_id: int, since: datetime, is_test: bool = False) -> tuple[str, dict]:
    """Renderiza o HTML do resumo diário de procurações. Retorna (html, digest)."""
    from flask import current_app, render_template

    digest = build_procuracoes_digest(law_firm_id, since=since)
    law_firm = LawFirm.query.get(law_firm_id)

    with current_app.test_request_context(base_url=app_public_url()):
        html = render_template(
            'emails/procuracoes_digest.html',
            digest=digest,
            law_firm=law_firm,
            periodo_inicio=since,
            gerado_em=datetime.now(SP_TZ),
            is_test=is_test,
        )
    return html, digest


def send_procuracoes_digest(law_firm_id: int, force: bool = False,
                            override_recipients: list[str] | None = None,
                            dry_run: bool = False) -> dict:
    """Envia o resumo diário de procurações (vencimentos + novas do período).

    Diferente dos demais digests, ``has_novidades`` é verdadeiro sempre que
    houver **qualquer** item nos blocos, mesmo sem novidade no período: uma
    procuração vencendo em três dias e sem nenhum evento novo é justamente o
    aviso mais importante, e exigir novidade a silenciaria.
    """
    setting = get_or_create_setting(law_firm_id, NotificationSetting.TYPE_PROCURACOES_DIGEST)
    is_test = override_recipients is not None

    recipients = email_service.normalize_recipients(
        override_recipients if is_test else setting.get_recipients()
    )
    if not recipients:
        return {'status': 'skipped', 'message': 'Nenhum destinatário válido configurado.'}

    now_utc = _utcnow()
    since = _digest_window_start(setting, now_utc)

    html, digest = render_procuracoes_digest(law_firm_id, since=since, is_test=is_test)
    totais = digest['totais']

    if not digest['has_novidades'] and not force:
        setting.last_sent_at = now_utc
        db.session.commit()
        return {'status': 'skipped', 'message': 'Nenhuma procuração vencendo ou nova — nenhum e-mail enviado.',
                'totais': totais}

    # A novidade vem primeiro no assunto, como no corpo.
    # "novas" aqui é cadastro no portal (data_cadastro), não estreia no nosso banco.
    partes = []
    if totais['novas']:
        partes.append(f"{totais['novas']} nova" + ('s' if totais['novas'] > 1 else ''))
    if totais['vencendo']:
        partes.append(f"{totais['vencendo']} vencendo")
    resumo = ' · '.join(partes) or 'sem pendências'
    hoje = datetime.now(SP_TZ).strftime('%d/%m/%Y')
    prefix = '[TESTE] ' if is_test else ''
    subject = f'{prefix}Procurações FAP — {resumo} ({hoje})'

    if dry_run:
        return {'status': 'dry_run', 'message': f'(dry-run) enviaria para {len(recipients)} destinatário(s).',
                'subject': subject, 'totais': totais, 'recipients': recipients}

    sent = email_service.send_email(recipients, subject, html, inline_images=_logo_bytes())
    if not sent:
        return {'status': 'failed',
                'message': 'Falha no envio (verifique a configuração SMTP e os logs).',
                'totais': totais}

    if not is_test:
        setting.last_sent_at = now_utc
        db.session.commit()

    return {'status': 'sent', 'message': f'Resumo enviado para {len(recipients)} destinatário(s).',
            'totais': totais, 'recipients': recipients}


# Tipo → função de envio. Novos tipos entram aqui.
SENDERS = {
    NotificationSetting.TYPE_FAP_DIGEST: send_fap_digest,
    NotificationSetting.TYPE_COMMUNICATIONS_DIGEST: send_communications_digest,
    NotificationSetting.TYPE_RADAR_DIGEST: send_radar_digest,
    NotificationSetting.TYPE_PROCURACOES_DIGEST: send_procuracoes_digest,
    NotificationSetting.TYPE_PROCURACOES_ALERT: send_procuracoes_alert,
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
