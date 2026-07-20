#!/usr/bin/env python3
"""
Teste das rotas do módulo de Comunicações e da triagem de descobertos.

Cobre: lista, detalhe (marca lida), isolamento de tenant, aba Descobertos do
Painel de Processos e confirmação/ignorar de processo descoberto.

    uv run python tests/test_communications_routes.py
"""

import sys
from datetime import date
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from main import app
from app.models import db, JudicialProcess, LawFirm, ProcessCommunication, User, UserPageVisit


def _login(client, user):
    with client.session_transaction() as sess:
        sess['user_id'] = user.id
        sess['law_firm_id'] = user.law_firm_id
        sess['user_role'] = user.role
        sess['user_name'] = user.name
        sess['user_email'] = user.email


def _cleanup_firms(firm_ids):
    db.session.rollback()
    ProcessCommunication.query.filter(ProcessCommunication.law_firm_id.in_(firm_ids)).delete()
    JudicialProcess.query.filter(JudicialProcess.law_firm_id.in_(firm_ids)).delete()
    UserPageVisit.query.filter(UserPageVisit.law_firm_id.in_(firm_ids)).delete()
    User.query.filter(User.law_firm_id.in_(firm_ids)).delete()
    LawFirm.query.filter(LawFirm.id.in_(firm_ids)).delete()
    db.session.commit()


def run():
    ok = True
    with app.app_context():
        # Remove sobras de execuções anteriores que falharam no meio.
        leftovers = [f.id for f in LawFirm.query.filter(
            LawFirm.cnpj.in_(['00000000000272', '00000000000353'])).all()]
        if leftovers:
            _cleanup_firms(leftovers)

        firm_a = LawFirm(name='Firma A Comunicações', cnpj='00000000000272')
        firm_b = LawFirm(name='Firma B Comunicações', cnpj='00000000000353')
        db.session.add_all([firm_a, firm_b])
        db.session.flush()

        user_a = User(law_firm_id=firm_a.id, name='Admin A', email='a@teste-comm-rotas.local', role='admin')
        user_a.set_password('x')
        user_b = User(law_firm_id=firm_b.id, name='Admin B', email='b@teste-comm-rotas.local', role='admin')
        user_b.set_password('x')
        db.session.add_all([user_a, user_b])
        db.session.flush()

        proc = JudicialProcess(
            law_firm_id=firm_a.id, user_id=user_a.id,
            process_number='0000001-11.2026.4.03.6100',
            title='Descoberto Teste', origin='comunica_auto',
            discovery_status='pending_review',
        )
        db.session.add(proc)
        db.session.flush()

        comm = ProcessCommunication(
            law_firm_id=firm_a.id, judicial_process_id=proc.id,
            hash='rota-hash-1', sigla_tribunal='TRF3', tipo_comunicacao='Intimação',
            numero_processo='00000011120264036100',
            numero_processo_mascara='0000001-11.2026.4.03.6100',
            data_disponibilizacao=date.today(), texto='Teor de teste',
        )
        db.session.add(comm)
        db.session.commit()

        firm_a_id, firm_b_id = firm_a.id, firm_b.id
        comm_id, proc_id = comm.id, proc.id

        try:
            with app.test_client() as client:
                _login(client, user_a)

                r = client.get('/comunicacoes/')
                assert r.status_code == 200, r.status_code
                assert b'rota-hash-1' not in r.data  # hash é interno
                assert 'Intimação'.encode() in r.data
                print('✅ 1) lista de comunicações responde 200 com dados')

                r = client.get(f'/comunicacoes/{comm_id}')
                assert r.status_code == 200 and b'Teor de teste' in r.data
                assert ProcessCommunication.query.get(comm_id).read_at is not None
                print('✅ 2) detalhe exibe teor e marca como lida')

                r = client.get('/process-panel/?discovery=descobertos')
                assert r.status_code == 200 and b'Descoberto Teste' in r.data
                r = client.get('/process-panel/')
                assert b'Descoberto Teste' not in r.data
                print('✅ 3) descoberto aparece só na aba Descobertos')

                r = client.post(f'/process-panel/{proc_id}/descoberta',
                                data={'action': 'confirm', 'next': 'lista'},
                                follow_redirects=False)
                assert r.status_code == 302
                assert JudicialProcess.query.get(proc_id).discovery_status == 'confirmed'
                print('✅ 4) confirmação move o processo para a lista principal')

            with app.test_client() as client:
                _login(client, user_b)
                r = client.get(f'/comunicacoes/{comm_id}')
                assert r.status_code == 404, f'tenant B acessou comunicação do A ({r.status_code})'
                r = client.get('/comunicacoes/')
                assert 'Intimação'.encode() not in r.data
                print('✅ 5) isolamento de tenant (escritório B não vê dados do A)')

        except AssertionError as e:
            print(f'❌ Falha: {e}')
            ok = False
        finally:
            _cleanup_firms([firm_a_id, firm_b_id])

    return ok


if __name__ == '__main__':
    print('🧪 Testando rotas de Comunicações...')
    sys.exit(0 if run() else 1)
