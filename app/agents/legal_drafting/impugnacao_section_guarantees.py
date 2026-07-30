"""Garantias de seção da impugnação gerada — o código, não o modelo, garante:

1. **Tabela de benefícios por tese** (Seção 5.3 do padrão do escritório): alguns
   modelos omitem a tabela dentro do `argument` (comportamento observado e já
   registrado com gpt-5-mini). Quando o argumento de uma tese não traz tabela,
   ela é injetada logo após o heading, montada a partir dos benefícios REAIS
   das seleções (verdade do banco, não do modelo).
2. **Seção "DOS PEDIDOS RECONHECIDOS PELA UNIÃO"** (template 5.5): quando a
   Decisão da União de algum benefício indica reconhecimento ("exclusão
   aceita", "reconhecido") e o modelo não redigiu a seção, ela é inserida
   deterministicamente antes da "DA INSUFICIÊNCIA TÉCNICA", com a tabela dos
   benefícios reconhecidos e o pedido de homologação (art. 487, III, "a", CPC).

Funções puras (dicts/strings → strings), testáveis sem LLM e sem banco.
O dict de benefício esperado: {benefit_number, nit_number, insured_name,
benefit_type, fap_vigencia_year, thesis_name, status_label, decision}.
"""
from __future__ import annotations

import re
import unicodedata

# Reconhecimento pela União: positivo tem de casar E nenhum negativo pode casar.
_RECOGNIZED_POSITIVE_RE = re.compile(r"aceit|reconhec|homolog", re.IGNORECASE)
_RECOGNIZED_NEGATIVE_RE = re.compile(
    r"n[ãa]o\s+(?:se\s+|foi\s+)?(?:aceit|reconhec)|sem\s+reconhec|improced|recusa",
    re.IGNORECASE,
)

_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|.*\|", re.MULTILINE)

_INSUFICIENCIA_HEADING_RE = re.compile(
    r"^\s*(?:#{1,3}\s*)?(?:\d{1,2}\.\s*)?(?:DA\s+)?INSUFICI[ÊE]NCIA\s+T[ÉE]CNICA",
    re.IGNORECASE | re.MULTILINE,
)

_RECOGNIZED_HEADING_RE = re.compile(
    r"PEDIDOS?\s+RECONHECIDOS?", re.IGNORECASE
)


def _norm(text) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def _cell(value) -> str:
    text = str(value or "").strip() or "—"
    return text.replace("|", "/")


def benefit_table_markdown(benefits: list[dict], include_thesis: bool = False) -> str:
    """Tabela padrão de identificação de benefícios (colunas com dado real).

    O padrão 5.3 completo do escritório inclui CNPJ e CAT/DIB/DCB, que não
    existem no cadastro do benefício — a tabela injetada usa as colunas com
    dado verdadeiro em vez de inventar/placeholder.
    """
    if not benefits:
        return ""
    headers = ["NB", "NIT", "Segurado", "Tipo", "Vigência FAP"]
    if include_thesis:
        headers.append("Tese")
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for benefit in benefits:
        row = [
            _cell(benefit.get("benefit_number")),
            _cell(benefit.get("nit_number")),
            _cell(benefit.get("insured_name")),
            _cell(benefit.get("benefit_type")),
            _cell(benefit.get("fap_vigencia_year")),
        ]
        if include_thesis:
            row.append(_cell(benefit.get("thesis_name")))
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def argument_has_table(argument: str) -> bool:
    return bool(_TABLE_ROW_RE.search(argument or ""))


def ensure_benefit_table_in_argument(
    argument: str, benefits: list[dict]
) -> tuple[str, bool]:
    """Injeta a tabela da tese logo após o heading quando o argumento não tem.

    Retorna (argumento_final, foi_injetada). Argumento que já contém qualquer
    tabela fica intacto — o modelo obedeceu e não vamos duplicar.
    """
    if not argument or not benefits or argument_has_table(argument):
        return argument, False

    table = benefit_table_markdown(benefits)
    lines = argument.splitlines()
    # O heading da tese é a primeira linha ("N.i. TÍTULO", contrato do schema).
    insert_at = 1 if lines else 0
    new_lines = lines[:insert_at] + ["", table] + lines[insert_at:]
    return "\n".join(new_lines), True


def detect_recognized_selections(benefits: list[dict]) -> list[dict]:
    """Benefícios cuja Decisão da União indica reconhecimento do pedido."""
    recognized = []
    for benefit in benefits:
        signal = f"{benefit.get('status_label') or ''} {benefit.get('decision') or ''}"
        if not signal.strip():
            continue
        if _RECOGNIZED_NEGATIVE_RE.search(signal):
            continue
        if _RECOGNIZED_POSITIVE_RE.search(signal):
            recognized.append(benefit)
    return recognized


def build_recognized_section_text(recognized: list[dict]) -> str:
    """Seção "DOS PEDIDOS RECONHECIDOS PELA UNIÃO" no template 5.5.

    Sem número no heading — a renumeração determinística atribui a posição.
    """
    if not recognized:
        return ""
    plural = len(recognized) > 1
    table = benefit_table_markdown(recognized, include_thesis=True)
    registro = "dos seguintes registros" if plural else "do seguinte registro"
    return (
        "DOS PEDIDOS RECONHECIDOS PELA UNIÃO\n\n"
        f"Em contestação, a União reconheceu a impropriedade {registro}, "
        "admitindo o equívoco na sua imputação como insumo do índice:\n\n"
        f"{table}\n\n"
        "Diante disso, requer-se a homologação do reconhecimento formulado pela União, "
        "com a consequente extinção parcial do processo, com resolução de mérito, nos "
        'termos do art. 487, III, "a", do CPC, bem como a condenação da Ré ao pagamento '
        "dos ônus sucumbenciais correspondentes ao pedido reconhecido."
    )


def insert_recognized_section(preliminary_notes: str, section_text: str) -> str:
    """Insere a seção de reconhecidos antes da "DA INSUFICIÊNCIA TÉCNICA".

    - Se o texto já contém heading de pedidos reconhecidos (o modelo redigiu),
      não faz nada — nunca duplicar.
    - Sem heading de insuficiência, a seção entra no início do bloco.
    """
    notes = preliminary_notes or ""
    if not section_text:
        return notes
    if _RECOGNIZED_HEADING_RE.search(notes):
        return notes

    match = _INSUFICIENCIA_HEADING_RE.search(notes)
    if match:
        pos = match.start()
        return notes[:pos].rstrip() + ("\n\n" if notes[:pos].strip() else "") \
            + section_text + "\n\n" + notes[pos:]
    if notes.strip():
        return section_text + "\n\n" + notes
    return section_text
