"""Blueprint: Base de Conhecimento do Painel de Processos.

Tela única que junta as duas bases que a IA usa para montar a impugnação — a
Base de Jurisprudência (`jurisprudence`) e as Peças-modelo
(`impugnacao_references`) — para o menu ter um item só. As telas de cada base
continuam nos endereços de sempre; aqui ficam a Visão geral e a busca nas duas.
As abas de todas elas vêm de `templates/partials/process_knowledge_header.html`.

Rotas:
    GET /process-panel/base-conhecimento/          Visão geral
    GET /process-panel/base-conhecimento/buscar    busca nas duas bases
"""
from __future__ import annotations

from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.services import jurisprudence_normalizer as norm
from app.services import process_knowledge_service as base

process_knowledge_bp = Blueprint('process_knowledge', __name__, url_prefix='/process-panel/base-conhecimento')

ESCOPOS = ('tudo', 'jurisprudencia', 'pecas')


def get_current_law_firm_id():
    return session.get('law_firm_id')


def require_law_firm(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_law_firm_id():
            flash('Você precisa estar associado a um escritório.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@process_knowledge_bp.app_context_processor
def _contagens_das_abas():
    """Números das abas, sob demanda: só a tela que desenha as abas paga os
    dois COUNTs (a função vai para o template, não o resultado)."""
    def base_conhecimento_contagens():
        law_firm_id = get_current_law_firm_id()
        return base.contagens(law_firm_id) if law_firm_id else {'decisoes': 0, 'pecas': 0}
    return {'base_conhecimento_contagens': base_conhecimento_contagens}


@process_knowledge_bp.route('/')
@require_law_firm
def index():
    return render_template(
        'process_knowledge/index.html',
        v=base.visao_geral(get_current_law_firm_id()),
        filtro=request.args.get('cobertura') if request.args.get('cobertura') == 'todas' else 'lacunas',
    )


@process_knowledge_bp.route('/buscar')
@require_law_firm
def buscar():
    escopo = request.args.get('em') if request.args.get('em') in ESCOPOS else 'tudo'
    return render_template(
        'process_knowledge/search.html',
        r=base.buscar(get_current_law_firm_id(), request.args.get('q') or '', escopo),
        resultado_labels=norm.RESULTADO_LABELS_CURTOS,
    )
