"""Painel FAP como MCP App.

Único módulo que importa Prefab. Duas funções puras sobre o dicionário
devolvido por ``fap_summary_handler`` — nenhuma query, nenhum contexto Flask.
"""

TOP_N = 8


def top_n(contagens: dict, n: int = TOP_N) -> list[tuple[str, int]]:
    """Os ``n`` maiores, seguidos de uma faixa "outros (N)" quando há resto.

    O rótulo do resto é explícito de propósito: corte silencioso lê como
    cobertura completa.
    """
    ordenado = sorted(contagens.items(), key=lambda kv: -kv[1])
    if len(ordenado) <= n:
        return ordenado
    resto = ordenado[n:]
    return ordenado[:n] + [(f"outros ({len(resto)})", sum(v for _, v in resto))]


def _recorte_dos_filtros(filtros: dict) -> list[str]:
    """Descreve os filtros aplicados, em texto — usado no cabeçalho do resumo.

    Compartilhado com o Prefab (Task 3): mesmo recorte, duas saídas.
    """
    recorte = []
    if filtros.get("ano_vigencia"):
        recorte.append(f"vigência {filtros['ano_vigencia']}")
    if filtros.get("cnpj"):
        recorte.append(f"CNPJ {filtros['cnpj']}")
    return recorte


def _linha(titulo: str, contagens: dict) -> str:
    if not contagens:
        return f"{titulo}: —"
    partes = ", ".join(f"{k}: {v}" for k, v in top_n(contagens))
    return f"{titulo}: {partes}"


def _moeda(valor: float) -> str:
    """Formata em Real no padrão pt-BR: R$ 12.345,67."""
    inteiro = f"{valor:,.2f}"
    return "R$ " + inteiro.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def resumo_em_texto(dados: dict) -> str:
    """Resumo textual do painel, para host que não renderiza MCP Apps.

    O envelope Prefab ocupa ``structured_content``, então este texto é a única
    coisa que um cliente sem suporte a MCP Apps enxerga.
    """
    filtros = dados.get("filtros") or {}
    cont = dados.get("contestacoes") or {}
    ben = dados.get("beneficios") or {}
    fin = ben.get("financeiro") or {}

    recorte = _recorte_dos_filtros(filtros)
    cabecalho = "Painel FAP" + (f" ({', '.join(recorte)})" if recorte else " (sem filtros)")

    return "\n".join([
        cabecalho,
        f"Contestações: {cont.get('total', 0)} | Benefícios: {ben.get('total', 0)}"
        f" | Total pago: {_moeda(fin.get('total_pago_soma', 0.0))}"
        f" | Com CAT: {ben.get('com_cat', 0)}, sem CAT: {ben.get('sem_cat', 0)}",
        _linha("Contestações por situação", cont.get("por_situacao") or {}),
        _linha("Contestações por ano", cont.get("por_ano_vigencia") or {}),
        _linha("Contestações por empresa", cont.get("por_empresa") or {}),
        _linha("Benefícios por tópico", ben.get("por_topico_contestacao") or {}),
        _linha("Benefícios 1ª instância", ben.get("por_status_primeira_instancia") or {}),
        _linha("Benefícios 2ª instância", ben.get("por_status_segunda_instancia") or {}),
    ])
