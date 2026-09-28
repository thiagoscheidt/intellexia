"""
O manual do MCP (e, por ele, o modal "Conectar sua IA") cobre tudo o que o
servidor publica.

Lê as ferramentas e os comandos direto do código de ``mcp_server/server.py``
(por AST, sem subir o servidor) e confere contra o catálogo do manual:

- toda ferramenta registrada está numa tabela de "Ferramentas por categoria";
- todo comando (prompt) está na tabela de "Comandos prontos";
- nada documentado deixou de existir no servidor;
- o "**N ferramentas**" do texto bate com a contagem real.

Uso:
    uv run python tests/test_mcp_catalogo.py
"""
import ast
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.mcp_catalog_service import catalogo  # noqa: E402

SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "mcp_server", "server.py")


def registrados():
    """(ferramentas, comandos) decorados com @mcp.tool / @mcp.prompt."""
    arvore = ast.parse(open(SERVER, encoding="utf-8").read())
    ferramentas, comandos = set(), set()
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in no.decorator_list:
            texto = ast.unparse(dec)
            nome = re.search(r"name=['\"](\w+)", texto)
            nome = nome.group(1) if nome else no.name
            if texto.startswith("mcp.tool"):
                ferramentas.add(nome)
            elif texto.startswith("mcp.prompt"):
                comandos.add(nome)
    return ferramentas, comandos


def main():
    ferramentas, comandos = registrados()
    cat = catalogo()
    doc_ferr = {i["nome"] for g in cat["grupos"] for i in g["itens"]}
    doc_cmd = {c["nome"] for c in cat["comandos"]}

    erros = []
    for falta in sorted(ferramentas - doc_ferr):
        erros.append(f"ferramenta sem documentação no manual: {falta}")
    for sobra in sorted(doc_ferr - ferramentas):
        erros.append(f"ferramenta no manual que não existe no servidor: {sobra}")
    for falta in sorted(comandos - doc_cmd):
        erros.append(f"comando sem documentação no manual: {falta}")
    for sobra in sorted(doc_cmd - comandos):
        erros.append(f"comando no manual que não existe no servidor: {sobra}")
    if cat["total_anunciado"] != len(ferramentas):
        erros.append(f"manual anuncia {cat['total_anunciado']} ferramentas, "
                     f"o servidor tem {len(ferramentas)}")

    print(f"servidor: {len(ferramentas)} ferramentas, {len(comandos)} comandos")
    print(f"manual:   {len(doc_ferr)} ferramentas em {len(cat['grupos'])} grupos, "
          f"{len(doc_cmd)} comandos")
    if erros:
        print("\n❌ " + "\n❌ ".join(erros))
        sys.exit(1)
    print("✅ manual e servidor em dia")


if __name__ == "__main__":
    main()
