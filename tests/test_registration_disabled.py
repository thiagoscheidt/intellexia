#!/usr/bin/env python3
"""
Testa que o autocadastro está fechado: sem link na tela de login, GET /register
volta para o login com aviso e POST /register é recusado antes de tocar o banco.

Uso: uv run python tests/test_registration_disabled.py
Não escreve no banco.
"""
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.blueprints.auth import REGISTRATION_ENABLED


def run():
    falhas = []

    def check(nome, condicao, detalhe=''):
        if condicao:
            print(f'✓ {nome}')
        else:
            print(f'✗ {nome} {detalhe}')
            falhas.append(nome)

    check('flag de autocadastro desligada', REGISTRATION_ENABLED is False)

    client = app.test_client()

    html = client.get('/login').get_data(as_text=True)
    check('tela de login sem link "Criar conta"', 'Criar conta' not in html)
    check('tela de login sem rota de cadastro', '/register' not in html)

    resp = client.get('/register')
    check('GET /register redireciona', resp.status_code == 302, str(resp.status_code))
    destino = urlparse(resp.headers.get('Location', ''))
    check('GET /register volta para o login', destino.path.endswith('/login'), destino.path)
    check('redirect avisa que o cadastro está fechado',
          parse_qs(destino.query).get('erro') == ['cadastro_fechado'], destino.query)

    aviso = client.get('/login?erro=cadastro_fechado').get_data(as_text=True)
    check('login exibe o aviso de cadastro fechado', 'showAlert("' in aviso)

    resp = client.post('/register', data={
        'full_name': 'Teste', 'email': 'novo@example.com', 'password': 'segredo123',
        'password_confirm': 'segredo123', 'terms': 'on',
        'law_firm_name': 'Escritório', 'law_firm_cnpj': '00000000000100',
    })
    dados = resp.get_json() or {}
    check('POST /register é recusado', dados.get('success') is False, str(dados))
    check('POST /register explica o motivo', 'cadastro' in (dados.get('message') or '').lower(),
          str(dados.get('message')))

    print()
    if falhas:
        print(f'{len(falhas)} verificação(ões) falharam: {", ".join(falhas)}')
        return 1
    print('Todas as verificações passaram.')
    return 0


if __name__ == '__main__':
    sys.exit(run())
