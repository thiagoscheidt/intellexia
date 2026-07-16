#!/usr/bin/env python3
"""
Teste das notificações por e-mail (SMTP) e do Resumo FAP.

Script executável, no padrão dos demais testes do projeto:

    uv run python tests/test_notifications.py
    uv run python tests/test_notifications.py --law-firm-id 1
    uv run python tests/test_notifications.py --send meu@email.com   # envio real (exige SMTP no .env)
    uv run python tests/test_notifications.py --save-html /tmp/resumo.html

Cobre:
  1. Configuração e helpers do email_service (validação/normalização de destinatários)
  2. Montagem da mensagem MIME (multipart + imagem inline por CID)
  3. Builders do digest e paridade com o dashboard (mesma função nos dois)
  4. Agendamento (is_due) em todas as combinações relevantes
  5. Renderização do template do e-mail
  6. (opcional) envio real ponta a ponta
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import LawFirm, NotificationSetting
from app.services import email_service, notification_service
from app.services.fap_digest_service import build_fap_digest
from app.utils.timezone import SP_TZ

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def test_email_service():
    print('\n1) email_service')
    check('is_configured() responde bool', isinstance(email_service.is_configured(), bool))
    check('e-mail válido aceito', email_service.is_valid_email('a@b.com.br'))
    check('e-mail inválido recusado', not email_service.is_valid_email('sem-arroba'))

    norm = email_service.normalize_recipients('a@b.com, a@b.com; c@d.com\ninvalido')
    check('normalize_recipients tira duplicado/inválido e mantém ordem',
          norm == ['a@b.com', 'c@d.com'], f'obtido: {norm}')

    check('normalize_recipients aceita lista',
          email_service.normalize_recipients(['x@y.com', '']) == ['x@y.com'])

    enviado = email_service.send_email([], 'assunto', '<p>oi</p>')
    check('send_email sem destinatário retorna False (não lança)', enviado is False)


def test_build_message():
    print('\n2) Montagem da mensagem')
    msg = email_service.build_message(
        ['a@b.com'], 'Assunto', '<p>Olá <b>mundo</b></p><img src="cid:logo">',
        inline_images={'logo': b'\x89PNG\r\n\x1a\n-fake'},
    )
    check('assunto preservado', msg['Subject'] == 'Assunto')
    check('mensagem é multipart', msg.is_multipart())

    tipos = [p.get_content_type() for p in msg.walk()]
    check('tem alternativa em texto puro', 'text/plain' in tipos, f'tipos: {tipos}')
    check('tem parte HTML', 'text/html' in tipos, f'tipos: {tipos}')
    check('tem imagem inline', any(t.startswith('image/') for t in tipos), f'tipos: {tipos}')

    html_part = [p for p in msg.walk() if p.get_content_type() == 'text/html'][0]
    html = html_part.get_content()
    check('cid:logo trocado por Content-ID real', 'cid:logo"' not in html and 'cid:' in html)

    texto = [p for p in msg.walk() if p.get_content_type() == 'text/plain'][0].get_content()
    check('texto puro sem tags HTML', '<b>' not in texto and 'mundo' in texto, f'texto: {texto!r}')


def test_digest(law_firm_id: int):
    print('\n3) Dados do Resumo FAP')
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3650)
    digest = build_fap_digest(law_firm_id, since=since, limit=5)

    check('digest tem novidades/recentes/totais',
          {'novidades', 'recentes', 'totais', 'has_novidades'} <= set(digest))
    check('três listas em novidades', set(digest['novidades']) == {'dou', 'cadastro', 'atualizacao'})
    check('respeita o limite',
          all(len(v) <= 5 for v in digest['recentes'].values()),
          str({k: len(v) for k, v in digest['recentes'].items()}))
    check('total bate com a soma das listas',
          digest['totais']['total'] == sum(len(v) for v in digest['novidades'].values()))

    # Janela vazia (futuro) não pode trazer novidade.
    futuro = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    vazio = build_fap_digest(law_firm_id, since=futuro, limit=5)
    check('janela no futuro não traz novidades', vazio['has_novidades'] is False,
          str(vazio['totais']))

    print(f"     (janela de 10 anos: {digest['totais']})")

    print('\n3b) Paridade com o dashboard')
    import app.blueprints.dashboard as dash
    from app.services import fap_digest_service
    check('dashboard usa o builder do serviço (D.O.U.)',
          dash.build_latest_dou is fap_digest_service.build_latest_dou)
    check('dashboard usa o builder do serviço (Cadastradas)',
          dash.build_latest_cadastro is fap_digest_service.build_latest_cadastro)
    check('dashboard usa o builder do serviço (Atualizadas)',
          dash.build_latest_atualizacao is fap_digest_service.build_latest_atualizacao)

    return digest


def test_is_due():
    print('\n4) Agendamento (is_due)')
    agora = datetime(2026, 7, 16, 8, 30, tzinfo=SP_TZ)  # quinta-feira, 08:30

    def setting(**kwargs):
        s = NotificationSetting(law_firm_id=1, notification_type=NotificationSetting.TYPE_FAP_DIGEST,
                                is_enabled=True, frequency='daily', send_hour=8, send_weekday=0)
        s.set_recipients(['a@b.com'])
        for k, v in kwargs.items():
            setattr(s, k, v)
        return s

    check('diário no horário → envia',
          notification_service.is_due(setting(), now_sp=agora))
    check('diário fora do horário → não envia',
          not notification_service.is_due(setting(send_hour=9), now_sp=agora))
    check('desligado → não envia',
          not notification_service.is_due(setting(is_enabled=False), now_sp=agora))

    sem_dest = setting()
    sem_dest.set_recipients([])
    check('sem destinatário → não envia', not notification_service.is_due(sem_dest, now_sp=agora))

    check('semanal no dia certo (quinta=3) → envia',
          notification_service.is_due(setting(frequency='weekly', send_weekday=3), now_sp=agora))
    check('semanal em outro dia → não envia',
          not notification_service.is_due(setting(frequency='weekly', send_weekday=0), now_sp=agora))

    # last_sent_at é UTC naive; 08:30 SP = 11:30 UTC.
    ja_enviou = setting(last_sent_at=datetime(2026, 7, 16, 11, 5))
    check('já enviou neste slot → não repete',
          not notification_service.is_due(ja_enviou, now_sp=agora))

    enviou_ontem = setting(last_sent_at=datetime(2026, 7, 15, 11, 5))
    check('enviou no slot de ontem → envia hoje',
          notification_service.is_due(enviou_ontem, now_sp=agora))


def test_render(law_firm_id: int, save_html: str | None):
    print('\n5) Renderização do e-mail')
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3650)
    html, digest = notification_service.render_fap_digest(law_firm_id, since=since)

    check('HTML gerado', bool(html) and len(html) > 500, f'{len(html or "")} chars')
    check('tem o título do resumo', 'Resumo FAP' in html)
    check('tem as três seções',
          all(s in html for s in ('Publicadas no D.O.U.', 'Cadastradas', 'Atualizadas')))
    check('tem seção de novidades e panorama',
          'O que mudou no período' in html and 'Mais recentes' in html)
    check('logo referenciado por CID', 'cid:logo' in html)

    # O HTML referenciar cid:logo não basta — a imagem precisa existir para ser anexada.
    logo = notification_service._logo_bytes()
    check('logo encontrado em disco para embutir',
          'logo' in logo and len(logo.get('logo', b'')) > 0,
          'o e-mail sairia sem logo')
    check('logo é um PNG válido', logo.get('logo', b'')[:8] == b'\x89PNG\r\n\x1a\n')
    check('links absolutos para o sistema',
          notification_service.app_public_url() + '/fap-panel' in html,
          'nenhum link com APP_PUBLIC_URL')
    check('sem marcador Jinja não resolvido', '{{' not in html and '{%' not in html)

    assunto = notification_service._digest_subject(digest['totais'])
    check('assunto montado', assunto.startswith('Resumo FAP —'), assunto)
    check('assunto de teste marcado',
          notification_service._digest_subject(digest['totais'], is_test=True).startswith('[TESTE]'))
    print(f'     assunto: {assunto}')

    if save_html:
        Path(save_html).write_text(html, encoding='utf-8')
        print(f'     💾 HTML salvo em {save_html}')

    return html


def test_send_real(law_firm_id: int, destino: str):
    print('\n6) Envio real')
    if not email_service.is_configured():
        print('  ⚠️  SMTP não configurado no .env — pulando envio real.')
        return
    result = notification_service.send_fap_digest(
        law_firm_id, force=True, override_recipients=[destino]
    )
    check(f'e-mail enviado para {destino}', result['status'] == 'sent', result['message'])


def main():
    parser = argparse.ArgumentParser(description='Testa as notificações por e-mail.')
    parser.add_argument('--law-firm-id', type=int, default=None)
    parser.add_argument('--send', metavar='EMAIL', default=None, help='faz um envio real de teste')
    parser.add_argument('--save-html', metavar='ARQUIVO', default=None,
                        help='salva o HTML renderizado para inspeção')
    args = parser.parse_args()

    with app.app_context():
        law_firm_id = args.law_firm_id
        if not law_firm_id:
            firm = LawFirm.query.order_by(LawFirm.id).first()
            if not firm:
                print('❌ Nenhum escritório no banco. Use --law-firm-id.')
                return 2
            law_firm_id = firm.id
        print(f'Escritório: {law_firm_id}')

        test_email_service()
        test_build_message()
        test_digest(law_firm_id)
        test_is_due()
        test_render(law_firm_id, args.save_html)
        if args.send:
            test_send_real(law_firm_id, args.send)

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
