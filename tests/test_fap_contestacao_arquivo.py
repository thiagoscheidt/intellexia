#!/usr/bin/env python3
"""
Visualizar/baixar o PDF da contestação quando o arquivo local não está no
disco — FAP-32 da Remessa R09.

Depois da cópia do banco da produção para a homologação, ``file_path`` aponta
para PDFs que só existem no disco da produção, e as duas rotas do arquivo
respondiam o 404 cru do Werkzeug. Agora caem no download ao vivo do portal —
a mesma rota que a tela usa para quem não tem arquivo local.

Cria um escritório/usuário descartável e remove no fim.

    uv run python tests/test_fap_contestacao_arquivo.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, LawFirm, User, UserPageVisit, FapWebContestacao

TEST_CNPJ = '00000000000299'
TEST_EMAIL = 'user__test_contestacao_arquivo@example.com'

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def setup():
    firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
    if firm:
        cleanup(firm)
    firm = LawFirm(name='Escritório Teste Arquivo Contestação', cnpj=TEST_CNPJ)
    db.session.add(firm)
    db.session.flush()
    user = User(law_firm_id=firm.id, name='teste', email=TEST_EMAIL, role='admin', is_active=True)
    user.set_password('x')
    db.session.add(user)
    db.session.commit()
    return firm, user


def cleanup(firm):
    users = User.query.filter_by(law_firm_id=firm.id).all()
    ids = [u.id for u in users]
    if ids:
        UserPageVisit.query.filter(UserPageVisit.user_id.in_(ids)).delete(synchronize_session=False)
    for u in users:
        db.session.delete(u)
    FapWebContestacao.query.filter_by(law_firm_id=firm.id).delete()
    db.session.delete(firm)
    db.session.commit()


def login(client, user):
    with client.session_transaction() as sess:
        sess['user_id'] = user.id
        sess['law_firm_id'] = user.law_firm_id
        sess['user_role'] = user.role
        sess['user_module_permissions'] = user.get_module_permissions()


def nova_contestacao(firm, contestacao_id, file_path):
    rec = FapWebContestacao(
        law_firm_id=firm.id, contestacao_id=contestacao_id,
        cnpj='1630766000232', cnpj_raiz='01630766', ano_vigencia=2026,
        protocolo='10128047537202517', file_path=file_path,
    )
    db.session.add(rec)
    db.session.commit()
    return rec


def run(firm, user, pdf_rel):
    client = app.test_client()
    login(client, user)

    print('\n1. file_path apontando para arquivo que não está no disco')
    sumido = nova_contestacao(firm, 990101, 'uploads/fap_web_contestacoes/nao/existe/990101_DEFERIDO.pdf')
    portal = f'/disputes-center/fap-auto-import/download-contestacao/2026/01630766000232/990101'

    r = client.get(f'/fap-panel/contestacoes/{sumido.id}/file?inline=1')
    check('visualizar não dá mais 404', r.status_code != 404, str(r.status_code))
    check('visualizar vai ao portal, inline',
          r.status_code == 302 and r.headers['Location'].endswith(portal + '?inline=1'),
          r.headers.get('Location', ''))

    r = client.get(f'/fap-panel/contestacoes/{sumido.id}/file')
    check('baixar vai ao portal, como anexo',
          r.status_code == 302 and r.headers['Location'].endswith(portal),
          r.headers.get('Location', ''))

    r = client.get(f'/fap-panel/contestacoes/{sumido.id}/view/FAP_10128047537202517.pdf')
    check('URL amigável também vai ao portal',
          r.status_code == 302 and r.headers['Location'].endswith(portal + '?inline=1'),
          r.headers.get('Location', ''))

    print('\n2. Arquivo local presente continua servido do disco')
    local = nova_contestacao(firm, 990102, pdf_rel)
    r = client.get(f'/fap-panel/contestacoes/{local.id}/file')
    check('baixar devolve o PDF local', r.status_code == 200 and r.data.startswith(b'%PDF'),
          str(r.status_code))
    r = client.get(f'/fap-panel/contestacoes/{local.id}/file?inline=1')
    check('visualizar redireciona para a URL amigável',
          r.status_code == 302 and '/view/FAP_10128047537202517.pdf' in r.headers['Location'],
          r.headers.get('Location', ''))

    print('\n3. Tenant')
    outra = LawFirm(name='Outro Escritório Teste Arquivo', cnpj='00000000000399')
    db.session.add(outra)
    db.session.commit()
    try:
        alheia = nova_contestacao(outra, 990103, pdf_rel)
        r = client.get(f'/fap-panel/contestacoes/{alheia.id}/file')
        check('contestação de outro escritório continua 404', r.status_code == 404, str(r.status_code))
    finally:
        cleanup(outra)


def main() -> int:
    with app.app_context():
        firm, user = setup()
        pasta = Path(app.root_path) / 'uploads' / 'fap_web_contestacoes' / '__teste_fap32__'
        pasta.mkdir(parents=True, exist_ok=True)
        fd, caminho = tempfile.mkstemp(suffix='.pdf', prefix='990102_', dir=pasta)
        os.write(fd, b'%PDF-1.4\n%teste\n')
        os.close(fd)
        try:
            run(firm, user, os.path.relpath(caminho, app.root_path))
        finally:
            db.session.rollback()
            cleanup(firm)
            os.remove(caminho)
            pasta.rmdir()

    print('\n' + '=' * 62)
    if _falhas:
        print(f'❌ {len(_falhas)} verificação(ões) falharam:')
        for nome in _falhas:
            print(f'   - {nome}')
        return 1
    print('✅ Tudo verde')
    return 0


if __name__ == '__main__':
    sys.exit(main())
