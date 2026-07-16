"""
Paginação das tools de listagem do MCP.

Toda listagem devolve uma janela (``limit``/``offset``) e diz honestamente se há
mais dados — o agente precisa saber que a resposta é parcial e como continuar,
senão conclui em cima de uma fatia achando que viu tudo.

**Ordenação estável é obrigatória.** Os dados vêm de sincronização em lote, então
empates no critério de ordenação são a regra, não a exceção (ex.: centenas de
benefícios com o mesmo ``created_at``). Sem um desempate único, o banco não
garante ordem entre iguais e a mesma linha pode aparecer em duas páginas enquanto
outra some. Por isso todo ``order_by`` paginado termina no ``id``.
"""

# Teto por página: acima disso a resposta enche o contexto do agente sem ajudar.
# Para volume, o caminho é exportar_*_excel (até 50 mil linhas).
MAX_LIMIT = 200


def clamp_limit(limit, default: int) -> int:
    """Limite válido: inteiro entre 1 e MAX_LIMIT."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return default
    if value < 1:
        return default
    return min(value, MAX_LIMIT)


def clamp_offset(offset) -> int:
    """Deslocamento válido: inteiro >= 0."""
    try:
        value = int(offset)
    except (TypeError, ValueError):
        return 0
    return max(value, 0)


def fetch_page(query, limit: int, offset: int):
    """Aplica a janela na query já ordenada."""
    return query.limit(limit).offset(offset).all()


def page_envelope(total: int, offset: int, itens: list) -> dict:
    """Resposta padrão das listagens.

    Mantém ``total_encontrado``/``retornados``/``itens`` (formato já consumido) e
    acrescenta o que torna o truncamento acionável: ``tem_mais`` e
    ``proximo_deslocamento``. As chaves seguem o português dos parâmetros das
    tools — a dica cita o nome exato do parâmetro a repetir.
    """
    tem_mais = (offset + len(itens)) < total
    envelope = {
        "total_encontrado": total,
        "retornados": len(itens),
        "deslocamento": offset,
        "tem_mais": tem_mais,
        "itens": itens,
    }
    if tem_mais:
        envelope["proximo_deslocamento"] = offset + len(itens)
        envelope["dica"] = (
            f"Resposta parcial: {len(itens)} de {total}. Para a próxima página, repita a "
            f"mesma busca com deslocamento={offset + len(itens)}. Antes de paginar, avalie: "
            f"para contagens/estatísticas use resumo_fap (uma chamada); para todos os "
            f"registros use a exportação em Excel; para achar um registro específico, "
            f"refine os filtros em vez de varrer as páginas."
        )
    return envelope
