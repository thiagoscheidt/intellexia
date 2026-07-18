"""Painel FAP como MCP App.

Único módulo que importa Prefab. Funções puras sobre o dicionário
devolvido por ``fap_summary_handler`` — nenhuma query, nenhum contexto Flask.
"""

from prefab_ui.components import Card, Grid, Metric, Page
from prefab_ui.components.charts import BarChart, ChartSeries

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
    if filtros.get("empresa"):
        recorte.append(f"empresa {filtros['empresa']}")
    return recorte


def _descricao_cobertura_topico(ben: dict) -> str:
    """Descrição honesta de cobertura para "Benefícios por tópico".

    ``com_topico_contestacao`` é a contagem exata de benefícios distintos com
    ao menos um tópico — vem do mesmo loop que monta ``por_topico_contestacao``
    em ``fap_summary_handler`` (nenhuma query nova). É diferente da soma das
    contagens por tópico: essa soma superestima quando um benefício tem mais
    de um tópico simultâneo. O denominador (total de benefícios) é mantido no
    rótulo de propósito — sem ele, o leitor conclui que a classificação é
    completa quando pode não ser.

    Dados de uma versão anterior podem não ter a chave nova; nesse caso caímos
    de volta para "0" em vez de quebrar o painel.
    """
    total = ben.get("total", 0)
    com_topico = ben.get("com_topico_contestacao")
    if com_topico is None:
        com_topico = 0
    return f"{com_topico} de {total} benefícios têm tópico classificado"


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
        _linha("Benefícios por tópico", ben.get("por_topico_contestacao") or {})
        + f" ({_descricao_cobertura_topico(ben)})",
        _linha("Benefícios 1ª instância", ben.get("por_status_primeira_instancia") or {}),
        _linha("Benefícios 2ª instância", ben.get("por_status_segunda_instancia") or {}),
    ])


def _barras(titulo: str, contagens: dict, descricao: str | None = None) -> Card:
    """Um cartão com barras horizontais de uma dimensão do resumo.

    ``descricao`` vai no Metric do cartão — usado quando o número de cima
    precisa de contexto para não ser lido como algo que não é (ex.: soma de
    marcações por tópico, não contagem de benefícios).
    """
    top = top_n(contagens)
    dados = [{"rotulo": k, "qtd": v} for k, v in top]
    return Card(children=[
        Metric(label=titulo, value=sum(v for _, v in top), description=descricao),
        BarChart(
            data=dados or [{"rotulo": "sem dados", "qtd": 0}],
            series=[ChartSeries(data_key="qtd", label="Quantidade")],
            x_axis="rotulo",
            horizontal=True,
            show_legend=False,
            height=240,
        ),
    ])


def construir_painel(dados: dict) -> Page:
    """Monta o painel visual a partir do dicionário de ``fap_summary_handler``."""
    filtros = dados.get("filtros") or {}
    cont = dados.get("contestacoes") or {}
    ben = dados.get("beneficios") or {}
    fin = ben.get("financeiro") or {}

    recorte = _recorte_dos_filtros(filtros)
    titulo = "Painel FAP" + (f" — {', '.join(recorte)}" if recorte else " — sem filtros")

    cards = Grid(children=[
        Metric(label="Contestações", value=cont.get("total", 0)),
        Metric(label="Benefícios", value=ben.get("total", 0)),
        Metric(
            label="Total pago",
            value=_moeda(fin.get("total_pago_soma", 0.0)),
            description=f"{fin.get('beneficios_com_valor_informado', 0)} com valor informado",
        ),
        Metric(
            label="Com CAT",
            value=ben.get("com_cat", 0),
            description=f"{ben.get('sem_cat', 0)} sem CAT",
        ),
    ])

    return Page(title=titulo, children=[
        cards,
        _barras("Contestações por situação", cont.get("por_situacao") or {}),
        _barras("Contestações por ano de vigência", cont.get("por_ano_vigencia") or {}),
        _barras("Contestações por empresa", cont.get("por_empresa") or {}),
        _barras(
            "Benefícios por tópico",
            ben.get("por_topico_contestacao") or {},
            _descricao_cobertura_topico(ben),
        ),
        _barras("Benefícios — 1ª instância", ben.get("por_status_primeira_instancia") or {}),
        _barras("Benefícios — 2ª instância", ben.get("por_status_segunda_instancia") or {}),
    ])
