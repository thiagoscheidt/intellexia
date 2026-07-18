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
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.apps.fap_panel import _moeda, _recorte_dos_filtros, resumo_em_texto, top_n

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
    print("\nTodos os testes passaram.")
