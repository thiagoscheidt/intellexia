# Painel FAP como MCP App — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expor o resumo estatístico do FAP como painel visual dentro da conversa do Claude, via MCP Apps, reusando `fap_summary_handler` sem alterar nenhuma tool existente.

**Architecture:** Um módulo novo (`mcp_server/apps/fap_panel.py`) concentra todo contato com Prefab em duas funções puras — uma monta o componente, outra gera o resumo textual de fallback. Uma tool nova em `server.py` liga o handler existente a essas funções via `ToolResult`. Nada mais é tocado.

**Tech Stack:** Python 3.12, FastMCP 3.2.4 (extra `apps`), prefab-ui 0.20.2, SQLAlchemy/Flask (contexto existente), `uv`.

## Global Constraints

- **Não alterar** `fap_summary_handler` (`mcp_server/tools/fap.py:472`), `resumo_fap` (`mcp_server/server.py:466`), nem qualquer tela de `/fap-panel`.
- **Não escrever query nova.** Todo dado vem de `fap_summary_handler`.
- `fastmcp` permanece em **3.2.4** — o extra `apps` resolve nessa versão, nenhum upgrade é permitido neste trabalho.
- `prefab-ui` pinado em **versão exata** (`==0.20.2`) no `pyproject.toml`.
- Permissão da tool nova: `require_module("fap_panel")`, idêntica à de `resumo_fap`.
- Multi-tenancy: `law_firm_id` sempre vem de `claims["law_firm_id"]`, nunca de argumento da tool.
- Top-N de tópicos e empresas: **8 maiores** + faixa `outros (N)` rotulada. Nunca cortar em silêncio.
- Dependência de `uv`: usar `uv add` / `uv run`, nunca `pip`.
- Testes são scripts standalone executáveis (`uv run python tests/...`), no padrão de `tests/test_mcp_fap_review.py`.

---

## File Structure

- **Create:** `mcp_server/apps/__init__.py` — pacote vazio.
- **Create:** `mcp_server/apps/fap_panel.py` — único arquivo que importa Prefab. Duas funções puras: `construir_painel(dados)` e `resumo_em_texto(dados)`.
- **Create:** `tests/test_mcp_fap_panel.py` — script standalone cobrindo builder, top-N, vazio, fallback e isolamento.
- **Modify:** `pyproject.toml` — extra `apps` + pin de `prefab-ui`.
- **Modify:** `mcp_server/server.py` — registro da tool `painel_fap`, com import isolado.

---

### Task 1: Dependência com pin exato

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: nada.
- Produces: `prefab_ui` e `fastmcp.apps` importáveis no venv do projeto.

- [ ] **Step 1: Verificar que Prefab ainda NÃO está disponível**

```bash
uv run python -c "import prefab_ui" 2>&1 | tail -1
```

Expected: `ModuleNotFoundError: No module named 'prefab_ui'`

- [ ] **Step 2: Adicionar o extra e o pin**

Em `pyproject.toml`, na lista `dependencies`, trocar a linha `"fastmcp>=2.0.0",` por estas duas:

```toml
    "fastmcp[apps]>=2.0.0",
    "prefab-ui==0.20.2",
```

O pin exato é exigido pela documentação do FastMCP: Prefab tem breaking changes frequentes e o FastMCP não fixa limite superior.

- [ ] **Step 3: Sincronizar**

```bash
uv sync
```

- [ ] **Step 4: Verificar que a versão do FastMCP não mudou e o Prefab entrou**

```bash
uv run python -c "
import fastmcp, prefab_ui
print('fastmcp', fastmcp.__version__)
from prefab_ui.components import Page, Metric, Card
from prefab_ui.components.charts import BarChart, ChartSeries
print('prefab ok')
"
```

