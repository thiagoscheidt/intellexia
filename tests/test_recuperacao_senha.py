#!/usr/bin/env python3
"""
FB-07 — recuperação de senha por e-mail.

Antes, ``forgot_password_post`` validava o formato do endereço e respondia
"você receberá as instruções" sem gerar link nem chamar o email_service: o
fluxo nunca existiu.

O link carrega um token assinado com a SECRET_KEY, com validade, amarrado ao
hash da senha atual — sem tabela nova. Trocou a senha, o hash muda e o link
morre: é isso que o torna de uso único.

Script standalone no padrão do projeto. Nenhum e-mail sai de verdade: o envio é
interceptado. Usa um escritório descartável, removido no fim.

    uv run python tests/test_recuperacao_senha.py
"""

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from main import app
from app.models import db, LawFirm, User, UserPageVisit
from app.services import email_service
from app.blueprints import auth as auth_mod

_falhas = []
FIRMA = '__TESTE_FB07__'
EMAIL = 'fb07.recuperacao@teste.invalid'
SENHA_ANTIGA = 'senha-antiga-123'
GENERICA = 'Se o email existir em nosso sistema, você receberá as instruções para redefinir sua senha.'


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


class CaixaDeSaida:
    """Troca o envio real por uma lista: nenhum e-mail sai deste teste."""

    def __init__(self):
        self.enviados = []
        self._original = email_service.send_email

    def __enter__(self):
        def falso(to, subject, html, text=None, **kwargs):
            self.enviados.append({'to': to, 'subject': subject, 'html': html, 'text': text})
            return True
        email_service.send_email = falso
        return self

    def __exit__(self, *exc):
        email_service.send_email = self._original


def remover():
    db.session.rollback()
    firma = LawFirm.query.filter_by(name=FIRMA).first()
    if not firma:
        return
    UserPageVisit.query.filter_by(law_firm_id=firma.id).delete()
    User.query.filter_by(law_firm_id=firma.id).delete()
    LawFirm.query.filter_by(id=firma.id).delete()
    db.session.commit()


def preparar():
    remover()
    firma = LawFirm(name=FIRMA, cnpj='00000000000191', is_active=True)
    db.session.add(firma); db.session.flush()
    usuario = User(law_firm_id=firma.id, name='Pessoa Teste', email=EMAIL, role='user', is_active=True)
    usuario.set_password(SENHA_ANTIGA)
    outro = User(law_firm_id=firma.id, name='Outra Pessoa', email='fb07.outra@teste.invalid',
                 role='user', is_active=True)
    outro.set_password('outra-senha-123')
    db.session.add_all([usuario, outro])
    db.session.commit()
    return firma.id, usuario.id, outro.id


def link_do_email(mensagem):
    achado = re.search(r'https?://[^\s"<>]+/reset-password/[^\s"<>]+', mensagem['html'])
    return achado.group(0) if achado else ''


def token_do_link(link):
    return link.rsplit('/reset-password/', 1)[-1]


def test_pedido_envia_link(client, usuario_id):
    print('\n1. Pedir recuperação manda um e-mail com link')

    with CaixaDeSaida() as caixa:
        r = client.post('/forgot-password', data={'email': EMAIL})
    dados = r.get_json()
    check('resposta de sucesso', dados and dados.get('success') is True, str(dados))
    check('mensagem não revela se o e-mail existe', dados and dados.get('message') == GENERICA)
    check('um e-mail enviado', len(caixa.enviados) == 1, str(len(caixa.enviados)))
    if not caixa.enviados:
        return ''
    mensagem = caixa.enviados[0]
    check('para o dono da conta', EMAIL in str(mensagem['to']), str(mensagem['to']))
    link = link_do_email(mensagem)
    check('com link de redefinição', bool(link), mensagem['html'][:200])
    check('versão em texto também traz o link', link and link in (mensagem['text'] or ''))
    return token_do_link(link)


def test_nao_revela_quem_existe(client):
    print('\n2. E-mail inexistente: mesma resposta, nenhum envio')

    with CaixaDeSaida() as caixa:
        r = client.post('/forgot-password', data={'email': 'ninguem.aqui@teste.invalid'})
    dados = r.get_json()
    check('mesma resposta de sucesso', dados and dados.get('success') is True and dados.get('message') == GENERICA)
    check('nenhum e-mail enviado', caixa.enviados == [])


def test_maiusculas_no_email(client):
    print('\n3. E-mail digitado com maiúsculas também encontra a conta')

    with CaixaDeSaida() as caixa:
        client.post('/forgot-password', data={'email': EMAIL.upper()})
    check('envia do mesmo jeito', len(caixa.enviados) == 1, str(len(caixa.enviados)))


