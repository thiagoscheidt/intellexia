from flask import session


def generate_chat_title_from_question(question: str) -> str:
    """Gera um título curto e legível para o chat com base na pergunta."""
    if not question:
        return 'Novo chat'

    cleaned = " ".join(question.strip().split())
    if not cleaned:
        return 'Novo chat'

    max_len = 80
    if len(cleaned) <= max_len:
        return cleaned
    return f"{cleaned[:max_len].rstrip()}..."


def get_current_law_firm_id():
    """Retorna o ID do escritório do usuário logado."""
    return session.get('law_firm_id')


def get_current_user_id():
    """Retorna o ID do usuário logado."""
    return session.get('user_id')
