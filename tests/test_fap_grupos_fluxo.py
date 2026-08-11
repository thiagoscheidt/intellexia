"""
Fluxo completo dos grupos empresariais: planilha → conferência → gravação → filtro.

Exercita as rotas de verdade pelo test_client, com um .xlsx gerado na hora no
formato da planilha do escritório. Roda contra SQLite descartável.

Executar:
    uv run python tests/test_fap_grupos_fluxo.py
"""

import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import app

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_tmp_fap_grupos_fluxo.db')
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_FILE}'
app.config['WTF_CSRF_ENABLED'] = False

from app.models import db  # noqa: E402

app.extensions.pop('sqlalchemy', None)
try:
    db._app_engines.pop(app, None)
except Exception:
    pass
db.init_app(app)

FALHAS = []


def check(rotulo, condicao, extra=''):
    print(f"  [{'OK ' if condicao else 'FALHA'}] {rotulo}{(' — ' + str(extra)) if extra else ''}")
    if not condicao:
        FALHAS.append(rotulo)


def planilha_xlsx(linhas):
    """Gera um .xlsx em memória no formato da planilha do escritório."""
    from openpyxl import Workbook
    wb = Workbook()
    aba = wb.active
    aba.append(['CNPJ Raiz Outorgante', 'Grupo', 'Razão Social'])
    for linha in linhas:
        aba.append(list(linha))
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


LINHAS = [
    ('60.659.463/', 'ACHE', 'ACHE LABORATORIOS FARMACEUTICOS SA'),
    ('00.383.649/', 'ADSERVI', '5 ESTRELAS SPECIAL SERVICE LIMP E SERV AUXILIARES LTDA'),
    ('11.312.620/', 'ADSERVI', '5 ESTRELAS SPECIAL SERVICE NORTE NORDESTE LTDA.'),
    ('11.312.655/', 'ADSERVI', '5 ESTRELAS SPECIAL SERVICE SUL SUDESTE LTDA.'),
    ('99.999.999/', 'FANTASMA', 'EMPRESA COM PROCURACAO VENCIDA LTDA'),  # sem FapCompany
    ('abc', 'X', 'CNPJ invalido'),                                        # erro
]


