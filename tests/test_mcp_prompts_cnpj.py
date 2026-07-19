#!/usr/bin/env python3
"""
Teste dos prompts de consulta por CNPJ no MCP.

    uv run python tests/test_mcp_prompts_cnpj.py

Cobre:
  1. Ambos os prompts registrados no servidor
  2. O CNPJ recebido chega ao texto gerado
  3. O texto instrui a usar a tool consultar_cnpj (pega renomeação silenciosa)
  4. Os três casos de borda continuam mencionados: filial, sem sócios e erro
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fastmcp

from mcp_server.server import ficha_empresa, mcp, socios_empresa

CNPJ = "60.701.190/0001-04"


def test_prompts_registrados():
    async def _run():
        async with fastmcp.Client(mcp) as cliente:
            nomes = {p.name for p in await cliente.list_prompts()}
            for esperado in ("ficha_empresa", "socios_empresa"):
                assert esperado in nomes, f"prompt {esperado} não registrado"

    asyncio.run(_run())
    print("OK  ficha_empresa e socios_empresa registrados no servidor")


def test_cnpj_chega_ao_texto():
    for func in (ficha_empresa, socios_empresa):
        texto = func(CNPJ)
        assert CNPJ in texto, f"{func.__name__} não repassa o CNPJ recebido"
    print("OK  o CNPJ informado aparece no texto dos dois prompts")


def test_texto_instrui_a_tool_certa():
    for func in (ficha_empresa, socios_empresa):
        texto = func(CNPJ)
        assert "consultar_cnpj" in texto, (
            f"{func.__name__} não menciona a tool consultar_cnpj — "
            "uma renomeação da tool quebraria o prompt em silêncio"
        )
    print("OK  os dois prompts apontam para a tool consultar_cnpj")


def test_casos_de_borda_mencionados():
    """Os três casos que a saída erra sozinha se a instrução não os cobrir."""
    for func in (ficha_empresa, socios_empresa):
        texto = func(CNPJ).lower()
        assert "filial" in texto, f"{func.__name__} não trata estabelecimento filial"
        assert "erro" in texto, f"{func.__name__} não trata CNPJ inválido/não encontrado"

    # Quadro societário vazio só precisa ser tratado onde os sócios são o assunto
    assert "sócio" in socios_empresa(CNPJ).lower()
    for termo in ("não há sócios", "sem sócios", "vazio"):
        if termo in socios_empresa(CNPJ).lower():
            break
    else:
        raise AssertionError("socios_empresa não trata o caso de quadro societário vazio")
    print("OK  filial, quadro vazio e erro estão cobertos nas instruções")


if __name__ == "__main__":
    test_prompts_registrados()
    test_cnpj_chega_ao_texto()
    test_texto_instrui_a_tool_certa()
    test_casos_de_borda_mencionados()
    print("\nTodos os testes passaram.")
