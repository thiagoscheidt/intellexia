"""Pré-checagem antes do --apply: alguma decisão seria apagada sem ser reconstruída?

O script apaga decisões com report_id NULL (órfãs) e as dos relatórios que vai
reprocessar. Órfã apagada não volta — é preciso saber se existe alguma antes.
"""
import os, sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
from main import app
from app.models import Benefit, BenefitContestationDecision, BenefitFapSourceHistory, db

BENEFIT_IDS = [
    59669, 59670, 59671, 59672, 59673, 59661, 59725, 59728, 59675, 59617,
    59678, 59621, 59683, 59626, 59687, 59688, 59689, 59628, 59706, 59708,
    59709, 59710, 59711, 59649, 59715, 59716, 59721, 59722, 59723, 59656,
    59724, 59731, 59737,
]
REPROCESS_IDS = [
    33770, 33772, 33773, 33774, 33779, 33784, 33787, 33798, 33799, 33802,
    33804, 33805, 33806, 33807, 33808, 33810, 33817, 33818, 33821, 33827, 33869,
]

with app.app_context():
    orfas = BenefitContestationDecision.query.filter(
        BenefitContestationDecision.benefit_id.in_(BENEFIT_IDS),
        BenefitContestationDecision.report_id.is_(None),
    ).all()
    fora = BenefitContestationDecision.query.filter(
        BenefitContestationDecision.benefit_id.in_(BENEFIT_IDS),
        BenefitContestationDecision.report_id.isnot(None),
        db.not_(BenefitContestationDecision.report_id.in_(REPROCESS_IDS)),
    ).all()

    print(f'decisões órfãs (report_id NULL) — SERIAM APAGADAS SEM VOLTAR: {len(orfas)}')
    for d in orfas[:20]:
        print(f'   decisão #{d.id} benefit #{d.benefit_id} inst {d.instancia} status {d.status!r}')

    print(f'\ndecisões de relatório FORA da lista de reprocesso — preservadas: {len(fora)}')
    for d in fora[:20]:
        print(f'   decisão #{d.id} benefit #{d.benefit_id} relatório #{d.report_id} status {d.status!r}')

    print('\nhistórico de fonte por benefício (relatórios que o alimentaram):')
    for bid in BENEFIT_IDS:
        b = db.session.get(Benefit, bid)
        rows = BenefitFapSourceHistory.query.filter_by(benefit_id=bid).all()
        rids = sorted({r.report_id for r in rows if r.report_id})
        faltando = [r for r in rids if r not in REPROCESS_IDS]
        marca = '  <-- relatório fora da lista' if faltando else ''
        print(f'   #{bid} NB {b.benefit_number if b else "?"} vigência {b.fap_vigencia_years if b else "?"!s:>10} '
              f'relatórios {rids}{marca}')

    print('\nVEREDITO:', 'SEGURO seguir para --apply' if not orfas else
          'PARE — há decisão órfã que não seria reconstruída')