def main():
    from datetime import datetime

    with app.app_context():
        from app.models import (
            LawFirm, User, FapCompany, FapCompanyGroup, FapWebContestacao,
        )
        assert DB_FILE in str(db.engine.url), 'ABORTADO: fora do sandbox'

        # Todas as tabelas: o layout base tem context processors que consultam
        # comunicações, prazos e revisões — sem elas toda página dá 500.
        db.create_all()
        db.session.add(LawFirm(id=1, name='Escritório', cnpj='00000000000191'))
        db.session.add(User(
            id=1, law_firm_id=1, name='Admin', email='a@b.c',
            password_hash='x', role='admin',
        ))
        agora = datetime(2026, 8, 1)
        # Empresas sincronizadas (cnpj = raiz de 8 dígitos)
        for i, (raiz, nome) in enumerate([
            ('60659463', 'ACHE LABORATORIOS'),
            ('00383649', '5 ESTRELAS LIMP'),
            ('11312620', '5 ESTRELAS NORTE'),
            ('11312655', '5 ESTRELAS SUL'),
            ('77777777', 'EMPRESA SEM GRUPO'),
        ], start=1):
            db.session.add(FapCompany(
                id=i, law_firm_id=1, cnpj=raiz, nome=nome, synced_at=agora,
            ))
        # Contestações: 3 de ADSERVI, 1 de ACHE, 1 sem grupo
        for i, raiz in enumerate(
            ['00383649', '11312620', '11312655', '60659463', '77777777'], start=1
        ):
            db.session.add(FapWebContestacao(
                id=i, law_firm_id=1, contestacao_id=500 + i,
                cnpj=raiz + '000100', cnpj_raiz=raiz, ano_vigencia=2024,
            ))
        db.session.commit()

    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao['user_id'] = 1
        sessao['law_firm_id'] = 1
        sessao['user_role'] = 'admin'

    # ── 1. upload e conferência (não pode gravar nada) ───────────────────
    print('\n1. upload → conferência')
    resposta = cliente.post(
        '/fap-panel/empresas/grupos/importar',
        data={'planilha': (planilha_xlsx(LINHAS), 'grupos.xlsx')},
        content_type='multipart/form-data', follow_redirects=True,
    )
    html = resposta.get_data(as_text=True)
    check('tela de conferência abre', resposta.status_code == 200, resposta.status_code)
    check('mostra as 5 empresas novas', '5' in html and 'ganharão grupo' in html)
    check('reporta a linha inválida', 'Linhas que serão ignoradas' in html)
    check('avisa sobre CNPJ sem empresa sincronizada',
          'Sem empresa sincronizada' in html and '99999999' in html)

    with app.app_context():
        from app.models import FapCompanyGroup
        check('conferência NÃO gravou nada',
              FapCompanyGroup.query.count() == 0, FapCompanyGroup.query.count())

    # ── 2. confirmar ─────────────────────────────────────────────────────
    print('\n2. confirmar importação')
    resposta = cliente.post('/fap-panel/empresas/grupos/importar/confirmar',
                            follow_redirects=True)
    check('confirmação redireciona para a lista', resposta.status_code == 200)

    with app.app_context():
        from app.models import FapCompanyGroup
        from app.services import fap_group_service as svc
        total = FapCompanyGroup.query.count()
        check('gravou as 5 linhas válidas', total == 5, total)
        check('ADSERVI ficou com 3 raízes',
              len(svc.roots_for_group(1, 'ADSERVI')) == 3, svc.roots_for_group(1, 'ADSERVI'))
        check('a linha inválida não virou registro',
              FapCompanyGroup.query.filter_by(cnpj_raiz='abc').count() == 0)

    # ── 3. reimportar a mesma planilha é idempotente ─────────────────────
    print('\n3. reimportar a mesma planilha')
    cliente.post('/fap-panel/empresas/grupos/importar',
                 data={'planilha': (planilha_xlsx(LINHAS), 'grupos.xlsx')},
                 content_type='multipart/form-data', follow_redirects=True)
    resposta = cliente.post('/fap-panel/empresas/grupos/importar/confirmar',
                            follow_redirects=True)
    html = resposta.get_data(as_text=True)
    check('nada é alterado na reimportação', 'sem mudança' in html, )
    with app.app_context():
        from app.models import FapCompanyGroup
        check('total continua 5', FapCompanyGroup.query.count() == 5,
              FapCompanyGroup.query.count())

    # ── 4. cadastro manual pelo botão ────────────────────────────────────
    print('\n4. botão de cadastro manual')
    resposta = cliente.post('/fap-panel/empresas/grupo',
                            data={'cnpj_raiz': '77777777', 'grupo': 'AVULSA'})
    check('salva o grupo manual', resposta.get_json().get('ok') is True, resposta.get_json())
    with app.app_context():
        from app.services import fap_group_service as svc
        check('grupo manual resolve a raiz',
              svc.roots_for_group(1, 'AVULSA') == ['77777777'], svc.roots_for_group(1, 'AVULSA'))

    resposta = cliente.post('/fap-panel/empresas/grupo',
                            data={'cnpj_raiz': '77777777', 'grupo': '  '})
    check('grupo vazio desvincula', resposta.get_json().get('acao') == 'removido',
          resposta.get_json())

    resposta = cliente.post('/fap-panel/empresas/grupo',
                            data={'cnpj_raiz': 'xx', 'grupo': 'Y'})
    check('CNPJ inválido devolve 400 com mensagem',
          resposta.status_code == 400 and 'erro' in resposta.get_json(),
          (resposta.status_code, resposta.get_json()))

    # ── 5. planilha vence manual, mas o de-para aparece antes ────────────
    print('\n5. conflito planilha × manual')
    cliente.post('/fap-panel/empresas/grupo',
                 data={'cnpj_raiz': '11312620', 'grupo': 'MEU GRUPO MANUAL'})
    resposta = cliente.post(
        '/fap-panel/empresas/grupos/importar',
        data={'planilha': (planilha_xlsx(LINHAS), 'grupos.xlsx')},
        content_type='multipart/form-data', follow_redirects=True,
    )
    html = resposta.get_data(as_text=True)
    check('conferência avisa que vai alterar', 'Grupos que serão alterados' in html)
    check('mostra o valor atual no de-para', 'MEU GRUPO MANUAL' in html)
    check('marca que veio de cadastro manual', 'cadastro manual' in html)

    # ── 6. filtro na tela de contestações ────────────────────────────────
    print('\n6. filtro por grupo nas telas')
    cliente.post('/fap-panel/empresas/grupos/importar/confirmar', follow_redirects=True)

    resposta = cliente.get('/fap-panel/contestacoes?grupo=ADSERVI&ano_vigencia=__all__')
    html = resposta.get_data(as_text=True)
    check('tela de contestações responde', resposta.status_code == 200, resposta.status_code)
    check('o select de grupo é renderizado', 'name="grupo"' in html)

    with app.app_context():
        from app.models import FapWebContestacao
        from app.services import fap_group_service as svc
        base = FapWebContestacao.query.filter_by(law_firm_id=1)
        adservi = svc.apply_group_filter(base, 1, 'ADSERVI',
                                         FapWebContestacao.cnpj_raiz, coluna_e_raiz=True)
        check('ADSERVI traz 3 contestações', adservi.count() == 3, adservi.count())
        sem = svc.apply_group_filter(base, 1, svc.SEM_GRUPO,
                                     FapWebContestacao.cnpj_raiz, coluna_e_raiz=True)
        check('sem grupo traz só a empresa não mapeada',
              [c.cnpj_raiz for c in sem.all()] == ['77777777'],
              [c.cnpj_raiz for c in sem.all()])

    # ── 7. tela de empresas mostra e filtra por grupo ────────────────────
    print('\n7. tela de empresas')
    resposta = cliente.get('/fap-panel/empresas')
    html = resposta.get_data(as_text=True)
    check('coluna Grupo aparece', 'Grupo Empresarial' in html)
    check('mostra o nome do grupo na linha', 'ADSERVI' in html)
    check('botão de importar aparece', 'Importar grupos' in html)

    resposta = cliente.get('/fap-panel/empresas?grupo=ADSERVI')
    html = resposta.get_data(as_text=True)
    check('filtro por grupo recorta a lista',
          '3 registro(s)' in html, [l for l in html.split('\n') if 'registro(s)' in l][:1])

    # ── 8. planilha fora do formato ──────────────────────────────────────
    print('\n8. planilha inválida')
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(['Coluna A', 'Coluna B'])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    resposta = cliente.post(
        '/fap-panel/empresas/grupos/importar',
        data={'planilha': (buffer, 'errada.xlsx')},
        content_type='multipart/form-data', follow_redirects=True,
    )
    html = resposta.get_data(as_text=True)
    check('mensagem amigável, sem stacktrace',
          'colunas esperadas' in html and 'Traceback' not in html)

    resposta = cliente.post(
        '/fap-panel/empresas/grupos/importar',
        data={'planilha': (io.BytesIO(b'nao sou xlsx'), 'arquivo.txt')},
        content_type='multipart/form-data', follow_redirects=True,
    )
    check('recusa arquivo que não é .xlsx',
          'formato .xlsx' in resposta.get_data(as_text=True))

    # ── 9. telas do Disputes Center (tiveram a semântica trocada) ────────
    print('\n9. Disputes Center com o filtro novo')
    telas = [
        ('/disputes-center/', 'quick_grupo'),
        ('/disputes-center/vigencias', 'grupo'),
        ('/disputes-center/cats', 'quick_grupo'),
        ('/disputes-center/payroll-masses', 'quick_grupo'),
        ('/disputes-center/employment-links', 'quick_grupo'),
        ('/disputes-center/turnover-rates', 'quick_grupo'),
    ]
    for caminho, parametro in telas:
        resposta = cliente.get(f'{caminho}?{parametro}=ADSERVI')
        nome = caminho.rstrip('/').rsplit('/', 1)[-1] or 'list'
        check(f'{nome} responde com grupo selecionado',
              resposta.status_code == 200, resposta.status_code)

    # As opções precisam ser grupos, não mais empresas uma a uma.
    resposta = cliente.get('/disputes-center/vigencias')
    html = resposta.get_data(as_text=True)
    check('opções do select são grupos', 'ADSERVI' in html and 'ACHE' in html)
    check('opção "sem grupo" está presente', 'Sem grupo' in html)

    print('\n' + '=' * 62)
    print('RESULTADO:', 'TUDO OK' if not FALHAS else f'{len(FALHAS)} FALHA(S): {FALHAS}')
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    return 1 if FALHAS else 0


if __name__ == '__main__':
    sys.exit(main())
