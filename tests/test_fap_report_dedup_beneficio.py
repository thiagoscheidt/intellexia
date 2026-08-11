"""
Deduplicação de benefícios na importação de relatório FAP.

Reproduz o defeito que duplicou 61 benefícios em produção: a busca por
benefício existente só reconhecia a linha quando o ano já estava gravado em
``fap_vigencia_years``. Esse campo, porém, só é escrito quando o relatório traz
o ano na capa e a atualização é aplicada — se a primeira importação não leu o
ano, a linha ficava sem ele, a importação seguinte não a encontrava e inseria
uma segunda. A assinatura em produção eram blocos contíguos de id, com as duas
cópias a 1–9 ids de distância.

Executar:
    uv run python tests/test_fap_report_dedup_beneficio.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_dedup.db')
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

from app.services.fap_contestation_judgment_report_service import (  # noqa: E402
    FapContestationJudgmentReportService,
)

FALHAS = []


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra else ''}")
    if not condicao:
        FALHAS.append(rotulo)


def main():
    from datetime import datetime

    with app.app_context():
        from app.models import LawFirm, Benefit
        assert DB_FILE in str(db.engine.url), 'ABORTADO: fora do sandbox'
        db.create_all()
        db.session.add(LawFirm(id=1, name='Escritório', cnpj='00000000000191'))
        db.session.add(LawFirm(id=2, name='Outro', cnpj='00000000000272'))
        db.session.commit()

        servico = FapContestationJudgmentReportService(app)

        def novo_beneficio(bid, numero, anos, law_firm_id=1):
            db.session.add(Benefit(
                id=bid, law_firm_id=law_firm_id, benefit_number=numero,
                fap_vigencia_years=anos, created_at=datetime(2026, 1, 1),
            ))
            db.session.commit()

        def procura(numero, ano, law_firm_id=1):
            return servico._find_existing_benefit_for_report(
                law_firm_id=law_firm_id, benefit_number=numero, validity_year=ano,
            )

        # ── o defeito ────────────────────────────────────────────────────
        print('\n1. benefício sem vigência gravada (o caso que duplicava)')
        novo_beneficio(1, '6316257396', None)
        achado = procura('6316257396', '2022')
        check('encontra a linha existente em vez de mandar criar outra',
              achado is not None and achado.id == 1,
              f'devolveu {achado.id if achado else None}')

        novo_beneficio(2, '1879727398', '')
        achado = procura('1879727398', '2022')
        check('idem com string vazia',
              achado is not None and achado.id == 2,
              f'devolveu {achado.id if achado else None}')

        # ── o que já funcionava e não pode regredir ──────────────────────
        print('\n2. comportamento que já estava correto')
        novo_beneficio(3, '6371831651', '2025')
        achado = procura('6371831651', '2025')
        check('ano igual → mesma linha', achado is not None and achado.id == 3,
              f'devolveu {achado.id if achado else None}')

        novo_beneficio(4, '6380574283', '2023')
        achado = procura('6380574283', '2025')
        check('ano diferente → cria nova linha (uma por vigência)',
              achado is None, f'devolveu {achado.id if achado else None}')

        novo_beneficio(5, '6386065550', '2021,2022,2023')
        achado = procura('6386065550', '2022')
        check('ano no meio da lista CSV é reconhecido',
              achado is not None and achado.id == 5,
              f'devolveu {achado.id if achado else None}')

        achado = procura('NAO_EXISTE', '2025')
        check('benefício inexistente → None', achado is None)

        achado = procura('6371831651', None)
        check('relatório sem ano na capa → primeira linha existente',
              achado is not None and achado.id == 3,
              f'devolveu {achado.id if achado else None}')

        # ── a escolha entre vários candidatos ────────────────────────────
        print('\n3. vários candidatos com o mesmo número')
        novo_beneficio(10, '9999999999', '2020')
        novo_beneficio(11, '9999999999', None)     # sem vigência
        novo_beneficio(12, '9999999999', '2024')
        achado = procura('9999999999', '2024')
        check('prefere o que já tem a vigência certa',
              achado is not None and achado.id == 12,
              f'devolveu {achado.id if achado else None}')
        achado = procura('9999999999', '2022')
        check('sem correspondência exata, adota o que está sem vigência',
              achado is not None and achado.id == 11,
              f'devolveu {achado.id if achado else None}')

        novo_beneficio(20, '8888888888', '2019')
        novo_beneficio(21, '8888888888', '2020')
        achado = procura('8888888888', '2025')
        check('todos com vigência diferente → cria nova (não rouba linha alheia)',
              achado is None, f'devolveu {achado.id if achado else None}')

        # ── multi-tenancy ────────────────────────────────────────────────
        print('\n4. multi-tenancy')
        novo_beneficio(30, '7777777777', None, law_firm_id=2)
        achado = procura('7777777777', '2025', law_firm_id=1)
        check('não adota benefício de outro escritório', achado is None,
              f'devolveu {achado.id if achado else None}')
        achado = procura('7777777777', '2025', law_firm_id=2)
        check('o próprio escritório encontra o seu',
              achado is not None and achado.id == 30)

    print('\n' + '=' * 62)
    print('RESULTADO:', 'TUDO OK' if not FALHAS else f'{len(FALHAS)} FALHA(S): {FALHAS}')
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    return 1 if FALHAS else 0


if __name__ == '__main__':
    sys.exit(main())
