#!/usr/bin/env python3
"""
Listagem do Painel de Contestações – Benefícios: uma passagem só pela tabela.

``benefits`` tem linhas de dezenas de KB (2,2 GB na homologação). Filtrar por
"Número contém 6505977833" levava 12 s: cada uma das ~7 contagens relia o
escritório inteiro, e a página pedia todas as colunas no ORDER BY … LIMIT.
Agora os ids filtrados saem numa passagem e o resto vai pela chave primária; NB
completo é igualdade (índice ``(law_firm_id, benefit_number)``).

Confere que a resposta é a mesma pelo caminho novo e pelo antigo (filtro amplo,
acima de ``_LISTA_IDS_PASSAGEM_UNICA``). Escritório descartável.

    uv run python tests/test_disputes_center_lista_rapida.py
"""

import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, LawFirm, User, UserPageVisit, Benefit
import app.blueprints.disputes_center as dc

TEST_CNPJ = '00000000001699'
EMAIL = 'user__test_lista_rapida@example.com'

_falhas = []


def check(nome, cond, detalhe=''):
    print(('  ✅ ' if cond else '  ❌ ') + nome + ((' — ' + str(detalhe)) if detalhe and not cond else ''))
    if not cond:
        _falhas.append(nome)


def setup():
    firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
    if firm:
        cleanup(firm)
    firm = LawFirm(name='Escritório Teste Lista Rápida', cnpj=TEST_CNPJ)
    db.session.add(firm)
    db.session.flush()
    user = User(law_firm_id=firm.id, name='t', email=EMAIL, role='admin', is_active=True)
    user.set_password('x')
    db.session.add(user)
    for i in range(30):
        db.session.add(Benefit(
            law_firm_id=firm.id, benefit_number=f'65059778{i:02d}', benefit_type='B91' if i % 3 else 'B94',
            first_instance_status=('indeferido', 'deferido', 'Em análise', None)[i % 4],
            second_instance_status=('indeferido', None)[i % 2],
            employer_cnpj='07718633008163',
        ))
    db.session.commit()
    return firm, user


def cleanup(firm):
    ids = [u.id for u in User.query.filter_by(law_firm_id=firm.id)]
    if ids:
        UserPageVisit.query.filter(UserPageVisit.user_id.in_(ids)).delete(synchronize_session=False)
    User.query.filter_by(law_firm_id=firm.id).delete()
    Benefit.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def _api(client, **extra):
    q = {'draw': '1', 'start': '0', 'length': '10', 'quick_vigencia': '__all__', **extra}
    d = client.get('/disputes-center/api/list?' + urllib.parse.urlencode(q)).get_json()
    d.pop('draw', None)
    return d


def _cf(*filtros):
    return json.dumps([dict(field=f, operator=o, value=v) for f, o, v in filtros])


def main():
    with app.app_context():
        firm, user = setup()
        original = dc._LISTA_IDS_PASSAGEM_UNICA
        try:
            client = app.test_client()
            with client.session_transaction() as s:
                s.update(user_id=user.id, law_firm_id=firm.id, user_role='admin',
                         user_module_permissions=user.get_module_permissions())

            casos = {
                'tudo': {},
                'pagina 2': {'start': '10'},
                'status 1ª indeferido': {'custom_filters': _cf(('first_instance_status', 'equals', 'indeferido'))},
                'trecho do número': {'custom_filters': _cf(('benefit_number', 'contains', '6505977'))},
                'ordem por número asc': {'order[0][column]': '1', 'order[0][dir]': 'asc'},
            }
            print('\n1. Caminho novo (passagem única) e antigo (filtro amplo) devolvem o mesmo')
            novo = {k: _api(client, **v) for k, v in casos.items()}
            dc._LISTA_IDS_PASSAGEM_UNICA = 5
            antigo = {k: _api(client, **v) for k, v in casos.items()}
            dc._LISTA_IDS_PASSAGEM_UNICA = original
            for nome in casos:
                check(nome, novo[nome] == antigo[nome])
            check('página na ordem pedida',
                  [r['benefit_number'] for r in novo['ordem por número asc']['data']]
                  == sorted(r['benefit_number'] for r in novo['ordem por número asc']['data']))
            check('contagem filtrada', novo['tudo']['recordsFiltered'] == 30
                  and novo['status 1ª indeferido']['recordsFiltered'] == 8,
                  str((novo['tudo']['recordsFiltered'], novo['status 1ª indeferido']['recordsFiltered'])))

            print('\n2. NB completo')
            d = _api(client, custom_filters=_cf(('benefit_number', 'contains', '6505977807')))
            check('"contém" com o NB inteiro acha o benefício',
                  d['recordsFiltered'] == 1 and d['data'][0]['benefit_number'] == '6505977807', str(d['recordsFiltered']))
            d = _api(client, custom_filters=_cf(('benefit_number', 'contains', '650597780')))
            check('trecho de 9 dígitos continua sendo "contém"', d['recordsFiltered'] == 10, str(d['recordsFiltered']))
        finally:
            dc._LISTA_IDS_PASSAGEM_UNICA = original
            db.session.rollback()
            cleanup(firm)

    print('\n' + ('✅ Tudo verde' if not _falhas else f'❌ {len(_falhas)} falha(s): {_falhas}'))
    return 1 if _falhas else 0


if __name__ == '__main__':
    sys.exit(main())
