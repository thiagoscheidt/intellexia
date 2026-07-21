#!/usr/bin/env python3
"""
Testa a sincronização por caderno do DJEN (sync_law_firm_from_cadernos):
matching por OAB, dedup por hash, dry-run e caderno indisponível.

Uso: uv run python tests/test_caderno_sync.py
Sem rede: o client é substituído por um fake que serve um caderno em memória.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, LawFirm, User, Lawyer, ProcessCommunication, JudicialProcess
from app.services import communication_monitor_service as monitor

failures = []


def check(name, cond, detail=''):
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f' — {detail}' if detail and not cond else ''))
    if not cond:
        failures.append(name)


def make_item(comm_id, oab, uf, processo='50012345620264047200'):
    return {
        'id': comm_id,
        'hash': f'hash-{comm_id}',
        'siglaTribunal': 'TRF4',
        'tipoComunicacao': 'Intimação',
        'nomeOrgao': 'Vara Federal',
        'texto': 'Teor da comunicação de teste',
        'numero_processo': processo,
        'numeroprocessocommascara': '5001234-56.2026.4.04.7200',
        'meio': 'D',
        'data_disponibilizacao': '2026-07-17',
        'link': 'https://example.org',
        'tipoDocumento': 'Despacho',
        'nomeClasse': 'Procedimento Comum',
        'codigoClasse': '7',
        'destinatarios': [{'nome': 'Empresa X', 'polo': 'A'}],
        'destinatarioadvogados': [
            {'advogado': {'id': 1, 'nome': 'Adv Teste', 'numero_oab': oab, 'uf_oab': uf}},
        ],
    }


class FakeCadernoClient:
    """Serve um caderno em memória; sem nenhuma chamada de rede."""

    def __init__(self, items, status='Processado'):
        self.items = items
        self.status = status
        self.parse_comunicacao = __import__(
            'app.services.comunica_pje_client', fromlist=['ComunicaPjeClient']
        ).ComunicaPjeClient.parse_comunicacao

    def get_caderno(self, sigla, data, meio='D'):
        return {'sigla_tribunal': sigla, 'status': self.status,
                'data': data.isoformat(), 'url': 'stub://caderno'}

    def iter_caderno_comunicacoes(self, meta):
        yield from self.items

    def get_comunicacoes_processo(self, numero):
        return []  # descoberta de processo sem histórico extra


with app.app_context():
    # setup idempotente: remove resíduo de execuções anteriores interrompidas
    leftover = LawFirm.query.filter_by(cnpj='00000000000195').first()
    if leftover:
        from app.models import CommunicationSyncState
        ProcessCommunication.query.filter_by(law_firm_id=leftover.id).delete(synchronize_session=False)
        CommunicationSyncState.query.filter_by(law_firm_id=leftover.id).delete(synchronize_session=False)
        JudicialProcess.query.filter_by(law_firm_id=leftover.id).delete(synchronize_session=False)
        Lawyer.query.filter_by(law_firm_id=leftover.id).delete(synchronize_session=False)
        User.query.filter_by(law_firm_id=leftover.id).delete(synchronize_session=False)
        db.session.delete(leftover)
        db.session.commit()

    firm = LawFirm(name='Firm Caderno Teste', cnpj='00000000000195')
    db.session.add(firm)
    db.session.flush()
    admin = User(law_firm_id=firm.id, name='Admin C', email='admin__t_cad@example.com',
                 role='admin', is_active=True)
    admin.set_password('x')
    lawyer = Lawyer(law_firm_id=firm.id, name='Dr. Caderno', oab_number='OAB/SC 99.111',
                    oab_uf='SC', email='cad@example.com')
    db.session.add_all([admin, lawyer])
    db.session.commit()
    ids = (firm.id, admin.id, lawyer.id)

    try:
        items = [
            make_item(1, '99111', 'SC'),          # do escritório (dígitos puros)
            make_item(2, '12345', 'SC'),          # de outro advogado
            make_item(3, 'OAB/SC 99.111', 'SC'),  # do escritório, OAB formatada
            make_item(4, '99111', 'SP'),          # mesmo número, UF errada
        ]

        # 1) matching por OAB normalizada
        summary = monitor.sync_law_firm_from_cadernos(
            firm.id, data=date(2026, 7, 17), siglas=['TRF4'],
            client=FakeCadernoClient(items))
        r = summary['results'][0]
        check('varreu todas as comunicações', r['scanned'] == 4, str(r))
        check('casou só as OABs do escritório (2 de 4)', r['matched'] == 2, str(r))
        check('criou 2 comunicações', r['created'] == 2, str(r))
        comms = ProcessCommunication.query.filter_by(law_firm_id=firm.id).all()
        check('comunicações vinculadas ao advogado',
              all(c.matched_lawyer_id == lawyer.id for c in comms), str([c.matched_lawyer_id for c in comms]))
        check('fonte carimbada como comunica_pje',
              all(c.source == ProcessCommunication.SOURCE_COMUNICA_PJE for c in comms),
              str([c.source for c in comms]))
        check('filtro por fonte funciona',
              monitor.communications_query(firm.id, source='comunica_pje').count() == 2
              and monitor.communications_query(firm.id, source='outra_fonte').count() == 0)
        check('processo descoberto automaticamente',
              JudicialProcess.query.filter_by(law_firm_id=firm.id, origin='comunica_auto').count() == 1)

        # 2) dedup: segunda rodada não duplica
        summary = monitor.sync_law_firm_from_cadernos(
            firm.id, data=date(2026, 7, 17), siglas=['TRF4'],
            client=FakeCadernoClient(items))
        r = summary['results'][0]
        check('segunda rodada não cria de novo', r['created'] == 0 and r['updated'] == 2, str(r))

        # 3) caderno indisponível → skipped, sem erro fatal
        summary = monitor.sync_law_firm_from_cadernos(
            firm.id, data=date(2026, 7, 17), siglas=['TRF4'],
            client=FakeCadernoClient(items, status='Em processamento'))
        r = summary['results'][0]
        check('caderno não processado → skipped', r['status'] == 'skipped', str(r))

        # 4) dry-run não persiste
        items_new = [make_item(9, '99111', 'SC', processo='50019999920264047200')]
        before = ProcessCommunication.query.filter_by(law_firm_id=firm.id).count()
        summary = monitor.sync_law_firm_from_cadernos(
            firm.id, data=date(2026, 7, 17), siglas=['TRF4'],
            client=FakeCadernoClient(items_new), dry_run=True)
        after = ProcessCommunication.query.filter_by(law_firm_id=firm.id).count()
        check('dry-run não persiste', before == after and summary['results'][0]['status'] == 'dry_run',
              f'{before} → {after}')

        # 5) siglas padrão vêm do histórico do escritório
        siglas = monitor.firm_tribunal_siglas(firm.id)
        check('siglas padrão derivadas do histórico', siglas == ['TRF4'], str(siglas))
    finally:
        firm_id, admin_id, lawyer_id = ids
        ProcessCommunication.query.filter_by(law_firm_id=firm_id).delete(synchronize_session=False)
        from app.models import CommunicationSyncState
        CommunicationSyncState.query.filter_by(law_firm_id=firm_id).delete(synchronize_session=False)
        JudicialProcess.query.filter_by(law_firm_id=firm_id).delete(synchronize_session=False)
        Lawyer.query.filter_by(id=lawyer_id).delete(synchronize_session=False)
        User.query.filter_by(id=admin_id).delete(synchronize_session=False)
        LawFirm.query.filter_by(id=firm_id).delete(synchronize_session=False)
        db.session.commit()

if failures:
    print(f'\n❌ {len(failures)} falha(s): {failures}')
    sys.exit(1)
print('\n✅ Todos os testes passaram!')
