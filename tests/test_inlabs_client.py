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
    def __init__(self, status_code=200, content=b'', cookies=None, headers=None):
        self.status_code = status_code
        self.content = content
        self.cookies = cookies or {}
        self.headers = headers or {'Content-Type': 'application/octet-stream'}


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


def test_data_inexistente_devolve_html():
    """O INLABS tem DUAS formas de dizer "não publicado".

    Quando a data existe mas a seção não (ex.: uma edição extra que não saiu),
    responde 404. Mas quando a **data inteira** não existe — fim de semana,
    feriado — responde **200 com a página HTML do portal**, ~37 KB. Tratar só o
    404 fazia o HTML chegar ao zipfile e estourar BadZipFile, marcando todo fim
    de semana como falha de captura.
    """
    print('\n6. Data inexistente: 200 com HTML também é "não publicado"')
    d = date(2026, 8, 8)  # sábado
    url = f'{ic.URL_DOWNLOAD}2026-08-08&dl=2026-08-08-DO1.zip'
    pagina = b'<!DOCTYPE html>\r\n<html>\r\n<head>\r\n<title>Imprensa Nacional - INLABS</title>'
    fake = FakeSession(respostas={
        url: FakeResponse(200, pagina, headers={'Content-Type': 'text/html; charset=utf-8'})
    })

    client = ic.InlabsClient(email='a@b.com', password='x')
    client._session = fake

    check('HTML com 200 devolve None, como o 404',
          client.download_xml_zip(d, 'DO1') is None,
          'devolveu a página HTML como se fosse o arquivo')

    # E o caminho normal não pode ter sido quebrado pela correção
    url_ok = f'{ic.URL_DOWNLOAD}2026-08-10&dl=2026-08-10-DO1.zip'
    fake_ok = FakeSession(respostas={url_ok: FakeResponse(200, b'PK\x03\x04dados')})
    client_ok = ic.InlabsClient(email='a@b.com', password='x')
    client_ok._session = fake_ok
    check('arquivo de verdade continua passando',
          client_ok.download_xml_zip(date(2026, 8, 10), 'DO1') == b'PK\x03\x04dados')


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


def test_portal_em_manutencao():
    """502 do portal não pode virar "verifique as credenciais".

    O INLABS responde 502 com uma página "Sistema em Manutenção". Como o login
    só checava a presença do cookie, uma indisponibilidade do portal era
    relatada como credencial errada — mandando quem lê o log do cron caçar
    problema no lugar errado.
    """
    print('\n7. Portal fora do ar é distinguido de credencial errada')

    class SessaoEmManutencao(FakeSession):
        def request(self, method, url, **kwargs):
            self.chamadas.append({'method': method, 'url': url, **kwargs})
            return FakeResponse(502, b'<html><title>Sistema em Manuten&ccedil;&atilde;o</title>',
                                headers={'Content-Type': 'text/html'})

    client = ic.InlabsClient(email='a@b.com', password='x')
    client._session = SessaoEmManutencao()
    try:
        client.login()
        check('502 levanta InlabsUnavailable', False, 'não levantou')
    except ic.InlabsUnavailable as exc:
        check('502 levanta InlabsUnavailable', True)
        check('a mensagem fala em indisponibilidade, não em credencial',
              'indisponível' in str(exc) and 'credenciais' not in str(exc), str(exc))
    except ic.InlabsAuthError as exc:
        check('502 levanta InlabsUnavailable', False,
              f'culpou a credencial: {exc}')


def main():
    print('=' * 60)
    print('TESTES DO CLIENT DO INLABS')
    print('=' * 60)

    test_nomes_de_arquivo()
    test_sem_credenciais()
    test_login_e_headers()
    test_404_nao_e_erro()
    test_data_inexistente_devolve_html()
    test_login_sem_cookie()
    test_portal_em_manutencao()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
