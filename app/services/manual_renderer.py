"""
Renderizador dos manuais dos painéis.

Converte os arquivos ``docs/MANUAL_*.md`` em HTML pronto para a página
``/docs/manuais``, preservando os realces visuais por meio de convenções:

- **Avisos coloridos**: uma citação (``>``) iniciada por um marcador vira um
  callout estilizado. Sem marcador, vira um callout neutro.
    ``> [!DOU] ...``    -> dourado (Diário Oficial)
    ``> [!ALERTA] ...`` -> âmbar
    ``> [!INFO] ...``   -> azul
    ``> [!IA] ...``     -> roxo
- **Etiquetas de origem**: numa tabela, quando o conteúdo de uma célula é
  exatamente um rótulo conhecido (``FAP Web``, ``IA``, ``Sistema``, ``Relatório``,
  ``Cálculo``) — ou uma lista deles separada por vírgula — vira pílula colorida.
- **Índice lateral (TOC)**: gerado a partir dos títulos de cada manual.
- **Endereços do sistema**: ``:url_mcp:`` e ``:url_app:`` viram a URL real desta
  instalação (produção e dev têm domínios diferentes — nunca escreva a URL fixa
  no markdown).
- **Botões de ação**: ``:btn-<estilo>[Texto]`` vira uma réplica visual do botão
  da tela, com as mesmas cores do Bootstrap usado no app. Estilos aceitos:
  ``success``, ``primary``, ``danger``, ``secondary``, ``warning`` e as
  variantes ``outline-*`` — ex.: ``:btn-success[Aprovar petição]``,
  ``:btn-outline-danger[Devolver para ajustes]``.

Os manuais são a **fonte única**: esta função é chamada em runtime pela rota e
o resultado é mantido em cache, invalidado quando qualquer ``.md`` muda ou quando
o domínio resolvido muda.
"""
import os
import re
import unicodedata

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from app.utils.urls import app_public_url, mcp_public_url

# Raiz do projeto: .../app/services/manual_renderer.py -> sobe 3 níveis
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DOCS_DIR = os.path.join(_PROJECT_ROOT, "docs")

# (id do módulo, rótulo exibido, arquivo em docs/)
_MANUALS = (
    ("dashboard", "Dashboard Principal", "MANUAL_DASHBOARD.md"),
    ("painel-fap", "Painel FAP", "MANUAL_PAINEL_FAP.md"),
    ("contestacoes", "Painel de Contestações", "MANUAL_PAINEL_CONTESTACOES.md"),
    ("revisor-peticoes", "Revisor de Petições", "MANUAL_REVISOR_PETICOES.md"),
    ("conectar-ia", "Conectar sua IA (MCP)", "MANUAL_MCP.md"),
)

# Marcador de callout -> classe CSS (string vazia = callout neutro).
_CALLOUT_CLASSES = {
    "DOU": "dou",
    "ALERTA": "warn-note",
    "INFO": "info",
    "IA": "ia-note",
    "NOTA": "",
}

# Rótulo de origem -> classe da pílula.
_ORIGIN_TAGS = {
    "FAP Web": "fap",
    "IA": "ia",
    "Sistema": "sys",
    "Cálculo": "sys",
    "Relatório": "rel",
}

_md = MarkdownIt("commonmark").enable("table")

# Ícone (spark) do Claude — usado onde o texto menciona o Claude, via marcador
# ``:claude:`` no markdown. SVG inline (sem asset externo), na cor da marca.
_CLAUDE_SVG = (
    '<svg class="claude-ico" viewBox="-24 -24 48 48" aria-label="Claude" role="img">'
    + "".join(
        f'<line x1="0" y1="-7.5" x2="0" y2="-{19 if i % 2 == 0 else 14.5}" '
        f'transform="rotate({i * 30})" stroke="#D97757" stroke-width="4.6" '
        f'stroke-linecap="round"/>'
        for i in range(12)
    )
    + "</svg>"
)

# Estilos aceitos pelo marcador de botão ``:btn-<estilo>[Texto]`` (cores do
# Bootstrap usadas nas telas — manter em sincronia com o CSS em manuais.html).
_BUTTON_STYLES = {
    "success", "primary", "danger", "secondary", "warning",
    "outline-success", "outline-primary", "outline-danger", "outline-secondary",
}

_BUTTON_RE = re.compile(r":btn-([a-z-]+)\[([^\]]+)\]")


def _replace_buttons(html: str) -> str:
    """Troca ``:btn-<estilo>[Texto]`` por uma réplica visual do botão da tela."""
    def _repl(match: re.Match) -> str:
        style, label = match.group(1), match.group(2)
        if style not in _BUTTON_STYLES:
            return match.group(0)
        return f'<span class="manual-btn mbtn-{style}">{label}</span>'

    return _BUTTON_RE.sub(_repl, html)


