"""Renumeração determinística da impugnação gerada + guardas de costura.

Motivação (caso real de produção, 29/07/2026): a numeração dos headings era
responsabilidade dividida com o modelo (`merit_section_number` com default 3 +
headings numerados dentro de `preliminary_notes`). Quando o modelo não cumpre a
parte dele, a peça sai com "DA INSUFICIÊNCIA" sem número, "3. DO MÉRITO" como
primeira seção numerada e "PEDIDOS" sem número — e o histórico do prompt
(patch v2.5.1) mostra que instrução não basta. A numeração final passa a ser
do código: `to_full_text` monta o documento e este módulo renumera tudo em
sequência (1..N), reescreve subseções e corrige as remissões internas
("subtópicos 3.2, 3.3" → numeração nova).

Todas as funções são puras (texto → texto) para serem testáveis sem LLM.
"""
from __future__ import annotations

import re
import unicodedata

# Títulos canônicos das seções de 1º nível do esqueleto do escritório
# (Seção 4 do system prompt). Linhas em CAIXA ALTA que casem com um destes
# padrões são headings de 1º nível mesmo quando o modelo esqueceu o número.
_CANONICAL_TOP_LEVEL_PATTERNS = [
    r"(?:DAS?\s+)?PRELIMINARES\b",
    r"PEDIDOS?\s+RECONHECIDOS?\b",
    r"(?:DA\s+)?INSUFICI[ÊE]NCIA\s+T[ÉE]CNICA\b",
    r"PEDIDOS\s+IMPUGNADOS\s+PELA\s+UNI[ÃA]O\b",  # variante 5.4-B
    r"(?:DO\s+)?M[ÉE]RITO\b",
    r"(?:DOS\s+)?HONOR[ÁA]RIOS\b",
    r"(?:DA\s+)?REPETI[ÇC][ÃA]O\s+DO\s+IND[ÉE]BITO\b",
    r"(?:DOS\s+)?PEDIDOS\s*$",
]
_CANONICAL_TOP_LEVEL_RE = re.compile(
    "|".join(f"(?:{p})" for p in _CANONICAL_TOP_LEVEL_PATTERNS)
)

# Heading de 1º nível já numerado: "3. TÍTULO EM CAPS" (não casa "3.1. ...").
_NUMBERED_TOP_RE = re.compile(r"^(\s*)(#{1,3}\s*)?(\d{1,2})\.\s+(\S.*)$")
# Subseção numerada: "3.1. TÍTULO" (nível 2; sub-subseções não são tocadas).
_NUMBERED_SUB_RE = re.compile(r"^(\s*)(#{1,4}\s*)?(\d{1,2})\.(\d{1,2})\.\s+(\S.*)$")
# Heading canônico sem número.
_UNNUMBERED_TOP_RE = re.compile(r"^(\s*)(#{1,3}\s*)?([A-ZÀ-Ü].*)$")

# Remissões internas cujo alvo é uma subseção da própria peça.
_REMISSION_KEYWORD_RE = re.compile(
    r"(?i)\b(subt[óo]picos?|subitens?|t[óo]picos?|itens?|se[çc](?:[ãa]o|[õo]es))\s+"
    r"((?:\d{1,2}\.\d{1,2})(?:(?:\s*,\s*|\s+e\s+)\d{1,2}\.\d{1,2})*)"
)

_CLOSING_TAIL_RE = re.compile(
    r"(?:\n|\A)\s*Nestes\s+termos\s*[,.]?\s*(?:\n+\s*)?[Pp]ede(?:-se)?\s+deferimento\s*\.?\s*\Z",
    re.IGNORECASE,
)


def _strip_accents_upper(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).upper()


def _is_caps_title(text: str) -> bool:
    """Título "em CAIXA ALTA": as letras são ≥90% maiúsculas e há pelo menos 4."""
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 4:
        return False
    upper = sum(1 for ch in letters if ch.isupper())
    return upper / len(letters) >= 0.9


def _is_canonical_title(title: str) -> bool:
    return bool(_CANONICAL_TOP_LEVEL_RE.search(_strip_accents_upper(title.strip())))


