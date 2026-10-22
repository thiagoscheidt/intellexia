#!/usr/bin/env python3
"""
Token de API: criação, guarda só do hash, autenticação, revogação e o módulo `api`.

O token é mostrado uma vez e o banco guarda só o SHA-256; vencido, revogado ou
de usuário inativo não autentica; revoga o dono ou um admin do mesmo
escritório. Escritórios descartáveis, removidos no fim.

    uv run python tests/test_api_tokens.py
"""

import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'database'))

from main import app
from app.models import db, ApiToken, LawFirm, User
from app.services import api_token_service as svc
from app.utils.permissions import get_default_module_permissions
import add_api_tokens_table as migration

CNPJS = ('00000000001180', '00000000001261')
_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _cleanup():
    for cnpj in CNPJS:
        firm = LawFirm.query.filter_by(cnpj=cnpj).first()
        if not firm:
            continue
        ApiToken.query.filter_by(law_firm_id=firm.id).delete()
        User.query.filter_by(law_firm_id=firm.id).delete()
        db.session.delete(firm)
    db.session.commit()


def _setup():
    _cleanup()
    firmas, usuarios = [], {}
    for i, cnpj in enumerate(CNPJS):
        firm = LawFirm(name=f'Escritório Teste API {i}', cnpj=cnpj)
        db.session.add(firm)
        db.session.flush()
        firmas.append(firm)
        for papel in ('admin', 'lawyer', 'assistant'):
            u = User(law_firm_id=firm.id, name=f'{papel} {i}', role=papel, is_active=True,
                     email=f'{papel}{i}__test_api_tokens@example.com')
            u.set_password('x')
            db.session.add(u)
            usuarios[(i, papel)] = u
    db.session.commit()
    return firmas, usuarios


def test_criacao(usuarios):
    print('\n1. Criação: token uma vez, banco só com o hash')
    u = usuarios[(0, 'lawyer')]
    reg, texto = svc.criar(u, 'Planilha do Claude')
    check('começa com itx_', texto.startswith('itx_'), texto[:6])
    check('tamanho > 40', len(texto) > 40, str(len(texto)))
    check('hash SHA-256 no banco', reg.token_hash == hashlib.sha256(texto.encode()).hexdigest())
    check('last4 = final do token', reg.last4 == texto[-4:])
    linha = db.session.execute(db.text('SELECT * FROM api_tokens WHERE id = :i'), {'i': reg.id}).mappings().one()
    check('texto do token em nenhuma coluna', all(texto not in str(v) for v in linha.values()))
    check('validade padrão de 90 dias',
          reg.expires_at and 89 <= (reg.expires_at - datetime.utcnow()).days <= 90, str(reg.expires_at))
    reg2, _ = svc.criar(u, 'Sem validade', dias=None)
    check('sem validade aceita', reg2.expires_at is None)
    try:
        svc.criar(u, 'Validade inventada', dias=7)
        check('validade fora da lista recusada', False)
    except ValueError:
        check('validade fora da lista recusada', True)
    s = svc.serializar(reg)
    check('serializar sem hash', 'token_hash' not in s and reg.token_hash not in json.dumps(s, default=str))
    check('serializar com final e situação', s['final'] == texto[-4:] and s['situacao'] == 'ativo', str(s))
    return texto


