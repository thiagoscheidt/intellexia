"""
Blueprint: link de envio do arquivo para a revisão pedida pelo Claude (RPI-37).

`/revisao/enviar/<token>` é público — o token do link é a autorização, e o
`check_session` desvia o prefixo como faz com `/api/v1`. O mesmo endereço serve
a pessoa (GET mostra a página, que envia por fetch) e o Claude (`curl -F
arquivo=@...`). Regras em `app/services/fap_review_upload_service.py`.
"""
from flask import Blueprint, current_app, jsonify, make_response, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.services import fap_review_service as _svc
from app.services import fap_review_upload_service as _up

fap_review_upload_bp = Blueprint('fap_review_upload', __name__)


def _sem_cache(resposta):
    resposta.headers['Cache-Control'] = 'no-store'
    resposta.headers['X-Robots-Tag'] = 'noindex'
    return resposta


@fap_review_upload_bp.route('/revisao/enviar/<token>', methods=['GET'])
def enviar(token: str):
    link, estado = _up.find_link(token)
    contexto = {'estado': estado, 'token': token}
    status = 200
    if estado == 'inexistente':
        status = 404
    elif estado == 'expirado':
        status = 410
    elif estado == 'usado':
        contexto['revisao'] = _up._revisao_do_link(link)
    else:
        contexto.update(_up.link_page_context(link))
        if contexto['em_andamento']:
            contexto['link_em_andamento'] = _svc.revision_result_url(contexto['em_andamento'].id)
    resposta = render_template('fap_review/envio_arquivo.html', **contexto)
    return _sem_cache(_resposta(resposta, status))


@fap_review_upload_bp.route('/revisao/enviar/<token>', methods=['POST'])
def receber(token: str):
    try:
        # O token é conferido antes de ler o corpo: endereço público não pode
        # gravar em disco o envio de quem nem tem link. Com link, o corpo tem teto.
        _link, estado = _up.find_link(token)
        arquivo = None
        if estado == 'valido':
            request.max_content_length = _up.MAX_UPLOAD_BYTES + 1024 * 1024
            arquivo = request.files.get('arquivo')
        resultado = _up.receive_upload(token, arquivo)
    except _up.UploadRecusado as e:
        return _sem_cache(_resposta(jsonify({'ok': False, 'erro': e.mensagem, **e.extra}), e.status_http))
    except RequestEntityTooLarge:
        mensagem = f'O arquivo passa de {_up.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.'
        return _sem_cache(_resposta(jsonify({'ok': False, 'erro': mensagem}), 413))
    except Exception:
        current_app.logger.exception('Envio do arquivo da revisão falhou (token %s…)', token[:6])
        return _sem_cache(_resposta(jsonify({
            'ok': False, 'erro': 'Não foi possível receber o arquivo agora. Tente de novo em instantes.',
        }), 500))
    return _sem_cache(_resposta(jsonify({'ok': True, **resultado}), 200))


def _resposta(corpo, status):
    return make_response(corpo, status)