def renumber_document(text: str) -> str:
    """Renumera as seções de 1º e 2º nível em sequência e corrige remissões.

    Regras:
    - Heading de 1º nível = linha CAPS já numerada ("3. TÍTULO"), ou linha CAPS
      sem número cujo título casa com o esqueleto canônico do escritório
      ("DA INSUFICIÊNCIA TÉCNICA...", "PEDIDOS", ...). A restrição ao canônico
      evita numerar CAPS soltos (endereçamento, células de tabela).
    - Numeração final é sequencial (1..N) na ordem de aparição; subseções são
      re-sequenciadas dentro da seção corrente (N.1, N.2, ...).
    - Remissões "subtópico(s)/item(ns)/seção(ões) X.Y" são reescritas pelo mapa
      antigo→novo. Números com outros formatos (leis "1.329/2017", artigos,
      CNPJ, nº de processo) nunca casam os padrões de heading/remissão.
    - Linhas de tabela (contêm "|") nunca são tratadas como heading.
    """
    if not text:
        return text

    lines = text.splitlines()
    top_counter = 0
    sub_counter = 0
    current_old_top: str | None = None
    sub_map: dict[str, str] = {}

    for idx, line in enumerate(lines):
        if "|" in line:
            continue

        numbered = _NUMBERED_TOP_RE.match(line)
        if numbered and _is_caps_title(numbered.group(4)):
            indent, hashes, _old, title = (
                numbered.group(1), numbered.group(2) or "", numbered.group(3), numbered.group(4)
            )
            top_counter += 1
            sub_counter = 0
            current_old_top = _old
            lines[idx] = f"{indent}{hashes}{top_counter}. {title}"
            continue

        sub = _NUMBERED_SUB_RE.match(line)
        if sub and _is_caps_title(sub.group(5)):
            indent, hashes, old_major, old_minor, title = (
                sub.group(1), sub.group(2) or "", sub.group(3), sub.group(4), sub.group(5)
            )
            if top_counter == 0:
                # Subseção antes de qualquer seção: não há onde ancorar; deixa como está.
                continue
            sub_counter += 1
            sub_map[f"{old_major}.{old_minor}"] = f"{top_counter}.{sub_counter}"
            lines[idx] = f"{indent}{hashes}{top_counter}.{sub_counter}. {title}"
            continue

        unnumbered = _UNNUMBERED_TOP_RE.match(line)
        if (
            unnumbered
            and _is_caps_title(unnumbered.group(3))
            and _is_canonical_title(unnumbered.group(3))
        ):
            indent, hashes, title = (
                unnumbered.group(1), unnumbered.group(2) or "", unnumbered.group(3).strip()
            )
            top_counter += 1
            sub_counter = 0
            current_old_top = None
            lines[idx] = f"{indent}{hashes}{top_counter}. {title}"
            continue

    del current_old_top  # usado apenas para clareza do fluxo acima

    result = "\n".join(lines)
    if text.endswith("\n") and not result.endswith("\n"):
        result += "\n"

    if sub_map:
        def _remap(match: re.Match) -> str:
            keyword, refs = match.group(1), match.group(2)
            remapped = re.sub(
                r"\d{1,2}\.\d{1,2}",
                lambda m: sub_map.get(m.group(0), m.group(0)),
                refs,
            )
            return f"{keyword} {remapped}"

        result = _REMISSION_KEYWORD_RE.sub(_remap, result)

    return result


def strip_trailing_closing(text: str) -> str:
    """Remove fecho ("Nestes termos, / Pede deferimento.") do FIM do campo.

    O fecho oficial vem sempre do campo `closing`; quando o modelo também o
    escreve no fim de `requests`, a peça sai com o fecho duplicado. Só remove
    no final do texto — "Nestes termos" em meio de frase fica intacto.
    """
    if not text:
        return text
    cleaned = text
    while True:
        stripped = _CLOSING_TAIL_RE.sub("", cleaned.rstrip())
        if stripped == cleaned.rstrip():
            return cleaned
        cleaned = stripped


def strip_leading_duplicate_heading(text: str, heading: str) -> str:
    """Remove do início do campo uma linha que duplica o título fixo da seção.

    O cabeçalho da subseção de compensação é adicionado pelo código; quando o
    modelo o repete como primeira linha do conteúdo, o título sai dobrado.
    """
    if not text:
        return text
    lines = text.lstrip().splitlines()
    if not lines:
        return text
    first = re.sub(r"^\s*(?:#{1,4}\s*)?(?:\d{1,2}(?:\.\d{1,2})?\.\s*)?", "", lines[0]).strip()
    target = _strip_accents_upper(re.sub(r"\s+", " ", heading)).strip()
    candidate = _strip_accents_upper(re.sub(r"\s+", " ", first)).strip(" .–-")
    if candidate and (candidate == target or candidate == target.rstrip(" .–-")):
        return "\n".join(lines[1:]).lstrip("\n")
    return text


# Padrões de material interno do escritório que jamais podem aparecer no corpo
# da peça (guia/system prompt, catálogo de teses, base de peças-modelo).
_INTERNAL_REFERENCE_PATTERNS = [
    (re.compile(r"cat[áa]logo\s+do\s+escrit[óo]rio", re.IGNORECASE), "catálogo do escritório"),
    (re.compile(r"\btese\s+\d{1,2}\.\d{1,2}\b", re.IGNORECASE), None),
    (re.compile(r"\bdeste\s+guia\b", re.IGNORECASE), "referência ao guia interno"),
    (re.compile(r"pe[çc]as?-modelo", re.IGNORECASE), "menção à base de peças-modelo"),
    (re.compile(r"system\s+prompt", re.IGNORECASE), "menção ao system prompt"),
]


def detect_internal_references(text: str) -> list[str]:
    """Detecta vazamentos de material interno no corpo da peça.

    Não edita o texto (editar prosa jurídica às cegas é arriscado): devolve
    notas para as Observações Internas, onde a expressão "revisão humana"
    já é destacada como alerta na tela.
    """
    if not text:
        return []
    notes: list[str] = []
    for pattern, label in _INTERNAL_REFERENCE_PATTERNS:
        for match in pattern.finditer(text):
            found = label or f'"{match.group(0)}"'
            notes.append(
                f"⚠️ Referência interna no corpo da peça ({found}) — reescrever o trecho "
                "sem mencionar material interno do escritório; revisão humana recomendada."
            )
            break  # uma nota por padrão basta
    return notes