def test_conta_inativa(client, usuario_id):
    print('\n4. Conta inativa não recebe link')

    usuario = db.session.get(User, usuario_id)
    usuario.is_active = False
    db.session.commit()
    try:
        with CaixaDeSaida() as caixa:
            r = client.post('/forgot-password', data={'email': EMAIL})
        check('mesma resposta genérica', r.get_json().get('message') == GENERICA)
        check('nenhum e-mail enviado', caixa.enviados == [])
    finally:
        usuario = db.session.get(User, usuario_id)
        usuario.is_active = True
        db.session.commit()


def test_redefinir(client, usuario_id, token):
    print('\n5. O link abre a tela e troca a senha')

    r = client.get(f'/reset-password/{token}')
    html = r.data.decode('utf-8')
    check('tela abre', r.status_code == 200, str(r.status_code))
    check('tem o formulário de nova senha', 'name="password"' in html and 'name="password_confirm"' in html)
    check('o token do endereço não vaza no Referer para CDN', 'name="referrer" content="no-referrer"' in html)

    r = client.post(f'/reset-password/{token}', data={'password': 'nova-senha-1', 'password_confirm': 'outra'})
    check('confirmação diferente é recusada', r.get_json().get('success') is False)

    r = client.post(f'/reset-password/{token}', data={'password': '123', 'password_confirm': '123'})
    check('senha curta é recusada', r.get_json().get('success') is False
          and '6' in r.get_json().get('message', ''), str(r.get_json()))

    db.session.expire_all()
    check('nada mudou nas tentativas recusadas',
          db.session.get(User, usuario_id).check_password(SENHA_ANTIGA))

    r = client.post(f'/reset-password/{token}', data={'password': 'nova-senha-1', 'password_confirm': 'nova-senha-1'})
    dados = r.get_json()
    check('senha trocada', dados and dados.get('success') is True, str(dados))
    db.session.expire_all()
    usuario = db.session.get(User, usuario_id)
    check('nova senha vale', usuario.check_password('nova-senha-1'))
    check('antiga não vale mais', not usuario.check_password(SENHA_ANTIGA))

    r = client.post('/login', data={'email': EMAIL, 'password': 'nova-senha-1'})
    check('entra com a nova senha', r.get_json().get('success') is True, str(r.get_json()))


def test_link_de_uso_unico(client, token):
    print('\n6. O mesmo link não serve duas vezes')

    r = client.get(f'/reset-password/{token}')
    html = r.data.decode('utf-8')
    check('tela diz que o link não vale mais', 'name="password"' not in html and 'expirou' in html.lower(),
          html[:200])
    r = client.post(f'/reset-password/{token}', data={'password': 'terceira-senha', 'password_confirm': 'terceira-senha'})
    check('segunda troca é recusada', r.get_json().get('success') is False)


def test_links_invalidos(client, usuario_id, outro_id):
    print('\n7. Link adulterado, vencido ou de outra pessoa')

    with app.test_request_context():
        usuario = db.session.get(User, usuario_id)
        token = auth_mod.gerar_token_redefinicao(usuario)
        check('token recém-gerado vale', auth_mod.usuario_do_token(token) is not None)
        check('token vencido não vale', auth_mod.usuario_do_token(token, max_idade=-1) is None)
        adulterado = token[:-3] + ('aaa' if not token.endswith('aaa') else 'bbb')
        check('token adulterado não vale', auth_mod.usuario_do_token(adulterado) is None)
        encontrado = auth_mod.usuario_do_token(token)
        check('token leva ao próprio dono, não a outra conta',
              encontrado is not None and encontrado.id == usuario_id and encontrado.id != outro_id)

    r = client.get('/reset-password/qualquer-coisa')
    check('lixo na URL mostra link inválido, sem erro', r.status_code == 200 and 'expirou' in r.data.decode().lower())


def test_rotas_publicas(client):
    print('\n8. As telas funcionam sem estar logado')

    r = client.get('/forgot-password')
    check('esqueci a senha abre sem login', r.status_code == 200, str(r.status_code))
    r = client.get('/reset-password/abc')
    check('redefinir abre sem login (não redireciona ao login)', r.status_code == 200, str(r.status_code))


def main() -> int:
    with app.app_context():
        try:
            _, usuario_id, outro_id = preparar()
            client = app.test_client()
            test_rotas_publicas(client)
            token = test_pedido_envia_link(client, usuario_id)
            test_nao_revela_quem_existe(client)
            test_maiusculas_no_email(client)
            test_conta_inativa(client, usuario_id)
            if token:
                test_redefinir(client, usuario_id, token)
                test_link_de_uso_unico(app.test_client(), token)
            test_links_invalidos(client, usuario_id, outro_id)
        finally:
            remover()

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
