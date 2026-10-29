"""
Blueprint: arquivos de uma revisão feita no Claude, anexados depois de gravar.

`/revisao/arquivos/<token>` é público — o token assinado do link é a
autorização, e o `check_session` desvia o prefixo como faz com `/api/v1`. O
mesmo endereço serve a pessoa (GET mostra a página, que envia por XHR) e o
Claude (`curl -F peticao=@... -F planilha=@...`). Regras em
`app/services/fap_review_arquivos_service.py`.
"""
from flask import Blueprint, current_app, jsonify, make_response, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.services import fap_review_arquivos_service as _arq

fap_review_arquivos_bp = Blueprint('fap_review_arquivos', __name__)


def _sem_cache(corpo, status: int = 200):
    resposta = make_response(corpo, status)
    resposta.headers['Cache-Control'] = 'no-store'
    resposta.headers['X-Robots-Tag'] = 'noindex'
    return resposta


@fap_review_arquivos_bp.route('/revisao/arquivos/<token>', methods=['GET'])
def pagina(token: str):
    execution, estado = _arq.ler_link(token)
    contexto = {'estado': estado}
    if execution:
        contexto.update(_arq.contexto_da_pagina(execution))
    status = {'inexistente': 404, 'expirado': 410}.get(estado, 200)
    return _sem_cache(render_template('fap_review/arquivos_claude.html', **contexto), status)


@fap_review_arquivos_bp.route('/revisao/arquivos/<token>', methods=['POST'])
def receber(token: str):
    try:
        # O token é conferido antes de ler o corpo: endereço público não grava
        # em disco o envio de quem nem tem link. Com link, o corpo tem teto.
        _execution, estado = _arq.ler_link(token)
        arquivos = {}
        if estado == 'valido':
            request.max_content_length = 3 * _arq.MAX_ARQUIVO_BYTES + 1024 * 1024
            arquivos = {campo: request.files.get(campo) for campo in request.files}
        resultado = _arq.receber(token, arquivos)
    except _arq.EnvioRecusado as e:
        return _sem_cache(jsonify({'ok': False, 'erro': e.mensagem}), e.status_http)
    except RequestEntityTooLarge:
        return _sem_cache(jsonify({'ok': False, 'erro': 'O envio é grande demais.'}), 413)
    except Exception:
        current_app.logger.exception('Envio de arquivos da revisão do Claude falhou (token %s…)', token[:6])
        return _sem_cache(jsonify({
            'ok': False, 'erro': 'Não foi possível receber os arquivos agora. Tente de novo em instantes.',
        }), 500)
    return _sem_cache(jsonify({'ok': True, **resultado}))
