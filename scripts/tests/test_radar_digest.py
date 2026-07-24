"""
Teste standalone do Resumo do Radar (notificação por e-mail).

Valida:
- build_radar_digest: has_novidades, is_new, is_decision, contagem de decisões;
- render_radar_digest: template renderiza sem erro (dry-run, sem SMTP);
- send_radar_digest dry_run não envia e-mail;
- build_communications_digest marca is_decision/decisoes.

Uso: uv run python scripts/tests/test_radar_digest.py
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import app
from app.services import process_radar_service, notification_service
from app.services import communication_monitor_service as cms
from app.models import NotificationSetting


def _fake_item(kind, label, when, is_decision, communication_id=None, process_id=1):
    return {
        'kind': kind, 'label': label, 'process_id': process_id,
        'communication_id': communication_id, 'process_number': '0000001-11.2024.5.04.0001',
        'when': when, 'url': '/x', 'is_decision': is_decision,
    }


def test_digest_flags():
    now = datetime(2026, 7, 24, 12, 0, 0)
    since = now - timedelta(days=1)
    items = [
        _fake_item('publicacao', 'Intimação', now, False, communication_id=10),
        _fake_item('decisao', 'Sentença de procedência', now - timedelta(hours=2), True),
        _fake_item('ia', 'Providência antiga', now - timedelta(days=5), False, communication_id=11),
    ]
    with patch.object(process_radar_service, 'build_radar', return_value=(items, len(items))):
        digest = process_radar_service.build_radar_digest(1, since=since)

    assert digest['has_novidades'] is True, 'deveria ter novidade (itens > since)'
    assert digest['totais']['decisoes'] == 1, digest['totais']
    assert digest['totais']['novos'] == 2, digest['totais']  # publicacao e decisao > since
    # Decisão deve vir primeiro (destaque no topo)
    assert digest['radar_items'][0]['is_decision'] is True
    print('OK  build_radar_digest — flags e ordenação')


def test_digest_sem_novidades():
    old = datetime(2026, 7, 1, 12, 0, 0)
    since = datetime(2026, 7, 24, 12, 0, 0)
    items = [_fake_item('publicacao', 'Antiga', old, False, communication_id=10)]
    with patch.object(process_radar_service, 'build_radar', return_value=(items, 1)):
        digest = process_radar_service.build_radar_digest(1, since=since)
    assert digest['has_novidades'] is False, 'nenhum item mais novo que since'
    print('OK  build_radar_digest — sem novidades não dispara')


def test_render_e_dry_run():
    now = datetime(2026, 7, 24, 12, 0, 0)
    items = [
        _fake_item('decisao', 'Sentença', now, True),
        _fake_item('publicacao', 'Intimação', now, False, communication_id=10),
    ]
    with patch.object(process_radar_service, 'build_radar', return_value=(items, 2)):
        html, digest = notification_service.render_radar_digest(1, since=now - timedelta(days=1))
        assert 'Radar' in html and 'Sentença' in html, 'template não renderizou o conteúdo'
        assert '⚖️' in html, 'bloco de decisões não apareceu'
        print('OK  render_radar_digest — HTML renderizado com destaque de decisão')

        setting = notification_service.get_or_create_setting(1, NotificationSetting.TYPE_RADAR_DIGEST)
        setting.set_recipients(['teste@exemplo.com'])
        res = notification_service.send_radar_digest(1, dry_run=True)
        assert res['status'] == 'dry_run', res
        print('OK  send_radar_digest — dry_run não envia')


def test_sender_registrado():
    assert NotificationSetting.TYPE_RADAR_DIGEST in notification_service.SENDERS
    print('OK  SENDERS contém radar_digest')


def test_comunicacoes_is_decision():
    comms = [
        SimpleNamespace(id=1, numero_processo='1', numero_processo_mascara='1',
                        judicial_process_id=None, sigla_tribunal='TRT4', nome_classe='X',
                        tipo_comunicacao='Sentença', tipo_documento='Acórdão',
                        nome_orgao='Vara', data_disponibilizacao=datetime(2026, 7, 24),
                        link='/x', created_at=datetime(2026, 7, 24)),
        SimpleNamespace(id=2, numero_processo='1', numero_processo_mascara='1',
                        judicial_process_id=None, sigla_tribunal='TRT4', nome_classe='X',
                        tipo_comunicacao='Intimação', tipo_documento='Despacho',
                        nome_orgao='Vara', data_disponibilizacao=datetime(2026, 7, 24),
                        link='/x', created_at=datetime(2026, 7, 24)),
    ]

    class FakeQuery:
        def filter_by(self, **k): return self
        def filter(self, *a): return self
        def order_by(self, *a): return self
        def limit(self, n): return self
        def all(self): return comms
        def count(self): return 0

    with patch.object(cms.ProcessCommunication, 'query', FakeQuery()), \
         patch.object(cms.JudicialProcess, 'query', FakeQuery()):
        digest = cms.build_communications_digest(1, since=datetime(2026, 7, 1))

    assert digest['totais']['decisoes'] == 1, digest['totais']
    flags = {c['id']: c['is_decision'] for g in digest['processos'] for c in g['comunicacoes']}
    assert flags[1] is True and flags[2] is False, flags
    print('OK  build_communications_digest — is_decision/decisoes')


if __name__ == '__main__':
    with app.app_context():
        test_digest_flags()
        test_digest_sem_novidades()
        test_render_e_dry_run()
        test_sender_registrado()
        test_comunicacoes_is_decision()
    print('\nTodos os testes passaram.')
    sys.exit(0)
