#!/usr/bin/env python3
"""
Teste de explain_new_communications (explicação IA automática pós-sync),
com explain_communication FAKE (sem tocar a OpenAI).

Cobre: só comunicações da rodada (created_at >= since), pula sem teor e já
explicadas, falha em uma não interrompe as demais, teto com contagem de
pendentes e idempotência (segunda chamada não regera nada).

    uv run python tests/test_explain_new_communications.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from main import app
from app.models import db, LawFirm, ProcessCommunication, User
from app.services import communication_monitor_service as monitor

CNPJ_TESTE = '00000000000200'


def _cleanup_firm(firm_id):
    db.session.rollback()
    ProcessCommunication.query.filter_by(law_firm_id=firm_id).delete()
    User.query.filter_by(law_firm_id=firm_id).delete()
    LawFirm.query.filter_by(id=firm_id).delete()
    db.session.commit()


def _comm(firm_id, hash_, texto='PODER JUDICIÁRIO — teste', analysis=None,
          created_at=None):
    comm = ProcessCommunication(
        law_firm_id=firm_id, hash=hash_, texto=texto, analysis_json=analysis,
        sigla_tribunal='TRF4', numero_processo='50011815620234036100',
    )
    if created_at is not None:
        comm.created_at = created_at
    db.session.add(comm)
    db.session.commit()
    return comm.id


def run():
    ok = True
    with app.app_context():
        leftover = LawFirm.query.filter_by(cnpj=CNPJ_TESTE).first()
        if leftover:
            _cleanup_firm(leftover.id)

        firm = LawFirm(name='Teste Auto-Explicação LTDA', cnpj=CNPJ_TESTE)
        db.session.add(firm)
        db.session.flush()
        user = User(law_firm_id=firm.id, name='Admin Teste',
                    email='admin@teste-autoexplain.local', role='admin')
        user.set_password('x')
        db.session.add(user)
        db.session.commit()

        # Fake: preenche analysis_json como a real; falha para hashes 'boom-*'.
        calls = []
        original_explain = monitor.explain_communication

        def fake_explain(law_firm_id, communication_id, user_id=None, force=False):
            comm = db.session.get(ProcessCommunication, communication_id)
            if comm.hash.startswith('boom'):
                raise ValueError('falha simulada do agente')
            comm.analysis_json = {'generated_at': 'x', 'model': 'fake',
                                  'data': {'resumo': 'fake'}}
            db.session.commit()
            calls.append((communication_id, user_id))

        monitor.explain_communication = fake_explain
        try:
            since = datetime.now() - timedelta(minutes=5)
            antiga = datetime.now() - timedelta(days=3)

            id_nova = _comm(firm.id, 'nova-1')
            id_sem_teor = _comm(firm.id, 'sem-teor', texto=None)
            id_ja_explicada = _comm(firm.id, 'ja-explicada',
                                    analysis={'data': {'resumo': 'antigo'}})
            id_antiga = _comm(firm.id, 'antiga-1', created_at=antiga)
            id_boom = _comm(firm.id, 'boom-1')

            # 1) Explica só a nova com teor; falha não interrompe as demais.
            stats = monitor.explain_new_communications(firm.id, since=since)
            assert stats == {'explained': 1, 'failed': 1, 'pending': 0}, stats
            assert [c[0] for c in calls] == [id_nova], calls
            assert calls[0][1] == user.id, 'user_id deve ser o admin do escritório'
            nova = db.session.get(ProcessCommunication, id_nova)
            assert nova.analysis_json['data']['resumo'] == 'fake'
            assert db.session.get(ProcessCommunication, id_antiga).analysis_json is None
            assert db.session.get(ProcessCommunication, id_ja_explicada) \
                .analysis_json['data']['resumo'] == 'antigo', 'não deve regerar'
            print('✓ explica só a nova da rodada; falha isolada não interrompe')

            # 2) Idempotência: segunda chamada não encontra nada novo
            #    ('boom-1' segue elegível e volta a falhar — fica para o botão).
            calls.clear()
            stats = monitor.explain_new_communications(firm.id, since=since)
            assert stats == {'explained': 0, 'failed': 1, 'pending': 0}, stats
            assert calls == [], calls
            print('✓ idempotente: nada é regerado')

            # 3) Teto: limit=1 explica uma e conta o restante em pending.
            _comm(firm.id, 'nova-2')
            _comm(firm.id, 'nova-3')
            calls.clear()
            stats = monitor.explain_new_communications(firm.id, since=since, limit=1)
            assert stats['explained'] == 1 and stats['pending'] >= 1, stats
            print('✓ teto respeitado com contagem de pendentes')
        except AssertionError as exc:
            ok = False
            print(f'✗ FALHA: {exc}')
        finally:
            monitor.explain_communication = original_explain
            _cleanup_firm(firm.id)

    print('RESULTADO:', 'OK' if ok else 'FALHOU')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(run())
