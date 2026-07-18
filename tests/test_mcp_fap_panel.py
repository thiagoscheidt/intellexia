#!/usr/bin/env python3
"""
Teste do painel FAP (MCP App).

    uv run python tests/test_mcp_fap_panel.py

Cobre:
  1. top_n — corte nos 8 maiores com faixa "outros (N)" rotulada, ordenado
     por contagem (não por ordem de inserção)
  2. resumo_em_texto — fallback para host que não renderiza MCP Apps
  3. _recorte_dos_filtros — helper compartilhado (Task 3 vai reusar)
  4. _moeda — formatação de valores em Real (padrão pt-BR)
  5. construir_painel — componente Prefab (Task 3)

Nota sobre serialização: as asserções de `construir_painel` navegam
`Component.to_json()`, não `model_dump()`/`model_dump_json()`. O pydantic
padrão serializa um campo `children: list[Component]` pelo *schema
declarado* (`Component`), não pelo tipo real de cada instância — então
`model_dump_json()` de um `Page` composto por `Metric`/`BarChart` sai sem
`label`, `value` ou `data` nenhum (campos existem só nas subclasses). Só
`to_json()` (método próprio do prefab_ui, usado por quem realmente serializa
o app para o host) percorre a árvore preservando os campos de cada
subclasse. Testar com `model_dump_json()` não passaria "por coincidência":
simplesmente não teria onde achar "12".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.apps.fap_panel import (
    _moeda,
    _recorte_dos_filtros,
    construir_painel,
    resumo_em_texto,
    top_n,
)

FIXTURE = {
    "filtros": {"ano_vigencia": 2023, "cnpj": None},
    "contestacoes": {
        "total": 12,
        "por_ano_vigencia": {"2023": 12},
        "por_situacao": {"Indeferida": 5, "Deferida": 7},
        "por_instancia": {"1ª": 12},
        "por_empresa": {"Acme": 4, "Bistek": 8},
    },
    "beneficios": {
        "total": 30,
        "por_tipo": {"B91": 20, "B94": 10},
        "por_tipo_pedido": {"Exclusão": 30},
        "por_status_primeira_instancia": {"Deferido": 18, "Indeferido": 12},
        "por_status_segunda_instancia": {"(vazio)": 30},
        "por_topico_contestacao": {"PRÉ-FAP": 9, "ACIDENTE DE TRAJETO": 15},
        "financeiro": {"total_pago_soma": 12345.67, "beneficios_com_valor_informado": 25},
        "com_cat": 22,
        "sem_cat": 8,
    },
}


def test_top_n_corta_e_rotula_o_resto():
    # Ordem de inserção deliberadamente embaralhada em relação à contagem —
    # se o sorted() da implementação sumir, estas asserções devem falhar.
    contagens = {
        "T5": 5, "T0": 10, "T11": -1, "T3": 7,
        "T8": 2, "T1": 9, "T9": 1, "T4": 6,
        "T6": 4, "T2": 8, "T10": 0, "T7": 3,
    }
    resultado = top_n(contagens, n=8)

    assert len(resultado) == 9, f"esperado 8 + faixa outros, veio {len(resultado)}"
    rotulo, valor = resultado[-1]
    assert rotulo == "outros (4)", f"faixa mal rotulada: {rotulo}"
    esperado_resto = sum(sorted(contagens.values())[:4])  # os 4 menores valores
    assert valor == esperado_resto, f"soma do resto errada: {valor} != {esperado_resto}"
    assert sum(v for _, v in resultado) == sum(contagens.values()), "soma não fecha"
    print("OK  top_n corta nos 8 maiores e rotula o restante")


def test_top_n_ordena_por_contagem_nao_por_insercao():
    # Ordem de inserção não é ordem de contagem — se o sorted() sumir,
    # o resultado sai na ordem de inserção e este teste falha.
    contagens = {"baixo": 1, "alto": 100, "medio": 50}
    resultado = top_n(contagens, n=8)
    assert resultado == [("alto", 100), ("medio", 50), ("baixo", 1)], resultado
    print("OK  top_n ordena por contagem, não por ordem de inserção")


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


def test_recorte_dos_filtros_com_os_dois():
    recorte = _recorte_dos_filtros({"ano_vigencia": 2023, "cnpj": "12.345.678/0001-90"})
    assert recorte == ["vigência 2023", "CNPJ 12.345.678/0001-90"], recorte
    print("OK  _recorte_dos_filtros com vigência e CNPJ")


def test_recorte_dos_filtros_com_um_so():
    assert _recorte_dos_filtros({"ano_vigencia": 2023, "cnpj": None}) == ["vigência 2023"]
    assert _recorte_dos_filtros({"ano_vigencia": None, "cnpj": "12345"}) == ["CNPJ 12345"]
    print("OK  _recorte_dos_filtros com um filtro só")


def test_recorte_dos_filtros_vazio():
    assert _recorte_dos_filtros({"ano_vigencia": None, "cnpj": None}) == []
    assert _recorte_dos_filtros({}) == []
    print("OK  _recorte_dos_filtros sem filtros retorna lista vazia")


def test_moeda_em_padrao_brasileiro():
    assert _moeda(12345.67) == "R$ 12.345,67", _moeda(12345.67)
    assert _moeda(0.0) == "R$ 0,00", _moeda(0.0)
    assert _moeda(1234567.89) == "R$ 1.234.567,89", _moeda(1234567.89)
    print("OK  _moeda formata em padrão pt-BR (R$ 12.345,67)")


def _coletar_por_tipo(no: dict, tipo: str, achados: list | None = None) -> list:
    """Percorre a árvore de ``Component.to_json()`` coletando nós de um tipo.

    Assertar por substring no JSON serializado deixa passar o número certo
    no campo errado ("12" bate com qualquer 12 no blob). Aqui navegamos a
    árvore de verdade e checamos o campo específico do componente.
    """
    if achados is None:
        achados = []
    if not isinstance(no, dict):
        return achados
    if no.get("type") == tipo:
        achados.append(no)
    for filho in no.get("children") or []:
        _coletar_por_tipo(filho, tipo, achados)
    return achados


def _metric(arvore: dict, label: str) -> dict:
    achados = [m for m in _coletar_por_tipo(arvore, "Metric") if m.get("label") == label]
    assert achados, f"Metric com label {label!r} não encontrado"
    return achados[0]


def _barchart_com_ponto(arvore: dict, rotulo: str) -> dict:
    for grafico in _coletar_por_tipo(arvore, "BarChart"):
        for ponto in grafico.get("data") or []:
            if ponto.get("rotulo") == rotulo:
                return grafico
    raise AssertionError(f"nenhum BarChart tem um ponto com rotulo {rotulo!r}")


def test_construir_painel_serializa_com_os_numeros():
    painel = construir_painel(FIXTURE)
    arvore = painel.to_json()

    assert painel.title, "painel sem título"
    assert painel.title == "Painel FAP — vigência 2023", painel.title

    assert _metric(arvore, "Contestações")["value"] == 12, "total de contestações no campo errado"
    assert _metric(arvore, "Benefícios")["value"] == 30, "total de benefícios no campo errado"

    grafico_situacao = _barchart_com_ponto(arvore, "Deferida")
    pontos = {p["rotulo"]: p["qtd"] for p in grafico_situacao["data"]}
    assert pontos == {"Deferida": 7, "Indeferida": 5}, pontos

    grafico_topico = _barchart_com_ponto(arvore, "ACIDENTE DE TRAJETO")
    pontos_topico = {p["rotulo"]: p["qtd"] for p in grafico_topico["data"]}
    assert pontos_topico == {"ACIDENTE DE TRAJETO": 15, "PRÉ-FAP": 9}, pontos_topico

    print("OK  construir_painel serializa com os números do fixture nos campos certos")


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
    assert painel.title == "Painel FAP — sem filtros", painel.title
    arvore = painel.to_json()
    assert arvore, "componente vazio não serializa"
    assert _metric(arvore, "Contestações")["value"] == 0
    assert _metric(arvore, "Benefícios")["value"] == 0
    for grafico in _coletar_por_tipo(arvore, "BarChart"):
        assert grafico["data"] == [{"rotulo": "sem dados", "qtd": 0}], grafico["data"]
    print("OK  construir_painel sobrevive a escritório sem dado")


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


if __name__ == "__main__":
    test_top_n_corta_e_rotula_o_resto()
    test_top_n_ordena_por_contagem_nao_por_insercao()
    test_top_n_nao_corta_quando_cabe()
    test_resumo_em_texto_traz_os_totais()
    test_resumo_em_texto_com_escritorio_vazio()
    test_recorte_dos_filtros_com_os_dois()
    test_recorte_dos_filtros_com_um_so()
    test_recorte_dos_filtros_vazio()
    test_moeda_em_padrao_brasileiro()
    test_construir_painel_serializa_com_os_numeros()
    test_construir_painel_com_escritorio_vazio()
    test_tool_registrada_no_servidor()
    test_tool_monta_resposta_com_os_dois_canais()
    print("\nTodos os testes passaram.")
