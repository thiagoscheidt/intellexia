#!/usr/bin/env python3
"""
DataJud lento ou fora do ar — RPI-34 da Remessa R09.

A busca do processo 5107621-25.2025.4.02.5101 no TRF2 mostrava
"Erro na busca: HTTPSConnectionPool(host='api-publica.datajud.cnj.jus.br',
port=443): Read timed out. (read timeout=30)" e, logo abaixo, "Nenhum
resultado encontrado". Agora: uma nova tentativa para falha transitória,
mensagem para a pessoa (o texto técnico vai para o log) e o "nenhum
resultado" só quando a consulta de fato respondeu vazio.

Não vai à rede: ``session.post`` é trocado por um dublê. A parte da tela usa
um escritório/usuário descartável, removido no fim.

    uv run python tests/test_datajud_indisponivel.py
"""

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, LawFirm, User, UserPageVisit
from app.services import data_jud_api
from app.services.data_jud_api import DataJudAPI

TEST_CNPJ = '00000000000499'
TEST_EMAIL = 'user__test_datajud@example.com'
NUMERO = '5107621-25.2025.4.02.5101'
TIMEOUT_CRU = ("HTTPSConnectionPool(host='api-publica.datajud.cnj.jus.br', port=443): "
               "Read timed out. (read timeout=30)")

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


class Resposta:
    def __init__(self, status_code, payload=None, text=''):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def dublê(*saidas):
    """``session.post`` que devolve (ou levanta) cada saída em ordem."""
    chamadas = []

    def post(url, json=None, timeout=None):
        chamadas.append(timeout)
        saida = saidas[len(chamadas) - 1]
        if isinstance(saida, Exception):
            raise saida
        return saida

    return post, chamadas


VAZIO = {'took': 5, 'hits': {'total': {'value': 0}, 'hits': []}}


def test_cliente():
    print('\n1. Cliente DataJud')
    data_jud_api.DATA_JUD_RETRY_WAIT = 0

    api = DataJudAPI()
    api.session.post, chamadas = dublê(requests.exceptions.ReadTimeout(TIMEOUT_CRU),
                                       requests.exceptions.ReadTimeout(TIMEOUT_CRU))
    r = api.buscar_por_numero_processo(NUMERO, 'TRF2')
    check('timeout tenta de novo uma vez só', len(chamadas) == 2, str(len(chamadas)))
    check('timeout volta como erro de indisponibilidade',
          r.get('error') and r.get('unavailable') is True, str(r))
    check('mensagem não tem o texto técnico', 'HTTPSConnectionPool' not in r['message'], r['message'])
    check('mensagem diz que o CNJ não respondeu', 'não respondeu a tempo' in r['message'], r['message'])
    check('texto técnico fica em detail', 'Read timed out' in r.get('detail', ''))
    check('timeout separa conexão de leitura', chamadas[0] == (10, 30), str(chamadas[0]))

    api.session.post, chamadas = dublê(Resposta(503, text='<html>erro</html>'), Resposta(200, VAZIO))
    r = api.buscar_por_numero_processo(NUMERO, 'TRF2')
    check('503 seguido de sucesso devolve a resposta', not r.get('error') and r.get('took') == 5, str(r))
    check('… depois de duas chamadas', len(chamadas) == 2, str(len(chamadas)))

    api.session.post, chamadas = dublê(Resposta(503, text='<html>erro</html>'),
                                       Resposta(503, text='<html>erro</html>'))
    r = api.buscar_por_assunto(1234, 'TRF2')
    check('503 persistente diz HTTP 503 sem o HTML no texto',
          'HTTP 503' in r['message'] and '<html>' not in r['message'], r['message'])

    api.session.post, chamadas = dublê(Resposta(404, text='index not found'))
    r = api.buscar_por_numero_processo(NUMERO, 'TRF2')
    check('404 não tenta de novo', len(chamadas) == 1, str(len(chamadas)))
    check('404 continua dizendo que o tribunal não está disponível',
          "Tribunal 'TRF2' não disponível" in r['message'] and r['unavailable'] is False, r['message'])

    api.session.post, chamadas = dublê(Resposta(400, text='parse error'))
    r = api.buscar_movimentos_por_codigo(1, 'TRF2')
    check('400 não tenta de novo e não é indisponibilidade',
          len(chamadas) == 1 and r['unavailable'] is False, str(r))


def _setup():
    firm = LawFirm.query.filter_by(cnpj=TEST_CNPJ).first()
    if firm:
        _cleanup(firm)
    firm = LawFirm(name='Escritório Teste DataJud', cnpj=TEST_CNPJ)
    db.session.add(firm)
    db.session.flush()
    user = User(law_firm_id=firm.id, name='teste', email=TEST_EMAIL, role='admin', is_active=True)
    user.set_password('x')
    db.session.add(user)
    db.session.commit()
    return firm, user


def _cleanup(firm):
    users = User.query.filter_by(law_firm_id=firm.id).all()
    ids = [u.id for u in users]
    if ids:
        UserPageVisit.query.filter(UserPageVisit.user_id.in_(ids)).delete(synchronize_session=False)
    for u in users:
        db.session.delete(u)
    db.session.delete(firm)
    db.session.commit()


def test_tela():
    print('\n2. Tela Ferramentas → Pesquisa em Processos Judiciais')
    original = DataJudAPI._post
    firm, user = _setup()
    try:
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['law_firm_id'] = user.law_firm_id
            sess['user_role'] = user.role
            sess['user_module_permissions'] = user.get_module_permissions()

        form = {'tipo_busca': 'numero', 'numero_processo': NUMERO, 'tribunal': 'TRF2'}

        DataJudAPI._post = lambda self, url, query, tribunal: DataJudAPI._erro(tribunal, None, TIMEOUT_CRU)
        html = client.post('/tools/datajud', data=form).get_data(as_text=True)
        check('mostra que o DataJud está indisponível', 'DataJud indisponível' in html)
        check('não mostra o texto técnico', 'HTTPSConnectionPool' not in html)
        check('não mostra "Nenhum resultado" junto do erro', 'Nenhum resultado encontrado' not in html)
        check('mantém o número digitado para tentar de novo', f'value="{NUMERO}"' in html)
        check('mantém o tribunal escolhido', 'value="TRF2" selected' in html)

        DataJudAPI._post = lambda self, url, query, tribunal: VAZIO
        html = client.post('/tools/datajud', data=form).get_data(as_text=True)
        check('consulta que respondeu vazia mostra "Nenhum resultado"',
              'Nenhum resultado encontrado' in html)
        check('… sem alerta de erro', 'DataJud indisponível' not in html and '<strong>Erro:</strong>' not in html)
    finally:
        DataJudAPI._post = original
        db.session.rollback()
        _cleanup(firm)


def main() -> int:
    test_cliente()
    with app.app_context():
        test_tela()

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
