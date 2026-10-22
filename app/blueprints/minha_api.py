"""
Minha API — tokens pessoais e documentação da API do IntellexIA (``/api/v1``).

Módulo de permissão ``api``. A API em si fica em ``public_api`` (autenticada só
por token); aqui é a parte logada: a documentação gerada do registro de rotas
e a gestão dos tokens.
"""
from __future__ import annotations

import json
from functools import wraps

from flask import Blueprint, flash, jsonify, make_response, redirect, render_template, request, session, url_for

from app.models import User, db
from app.services import api_token_service
from app.services import public_api_campos as campos
from app.services import public_api_catalogo as catalogo
from app.utils.urls import app_public_url

minha_api_bp = Blueprint('minha_api', __name__, url_prefix='/minha-api')

VALIDADES = ((30, '30 dias'), (90, '90 dias'), (180, '180 dias'), (None, 'Sem validade'))


def _usuario() -> User:
    return db.session.get(User, session['user_id'])


def require_admin_user(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = _usuario() if session.get('user_id') else None
        if not user or user.role != 'admin':
            flash('Acesso negado: privilégio de administrador necessário.', 'danger')
            return redirect(url_for('minha_api.index'))
        return f(*args, **kwargs)
    return decorated_function


def _tela(aba: str, user: User, novo_token: str | None = None, novo_registro=None):
    if aba == 'escritorio':
        tokens = api_token_service.listar_do_escritorio(user.law_firm_id)
        donos = {u.id: u.name for u in User.query.filter_by(law_firm_id=user.law_firm_id)}
    else:
        tokens = api_token_service.listar(user)
        donos = {user.id: user.name}
    linhas = [{**api_token_service.serializar(t), 'dono': donos.get(t.user_id, '—'), 'registro': t}
              for t in tokens]
    return render_template(
        'minha_api/index.html',
        aba=aba,
        tokens=linhas,
        validades=VALIDADES,
        novo_token=novo_token,
        novo_registro=api_token_service.serializar(novo_registro) if novo_registro else None,
        base_api=app_public_url() + '/api/v1',
        eh_admin=user.role == 'admin',
    )


@minha_api_bp.route('/')
def index():
    return _tela('meus', _usuario())


@minha_api_bp.route('/escritorio')
@require_admin_user
def escritorio():
    return _tela('escritorio', _usuario())


@minha_api_bp.route('/tokens', methods=['POST'])
def criar_token():
    user = _usuario()
    bruto = (request.form.get('validade') or '').strip()
    try:
        dias = int(bruto) if bruto else None
        registro, texto = api_token_service.criar(user, request.form.get('nome', ''), dias)
    except ValueError:
        flash('Validade inválida. Escolha 30, 90, 180 dias ou sem validade.', 'danger')
        return redirect(url_for('minha_api.index'))
    # O token vai só nesta resposta: nem flash (fica na sessão) nem URL, nem cache.
    resp = make_response(_tela('meus', user, novo_token=texto, novo_registro=registro))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@minha_api_bp.route('/tokens/<int:token_id>/revogar', methods=['POST'])
def revogar_token(token_id: int):
    user = _usuario()
    try:
        api_token_service.revogar(token_id, user)
        flash('Token revogado. Ele parou de funcionar agora.', 'success')
    except PermissionError as e:
        flash(str(e), 'danger')
    if request.form.get('voltar') == 'escritorio' and user.role == 'admin':
        return redirect(url_for('minha_api.escritorio'))
    return redirect(url_for('minha_api.index'))


# ── modal da API no cabeçalho (JSON, sessão do app) ──────────────────────────

@minha_api_bp.app_context_processor
def _modal_api():
    """``api_catalogo()`` para o modal do cabeçalho: chamada só se o modal renderiza."""
    def api_catalogo():
        grupos = []
        for chave, rotulo in catalogo.GRUPOS.items():
            rotas = [{'metodo': r.metodo, 'caminho': r.caminho, 'resumo': r.resumo}
                     for r in catalogo.ROTAS if r.grupo == chave]
            if rotas:
                grupos.append({'chave': chave, 'rotulo': rotulo, 'rotas': rotas})
        return {'base': app_public_url() + '/api/v1', 'grupos': grupos,
                'total': len(catalogo.ROTAS) + len(catalogo._ROTAS_PROPRIAS)}
    return {'api_catalogo': api_catalogo}


def _sem_cache(resp):
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@minha_api_bp.route('/tokens.json')
def tokens_json():
    user = _usuario()
    return _sem_cache(jsonify({'tokens': [api_token_service.serializar(t) for t in api_token_service.listar(user)]}))


@minha_api_bp.route('/tokens.json', methods=['POST'])
def criar_token_json():
    user = _usuario()
    dados = request.get_json(silent=True) or {}
    validade = dados.get('validade', api_token_service.VALIDADE_PADRAO)
    try:
        dias = None if validade in (None, '') else int(validade)
        registro, texto = api_token_service.criar(user, str(dados.get('nome') or ''), dias)
    except (TypeError, ValueError):
        return _sem_cache(jsonify({'erro': 'Validade inválida. Escolha 30, 90, 180 dias ou sem validade.'})), 400
    # Única resposta com o token em claro.
    return _sem_cache(jsonify({**api_token_service.serializar(registro), 'token': texto})), 201


@minha_api_bp.route('/tokens/<int:token_id>/revogar.json', methods=['POST'])
def revogar_token_json(token_id: int):
    try:
        registro = api_token_service.revogar(token_id, _usuario())
    except PermissionError as e:
        return _sem_cache(jsonify({'erro': str(e)})), 403
    return _sem_cache(jsonify({'ok': True, 'token': api_token_service.serializar(registro)}))


@minha_api_bp.route('/documentacao')
def documentacao():
    base = app_public_url()
    grupos = []
    for chave, rotulo in catalogo.GRUPOS.items():
        rotas = [r for r in catalogo.ROTAS if r.grupo == chave]
        if rotas:
            grupos.append({'chave': chave, 'rotulo': rotulo, 'rotas': [
                {'rota': r, 'curl': catalogo.exemplo_curl(r, base), **_resposta(r.resposta)} for r in rotas]})
    return render_template(
        'minha_api/documentacao.html',
        base_api=base + '/api/v1',
        grupos=grupos,
        rotas_proprias=[{'metodo': m, 'caminho': c, 'resumo': t, **_resposta(campos.EU)}
                        for m, c, t in catalogo._ROTAS_PROPRIAS],
        teto_pagina=catalogo.TETO_PAGINA,
    )


def _resposta(declarados) -> dict:
    """Tabela dos campos e exemplo de JSON de uma rota, montados da declaração."""
    return {'campos': campos.linhas(declarados),
            'exemplo': json.dumps(campos.exemplo(declarados), ensure_ascii=False, indent=2)}
