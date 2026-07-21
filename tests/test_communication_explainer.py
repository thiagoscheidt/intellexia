#!/usr/bin/env python3
"""
Testa a explicação de comunicações via IA (service + rota), com o agente mockado:
cache em analysis_json, isolamento de tenant, comunicação sem teor e erros.

Uso: uv run python tests/test_communication_explainer.py
Não faz chamadas reais à OpenAI.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, LawFirm, User, ProcessCommunication
from app.services import communication_monitor_service as monitor
from app.agents.processes.communication_explainer_agent import (
    CommunicationDeadline, CommunicationExplanation,
)

failures = []


def check(name, cond, detail=''):
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f' — {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(name)


FAKE_EXPLANATION = CommunicationExplanation(
    resumo='O processo foi incluído na pauta da sessão virtual de 06/08/2026.',
    acao_requerida='acao_facultativa',
    acao_descricao='Manifestar-se até 2 dias úteis antes do início da sessão, se desejar.',
    prazo=CommunicationDeadline(existe=True, descricao='Manifestação facultativa', dias=2,
                                tipo_contagem='uteis', data_limite_estimada='2026-07-28',
                                base_calculo='início da sessão virtual (30/07)'),
    datas_chave=[],
    papel_escritorio='Advogada do apelado',
    urgencia='media',
    urgencia_justificativa='Janela de manifestação curta, mas facultativa.',
    glossario=[],
)


with app.app_context():
    firm = LawFirm(name='Firm Explainer Teste', cnpj='00000000000194')
    other_firm = LawFirm(name='Outro Firm Expl', cnpj='00000000000193')
    db.session.add_all([firm, other_firm])
    db.session.flush()
    admin = User(law_firm_id=firm.id, name='Admin E', email='admin__t_expl@example.com',
                 role='admin', is_active=True)
    admin.set_password('x')
    comm = ProcessCommunication(law_firm_id=firm.id, hash='hash-expl-1', texto='Teor de teste',
                                sigla_tribunal='TRF4', tipo_comunicacao='Intimação')
    comm_sem_teor = ProcessCommunication(law_firm_id=firm.id, hash='hash-expl-2', texto=None)
    db.session.add_all([admin, comm, comm_sem_teor])
    db.session.commit()
    ids = (firm.id, other_firm.id, admin.id, comm.id, comm_sem_teor.id)

    try:
        calls = {'n': 0}

        def fake_explain(self, payload, user_id=None, law_firm_id=None):
            calls['n'] += 1
            return FAKE_EXPLANATION

        with patch('app.agents.processes.communication_explainer_agent.'
                   'CommunicationExplainerAgent.explain', fake_explain):
            # 1) primeira chamada gera e salva cache
            r1 = monitor.explain_communication(firm.id, comm.id, user_id=admin.id)
            check('primeira chamada gera análise', r1['cached'] is False and calls['n'] == 1)
            check('resumo presente', 'pauta' in r1['data']['resumo'])
            db.session.refresh(comm)
            check('cache persistido em analysis_json', bool(comm.analysis_json))

            # 2) segunda chamada usa cache (não chama a IA)
            r2 = monitor.explain_communication(firm.id, comm.id, user_id=admin.id)
            check('segunda chamada vem do cache', r2['cached'] is True and calls['n'] == 1)

            # 3) sem teor → erro amigável
            try:
                monitor.explain_communication(firm.id, comm_sem_teor.id)
                check('sem teor levanta ValueError', False)
            except ValueError as e:
                check('sem teor levanta ValueError', 'teor' in str(e).lower())

            # 4) outro escritório não acessa (tenant)
            try:
                monitor.explain_communication(other_firm.id, comm.id)
                check('outro escritório → erro', False)
            except ValueError:
                check('outro escritório → erro', True)

            # 5) rota HTTP
            with app.test_client() as client:
                with client.session_transaction() as s:
                    s['user_id'] = admin.id; s['law_firm_id'] = firm.id; s['user_role'] = 'admin'
                    s['user_module_permissions'] = admin.get_module_permissions()
                resp = client.post(f'/comunicacoes/{comm.id}/explicar')
                payload = resp.get_json()
                check('rota responde 200 com cache', resp.status_code == 200 and payload['cached'] is True)
                resp = client.post(f'/comunicacoes/{comm_sem_teor.id}/explicar')
                check('rota sem teor → 400', resp.status_code == 400)
                resp = client.post('/comunicacoes/999999/explicar')
                check('rota id inexistente → 400', resp.status_code == 400)

        # 6) falha da IA não persiste nada
        comm.analysis_json = None
        db.session.commit()

        def broken_explain(self, payload, user_id=None, law_firm_id=None):
            raise RuntimeError('api down')

        with patch('app.agents.processes.communication_explainer_agent.'
                   'CommunicationExplainerAgent.explain', broken_explain):
            with app.test_client() as client:
                with client.session_transaction() as s:
                    s['user_id'] = admin.id; s['law_firm_id'] = firm.id; s['user_role'] = 'admin'
                    s['user_module_permissions'] = admin.get_module_permissions()
                resp = client.post(f'/comunicacoes/{comm.id}/explicar')
                check('falha da IA → 500 com mensagem amigável', resp.status_code == 500
                      and 'Tente novamente' in resp.get_json()['message'])
            db.session.refresh(comm)
            check('falha não grava cache', comm.analysis_json is None)
    finally:
        firm_id, other_firm_id, admin_id, c1, c2 = ids
        ProcessCommunication.query.filter(ProcessCommunication.id.in_([c1, c2])).delete(synchronize_session=False)
        User.query.filter_by(id=admin_id).delete(synchronize_session=False)
        LawFirm.query.filter(LawFirm.id.in_([firm_id, other_firm_id])).delete(synchronize_session=False)
        db.session.commit()

if failures:
    print(f'\n❌ {len(failures)} falha(s): {failures}')
    sys.exit(1)
print('\n✅ Todos os testes passaram!')
