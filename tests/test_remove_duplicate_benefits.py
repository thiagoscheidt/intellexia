"""
Mesclagem de benefícios duplicados (database/remove_duplicate_benefits.py).

A regra que importa: fica a linha MAIS ADIANTADA, não a mais antiga — depois
da duplicata só uma das cópias continuava recebendo os relatórios seguintes, e
é ela que tem a decisão da 2ª instância.

Executar:
    uv run python tests/test_remove_duplicate_benefits.py
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_merge_dup.db')
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_FILE}'

from app.models import db  # noqa: E402

app.extensions.pop('sqlalchemy', None)
try:
    db._app_engines.pop(app, None)
except Exception:
    pass
db.init_app(app)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'database')))
import remove_duplicate_benefits as rdb  # noqa: E402

FALHAS = []
CNPJ = '58.160.789/0001-28'


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra else ''}")
    if not condicao:
        FALHAS.append(rotulo)


def main():
    with app.app_context():
        from app.models import (
            Benefit, BenefitContestationDecision, BenefitFapSourceHistory,
            BenefitManualHistory, LawFirm,
        )
        assert DB_FILE in str(db.engine.url), 'ABORTADO: fora do sandbox'
        db.create_all()
        db.session.add(LawFirm(id=1, name='Escritório', cnpj='00000000000191'))
        db.session.commit()

        def beneficio(bid, numero, anos='2026', cnpj=CNPJ, **campos):
            b = Benefit(id=bid, law_firm_id=1, benefit_number=numero, employer_cnpj=cnpj,
                        fap_vigencia_years=anos, created_at=datetime(2026, 8, 27), **campos)
            db.session.add(b)
            return b

        def historico(bid, report_id, quando):
            db.session.add(BenefitFapSourceHistory(
                law_firm_id=1, benefit_id=bid, report_id=report_id, transmission_datetime=quando,
            ))

        def decisao(bid, instancia, fingerprint):
            db.session.add(BenefitContestationDecision(
                law_firm_id=1, benefit_id=bid, instancia=instancia, sequence=0,
                status='analyzing', fingerprint=fingerprint,
            ))

        # ── o caso de produção ───────────────────────────────────────────
        print('\n1. a cópia mais nova tem a decisão da 2ª instância')
        beneficio(1, '7173005613', first_instance_status='approved',
                  second_instance_status='analyzing', cat_number='CAT-123')
        beneficio(2, '7173005613', first_instance_status='approved',
                  second_instance_status='approved',
                  second_instance_justification='Recurso deferido')
        historico(1, 5, datetime(2026, 8, 27))
        historico(1, 6, datetime(2026, 8, 27))
        historico(2, 6, datetime(2026, 8, 27))
        historico(2, 7, datetime(2026, 9, 10))
        decisao(1, 1, 'a1')
        decisao(1, 2, 'a2')
        decisao(2, 2, 'b2')
        db.session.add(BenefitManualHistory(law_firm_id=1, benefit_id=1,
                                            new_first_instance_status='approved'))
        db.session.commit()

        linhas = Benefit.query.filter_by(benefit_number='7173005613').all()
        grupos, ambiguas = rdb.agrupar(linhas)
        check('um grupo de duplicatas, nada ambíguo', len(grupos) == 1 and not ambiguas)
        referencias = rdb._referencias([b.id for b in grupos[0]])
        fica, saem, _ = rdb.mesclar(grupos[0], referencias)
        db.session.commit()

        check('fica a cópia com 2ª instância decidida (a de id maior)', fica.id == 2, fica.id)
        check('a duplicata foi apagada', Benefit.query.get(1) is None)
        fica = Benefit.query.get(2)
        check('a decisão da 2ª instância continua', fica.second_instance_status == 'approved'
              and fica.second_instance_justification == 'Recurso deferido')
        check('campo que só a duplicata tinha é aproveitado', fica.cat_number == 'CAT-123')
        relatorios = sorted(h.report_id for h in
                            BenefitFapSourceHistory.query.filter_by(benefit_id=2))
        check('histórico de origem unido, sem repetir o relatório 6', relatorios == [5, 6, 7],
              relatorios)
        insts = sorted((d.instancia, d.fingerprint) for d in
                       BenefitContestationDecision.query.filter_by(benefit_id=2))
        check('traz a análise da 1ª instância, mantém a própria da 2ª',
              insts == [(1, 'a1'), (2, 'b2')], insts)
        check('histórico manual acompanha',
              BenefitManualHistory.query.filter_by(benefit_id=2).count() == 1)
        check('nada órfão', BenefitContestationDecision.query.filter_by(benefit_id=1).count() == 0
              and BenefitFapSourceHistory.query.filter_by(benefit_id=1).count() == 0)

        print('\n2. empate de status: decide o documento FAP mais recente')
        beneficio(10, '7000000010', second_instance_status='analyzing')
        beneficio(11, '7000000010', second_instance_status='analyzing')
        historico(10, 20, datetime(2026, 9, 15))
        historico(11, 21, datetime(2026, 8, 27))
        db.session.commit()
        grupos, _ = rdb.agrupar(Benefit.query.filter_by(benefit_number='7000000010').all())
        fica, _, _ = rdb.mesclar(grupos[0], rdb._referencias([10, 11]))
        db.session.commit()
        check('fica a de documento mais novo', fica.id == 10, fica.id)

        print('\n2b. status em português, como a importação grava em produção')
        beneficio(20, '7000000020', first_instance_status='Indeferido',
                  second_instance_status='Indeferido')
        beneficio(21, '7000000020', first_instance_status='Indeferido')
        historico(20, 22, datetime(2026, 1, 1))   # documento MAIS VELHO que o da outra
        historico(21, 23, datetime(2026, 5, 1))
        db.session.commit()
        grupos, _ = rdb.agrupar(Benefit.query.filter_by(benefit_number='7000000020').all())
        fica, _, _ = rdb.mesclar(grupos[0], rdb._referencias([20, 21]))
        db.session.commit()
        check('"Indeferido" na 2ª instância vence mesmo com documento mais velho', fica.id == 20,
              fica.id)
        check('pesos por vocabulário',
              [rdb.peso_status(v) for v in (None, '', 'Pendente', 'Em análise', 'analyzing',
                                            'Indeferido', 'Deferimento Parcial', 'approved')]
              == [0, 0, 1, 2, 2, 3, 3, 3])

        # ── o que não é duplicata ────────────────────────────────────────
        print('\n3. o que não pode ser mesclado')
        beneficio(30, '7000000030', anos='2025')
        beneficio(31, '7000000030', anos='2026')
        db.session.commit()
        grupos, _ = rdb.agrupar(Benefit.query.filter_by(benefit_number='7000000030').all())
        check('vigências diferentes são linhas legítimas', grupos == [])

        beneficio(40, '7000000040', cnpj='11.111.111/0001-11')
        beneficio(41, '7000000040', cnpj='22.222.222/0001-22')
        db.session.commit()
        grupos, _ = rdb.agrupar(Benefit.query.filter_by(benefit_number='7000000040').all())
        check('CNPJs diferentes não se misturam', grupos == [])

        # ── linha sem vigência (resto do defeito de agosto) ──────────────
        print('\n4. linha sem vigência')
        beneficio(50, '7000000050', anos='2026')
        beneficio(51, '7000000050', anos=None)
        db.session.commit()
        grupos, ambiguas = rdb.agrupar(Benefit.query.filter_by(benefit_number='7000000050').all())
        check('um único candidato: entra no grupo', len(grupos) == 1 and len(grupos[0]) == 2
              and not ambiguas)

        beneficio(60, '7000000060', anos='2025')
        beneficio(61, '7000000060', anos='2026')
        beneficio(62, '7000000060', anos=None)
        db.session.commit()
        grupos, ambiguas = rdb.agrupar(Benefit.query.filter_by(benefit_number='7000000060').all())
        check('dois candidatos: ambígua, não é tocada',
              grupos == [] and [b.id for b in ambiguas] == [62])

    print('\n' + '=' * 62)
    print('RESULTADO:', 'TUDO OK' if not FALHAS else f'{len(FALHAS)} FALHA(S): {FALHAS}')
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    return 1 if FALHAS else 0


if __name__ == '__main__':
    sys.exit(main())
