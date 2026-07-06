"""
Blueprint de documentação / manuais internos.

Serve a página estática de manuais dos painéis (``docs/manual_paineis.html``)
por uma URL amigável. Exige apenas autenticação — o prefixo ``docs.`` não está
mapeado a nenhum módulo de permissão, então qualquer usuário logado acessa.
"""
import os

from flask import Blueprint, send_file, abort

docs_bp = Blueprint('docs', __name__, url_prefix='/docs')

# Raiz do projeto: .../app/blueprints/docs.py -> sobe 3 níveis
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MANUAL_PATH = os.path.join(_PROJECT_ROOT, 'docs', 'manual_paineis.html')


@docs_bp.route('/manuais')
def manuais():
    """Manual de uso dos painéis (Dashboard, Painel FAP, Painel de Contestações)."""
    if not os.path.exists(_MANUAL_PATH):
        abort(404)
    return send_file(_MANUAL_PATH, mimetype='text/html')