def test_autenticacao(usuarios, texto):
    print('\n2. Autenticação')
    u = usuarios[(0, 'lawyer')]
    check('token válido devolve o usuário', svc.autenticar(texto, '10.0.0.1').id == u.id)
    db.session.commit()
    reg = ApiToken.query.filter_by(last4=texto[-4:], user_id=u.id).first()
    check('último uso gravado', reg.last_used_at is not None and reg.last_used_ip == '10.0.0.1')

    for nome, valor in (('token errado', 'itx_errado'), ('vazio', ''), ('None', None)):
        try:
            svc.autenticar(valor)
            check(f'{nome} recusado', False)
        except svc.TokenInvalido:
            check(f'{nome} recusado', True)

    vencido, texto_vencido = svc.criar(u, 'Vencido')
    vencido.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    try:
        svc.autenticar(texto_vencido)
        check('vencido recusado', False)
    except svc.TokenInvalido as e:
        check('vencido recusado com "vencido"', 'vencido' in e.mensagem, e.mensagem)
    check('situação vencido', svc.serializar(vencido)['situacao'] == 'vencido')

    revogado, texto_revogado = svc.criar(u, 'Revogado')
    svc.revogar(revogado.id, u)
    try:
        svc.autenticar(texto_revogado)
        check('revogado recusado', False)
    except svc.TokenInvalido as e:
        check('revogado recusado com "revogado"', 'revogado' in e.mensagem, e.mensagem)

    inativo = usuarios[(0, 'assistant')]
    _, texto_inativo = svc.criar(inativo, 'De quem saiu')
    inativo.is_active = False
    db.session.commit()
    try:
        svc.autenticar(texto_inativo)
        check('usuário inativo recusado', False)
    except svc.TokenInvalido:
        check('usuário inativo recusado', True)
    inativo.is_active = True
    db.session.commit()

    firma = db.session.get(LawFirm, u.law_firm_id)
    firma.is_active = False
    db.session.commit()
    try:
        svc.autenticar(texto)
        check('escritório desativado recusado', False)
    except svc.TokenInvalido:
        check('escritório desativado recusado', True)
    firma.is_active = True
    db.session.commit()


def test_revogacao(usuarios):
    print('\n3. Revogação: dono ou admin do escritório')
    dono = usuarios[(0, 'lawyer')]
    reg, _ = svc.criar(dono, 'Para revogar')
    for nome, quem in (('outro usuário do escritório', usuarios[(0, 'assistant')]),
                       ('admin de outro escritório', usuarios[(1, 'admin')])):
        try:
            svc.revogar(reg.id, quem)
            check(f'{nome} não revoga', False)
        except PermissionError:
            check(f'{nome} não revoga', True)
    admin = usuarios[(0, 'admin')]
    svc.revogar(reg.id, admin)
    check('admin do escritório revoga', reg.revoked_at is not None and reg.revoked_by_id == admin.id)
    svc.revogar(reg.id, dono)
    check('revogar de novo é idempotente', reg.revoked_by_id == admin.id)

    meus = svc.listar(dono)
    check('listar só do usuário', meus and all(t.user_id == dono.id for t in meus))
    do_escritorio = svc.listar_do_escritorio(dono.law_firm_id)
    check('listar do escritório só do escritório',
          do_escritorio and all(t.law_firm_id == dono.law_firm_id for t in do_escritorio))


def test_modulo_api(usuarios):
    print('\n4. Módulo api')
    check('padrão de lawyer tem api', 'api' in get_default_module_permissions('lawyer'))
    check('padrão de assistant tem api', 'api' in get_default_module_permissions('assistant'))
    u = usuarios[(1, 'lawyer')]
    u.module_permissions = json.dumps(['fap_panel', 'knowledge_base'])
    db.session.commit()
    check('lista gravada antiga sem api', 'api' not in u.get_module_permissions())
    alterados = migration.aplicar_modulo_api()
    db.session.refresh(u)
    check('migration acrescenta api a quem tem lista gravada', 'api' in u.get_module_permissions())
    check('migration conta quem mudou', alterados >= 1, str(alterados))
    check('segunda rodada não muda ninguém', migration.aplicar_modulo_api() == 0)
    u.set_module_permissions([m for m in u.get_module_permissions() if m != 'api'])
    db.session.commit()
    migration.run()
    db.session.refresh(u)
    check('rodar a migration de novo não devolve api tirado pelo admin', 'api' not in u.get_module_permissions())


def test_cascade(usuarios):
    print('\n5. Usuário apagado leva os tokens')
    u = usuarios[(1, 'assistant')]
    reg, _ = svc.criar(u, 'Some com o usuário')
    tid = reg.id
    db.session.delete(u)
    db.session.commit()
    check('token apagado junto', db.session.get(ApiToken, tid) is None)


def main() -> int:
    with app.app_context():
        migration.criar_tabela()
        _, usuarios = _setup()
        try:
            texto = test_criacao(usuarios)
            test_autenticacao(usuarios, texto)
            test_revogacao(usuarios)
            test_modulo_api(usuarios)
            test_cascade(usuarios)
        finally:
            db.session.rollback()
            _cleanup()

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
