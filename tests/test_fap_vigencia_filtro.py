"""
Filtro de vigência: serviço + as telas que ganharam a caixa dedicada.

Roda contra SQLite descartável — o teste grava dados.

Executar:
    uv run python tests/test_fap_vigencia_filtro.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_vigencia.db')
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

from app.services import fap_vigencia_service as svc  # noqa: E402

FALHAS = []


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra else ''}")
    if not condicao:
        FALHAS.append(rotulo)


def main():
    from datetime import datetime

    with app.app_context():
        from app.models import (
            LawFirm, User, Benefit, FapVigenciaCnpj, FapContestationCat,
            FapContestationJudgmentReport,
        )
        assert DB_FILE in str(db.engine.url), 'ABORTADO: fora do sandbox'
        db.create_all()

        db.session.add(LawFirm(id=1, name='Escritório A', cnpj='00000000000191'))
        db.session.add(LawFirm(id=2, name='Escritório B', cnpj='00000000000272'))
        db.session.add(User(id=1, law_firm_id=1, name='Admin', email='a@b.c',
                            password_hash='x', role='admin'))

        # Vigências: 2026 (2 empresas), 2023, 2021 — e uma do outro escritório
        vigencias = [
            (1, 1, '2026', '11111111000100'), (2, 1, '2026', '22222222000100'),
            (3, 1, '2023', '11111111000100'), (4, 1, '2021', '11111111000100'),
            (5, 2, '2019', '33333333000100'),
        ]
        for vid, lf, ano, cnpj in vigencias:
            db.session.add(FapVigenciaCnpj(
                id=vid, law_firm_id=lf, vigencia_year=ano, employer_cnpj=cnpj,
            ))
        # CATs exigem um relatório de origem (report_id é NOT NULL)
        db.session.add(FapContestationJudgmentReport(
            id=1, user_id=1, law_firm_id=1,
            original_filename='r.pdf', file_path='/tmp/r.pdf', status='completed',
        ))
        db.session.flush()

        # Benefícios pendurados nas vigências (é assim que o ano é resolvido)
        for bid, lf, vig in [(1, 1, 1), (2, 1, 1), (3, 1, 2), (4, 1, 3), (5, 1, 4), (6, 2, 5)]:
            db.session.add(Benefit(
                id=bid, law_firm_id=lf, benefit_number=f'B{bid}',
                fap_vigencia_cnpj_id=vig, created_at=datetime(2026, 1, 1),
            ))

        # CATs: ano desnormalizado na própria tabela, incluindo uma sem vigencia_id
        for cid, lf, ano, vig in [(1, 1, '2026', 1), (2, 1, '2023', 3), (3, 1, '2026', None)]:
            db.session.add(FapContestationCat(
                id=cid, law_firm_id=lf, report_id=1, cat_number=f'CAT{cid}',
                vigencia_year=ano, vigencia_id=vig,
                employer_cnpj='11111111000100',
            ))
        db.session.commit()

        # ── normalização ──────────────────────────────────────────────────
        print('\n1. normalize_year')
        check("'2026' → 2026", svc.normalize_year('2026') == '2026')
        check("'__all__' desliga o filtro", svc.normalize_year(svc.TODAS) == '')
        check("vazio desliga o filtro", svc.normalize_year('') == '')
        check("lixo é recusado", svc.normalize_year('abc') == '', svc.normalize_year('abc'))
        check("ano incompleto é recusado", svc.normalize_year('202') == '')

        # ── anos disponíveis ──────────────────────────────────────────────
        print('\n2. anos disponíveis (só os que a tela tem)')
        anos_ben = svc.benefit_available_years(1)
        check('benefícios: 2026, 2023, 2021 em ordem decrescente',
              anos_ben == ['2026', '2023', '2021'], anos_ben)
        anos_cat = svc.available_years(1, FapContestationCat.vigencia_year,
                                       FapContestationCat.law_firm_id)
        check('CATs: só 2026 e 2023', anos_cat == ['2026', '2023'], anos_cat)
        check('ordenação é numérica, não alfabética',
              svc.available_years(1, FapContestationCat.vigencia_year,
                                  FapContestationCat.law_firm_id)[0] == '2026')

        # ── padrão e resolução ────────────────────────────────────────────
        print('\n3. ano padrão e resolução do select')
        check('padrão é o mais recente', svc.default_year(anos_ben) == '2026')
        check('sem anos, padrão é "Todas"', svc.default_year([]) == svc.TODAS)
        check('param ausente → aplica o padrão',
              svc.resolve_selected(None, anos_ben, ausente=True) == '2026')
        check('"Todas" escolhido pelo usuário é respeitado',
              svc.resolve_selected(svc.TODAS, anos_ben, ausente=False) == svc.TODAS)
        check('ano escolhido é respeitado',
              svc.resolve_selected('2023', anos_ben, ausente=False) == '2023')

        # ── filtro em coluna própria (CATs) ───────────────────────────────
        print('\n4. filtro por coluna vigencia_year (CATs)')
        base_cat = FapContestationCat.query.filter_by(law_firm_id=1)
        r = svc.apply_year_filter(base_cat, '2026', FapContestationCat.vigencia_year)
        check('2026 traz as 2 CATs do ano', r.count() == 2, r.count())
        check('inclui a CAT com vigencia_id nulo',
              3 in [c.id for c in r.all()], [c.id for c in r.all()])
        check('"Todas" não filtra',
              svc.apply_year_filter(base_cat, svc.TODAS,
                                    FapContestationCat.vigencia_year).count() == 3)

        # ── filtro de benefícios (via FK) ─────────────────────────────────
        print('\n5. filtro de benefícios (resolvido pela FK)')
        base_ben = Benefit.query.filter_by(law_firm_id=1)
        r = svc.apply_benefit_year_filter(base_ben, '2026', 1)
        check('2026 traz os 3 benefícios (2 vigências do mesmo ano)',
              r.count() == 3, sorted(b.id for b in r.all()))
        check('2023 traz 1', svc.apply_benefit_year_filter(base_ben, '2023', 1).count() == 1)
        check('"Todas" não filtra',
              svc.apply_benefit_year_filter(base_ben, svc.TODAS, 1).count() == 5)
        check('ano sem vigência filtra para vazio, não ignora o filtro',
              svc.apply_benefit_year_filter(base_ben, '1999', 1).count() == 0)

        # ── multi-tenancy ─────────────────────────────────────────────────
        print('\n6. multi-tenancy')
        check('escritório 2 só enxerga o próprio ano',
              svc.benefit_available_years(2) == ['2019'], svc.benefit_available_years(2))
        check('2026 do escritório 1 não alcança o escritório 2',
              svc.apply_benefit_year_filter(
                  Benefit.query.filter_by(law_firm_id=2), '2026', 2).count() == 0)
        check('escritório 2 não vê benefícios do 1 no próprio ano',
              svc.apply_benefit_year_filter(
                  Benefit.query.filter_by(law_firm_id=2), '2019', 2).count() == 1)

    # ── telas ─────────────────────────────────────────────────────────────
    print('\n7. telas respondem e abrem na vigência mais recente')
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao['user_id'] = 1
        sessao['law_firm_id'] = 1
        sessao['user_role'] = 'admin'

    telas = [
        ('/disputes-center/', 'Benefícios'),
        ('/disputes-center/vigencias', 'Vigências'),
        ('/disputes-center/cats', 'CATs'),
        ('/disputes-center/payroll-masses', 'Massas salariais'),
        ('/disputes-center/employment-links', 'Vínculos'),
        ('/disputes-center/turnover-rates', 'Rotatividade'),
        ('/process-panel/beneficios', 'Processos › Benefícios'),
    ]
    for caminho, nome in telas:
        resposta = cliente.get(caminho)
        html = resposta.get_data(as_text=True)
        check(f'{nome}: responde 200', resposta.status_code == 200, resposta.status_code)
        check(f'{nome}: tem a caixa de vigência',
              'quickVigenciaFilter' in html or 'vigenciaFilter' in html or 'vigencia_filter' in html)

    # o select abre na vigência mais recente
    html = cliente.get('/disputes-center/').get_data(as_text=True)
    import re
    bloco = re.search(r'<select id="quickVigenciaFilter".*?</select>', html, re.S)
    check('Benefícios abre com 2026 selecionado',
          bloco and 'value="2026" selected' in bloco.group(0),
          bloco.group(0)[:200] if bloco else '(select não encontrado)')

    # e respeita "Todas" quando escolhido
    html = cliente.get('/disputes-center/?quick_vigencia=__all__').get_data(as_text=True)
    bloco = re.search(r'<select id="quickVigenciaFilter".*?</select>', html, re.S)
    check('"Todas" escolhido não é sobrescrito pelo padrão',
          bloco and 'value="__all__" selected' in bloco.group(0),
          bloco.group(0)[:160] if bloco else '(não encontrado)')

    # a API de listagem respeita o recorte
    print('\n8. API de listagem')
    import json as _json
    resposta = cliente.get('/disputes-center/api/list?quick_vigencia=2023&draw=1&start=0&length=25')
    if resposta.status_code == 200:
        dados = _json.loads(resposta.get_data(as_text=True))
        check('API filtra por 2023', len(dados.get('data', [])) == 1,
              len(dados.get('data', [])))
        resposta = cliente.get('/disputes-center/api/list?quick_vigencia=__all__&draw=1&start=0&length=25')
        dados = _json.loads(resposta.get_data(as_text=True))
        check('API com "Todas" devolve tudo', len(dados.get('data', [])) == 5,
              len(dados.get('data', [])))
    else:
        check('API de listagem responde', False, resposta.status_code)

    print('\n' + '=' * 62)
    print('RESULTADO:', 'TUDO OK' if not FALHAS else f'{len(FALHAS)} FALHA(S): {FALHAS}')
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    return 1 if FALHAS else 0


if __name__ == '__main__':
    sys.exit(main())
