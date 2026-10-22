"""
API do IntellexIA (``/api/v1``) — os dados do escritório para quem monta as
próprias telas e automações (Claude Code, planilhas, scripts).

Autenticação **só** por ``Authorization: Bearer <token>`` (token pessoal de
``api_token_service``). Cookie de sessão não vale aqui de propósito: senão
qualquer página aberta no navegador logado chamaria a API em nome da pessoa.
Por isso também o CORS pode ficar aberto — sem o token, a origem não ganha nada.

Cada rota passa por ``executar``: autentica, confere o módulo **atual** do
usuário, aplica o limite por minuto, chama, converte erros para
``{"erro": "..."}`` e registra o uso em ``user_mcp_calls`` (``kind='api'``, sem
argumentos). As rotas de dados saem do registro em
``app/services/public_api_catalogo.py``.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from flask import Blueprint, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from app.models import db
from app.services import access_audit_service, api_token_service
from app.utils.permissions import MODULE_PERMISSIONS
from app.utils.urls import app_public_url

logger = logging.getLogger(__name__)

PREFIXO = '/api/v1'
public_api_bp = Blueprint('public_api', __name__, url_prefix=PREFIXO)

_CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Max-Age': '600',
}


@dataclass(frozen=True)
class Contexto:
    user_id: int
    law_firm_id: int
    modulos: list[str]
    papel: str
    app_public_url: str
    token_id: int


class ErroApi(Exception):
    def __init__(self, mensagem: str, status: int = 400, retry_after: int | None = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status
        self.retry_after = retry_after


# ── limite por minuto ────────────────────────────────────────────────────────
# Em memória, por processo do Gunicorn: com N workers o teto real fica entre o
# limite e N vezes ele. Basta para conter um loop descontrolado sem Redis.
_janelas: dict[int, deque] = {}
_trava = threading.Lock()


def limite_por_minuto() -> int:
    try:
        return max(1, int(os.getenv('API_LIMITE_POR_MINUTO', '120')))
    except ValueError:
        return 120


def _conferir_limite(token_id: int) -> None:
    agora = time.monotonic()
    limite = limite_por_minuto()
    with _trava:
        janela = _janelas.setdefault(token_id, deque())
        while janela and agora - janela[0] >= 60:
            janela.popleft()
        if len(janela) >= limite:
            espera = max(1, int(60 - (agora - janela[0])) + 1)
            raise ErroApi(f'Limite de {limite} requisições por minuto atingido. '
                          f'Tente de novo em {espera} s.', 429, retry_after=espera)
        janela.append(agora)


# ── núcleo ───────────────────────────────────────────────────────────────────

def _status_do_tool_error(e) -> int:
    """Status HTTP de um ``ToolError`` dos handlers do MCP.

    A causa (``raise ToolError(...) from causa``) manda quando diz o status:
    ``NomeNaoRevelavel.status_http`` (404 fora da base, 429 cota) e fornecedor
    indisponível (503). Sem causa: "Acesso negado" é 403, o resto é pedido inválido.
    """
    from app.services.cpf_nome_client import CpfNomeIndisponivel

    causa = e.__cause__
    if isinstance(causa, CpfNomeIndisponivel):
        return 503
    status = getattr(causa, 'status_http', None)
    if isinstance(status, int):
        return status
    return 403 if str(e).startswith('Acesso negado') else 400


def _segundos_ate_amanha() -> int:
    from datetime import timedelta

    from app.utils.timezone import now_sp

    agora = now_sp()
    amanha = (agora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((amanha - agora).total_seconds()))


def _token_do_header() -> str:
    valor = (request.headers.get('Authorization') or '').strip()
    esquema, _, token = valor.partition(' ')
    if esquema.lower() != 'bearer' or not token.strip():
        raise api_token_service.TokenInvalido(
            'Informe o token no header "Authorization: Bearer <token>". Crie o seu em Minha API.')
    return token.strip()


def _ip() -> str | None:
    encaminhado = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    return encaminhado or request.remote_addr


def _json(corpo: dict, status: int, extra_headers: dict | None = None) -> Response:
    resp = jsonify(corpo)
    resp.status_code = status
    for k, v in (extra_headers or {}).items():
        resp.headers[k] = v
    return resp


def executar(nome_uso: str, modulo: str | None,
             funcao: Callable[[Contexto], dict | tuple[dict, int]]) -> Response:
    """Roda uma rota da API: autenticação, módulo, limite, erros e registro de uso."""
    inicio = time.perf_counter()
    user = None
    headers = {}
    erro_log = None
    try:
        texto = _token_do_header()
        user = api_token_service.autenticar(texto, _ip())
        token = api_token_service.token_da_requisicao(texto)
        db.session.commit()  # último uso do token
        _conferir_limite(token.id)

        modulos = user.get_module_permissions()
        if 'api' not in modulos:
            raise ErroApi('Acesso negado: seu usuário não tem o módulo "API e integrações". '
                          'Solicite a um administrador do escritório.', 403)
        if modulo and modulo not in modulos:
            label = MODULE_PERMISSIONS.get(modulo, modulo)
            raise ErroApi(f"Acesso negado: seu usuário não tem permissão para o módulo '{label}'. "
                          'Solicite acesso a um administrador do escritório.', 403)

        ctx = Contexto(user_id=user.id, law_firm_id=user.law_firm_id, modulos=modulos,
                       papel=str(user.role or ''), app_public_url=app_public_url(), token_id=token.id)
        resultado = funcao(ctx)
        corpo, status = resultado if isinstance(resultado, tuple) else (resultado, 200)
    except api_token_service.TokenInvalido as e:
        db.session.rollback()
        corpo, status = {'erro': e.mensagem}, 401
        user = None  # sem dono confirmado, não há uso a registrar
    except ErroApi as e:
        db.session.rollback()
        corpo, status = {'erro': e.mensagem}, e.status
        if e.retry_after:
            headers['Retry-After'] = str(e.retry_after)
    except Exception as e:
        db.session.rollback()
        from fastmcp.exceptions import ToolError

        if isinstance(e, ToolError):
            mensagem = str(e)
            corpo, status = {'erro': mensagem}, _status_do_tool_error(e)
            if status == 429:
                headers['Retry-After'] = str(_segundos_ate_amanha())
        else:
            logger.exception('Erro na API (%s)', nome_uso)
            corpo, status = {'erro': 'Erro interno ao processar a requisição.'}, 500
            # Só o tipo: o texto da exceção pode trazer argumento (CPF num SQL).
            erro_log = type(e).__name__

    if user is not None:
        ms = int((time.perf_counter() - inicio) * 1000)
        if status >= 400 and erro_log is None:
            erro_log = str(corpo.get('erro') or status)
        access_audit_service.record_mcp_call(
            user.id, user.law_firm_id, 'api', nome_uso, status < 400, ms, erro_log)
    return _json(corpo, status, headers)


# ── CORS, preflight e erros de roteamento ────────────────────────────────────

@public_api_bp.before_request
def _preflight():
    if request.method == 'OPTIONS':
        return Response(status=204)


@public_api_bp.after_request
def _cors(resp):
    resp.headers.update(_CORS)
    # Dado de escritório (CPF, nomes): nada de cache em navegador ou proxy.
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@public_api_bp.app_errorhandler(404)
@public_api_bp.app_errorhandler(405)
def _erro_de_rota(e: HTTPException):
    """Na API, rota inexistente responde JSON; no resto do app, o padrão do Flask."""
    if not request.path.startswith(PREFIXO + '/') and request.path != PREFIXO:
        return e
    mensagem = ('Rota não encontrada na API. Veja a documentação em Minha API.'
                if e.code == 404 else 'Método não permitido nesta rota.')
    return _json({'erro': mensagem}, e.code, _CORS)


# ── rotas próprias ───────────────────────────────────────────────────────────

@public_api_bp.route('/eu', methods=['GET'])
def eu():
    def montar(ctx: Contexto) -> dict:
        from app.models import ApiToken, LawFirm, User
        from app.services import segurado_nome_service

        user = db.session.get(User, ctx.user_id)
        firm = db.session.get(LawFirm, ctx.law_firm_id)
        token = api_token_service.serializar(db.session.get(ApiToken, ctx.token_id))
        corpo = {
            'usuario': {'id': user.id, 'nome': user.name, 'email': user.email, 'papel': ctx.papel},
            'escritorio': {'id': firm.id, 'nome': firm.name},
            'modulos': ctx.modulos,
            'token': {'nome': token['nome'], 'final': token['final'], 'expira_em': token['expira_em']},
        }
        if 'fap_panel' in ctx.modulos:
            corpo['consultas_nome_restantes_hoje'] = segurado_nome_service.consultas_restantes_hoje(
                ctx.law_firm_id, ctx.user_id)
        return corpo

    return executar('GET /eu', None, montar)


# ── rotas de dados (registro em public_api_catalogo) ─────────────────────────

def _corpo_json() -> dict:
    corpo = request.get_json(silent=True)
    if corpo is None:
        if request.get_data():
            raise ErroApi('O corpo da requisição precisa ser JSON (Content-Type: application/json).')
        return {}
    if not isinstance(corpo, dict):
        raise ErroApi('O corpo da requisição precisa ser um objeto JSON.')
    return corpo


def _montar(rota):
    from app.services.public_api_catalogo import ler_parametros, para_api
    from mcp_server.tools.pagination import teto_da_pagina

    def view(**caminho):
        def chamar(ctx: Contexto):
            from fastmcp.exceptions import ToolError

            corpo = _corpo_json() if rota.metodo == 'POST' else None
            try:
                params = ler_parametros(rota, request.args, corpo, caminho)
                # O handler é o do MCP; o teto da página é o da API.
                with teto_da_pagina(rota.teto):
                    resultado = rota.chamar(ctx, params)
            except ToolError as e:
                # Parte dos handlers de detalhe levanta em vez de devolver {"erro"}.
                if rota.detalhe and 'não encontrad' in str(e).lower():
                    raise ErroApi(str(e), 404) from e
                raise
            # Os handlers do MCP devolvem {"erro": ...} em vez de levantar quando o
            # pedido não serve (registro de outro escritório, filtro faltando).
            if isinstance(resultado, dict) and set(resultado) == {'erro'}:
                nao_achou = rota.detalhe and 'não encontrad' in str(resultado['erro']).lower()
                return resultado, 404 if nao_achou else 400
            return para_api(resultado)

        return executar(rota.nome_uso, rota.modulo, chamar)

    caminho_flask = rota.caminho.replace('{id}', '<int:id>').replace('{', '<').replace('}', '>')
    endpoint = 'rota_' + rota.metodo.lower() + rota.caminho.replace('/', '_').replace('{', '').replace('}', '').replace('-', '_')
    public_api_bp.add_url_rule(caminho_flask, endpoint=endpoint, view_func=view, methods=[rota.metodo])


def _montar_rotas():
    from app.services.public_api_catalogo import ROTAS

    for rota in ROTAS:
        _montar(rota)


_montar_rotas()


@public_api_bp.route('/openapi.json', methods=['GET'])
def openapi_json():
    from app.services.public_api_catalogo import openapi

    return executar('GET /openapi.json', None, lambda ctx: openapi(ctx.app_public_url))
