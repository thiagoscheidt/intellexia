#!/usr/bin/env python3
"""
Testes do client do INLABS (app/services/inlabs_client.py).

Não toca a rede: a sessão HTTP é substituída por um duplo que devolve
respostas programadas. Cobre montagem de URL, headers obrigatórios,
404 como estado normal e degradação sem credenciais.

    uv run python tests/test_inlabs_client.py
"""

import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import inlabs_client as ic

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


class FakeResponse:
    def __init__(self, status_code=200, content=b'', cookies=None):
        self.status_code = status_code
        self.content = content
        self.cookies = cookies or {}


class FakeSession:
    """Duplo da requests.Session: registra chamadas e devolve respostas fixas."""

    def __init__(self, respostas=None, cookie='COOKIE-FAKE'):
        self.chamadas = []
        self.respostas = respostas or {}
        self.cookies = {}
        self._cookie = cookie

    def request(self, method, url, **kwargs):
        self.chamadas.append({'method': method, 'url': url, **kwargs})
        if 'logar.php' in url:
            if self._cookie is not None:
                self.cookies['inlabs_session_cookie'] = self._cookie
            return FakeResponse(200)
        return self.respostas.get(url, FakeResponse(404))


def test_nomes_de_arquivo():
    print('\n1. Montagem dos nomes de arquivo')
    d = date(2026, 8, 10)
    check('XML usa hífen e seção maiúscula',
          ic.xml_filename(d, 'DO1') == '2026-08-10-DO1.zip', ic.xml_filename(d, 'DO1'))
    check('XML de edição extra',
          ic.xml_filename(d, 'DO1E') == '2026-08-10-DO1E.zip', ic.xml_filename(d, 'DO1E'))
    check('PDF usa underscore e seção minúscula',
          ic.pdf_filename(d, 'do1') == '2026_08_10_ASSINADO_do1.pdf', ic.pdf_filename(d, 'do1'))
    check('PDF normaliza seção passada em maiúscula',
          ic.pdf_filename(d, 'DO2') == '2026_08_10_ASSINADO_do2.pdf', ic.pdf_filename(d, 'DO2'))


def test_sem_credenciais():
    print('\n2. Degradação sem credenciais')
    antigo_email = os.environ.pop('INLABS_EMAIL', None)
    antiga_senha = os.environ.pop('INLABS_PASSWORD', None)
    try:
        check('is_configured() é False sem .env', ic.is_configured() is False)
        try:
            ic.InlabsClient().login()
            check('login sem credenciais levanta InlabsNotConfigured', False, 'não levantou')
        except ic.InlabsNotConfigured:
            check('login sem credenciais levanta InlabsNotConfigured', True)
    finally:
        if antigo_email:
            os.environ['INLABS_EMAIL'] = antigo_email
        if antiga_senha:
            os.environ['INLABS_PASSWORD'] = antiga_senha


def test_login_e_headers():
    print('\n3. Login e headers obrigatórios do download')
    d = date(2026, 8, 10)
    url = f'{ic.URL_DOWNLOAD}2026-08-10&dl=2026-08-10-DO1.zip'
    fake = FakeSession(respostas={url: FakeResponse(200, b'PK\x03\x04conteudo')})

    client = ic.InlabsClient(email='a@b.com', password='x')
    client._session = fake
    conteudo = client.download_xml_zip(d, 'DO1')

    check('devolve os bytes do ZIP', conteudo == b'PK\x03\x04conteudo', repr(conteudo))
    check('fez login antes de baixar', any('logar.php' in c['url'] for c in fake.chamadas))

    login = next(c for c in fake.chamadas if 'logar.php' in c['url'])
    check('login é POST', login['method'] == 'POST', login['method'])
    check('login manda email e password',
          login['data'] == {'email': 'a@b.com', 'password': 'x'}, repr(login.get('data')))

    download = next(c for c in fake.chamadas if 'dl=' in c['url'])
    headers = download['headers']
    check('manda o cookie da sessão',
          headers['Cookie'] == 'inlabs_session_cookie=COOKIE-FAKE', repr(headers.get('Cookie')))
    check("manda o header origem='736372697074'",
          headers['origem'] == '736372697074', repr(headers.get('origem')))
    check('download tem timeout', download.get('timeout') is not None)


def test_404_nao_e_erro():
    print('\n4. HTTP 404 é estado normal, não exceção')
    fake = FakeSession()  # tudo que não for login devolve 404
    client = ic.InlabsClient(email='a@b.com', password='x')
    client._session = fake

    resultado = client.download_xml_zip(date(2026, 8, 10), 'DO1E')
    check('404 devolve None em vez de levantar', resultado is None, repr(resultado))


def test_login_sem_cookie():
    print('\n5. Credencial inválida (login não devolve cookie)')
    fake = FakeSession(cookie=None)
    client = ic.InlabsClient(email='a@b.com', password='errada')
    client._session = fake
    try:
        client.login()
        check('login sem cookie levanta InlabsAuthError', False, 'não levantou')
    except ic.InlabsAuthError:
        check('login sem cookie levanta InlabsAuthError', True)


def main():
    print('=' * 60)
    print('TESTES DO CLIENT DO INLABS')
    print('=' * 60)

    test_nomes_de_arquivo()
    test_sem_credenciais()
    test_login_e_headers()
    test_404_nao_e_erro()
    test_login_sem_cookie()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
