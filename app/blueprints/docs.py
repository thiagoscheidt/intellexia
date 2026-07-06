"""
Blueprint de documentação / manuais internos.

Serve a página estática de manuais dos painéis (``docs/manual_paineis.html``)
por uma URL amigável. Exige apenas autenticação — o prefixo ``docs.`` não está
mapeado a nenhum módulo de permissão, então qualquer usuário logado acessa.
"""
from flask import Blueprint, render_template, request, jsonify, session

docs_bp = Blueprint('docs', __name__, url_prefix='/docs')

# Instância única do assistente (compartilha o cache dos manuais). Criada de forma
# preguiçosa para não construir o cliente LLM no import do blueprint.
_assistant = None


def _get_assistant():
    global _assistant
    if _assistant is None:
        from app.services.manual_assistant_service import ManualAssistantService
        _assistant = ManualAssistantService()
    return _assistant


@docs_bp.route('/manuais')
def manuais():
    """Manual de uso dos painéis, renderizado a partir dos markdowns em docs/.

    Fonte única: ``docs/MANUAL_*.md`` — os mesmos arquivos que o assistente lê.
    O HTML é gerado em runtime (com cache por data de modificação), então editar
    o markdown é suficiente; nada precisa ser gerado manualmente.
    """
    from app.services.manual_renderer import render_modules
    return render_template('docs/manuais.html', modules=render_modules())


@docs_bp.route('/chat', methods=['POST'])
def chat():
    """Assistente do manual: responde dúvidas com base nos manuais dos painéis."""
    data = request.get_json(silent=True) or {}
    message = str(data.get('message') or '').strip()
    history = data.get('history')
    if not message:
        return jsonify({'error': 'Mensagem é obrigatória.'}), 400
    if not isinstance(history, list):
        history = []

    result = _get_assistant().answer(
        message,
        history,
        user_id=session.get('user_id'),
        law_firm_id=session.get('law_firm_id'),
    )
    return jsonify({'reply': result.get('reply', ''), 'ok': bool(result.get('ok'))})
