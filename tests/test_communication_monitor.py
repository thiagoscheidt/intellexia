#!/usr/bin/env python3
"""
Teste do communication_monitor_service com client FAKE (sem tocar a API real).

Cobre: dedup por hash, criação flagada de processo descoberto (origin/discovery),
importação de histórico, marca d'água em sucesso e falha, e CNJ inválido.

    uv run python tests/test_communication_monitor.py
"""

import sys
from datetime import date
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from main import app
from app.models import (
    db, CommunicationSyncState, JudicialProcess, LawFirm, Lawyer,
    ProcessCommunication, User,
)
from app.services import communication_monitor_service as monitor
from app.services.comunica_pje_client import ComunicaPjeClient, ComunicaPjeError

PROC_1 = '5001181562023403610' + '0'  # 20 dígitos


def _item(hash_, numero=PROC_1, tipo='Intimação', data='2026-07-18'):
    return {
        'id': abs(hash(hash_)) % 10**9,
        'hash': hash_,
        'siglaTribunal': 'TRF3',
        'tipoComunicacao': tipo,
        'tipoDocumento': 'Despacho',
        'nomeOrgao': '1ª Vara Federal',
        'nomeClasse': 'Procedimento Comum',
        'data_disponibilizacao': data,
        'numero_processo': numero,
        'numeroprocessocommascara': monitor.format_cnj(numero),
        'texto': 'PODER JUDICIÁRIO — teste',
        'link': 'https://example.org/doc',
        'destinatarios': [{'nome': 'EMPRESA X', 'polo': 'A'}],
        'destinatarioadvogados': [{'advogado': {'nome': 'ADV', 'numero_oab': '53004', 'uf_oab': 'SC'}}],
    }


class FakeClient(ComunicaPjeClient):
    """Client fake: devolve itens pré-definidos, sem rede."""

    def __init__(self, oab_items=None, history_items=None, fail=False):
        super().__init__()
        self.oab_items = oab_items or []
        self.history_items = history_items or []
        self.fail = fail

    def iter_comunicacoes(self, **kwargs):
        if self.fail:
            raise ComunicaPjeError('simulated failure')
        yield from self.oab_items

    def get_comunicacoes_processo(self, numero_processo):
        return self.history_items


def _cleanup_firm(firm_id):
    db.session.rollback()
    ProcessCommunication.query.filter_by(law_firm_id=firm_id).delete()
    CommunicationSyncState.query.filter_by(law_firm_id=firm_id).delete()
    JudicialProcess.query.filter_by(law_firm_id=firm_id).delete()
    Lawyer.query.filter_by(law_firm_id=firm_id).delete()
    User.query.filter_by(law_firm_id=firm_id).delete()
    LawFirm.query.filter_by(id=firm_id).delete()
    db.session.commit()


def run():
    ok = True
    with app.app_context():
        # Remove sobras de execuções anteriores que falharam no meio.
        leftover = LawFirm.query.filter_by(cnpj='00000000000191').first()
        if leftover:
            _cleanup_firm(leftover.id)

        firm = LawFirm(name='Teste Comunicações LTDA', cnpj='00000000000191')
        db.session.add(firm)
        db.session.flush()
        user = User(law_firm_id=firm.id, name='Admin Teste', email='admin@teste-comm.local',
                    role='admin')
        user.set_password('x')
        db.session.add(user)
        lawyer = Lawyer(law_firm_id=firm.id, name='Dr. Teste', oab_number='99999-teste',
                        oab_uf='SC')
        db.session.add(lawyer)
        db.session.commit()

        try:
            # 1) Sync cria comunicação + processo descoberto flagado, com histórico
            client = FakeClient(
                oab_items=[_item('hash-a')],
                history_items=[_item('hash-a'), _item('hash-b', data='2023-05-01')],
            )
            stats = monitor.sync_lawyer(firm.id, lawyer, client=client)
            assert stats['status'] == 'ok', stats
            assert stats['processes_created'] == 1, stats
            comms = ProcessCommunication.query.filter_by(law_firm_id=firm.id).all()
            assert len(comms) == 2, f'esperava 2 comunicações (atual + histórico), veio {len(comms)}'
            proc = JudicialProcess.query.filter_by(law_firm_id=firm.id).one()
            assert proc.origin == 'comunica_auto' and proc.discovery_status == 'pending_review'
            assert all(c.judicial_process_id == proc.id for c in comms)
            print('✅ 1) descoberta de processo flagado + histórico importado')

            # 2) Marca d'água avançou
            state = CommunicationSyncState.query.filter_by(lawyer_id=lawyer.id).one()
            assert state.last_synced_date == date.today(), state.last_synced_date
            print("✅ 2) marca d'água avançou no sucesso")

            # 3) Re-sync com mesmo hash → dedup (UPDATE, não INSERT)
            stats = monitor.sync_lawyer(firm.id, lawyer, client=client)
            assert stats['created'] == 0 and stats['updated'] >= 1, stats
            assert ProcessCommunication.query.filter_by(law_firm_id=firm.id).count() == 2
            print('✅ 3) dedup por hash (mesmo hash → UPDATE)')

            # 4) CNJ inválido → salva sem vínculo
            client2 = FakeClient(oab_items=[_item('hash-c', numero='123')])
            monitor.sync_lawyer(firm.id, lawyer, client=client2)
            orphan = ProcessCommunication.query.filter_by(law_firm_id=firm.id, hash='hash-c').one()
            assert orphan.judicial_process_id is None
            print('✅ 4) CNJ inválido salvo sem vínculo (nada se perde)')

            # 5) Falha → marca d'água não avança e erro registrado
            state.last_synced_date = date(2020, 1, 1)
            db.session.commit()
            stats = monitor.sync_lawyer(firm.id, lawyer, client=FakeClient(fail=True))
            assert stats['status'] == 'failed'
            state = CommunicationSyncState.query.filter_by(lawyer_id=lawyer.id).one()
            assert state.last_synced_date == date(2020, 1, 1)
            assert state.last_error and 'simulated' in state.last_error
            print("✅ 5) falha não avança a marca d'água e registra o erro")

            # 6) Digest agrupa por processo
            from datetime import datetime, timedelta
            digest = monitor.build_communications_digest(
                firm.id, since=datetime.now() - timedelta(days=1))
            assert digest['has_novidades'] and digest['totais']['total'] >= 2, digest['totais']
            print('✅ 6) digest com novidades agrupadas por processo')

        except AssertionError as e:
            print(f'❌ Falha: {e}')
            ok = False
        finally:
            _cleanup_firm(firm.id)

    return ok


if __name__ == '__main__':
    print('🧪 Testando communication_monitor_service (client fake)...')
    sys.exit(0 if run() else 1)
