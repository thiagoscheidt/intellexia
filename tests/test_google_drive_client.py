"""
Client do Google Drive pela conta de serviço, contra uma sessão HTTP falsa.

Cobre o token (JWT assinado, reuso e renovação no 401), a paginação da
listagem, a tradução dos erros do Drive (404 = não compartilhado, API
desativada, limite, 5xx) e o download — que só grava o arquivo depois de
conferir que veio o arquivo inteiro, e nunca a página HTML de erro.

    uv run python tests/test_google_drive_client.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services import google_drive_client as gdrive

_PEM = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
INFO = {'client_email': 'teste@projeto.iam.gserviceaccount.com', 'private_key': _PEM,
        'private_key_id': 'abc123', 'token_uri': 'https://oauth2.googleapis.com/token'}


class Resp:
    def __init__(self, status=200, corpo=None, conteudo=b'', tipo='application/json'):
        self.status_code = status
        self._corpo = corpo
        self._conteudo = conteudo
        self.headers = {'Content-Type': tipo}
        self.fechada = False

    def json(self):
        if self._corpo is None:
            raise ValueError('sem json')
        return self._corpo

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._conteudo), chunk_size):
            yield self._conteudo[i:i + chunk_size]

    def close(self):
        self.fechada = True


class Http:
    """Responde por fila: cada GET consome a próxima resposta."""

    def __init__(self, respostas, token_status=200):
        self.respostas = list(respostas)
        self.tokens_pedidos = 0
        self.gets = []
        self.token_status = token_status

    def post(self, url, data=None, timeout=None):
        self.tokens_pedidos += 1
        assert data['grant_type'] == 'urn:ietf:params:oauth:grant-type:jwt-bearer'
        assert data['assertion'].count('.') == 2  # JWT assinado
        if self.token_status != 200:
            return Resp(self.token_status, {'error': 'invalid_grant'})
        return Resp(200, {'access_token': f'tok{self.tokens_pedidos}', 'expires_in': 3600})

    def get(self, url, params=None, headers=None, stream=False, timeout=None):
        self.gets.append((url, dict(params or {}), headers['Authorization']))
        return self.respostas.pop(0)


def _erro(status, motivo):
    return Resp(status, {'error': {'code': status, 'errors': [{'reason': motivo}], 'message': motivo}})


def test_configuracao_pelo_env():
    antigo = dict(os.environ)
    try:
        os.environ.pop('GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE', None)
        assert not gdrive.configurado()
        os.environ['GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE'] = 'instance/nao-existe.json'
        assert not gdrive.configurado()
        assert gdrive.caminho_da_chave().startswith(str(Path(__file__).resolve().parent.parent))
        os.environ['GOOGLE_DRIVE_LAW_FIRM_ID'] = '7'
        assert gdrive.law_firm_id_configurado() == 7
        os.environ['GOOGLE_DRIVE_LAW_FIRM_ID'] = 'abc'
        assert gdrive.law_firm_id_configurado() is None
        try:
            gdrive.cliente()
            raise AssertionError('esperava DriveNaoConfigurado')
        except gdrive.DriveNaoConfigurado:
            pass
    finally:
        os.environ.clear()
        os.environ.update(antigo)


def test_chave_incompleta():
    try:
        gdrive.DriveClient({'client_email': 'x'}, http=Http([]))
        raise AssertionError('esperava DriveNaoConfigurado')
    except gdrive.DriveNaoConfigurado as e:
        assert 'private_key' in str(e)


def test_listagem_pagina_e_reusa_token():
    http = Http([
        Resp(200, {'files': [{'id': 'a', 'name': 'A.pdf'}], 'nextPageToken': 'p2'}),
        Resp(200, {'files': [{'id': 'b', 'name': 'B'}]}),
    ])
    c = gdrive.DriveClient(INFO, http=http)
    itens = c.listar()
    assert [i['id'] for i in itens] == ['a', 'b']
    assert http.tokens_pedidos == 1                       # um token para as duas páginas
    assert http.gets[1][1]['pageToken'] == 'p2'
    assert http.gets[0][1]['supportsAllDrives'] == 'true'
    assert http.gets[0][2] == 'Bearer tok1'


def test_401_renova_o_token_uma_vez():
    http = Http([Resp(401, {'error': {'code': 401}}), Resp(200, {'id': 'a'})])
    c = gdrive.DriveClient(INFO, http=http)
    assert c.metadados('a') == {'id': 'a'}
    assert http.tokens_pedidos == 2
    assert http.gets[1][2] == 'Bearer tok2'


def test_traducao_dos_erros():
    casos = [
        (Resp(404, {'error': {'code': 404}}), gdrive.DriveSemAcesso, 'não está compartilhado'),
        (_erro(403, 'accessNotConfigured'), gdrive.DriveIndisponivel, 'desativada'),
        (_erro(403, 'userRateLimitExceeded'), gdrive.DriveIndisponivel, 'Limite'),
        (_erro(403, 'insufficientFilePermissions'), gdrive.DriveSemAcesso, 'permissão'),
        (Resp(429, {}), gdrive.DriveIndisponivel, 'Limite'),
        (Resp(503, None), gdrive.DriveIndisponivel, 'indisponível'),
    ]
    for resposta, classe, trecho in casos:
        c = gdrive.DriveClient(INFO, http=Http([resposta]))
        try:
            c.metadados('x')
            raise AssertionError(f'esperava {classe.__name__}')
        except classe as e:
            assert trecho in str(e), (trecho, str(e))


def test_chave_recusada():
    c = gdrive.DriveClient(INFO, http=Http([], token_status=400))
    try:
        c.listar()
        raise AssertionError('esperava DriveIndisponivel')
    except gdrive.DriveIndisponivel as e:
        assert 'invalid_grant' in str(e) and 'revogada' in str(e)


def test_download_grava_inteiro():
    pdf = b'%PDF-1.7\n' + b'x' * 200000
    meta = {'id': 'arq123456789', 'name': 'Impugnação Madife.pdf', 'mimeType': gdrive.MIME_PDF, 'size': str(len(pdf))}
    with tempfile.TemporaryDirectory() as d:
        http = Http([Resp(200, conteudo=pdf, tipo='application/pdf')])
        caminho, nome, sha = gdrive.DriveClient(INFO, http=http).baixar('arq123456789', d, meta=meta)
        assert nome == 'Impugnação Madife.pdf'
        assert open(caminho, 'rb').read() == pdf
        assert len(sha) == 64
        assert os.listdir(d) == [os.path.basename(caminho)]   # sem .part sobrando
        assert http.gets[0][1]['alt'] == 'media'


def test_download_recusa_html_e_incompleto():
    with tempfile.TemporaryDirectory() as d:
        meta = {'id': 'arq123456789', 'name': 'x.pdf', 'mimeType': gdrive.MIME_PDF, 'size': '9999'}
        for resposta, trecho in (
            (Resp(200, conteudo=b'<!DOCTYPE html><html>login</html>', tipo='text/html'), 'página'),
            (Resp(200, conteudo=b'%PDF-1.7 curto', tipo='application/pdf'), 'incompleto'),
        ):
            try:
                gdrive.DriveClient(INFO, http=Http([resposta])).baixar('arq123456789', d, meta=meta)
                raise AssertionError('esperava DriveIndisponivel')
            except gdrive.DriveIndisponivel as e:
                assert trecho in str(e), str(e)
        assert os.listdir(d) == []                           # nada gravado


def test_google_docs_exporta_pdf():
    meta = {'id': 'doc123456789', 'name': 'Minuta', 'mimeType': 'application/vnd.google-apps.document'}
    with tempfile.TemporaryDirectory() as d:
        http = Http([Resp(200, conteudo=b'%PDF-1.4 exportado', tipo='application/pdf')])
        caminho, nome, _ = gdrive.DriveClient(INFO, http=http).baixar('doc123456789', d, meta=meta)
        assert nome == 'Minuta.pdf' and caminho.endswith('.pdf')
        assert http.gets[0][0].endswith('/files/doc123456789/export')
        assert http.gets[0][1]['mimeType'] == gdrive.MIME_PDF


def test_pasta_nao_baixa():
    try:
        gdrive.DriveClient(INFO, http=Http([])).baixar('p', '/tmp', meta={'mimeType': gdrive.MIME_PASTA})
        raise AssertionError('esperava DriveSemAcesso')
    except gdrive.DriveSemAcesso:
        pass


def test_tipos():
    assert gdrive.tipo_do_arquivo(gdrive.MIME_PDF) == 'pdf'
    assert gdrive.tipo_do_arquivo(gdrive.MIME_DOCX) == 'docx'
    assert gdrive.tipo_do_arquivo('application/vnd.google-apps.document') == 'gdoc'
    assert gdrive.tipo_do_arquivo('image/png') is None
    assert gdrive.tipo_do_arquivo(gdrive.MIME_PASTA) is None


def test_cliente_reaproveitado_e_recriado_quando_a_chave_muda():
    antigo = dict(os.environ)
    with tempfile.TemporaryDirectory() as d:
        chave = os.path.join(d, 'chave.json')
        with open(chave, 'w') as fh:
            json.dump(INFO, fh)
        try:
            os.environ['GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE'] = chave
            primeiro = gdrive.cliente()
            assert gdrive.cliente() is primeiro
            os.utime(chave, (1, 1))
            assert gdrive.cliente() is not primeiro
        finally:
            os.environ.clear()
            os.environ.update(antigo)


def test_importadores_tentam_a_conta_primeiro():
    """`download_drive_file` (peças em lote e "Buscar PDFs no Drive") usa a conta e cai no anônimo."""
    from app.services import impugnacao_import_service as imp

    originais = (gdrive.configurado, gdrive.cliente, gdrive.law_firm_id_configurado, imp._download_anonymous)
    chamadas = []

    class Conta:
        def __init__(self, erro=None):
            self.erro = erro

        def baixar(self, file_id, dest_dir):
            chamadas.append('conta')
            if self.erro:
                raise self.erro
            return ('/conta.pdf', 'conta.pdf', 'h')

    def anonimo(file_id, dest_dir, timeout):
        chamadas.append('anonimo')
        raise imp.DriveAccessError(imp._RESTRICTED_MESSAGE)

    try:
        with tempfile.TemporaryDirectory() as d:
            imp._download_anonymous = anonimo
            gdrive.configurado = lambda: True
            gdrive.law_firm_id_configurado = lambda: 1
            gdrive.cliente = lambda: Conta()
            assert imp.download_drive_file('x', d, law_firm_id=1) == ('/conta.pdf', 'conta.pdf', 'h')
            assert chamadas == ['conta']

            chamadas.clear()
            gdrive.cliente = lambda: Conta(gdrive.DriveSemAcesso('não compartilhado'))
            try:
                imp.download_drive_file('x', d, law_firm_id=1)
                raise AssertionError('esperava DriveAccessError')
            except imp.DriveAccessError as e:
                assert chamadas == ['conta', 'anonimo']
                assert 'conta de serviço' in str(e) and 'compartilhamento' in str(e)  # a Jurisprudência para por esta palavra

            # outro escritório nunca usa a conta, mesmo configurada
            chamadas.clear()
            gdrive.cliente = lambda: Conta()
            try:
                imp.download_drive_file('x', d, law_firm_id=2)
                raise AssertionError('esperava DriveAccessError')
            except imp.DriveAccessError as e:
                assert chamadas == ['anonimo'] and str(e) == imp._RESTRICTED_MESSAGE

            chamadas.clear()
            gdrive.configurado = lambda: False
            try:
                imp.download_drive_file('x', d, law_firm_id=1)
            except imp.DriveAccessError as e:
                assert chamadas == ['anonimo'] and str(e) == imp._RESTRICTED_MESSAGE
    finally:
        gdrive.configurado, gdrive.cliente, gdrive.law_firm_id_configurado, imp._download_anonymous = originais


if __name__ == '__main__':
    falhas = 0
    for nome, fn in list(globals().items()):
        if nome.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'✓ {nome}')
            except Exception as e:
                falhas += 1
                print(f'✗ {nome}: {type(e).__name__}: {e}')
    print('\nOK' if not falhas else f'\n{falhas} falha(s)')
    sys.exit(1 if falhas else 0)