# Cache: {"key": (mtimes,), "modules": [...]}
_cache: dict = {"key": None, "modules": None}


def _slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9\s-]", "", t).strip().lower()
    t = re.sub(r"\s+", "-", t)
    return t or "sec"


def _process(html: str, module_id: str) -> tuple[str, list[dict]]:
    """Aplica IDs, coleta TOC (h2), transforma callouts e pílulas, embrulha tabelas."""
    soup = BeautifulSoup(html, "html.parser")
    toc: list[dict] = []

    # O título do módulo vem do rótulo (no template); remove o # H1 do markdown
    # para não duplicar.
    first_h1 = soup.find("h1")
    if first_h1 is not None:
        first_h1.decompose()

    # IDs + TOC pelos níveis ORIGINAIS (h2 alimenta o índice lateral)...
    for h in soup.find_all(["h2", "h3"]):
        text = h.get_text(strip=True)
        has_claude = ":claude:" in text
        text = text.replace(":claude:", "").strip()
        hid = f"{module_id}-{_slugify(text)}"
        h["id"] = hid
        if h.name == "h2":
            toc.append({"id": hid, "text": text, "claude": has_claude})

    # ...e rebaixa um nível para o título do módulo (h2 no template) ser o topo:
    # markdown ## -> h3 (seção), markdown ### -> h4 (subseção).
    for h in soup.find_all("h3"):
        h.name = "h4"
    for h in soup.find_all("h2"):
        h.name = "h3"

    # Callouts a partir de blockquotes
    for bq in soup.find_all("blockquote"):
        first_p = bq.find("p")
        css_class = ""
        if first_p is not None:
            inner = first_p.decode_contents()
            m = re.match(r"\s*\[!(\w+)\]\s*(.*)", inner, re.S)
            if m:
                marker = m.group(1).upper()
                css_class = _CALLOUT_CLASSES.get(marker, "")
                # remove o marcador do texto
                new_p = BeautifulSoup(f"<p>{m.group(2)}</p>", "html.parser").p
                first_p.replace_with(new_p)
        bq.name = "div"
        bq["class"] = ("callout " + css_class).strip()

    # Pílulas de origem em células de tabela
    for td in soup.find_all("td"):
        raw = td.get_text(strip=True)
        if not raw:
            continue
        parts = [p.strip() for p in raw.split(",")]
        if parts and all(p in _ORIGIN_TAGS for p in parts):
            td.clear()
            for i, p in enumerate(parts):
                span = soup.new_tag("span")
                span["class"] = "tag " + _ORIGIN_TAGS[p]
                span.string = p
                td.append(span)
                if i < len(parts) - 1:
                    td.append(" ")

    # Embrulha tabelas para rolagem/estilo
    for table in soup.find_all("table"):
        wrapper = soup.new_tag("div")
        wrapper["class"] = "table-wrap"
        table.wrap(wrapper)

    # Marcadores finais: ícone do Claude, endereços desta instalação e botões.
    html_out = (
        str(soup)
        .replace(":claude:", _CLAUDE_SVG)
        .replace(":url_mcp:", mcp_public_url())
        .replace(":url_app:", app_public_url())
    )
    html_out = _replace_buttons(html_out)
    return html_out, toc


def _cache_key() -> tuple:
    """Invalida o cache quando um manual muda **ou** quando o domínio muda.

    O domínio entra na chave porque os marcadores ``:url_mcp:``/``:url_app:``
    são resolvidos no render: sem isso, uma instalação poderia servir a URL de
    outra a partir do cache.
    """
    out = []
    for _mid, _label, filename in _MANUALS:
        path = os.path.join(_DOCS_DIR, filename)
        try:
            out.append(os.path.getmtime(path))
        except OSError:
            out.append(0.0)
    out.append(mcp_public_url())
    out.append(app_public_url())
    return tuple(out)


def render_modules() -> list[dict]:
    """Renderiza os manuais. Retorna lista de módulos:

    ``[{"id", "title", "html", "toc": [{"id", "text"}]}]``

    Usa cache invalidado pela data de modificação dos arquivos.
    """
    key = _cache_key()
    if _cache["key"] == key and _cache["modules"] is not None:
        return _cache["modules"]

    modules: list[dict] = []
    for module_id, label, filename in _MANUALS:
        path = os.path.join(_DOCS_DIR, filename)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        html = _md.render(text)
        processed, toc = _process(html, module_id)
        modules.append({"id": module_id, "title": label, "html": processed, "toc": toc})

    _cache["key"] = key
    _cache["modules"] = modules
    return modules
