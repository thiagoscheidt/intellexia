"""
Corrida entre dois relatórios FAP com os mesmos benefícios.

Reproduz a duplicação de 27/08/2026: os relatórios 33389 e 33390 — o mesmo PDF
(a linha de 1ª e a de 2ª instância do portal apontam para o mesmo protocolo) —
foram processados a 2 s um do outro. Cada um procurou o NB antes de o outro
gravar, nenhum achou, e os dois inseriram.

Precisa de MySQL de verdade: a corrida depende do isolamento do InnoDB e o
SQLite serializa toda escrita, o que esconderia o defeito. Nunca aponte para o
banco da aplicação — o teste esvazia as tabelas que usa.

    docker run -d --rm --name dedup-test-mysql -e MYSQL_ROOT_PASSWORD=teste \\
        -e MYSQL_DATABASE=dedup -p 127.0.0.1:33999:3306 mysql:8.0
    DEDUP_TEST_MYSQL_URL='mysql+pymysql://root:teste@127.0.0.1:33999/dedup?charset=utf8mb4' \\
        uv run python tests/test_fap_report_corrida_beneficio.py
    docker stop dedup-test-mysql
"""

import os
import sys
import threading
import time
from types import SimpleNamespace

from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

URL = os.environ.get('DEDUP_TEST_MYSQL_URL')
if not URL:
    print('DEDUP_TEST_MYSQL_URL não definida — veja o docstring. Pulando.')
    sys.exit(0)

from main import app  # noqa: E402

app.config['SQLALCHEMY_DATABASE_URI'] = URL
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
TABELAS = ('benefit_contestation_decisions', 'benefit_fap_source_history', 'benefits',
           'fap_vigencia_cnpjs', 'fap_contestation_judgment_reports', 'users', 'law_firms')
NBS = ['7178102552', '7177147196', '7176785717', '7173005613']
CNPJ = '58.160.789/0001-28'


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra else ''}")
    if not condicao:
        FALHAS.append(rotulo)


class ServicoSemPdf(FapContestationJudgmentReportService):
    """O processamento real, com a leitura do PDF trocada por dados fixos."""

    def extract_metadata_from_first_page_with_pdfplumber(self, file_path):
        return SimpleNamespace(
            establishment_cnpj=CNPJ, validity_year='2026',
            transmission_datetime='27/08/2026 08:00:00', publication_date=None,
        )

    def extract_all_sections_with_pdfplumber(self, file_path):
        beneficios = [{'benefit_number': nb, 'benefit_type': 'B91'} for nb in NBS]
        vazio = []
        return ({'benefits': beneficios, 'cats': vazio, 'payroll_masses': vazio,
                 'employment_links': vazio, 'turnover_rates': vazio},
                {k: 0.0 for k in ('benefits', 'cats', 'payroll_masses',
                                  'employment_links', 'turnover_rates')})

    def _upsert_client_from_cnpj(self, law_firm_id, cnpj_raw):
        return None, None, CNPJ

    def _upsert_cats_from_report(self, report, extracted_cats, metadata):
        # Alarga a janela entre gravar os benefícios e o commit, que em
        # produção é o tempo das CATs, massas, vínculos e rotatividade.
        time.sleep(1.5)
        return 0


def rodar_corrida(com_trava: bool, read_committed: bool = True) -> list:
    from app.models import Benefit, FapContestationJudgmentReport, FapVigenciaCnpj, LawFirm, User

    with app.app_context():
        db.create_all()
        db.session.execute(text('SET FOREIGN_KEY_CHECKS = 0'))
        for tabela in TABELAS:
            db.session.execute(text(f'TRUNCATE TABLE {tabela}'))
        db.session.execute(text('SET FOREIGN_KEY_CHECKS = 1'))
        db.session.add(LawFirm(id=1, name='Escritório', cnpj='00000000000191'))
        db.session.add(User(id=1, law_firm_id=1, name='Teste', email='t@t.t', password_hash='x'))
        # A vigência já existe, como em produção (a empresa tinha relatório
        # anterior). Sem ela, o INSERT da própria vigência serializa os dois
        # relatórios e esconde a corrida.
        db.session.add(FapVigenciaCnpj(law_firm_id=1, employer_cnpj='58160789000128',
                                       vigencia_year='2026'))
        for rid in (1, 2):
            db.session.add(FapContestationJudgmentReport(
                id=rid, user_id=1, law_firm_id=1, original_filename='FAP_10128047929202586.pdf',
                file_path='/nao/existe.pdf', status='pending',
            ))
        db.session.commit()

    servico = ServicoSemPdf(app)
    if not com_trava:
        servico._travar_vigencia_do_relatorio = lambda registro: None
    if not read_committed:
        servico._iniciar_transacao_read_committed = lambda: None

    erros = []

    def processar(report_id, atraso):
        time.sleep(atraso)
        with app.app_context():
            ok, _, erro = servico.process_single_report(report_id)
            if not ok:
                erros.append(erro)

    threads = [threading.Thread(target=processar, args=(1, 0.0)),
               threading.Thread(target=processar, args=(2, 0.3))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with app.app_context():
        linhas = Benefit.query.filter_by(law_firm_id=1).all()
        return [b.benefit_number for b in linhas], erros


def main():
    with app.app_context():
        assert 'dedup' in str(db.engine.url), 'ABORTADO: não é o banco de teste'

    print('\n1. sem a trava (o comportamento de 27/08)')
    numeros, erros = rodar_corrida(com_trava=False)
    check('reproduz a duplicação', len(numeros) == 2 * len(NBS),
          f'{len(numeros)} linhas para {len(NBS)} NBs; erros={erros}')

    print('\n2. com a trava')
    numeros, erros = rodar_corrida(com_trava=True)
    check('os dois relatórios terminam sem erro', not erros, erros)
    check('uma linha por NB', sorted(numeros) == sorted(NBS),
          f'{len(numeros)} linhas para {len(NBS)} NBs')

    print('\n3. trava sem READ COMMITTED (por que as duas peças são necessárias)')
    numeros, erros = rodar_corrida(com_trava=True, read_committed=False)
    check('no REPEATABLE READ a trava serializa mas não deduplica',
          len(numeros) == 2 * len(NBS), f'{len(numeros)} linhas para {len(NBS)} NBs')

    print('\n' + '=' * 62)
    print('RESULTADO:', 'TUDO OK' if not FALHAS else f'{len(FALHAS)} FALHA(S): {FALHAS}')
    return 1 if FALHAS else 0


if __name__ == '__main__':
    sys.exit(main())
