"""
Parser do XML do Diário Oficial da União (INLABS).

Função pura: recebe os bytes de um arquivo XML e devolve dicts prontos para
virar linhas de ``DouArticle``. Não faz rede, não toca banco, não depende de
Flask — é a peça mais provável de quebrar quando a Imprensa Nacional alterar o
schema, e deve ser a única que precisa mudar nesse caso.

Formato: cada arquivo do ZIP contém ``<articles><article .../></articles>``,
com os metadados em atributos do ``<article>`` e o conteúdo em ``<body>``. O
``<Texto>`` traz HTML escapado.

Segurança: o XML vem de um ZIP baixado da rede, então é entrada não confiável
por definição — mesmo vindo de endpoint autenticado do governo. Por isso o
parse usa ``defusedxml``, que recusa DTD e expansão de entidades.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime

# defusedxml, nunca xml.etree: o parser da stdlib expande entidades e um XML
# malicioso dentro do ZIP ("billion laughs") consumiria toda a memória do
# servidor. A API é a mesma; o comportamento perigoso é que sai.
import defusedxml.ElementTree as ElementTree

from bs4 import BeautifulSoup

# Atributo do <article> → chave do dict de saída
_ATTR_MAP = {
    'art_id': 'id',
    'id_materia': 'idMateria',
    'pub_name': 'pubName',
    'edicao': 'editionNumber',
    'pagina': 'numberPage',
    'pdf_page': 'pdfPage',
    'orgao_hierarquia': 'artCategory',
    'art_type': 'artType',
    'art_class': 'artClass',
}

# Tag dentro de <body> → chave do dict de saída
_BODY_MAP = {
    'identifica': 'Identifica',
    'ementa': 'Ementa',
    'titulo': 'Titulo',
    'subtitulo': 'SubTitulo',
}

_WHITESPACE = re.compile(r'\s+')


def strip_html(value: str | None) -> str:
    """Converte o HTML do <Texto> em texto corrido, com espaços colapsados."""
    if not value:
        return ''
    texto = BeautifulSoup(value, 'html.parser').get_text(separator=' ')
    return _WHITESPACE.sub(' ', texto).strip()


def _parse_date(value: str | None) -> date | None:
    """A data do INLABS vem como dd/mm/aaaa. Valor ausente ou inesperado → None."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), '%d/%m/%Y').date()
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    """Só os dígitos: 'numberPage' é texto e pode vir vazio ou fora do padrão."""
    if not value:
        return None
    digitos = ''.join(c for c in value if c.isdigit())
    return int(digitos) if digitos else None


def _clean(value: str | None) -> str | None:
    """Normaliza texto de tag: vazio vira None, para não poluir o banco."""
    if value is None:
        return None
    texto = _WHITESPACE.sub(' ', value).strip()
    return texto or None


def article_hash(art_id, id_materia, pub_date, pub_name, raw_xml) -> str:
    """SHA-256 sobre identidade + conteúdo bruto.

    Incluir ``raw_xml`` significa que qualquer alteração de conteúdo gera hash
    novo — republicação com texto corrigido não passa despercebida. O whitespace
    é normalizado antes para que reindentação do XML não conte como mudança.
    """
    normalizado = _WHITESPACE.sub(' ', raw_xml or '').strip()
    partes = [
        str(art_id or ''),
        str(id_materia or ''),
        pub_date.isoformat() if pub_date else '',
        str(pub_name or ''),
        normalizado,
    ]
    return hashlib.sha256('|'.join(partes).encode('utf-8')).hexdigest()


def parse_article_xml(xml_bytes: bytes) -> list[dict]:
    """Bytes de um XML do INLABS → lista de dicts (uma por <article>).

    Recebe **bytes**, não str: a declaração ``<?xml encoding=...?>`` varia entre
    ISO-8859-1 e UTF-8, e o ElementTree só a respeita quando lê bytes.

    Levanta ``ElementTree.ParseError`` em XML malformado e ``DefusedXmlException``
    (p.ex. ``EntitiesForbidden``) em XML hostil — quem chama decide se aborta a
    edição ou apenas registra e segue.
    """
    root = ElementTree.fromstring(xml_bytes)
    elementos = root.iter('article') if root.tag != 'article' else [root]

    artigos = []
    for article in elementos:
        dados = {chave: _clean(article.get(attr)) for chave, attr in _ATTR_MAP.items()}
        dados['pub_date'] = _parse_date(article.get('pubDate'))
        dados['pagina_num'] = _parse_int(dados['pagina'])

        body = article.find('body')
        for chave, tag in _BODY_MAP.items():
            elem = body.find(tag) if body is not None else None
            dados[chave] = _clean(elem.text) if elem is not None else None

        texto_elem = body.find('Texto') if body is not None else None
        texto_html = texto_elem.text if texto_elem is not None and texto_elem.text else ''
        dados['texto_html'] = texto_html
        dados['texto'] = strip_html(texto_html)

        dados['raw_xml'] = ElementTree.tostring(article, encoding='unicode')
        dados['hash'] = article_hash(
            dados['art_id'], dados['id_materia'], dados['pub_date'],
            dados['pub_name'], dados['raw_xml'],
        )
        artigos.append(dados)

    return artigos
