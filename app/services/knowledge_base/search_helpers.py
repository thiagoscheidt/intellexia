import re
import unicodedata


def highlight_search_terms(text: str, search_query: str) -> str:
    """Destaca os termos da busca no texto com markup HTML."""
    if not search_query or not text:
        return text

    search_terms = search_query.strip().split()
    search_terms = [term for term in search_terms if len(term) > 2]

    highlighted_text = text
    for term in search_terms:
        escaped_term = re.escape(term)
        pattern = re.compile(f'({escaped_term})', re.IGNORECASE)
        highlighted_text = pattern.sub(r'<mark class="highlight-term">\1</mark>', highlighted_text)

    return highlighted_text


def looks_like_name_query(query: str) -> bool:
    """Heurística simples para identificar buscas com cara de nome de pessoa."""
    if not query:
        return False

    normalized_query = " ".join(query.strip().split())
    if len(normalized_query) < 4:
        return False

    parts = normalized_query.split(" ")
    if len(parts) < 2 or len(parts) > 5:
        return False

    disallowed_tokens = {
        'fap', 'inss', 'processo', 'acidente', 'trabalho', 'benefício',
        'petição', 'recurso', 'sentença', 'lei', 'decreto', 'portaria'
    }

    alpha_parts = 0
    for part in parts:
        cleaned = re.sub(r"[^a-zA-ZÀ-ÿ]", "", part).lower()
        if not cleaned:
            continue
        if cleaned in disallowed_tokens:
            return False
        if len(cleaned) >= 2:
            alpha_parts += 1

    return alpha_parts >= 2


def normalize_for_match(value: str) -> str:
    """Normaliza texto para comparação robusta (acentos, pontuação e espaços)."""
    if not value:
        return ""

    normalized = unicodedata.normalize('NFKD', value)
    normalized = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r'[^a-z0-9\s]', ' ', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized


def name_tokens(query: str):
    """Extrai tokens relevantes de nome, removendo conectores comuns."""
    ignored = {'de', 'da', 'do', 'dos', 'das', 'e'}
    normalized_query = normalize_for_match(query)
    return [token for token in normalized_query.split(' ') if token and token not in ignored and len(token) >= 2]
