"""
Catálogo das ferramentas e comandos do conector MCP, lido do manual.

Fonte única: ``docs/MANUAL_MCP.md`` — as tabelas de "Ferramentas por categoria"
e de "Comandos prontos". O modal "Conectar sua IA" (header) mostra este
catálogo resumido; o manual continua sendo o texto completo. Assim, documentar
uma ferramenta nova no manual já a leva ao modal, sem lista paralela no template.

O manual não pode ficar para trás do servidor: ``tests/test_mcp_catalogo.py``
confere que toda ferramenta e todo comando registrados em
``mcp_server/server.py`` aparecem aqui, e que a contagem anunciada bate.
"""
import os
import re

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANUAL_PATH = os.path.join(_PROJECT_ROOT, "docs", "MANUAL_MCP.md")

_SECAO_FERRAMENTAS = "## Ferramentas por categoria"
_SECAO_COMANDOS = "## Comandos prontos"
# Linha de tabela cuja 1ª célula é só um nome em código: | `nome` | descrição | ...
# O nome começa por letra: exemplos como `5001181` em tabelas de apoio não contam.
_LINHA_ITEM = re.compile(r"^\|\s*`([a-z][a-z0-9_]*)`\s*\|\s*(.*?)\s*\|")

# Ordem dos grupos no modal: Jurisprudência e tudo do FAP primeiro (decisão do
# produto). Grupo fora da lista mantém a ordem do manual, depois destes.
_ORDEM_MODAL = (
    "Base de Jurisprudência",
    "Painel FAP — consultas",
    "Painel FAP — análises e acompanhamento",
    "Relatórios em Excel",
    "Painel de Contestações",
)

# Ícone (Bootstrap Icons) de cada grupo no modal — os mesmos do menu lateral
# quando o módulo tem um. Grupo sem ícone aqui usa ICONE_PADRAO.
_ICONES = {
    "Base de Jurisprudência": "bi-bank",
    "Painel FAP — consultas": "bi-shield-check",
    "Painel FAP — análises e acompanhamento": "bi-graph-up",
    "Relatórios em Excel": "bi-file-earmark-spreadsheet",
    "Painel de Contestações": "bi-collection",
    "Base de Conhecimento": "bi-book",
    "Processos Judiciais": "bi-diagram-3-fill",
    "Monitoramento de Processos": "bi-broadcast",
    "Utilidades": "bi-tools",
    "Revisão de Petições": "bi-file-earmark-check",
}
ICONE_PADRAO = "bi-grid"

_cache = {"mtime": None, "catalogo": None}


def _texto_simples(md):
    """Descrição da tabela sem marcação: **negrito**, `código`, links."""
    md = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md)
    md = md.replace("**", "").replace("`", "")
    return md.strip()


def _secao(linhas, titulo):
    """Linhas entre o título `## ...` pedido e o próximo `## `."""
    dentro, saida = False, []
    for linha in linhas:
        if linha.startswith("## "):
            if dentro:
                break
            dentro = linha.strip() == titulo
            continue
        if dentro:
            saida.append(linha)
    return saida


def _parse(texto):
    linhas = texto.splitlines()

    grupos, atual = [], None
    for linha in _secao(linhas, _SECAO_FERRAMENTAS):
        if linha.startswith("### "):
            # Sem o emoji do manual: no modal ele disputa com os ícones do app e,
            # sem fonte de emoji no sistema, vira um quadrado vazio.
            titulo = re.sub(r"^[^\wÀ-ÿ]+", "", linha[4:]).strip()
            atual = {"titulo": titulo, "icone": _ICONES.get(titulo, ICONE_PADRAO), "itens": []}
            grupos.append(atual)
            continue
        m = _LINHA_ITEM.match(linha)
        if m and atual is not None:
            atual["itens"].append({"nome": m.group(1), "descricao": _texto_simples(m.group(2))})
    grupos = [g for g in grupos if g["itens"]]
    prioridade = {titulo: i for i, titulo in enumerate(_ORDEM_MODAL)}
    grupos.sort(key=lambda g: prioridade.get(g["titulo"], len(_ORDEM_MODAL)))  # sort estável

    comandos = []
    for linha in _secao(linhas, _SECAO_COMANDOS):
        m = _LINHA_ITEM.match(linha)
        if m:
            comandos.append({"nome": m.group(1), "descricao": _texto_simples(m.group(2))})

    anunciado = re.search(r"\*\*(\d+) ferramentas\*\*", texto)
    return {
        "grupos": grupos,
        "comandos": comandos,
        "total_ferramentas": sum(len(g["itens"]) for g in grupos),
        "total_anunciado": int(anunciado.group(1)) if anunciado else None,
    }


def catalogo():
    """Catálogo do manual, em cache até o arquivo mudar. Vazio se não houver manual."""
    try:
        mtime = os.path.getmtime(MANUAL_PATH)
    except OSError:
        return {"grupos": [], "comandos": [], "total_ferramentas": 0, "total_anunciado": None}
    if _cache["mtime"] != mtime:
        with open(MANUAL_PATH, encoding="utf-8") as f:
            _cache["catalogo"] = _parse(f.read())
        _cache["mtime"] = mtime
    return _cache["catalogo"]