Expected: `fastmcp 3.2.4` seguido de `prefab ok`. Se a versão do FastMCP tiver mudado, PARE — a constraint global foi violada.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: fastmcp[apps] + prefab-ui pinado para o painel FAP"
```

---

### Task 2: Resumo textual (fallback)

Esta task vem antes do componente de propósito: é a parte que não depende de Prefab, e entrega sozinha a garantia de degradação.

**Files:**
- Create: `mcp_server/apps/__init__.py`
- Create: `mcp_server/apps/fap_panel.py`
- Create: `tests/test_mcp_fap_panel.py`

**Interfaces:**
- Consumes: o dicionário devolvido por `fap_summary_handler` — formato:
  ```python
  {
      "filtros": {"ano_vigencia": int | None, "cnpj": str | None},
      "contestacoes": {
          "total": int,
          "por_ano_vigencia": dict[str, int],
          "por_situacao": dict[str, int],
          "por_instancia": dict[str, int],
          "por_empresa": dict[str, int],
      },
      "beneficios": {
          "total": int,
          "por_tipo": dict[str, int],
          "por_tipo_pedido": dict[str, int],
          "por_status_primeira_instancia": dict[str, int],
          "por_status_segunda_instancia": dict[str, int],
          "por_topico_contestacao": dict[str, int],
          "financeiro": {"total_pago_soma": float, "beneficios_com_valor_informado": int},
          "com_cat": int,
          "sem_cat": int,
      },
  }
  ```
- Produces: `resumo_em_texto(dados: dict) -> str` e `top_n(contagens: dict[str, int], n: int = 8) -> list[tuple[str, int]]`, ambos em `mcp_server/apps/fap_panel.py`.

- [ ] **Step 1: Criar o pacote**

Criar `mcp_server/apps/__init__.py` vazio (arquivo de zero bytes).

- [ ] **Step 2: Escrever o teste que falha**

Criar `tests/test_mcp_fap_panel.py`:

```python
#!/usr/bin/env python3
"""
Teste do painel FAP (MCP App).

    uv run python tests/test_mcp_fap_panel.py

Cobre:
  1. top_n — corte nos 8 maiores com faixa "outros (N)" rotulada
  2. resumo_em_texto — fallback para host que não renderiza MCP Apps
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.apps.fap_panel import resumo_em_texto, top_n

FIXTURE = {
    "filtros": {"ano_vigencia": 2023, "cnpj": None},
    "contestacoes": {
        "total": 12,
        "por_ano_vigencia": {"2023": 12},
        "por_situacao": {"Deferida": 7, "Indeferida": 5},
        "por_instancia": {"1ª": 12},
        "por_empresa": {"Bistek": 8, "Acme": 4},
    },
    "beneficios": {
        "total": 30,
        "por_tipo": {"B91": 20, "B94": 10},
        "por_tipo_pedido": {"Exclusão": 30},
        "por_status_primeira_instancia": {"Deferido": 18, "Indeferido": 12},
        "por_status_segunda_instancia": {"(vazio)": 30},
        "por_topico_contestacao": {"ACIDENTE DE TRAJETO": 15, "PRÉ-FAP": 9},
        "financeiro": {"total_pago_soma": 12345.67, "beneficios_com_valor_informado": 25},
        "com_cat": 22,
        "sem_cat": 8,
    },
}


def test_top_n_corta_e_rotula_o_resto():
    contagens = {f"T{i}": 10 - i for i in range(12)}
    resultado = top_n(contagens, n=8)

    assert len(resultado) == 9, f"esperado 8 + faixa outros, veio {len(resultado)}"
    rotulo, valor = resultado[-1]
    assert rotulo == "outros (4)", f"faixa mal rotulada: {rotulo}"
    assert valor == sum(v for _, v in list(contagens.items())[8:])
    assert sum(v for _, v in resultado) == sum(contagens.values()), "soma não fecha"
    print("OK  top_n corta nos 8 maiores e rotula o restante")


def test_top_n_nao_corta_quando_cabe():
    contagens = {"A": 3, "B": 2}
    assert top_n(contagens, n=8) == [("A", 3), ("B", 2)]
    print("OK  top_n não inventa faixa quando tudo cabe")


def test_resumo_em_texto_traz_os_totais():
    texto = resumo_em_texto(FIXTURE)

    assert "12" in texto, "total de contestações ausente"
    assert "30" in texto, "total de benefícios ausente"
    assert "Deferida" in texto, "situação ausente"
    assert "ACIDENTE DE TRAJETO" in texto, "tópico ausente"
    assert "2023" in texto, "filtro de vigência ausente"
    print("OK  resumo_em_texto traz totais, dimensões e filtros")


def test_resumo_em_texto_com_escritorio_vazio():
    vazio = {
        "filtros": {"ano_vigencia": None, "cnpj": None},
        "contestacoes": {"total": 0, "por_ano_vigencia": {}, "por_situacao": {},
                         "por_instancia": {}, "por_empresa": {}},
        "beneficios": {"total": 0, "por_tipo": {}, "por_tipo_pedido": {},
                       "por_status_primeira_instancia": {},
                       "por_status_segunda_instancia": {},
                       "por_topico_contestacao": {},
                       "financeiro": {"total_pago_soma": 0.0,
                                      "beneficios_com_valor_informado": 0},
                       "com_cat": 0, "sem_cat": 0},
    }
    texto = resumo_em_texto(vazio)
    assert isinstance(texto, str) and texto.strip(), "resumo vazio não pode ser string vazia"
    print("OK  resumo_em_texto sobrevive a escritório sem dado")


if __name__ == "__main__":
    test_top_n_corta_e_rotula_o_resto()
    test_top_n_nao_corta_quando_cabe()
    test_resumo_em_texto_traz_os_totais()
    test_resumo_em_texto_com_escritorio_vazio()
    print("\nTodos os testes passaram.")
```

- [ ] **Step 3: Rodar e ver falhar**

```bash
uv run python tests/test_mcp_fap_panel.py
```

Expected: FAIL com `ModuleNotFoundError: No module named 'mcp_server.apps.fap_panel'`

- [ ] **Step 4: Implementar o mínimo**

Criar `mcp_server/apps/fap_panel.py`:

```python
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


def _linha(titulo: str, contagens: dict) -> str:
    if not contagens:
        return f"{titulo}: —"
    partes = ", ".join(f"{k}: {v}" for k, v in top_n(contagens))
    return f"{titulo}: {partes}"


def resumo_em_texto(dados: dict) -> str:
    """Resumo textual do painel, para host que não renderiza MCP Apps.

    O envelope Prefab ocupa ``structured_content``, então este texto é a única
    coisa que um cliente sem suporte a MCP Apps enxerga.
    """
    filtros = dados.get("filtros") or {}
    cont = dados.get("contestacoes") or {}
    ben = dados.get("beneficios") or {}
    fin = ben.get("financeiro") or {}

    recorte = []
    if filtros.get("ano_vigencia"):
        recorte.append(f"vigência {filtros['ano_vigencia']}")
    if filtros.get("cnpj"):
        recorte.append(f"CNPJ {filtros['cnpj']}")
    cabecalho = "Painel FAP" + (f" ({', '.join(recorte)})" if recorte else " (sem filtros)")

    return "\n".join([
        cabecalho,
        f"Contestações: {cont.get('total', 0)} | Benefícios: {ben.get('total', 0)}"
        f" | Total pago: R$ {fin.get('total_pago_soma', 0.0):,.2f}"
        f" | Com CAT: {ben.get('com_cat', 0)}, sem CAT: {ben.get('sem_cat', 0)}",
        _linha("Contestações por situação", cont.get("por_situacao") or {}),
        _linha("Contestações por ano", cont.get("por_ano_vigencia") or {}),
        _linha("Contestações por empresa", cont.get("por_empresa") or {}),
        _linha("Benefícios por tópico", ben.get("por_topico_contestacao") or {}),
        _linha("Benefícios 1ª instância", ben.get("por_status_primeira_instancia") or {}),
        _linha("Benefícios 2ª instância", ben.get("por_status_segunda_instancia") or {}),
    ])
```

- [ ] **Step 5: Rodar e ver passar**

```bash
uv run python tests/test_mcp_fap_panel.py
```

Expected: quatro linhas `OK` e `Todos os testes passaram.`

- [ ] **Step 6: Commit**

```bash
git add mcp_server/apps/__init__.py mcp_server/apps/fap_panel.py tests/test_mcp_fap_panel.py
git commit -m "feat(mcp): resumo textual do painel FAP com top-N rotulado"
```

---

### Task 3: Componente Prefab

**Files:**
- Modify: `mcp_server/apps/fap_panel.py`
- Modify: `tests/test_mcp_fap_panel.py`

**Interfaces:**
- Consumes: `top_n(contagens, n=8)` da Task 2; o mesmo dicionário de `fap_summary_handler`.
- Produces: `construir_painel(dados: dict) -> Page` em `mcp_server/apps/fap_panel.py`.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/test_mcp_fap_panel.py`, trocar a linha de import por:

```python
from mcp_server.apps.fap_panel import construir_painel, resumo_em_texto, top_n
```

e acrescentar, antes do bloco `if __name__ == "__main__":`:

```python
def test_construir_painel_serializa_com_os_numeros():
    painel = construir_painel(FIXTURE)
    bruto = painel.model_dump_json()

    assert painel.title, "painel sem título"
    assert "12" in bruto, "total de contestações ausente no componente"
    assert "30" in bruto, "total de benefícios ausente no componente"
    assert "Deferida" in bruto, "série de situação ausente"
    assert "ACIDENTE DE TRAJETO" in bruto, "série de tópicos ausente"
    print("OK  construir_painel serializa com os números do fixture")


def test_construir_painel_com_escritorio_vazio():
    vazio = {
        "filtros": {"ano_vigencia": None, "cnpj": None},
        "contestacoes": {"total": 0, "por_ano_vigencia": {}, "por_situacao": {},
                         "por_instancia": {}, "por_empresa": {}},
        "beneficios": {"total": 0, "por_tipo": {}, "por_tipo_pedido": {},
                       "por_status_primeira_instancia": {},
                       "por_status_segunda_instancia": {},
                       "por_topico_contestacao": {},
                       "financeiro": {"total_pago_soma": 0.0,
                                      "beneficios_com_valor_informado": 0},
                       "com_cat": 0, "sem_cat": 0},
    }
    painel = construir_painel(vazio)
    assert painel.model_dump_json(), "componente vazio não serializa"
    print("OK  construir_painel sobrevive a escritório sem dado")
```

e registrar as duas no bloco `__main__`, logo antes do `print` final:

```python
    test_construir_painel_serializa_com_os_numeros()
    test_construir_painel_com_escritorio_vazio()
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
uv run python tests/test_mcp_fap_panel.py
```

Expected: FAIL com `ImportError: cannot import name 'construir_painel'`

- [ ] **Step 3: Implementar**

No topo de `mcp_server/apps/fap_panel.py`, logo abaixo do docstring, acrescentar os imports:

```python
from prefab_ui.components import Card, Grid, Metric, Page
from prefab_ui.components.charts import BarChart, ChartSeries
```

E ao final do arquivo, acrescentar:

```python
def _barras(titulo: str, contagens: dict) -> Card:
    """Um cartão com barras horizontais de uma dimensão do resumo."""
    dados = [{"rotulo": k, "qtd": v} for k, v in top_n(contagens)]
    return Card(children=[
        Metric(label=titulo, value=sum(v for _, v in top_n(contagens))),
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

    recorte = []
    if filtros.get("ano_vigencia"):
        recorte.append(f"vigência {filtros['ano_vigencia']}")
    if filtros.get("cnpj"):
        recorte.append(f"CNPJ {filtros['cnpj']}")
    titulo = "Painel FAP" + (f" — {', '.join(recorte)}" if recorte else " — sem filtros")

    cards = Grid(children=[
        Metric(label="Contestações", value=cont.get("total", 0)),
        Metric(label="Benefícios", value=ben.get("total", 0)),
        Metric(
            label="Total pago",
            value=f"R$ {fin.get('total_pago_soma', 0.0):,.2f}",
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
        _barras("Benefícios por tópico", ben.get("por_topico_contestacao") or {}),
        _barras("Benefícios — 1ª instância", ben.get("por_status_primeira_instancia") or {}),
        _barras("Benefícios — 2ª instância", ben.get("por_status_segunda_instancia") or {}),
    ])
```

- [ ] **Step 4: Rodar e ver passar**

```bash
uv run python tests/test_mcp_fap_panel.py
```

Expected: seis linhas `OK` e `Todos os testes passaram.`

- [ ] **Step 5: Commit**

```bash
git add mcp_server/apps/fap_panel.py tests/test_mcp_fap_panel.py
git commit -m "feat(mcp): componente Prefab do painel FAP"
```

---

### Task 4: Tool `painel_fap` com import isolado

**Files:**
- Modify: `mcp_server/server.py` (após `resumo_fap`, que termina na linha 488)
- Modify: `tests/test_mcp_fap_panel.py`

**Interfaces:**
- Consumes: `construir_painel(dados)` e `resumo_em_texto(dados)` das Tasks 2–3; `fap_summary_handler(law_firm_id, ano_vigencia, cnpj, empresa)`, já importado em `server.py`.
- Produces: tool MCP `painel_fap(ano_vigencia, cnpj, empresa) -> ToolResult`.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/test_mcp_fap_panel.py`, acrescentar antes do bloco `__main__`:

```python
def test_tool_registrada_no_servidor():
    """painel_fap aparece no catálogo, sem derrubar as tools existentes."""
    import asyncio

    import fastmcp

    from mcp_server.server import mcp

    async def chamar():
        async with fastmcp.Client(mcp) as cliente:
            ferramentas = {t.name for t in await cliente.list_tools()}
            assert "painel_fap" in ferramentas, "tool painel_fap não registrada"

    asyncio.run(chamar())
    print("OK  painel_fap registrada no servidor MCP")


def test_tool_monta_resposta_com_os_dois_canais():
    from fastmcp.tools.tool import ToolResult

    from mcp_server.apps.fap_panel import construir_painel, resumo_em_texto

    resultado = ToolResult(
        content=resumo_em_texto(FIXTURE),
        structured_content=construir_painel(FIXTURE),
    )
    bloco = resultado.to_mcp_result()[0][0]

    assert "$prefab" in str(resultado.structured_content), "envelope Prefab ausente"
    assert "Contestações" in bloco.text, "fallback textual ausente"
    print("OK  resposta carrega envelope Prefab e fallback textual juntos")
```

e registrar as duas no bloco `__main__`:

```python
    test_tool_registrada_no_servidor()
    test_tool_monta_resposta_com_os_dois_canais()
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
uv run python tests/test_mcp_fap_panel.py
```

Expected: FAIL com `AssertionError: tool painel_fap não registrada`

- [ ] **Step 3: Implementar**

Em `mcp_server/server.py`, logo após o fim de `resumo_fap` (linha 488) e antes do próximo `@mcp.tool()`, inserir:

```python
try:
    from fastmcp.tools.tool import ToolResult

    from mcp_server.apps.fap_panel import construir_painel, resumo_em_texto
except ImportError as exc:  # pragma: no cover - depende de extra opcional
    logging.getLogger(__name__).warning(
        "Painel FAP indisponível (%s) — tool painel_fap não registrada; "
        "resumo_fap segue funcionando.",
        exc,
    )
else:

    @mcp.tool(app=True)
    def painel_fap(
        ano_vigencia: int | None = None,
        cnpj: str | None = None,
        empresa: str | None = None,
    ) -> ToolResult:
        """Painel visual do resumo FAP: cartões e gráficos de barras.

        Use quando o usuário pedir para *ver* o panorama do FAP — um painel,
        gráfico, dashboard ou comparação visual. Para responder uma pergunta
        pontual de contagem em texto, prefira `resumo_fap`.

        Mostra contestações por situação, ano de vigência e empresa; benefícios
        por tópico de contestação e status de 1ª/2ª instância; e cartões com
        totais, valor pago e cobertura de CAT.

        Args:
            ano_vigencia: Restringe a um ano de vigência FAP (opcional).
            cnpj: Restringe a um estabelecimento — aceita formatado, só dígitos
                ou raiz de 8 dígitos (opcional).
            empresa: Nome (ou parte do nome) da empresa (opcional).
        """
        claims = require_module("fap_panel")
        with app.app_context():
            dados = fap_summary_handler(
                claims["law_firm_id"], ano_vigencia, cnpj, empresa
            )
        return ToolResult(
            content=resumo_em_texto(dados),
            structured_content=construir_painel(dados),
        )
```

`logging` já está importado em `mcp_server/server.py:35`, e o arquivo usa
`logging.getLogger(__name__)` inline (ver linha 120) — não há um `logger` de
módulo. Manter esse padrão, como no código acima.

- [ ] **Step 4: Rodar e ver passar**

```bash
uv run python tests/test_mcp_fap_panel.py
```

Expected: oito linhas `OK` e `Todos os testes passaram.`

- [ ] **Step 5: Verificar que nada existente quebrou**

```bash
uv run python tests/test_mcp_fap_review.py
```

Expected: a suíte existente passa como antes. Se falhar, PARE — a tool nova não pode afetar o resto do servidor.

- [ ] **Step 6: Commit**

```bash
git add mcp_server/server.py tests/test_mcp_fap_panel.py
git commit -m "feat(mcp): tool painel_fap com degradação para host sem MCP Apps"
```

---

### Task 5: Isolamento por escritório

**Files:**
- Modify: `tests/test_mcp_fap_panel.py`

**Interfaces:**
- Consumes: `fap_summary_handler`, `construir_painel`, `resumo_em_texto`.
- Produces: nada — é a task de verificação da regra de multi-tenancy.

- [ ] **Step 1: Escrever o teste**

Em `tests/test_mcp_fap_panel.py`, acrescentar antes do bloco `__main__`:

```python
def test_painel_respeita_o_escritorio():
    """O painel só pode enxergar o law_firm_id do chamador."""
    from main import app as flask_app
    from app.models import LawFirm

    from mcp_server.apps.fap_panel import construir_painel, resumo_em_texto
    from mcp_server.tools.fap import fap_summary_handler

    with flask_app.app_context():
        escritorios = LawFirm.query.limit(2).all()
        if not escritorios:
            print("PULADO  nenhum escritório no banco — teste requer dado real")
            return

        for firma in escritorios:
            dados = fap_summary_handler(firma.id, None, None, None)
            assert construir_painel(dados).model_dump_json()
            assert resumo_em_texto(dados)

        # Isolamento de verdade: o total do escritório A somado ao de B não pode
        # ser menor que o total de qualquer um deles isoladamente, e nenhum dos
        # dois pode enxergar o total global. Compara-se contra a contagem sem
        # filtro de escritório, que é o vazamento que se quer impedir.
        if len(escritorios) > 1:
            from app.models import Benefit

            a = fap_summary_handler(escritorios[0].id, None, None, None)
            b = fap_summary_handler(escritorios[1].id, None, None, None)
            global_ = Benefit.query.count()

            ta = a["beneficios"]["total"]
            tb = b["beneficios"]["total"]
            assert ta + tb <= global_, (
                f"vazamento: A={ta} + B={tb} excede o total global {global_}"
            )
            if global_ > 0 and ta > 0 and tb > 0:
                assert ta < global_ and tb < global_, (
                    "um escritório está enxergando o total global"
                )
            print(f"OK  escritórios isolados (A={ta}, B={tb}, global={global_})")
        else:
            print("OK  painel monta com dado real (só um escritório no banco)")
```

e registrar no bloco `__main__`:

```python
    test_painel_respeita_o_escritorio()
```

- [ ] **Step 2: Rodar**

```bash
uv run python tests/test_mcp_fap_panel.py
```

Expected: todas as linhas `OK` (a última pode ser `PULADO` num banco vazio) e `Todos os testes passaram.`

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_fap_panel.py
git commit -m "test(mcp): isolamento por escritório no painel FAP"
```

---

### Task 6: Verificação end-to-end antes do deploy

**Files:** nenhum — é a task de verificação real, com o servidor de pé.

**Interfaces:**
- Consumes: tudo das tasks anteriores.
- Produces: evidência de que a tool responde no servidor rodando.

- [ ] **Step 1: Subir o servidor MCP local**

```bash
uv run python -m mcp_server.server
```

Rodar em background ou noutro terminal. Confirmar nos logs que **não** aparece o aviso `Painel FAP indisponível`.

- [ ] **Step 2: Chamar a tool no servidor em memória e inspecionar a resposta**

```bash
uv run python -c "
import asyncio, fastmcp
from mcp_server.server import mcp

async def main():
    async with fastmcp.Client(mcp) as c:
        nomes = sorted(t.name for t in await c.list_tools())
        print('painel_fap registrada:', 'painel_fap' in nomes)
        print('resumo_fap intacta:', 'resumo_fap' in nomes)
        print('total de tools:', len(nomes))
asyncio.run(main())
"
```

Expected: `painel_fap registrada: True`, `resumo_fap intacta: True`, e a contagem de tools igual à anterior **mais um**.

- [ ] **Step 3: Confirmar a degradação com o Prefab ausente**

```bash
uv run python -c "
import sys
sys.modules['prefab_ui'] = None  # força o ImportError no registro
import importlib, mcp_server.server as s
importlib.reload(s)
print('servidor subiu sem Prefab')
" 2>&1 | tail -3
```

Expected: a mensagem `servidor subiu sem Prefab` (o aviso em log é esperado e desejado). Se o processo abortar, o `try/except` da Task 4 está mal posicionado.

- [ ] **Step 4: Commit final da spec como implementada**

Atualizar o campo `**Status:**` no topo de `docs/superpowers/specs/2026-07-18-painel-fap-mcp-app-design.md` de `aprovado, aguardando plano de implementação` para `implementado`.

```bash
git add docs/superpowers/specs/2026-07-18-painel-fap-mcp-app-design.md
git commit -m "docs: painel FAP implementado"
```

---

## Deploy

Nada de infraestrutura muda. `deploy/deploy_mcp.sh` já roda `uv sync` e reinicia `intellexia-mcp.service`, então o extra `apps` e o `prefab-ui` pinado entram sozinhos no próximo deploy.

Depois do deploy, confirmar no servidor:

```bash
systemctl --no-pager --lines 20 status intellexia-mcp.service | grep -i "painel FAP indisponível" || echo "painel OK"
```

Expected: `painel OK`. Se o aviso aparecer, o `uv sync` não trouxe o Prefab no ambiente de produção.
