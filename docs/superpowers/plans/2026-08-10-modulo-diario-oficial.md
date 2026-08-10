# Módulo Diário Oficial — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capturar diariamente as edições do Diário Oficial da União no INLABS, quebrar o XML matéria a matéria, persistir em banco e expor um acervo navegável mais um painel de saúde da captura.

**Architecture:** Espelha o módulo `communications`: um client HTTP isolado (`inlabs_client`) é o único ponto que fala com o INLABS; um parser puro (`dou_xml_parser`) converte bytes de XML em dicts sem tocar rede nem banco; um serviço de ingestão (`dou_ingestion_service`) orquestra download → disco → parse → upsert. O blueprint só lê e apresenta — nunca baixa nada de forma síncrona numa requisição de usuário.

**Tech Stack:** Python 3.11+, Flask 3.1, SQLAlchemy (Flask-SQLAlchemy), `requests` (já é dependência), `xml.etree.ElementTree` (stdlib), BeautifulSoup4 (já disponível, usado pelo `manual_renderer`), Jinja2 + AdminLTE 4 + Bootstrap 5.

**Spec:** `docs/superpowers/specs/2026-08-10-acervo-dou-inlabs-design.md`

## Global Constraints

- **Sem instalar nada novo.** `requests`, `bs4`, `defusedxml` e a stdlib bastam. Não instalar `lxml`.
- **XML sempre por `defusedxml.ElementTree`, nunca por `xml.etree.ElementTree`.** O parser da stdlib é vulnerável a expansão de entidades ("billion laughs"): um XML malicioso dentro do ZIP consumiria toda a memória do servidor. `defusedxml` 0.7.1 já está no `uv.lock` como dependência transitiva — usá-lo não baixa nada novo, mas precisa ser **declarado como dependência direta** (Task 1, Step 6), porque depender de um pacote transitivo quebra silenciosamente quando o pacote-pai troca de dependências.
- **Gerenciador de pacotes é `uv`.** Nunca `pip`. Rodar tudo com `uv run python ...`.
- **Tabelas do DOU não têm `law_firm_id`.** Exceção consciente ao invariante multi-tenant do projeto (dado público federal, corpus global compartilhado). Documentada na Task 7.
- **Sem Alembic.** Migração é script standalone em `database/`, idempotente, dentro de `with app.app_context():`.
- **Sem framework de testes.** Testes são scripts executáveis em `tests/`, com o helper `check(nome, condicao, detalhe)` no padrão de `tests/test_notifications.py`.
- **Datetimes em UTC no banco**, exibição em São Paulo via filtros Jinja `datetime_sp` / `date_sp`.
- **Caminhos de arquivo gravados no banco são relativos** (`uploads/dou/...`), nunca absolutos — dev e produção têm raízes diferentes.
- **Nome do módulo:** "Diário Oficial". Blueprint `dou_bp`, endpoint `dou`, prefixo `/dou`.
- **Seções XML:** `DO1 DO2 DO3 DO1E DO2E DO3E` (maiúsculas). **Seções PDF:** `do1 do2 do3` (minúsculas).
- **HTTP 404 do INLABS é resultado normal**, não erro — significa "não publicado naquele dia/seção".

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `app/services/dou_xml_parser.py` | **Criar.** Função pura: bytes de XML → `list[dict]`. Sem rede, sem banco, sem Flask. |
| `app/services/inlabs_client.py` | **Criar.** Único ponto que fala com o INLABS: login, cookie, montagem de URL, download, retry, timeout. Não conhece banco. |
| `app/services/dou_ingestion_service.py` | **Criar.** Orquestra: client → disco → parser → upsert → auditoria. Único que conhece as três camadas. |
| `app/models.py` | **Modificar.** Acrescentar `DouEdition`, `DouArticle`, `DouSyncRun` ao final do arquivo. |
| `database/add_dou_tables.py` | **Criar.** Migração standalone idempotente. |
| `scripts/sync_dou.py` | **Criar.** CLI: cron, backfill, reprocesso de data, poda de PDF. |
| `app/blueprints/dou.py` | **Criar.** Rotas do acervo e da captura. |
| `templates/dou/acervo.html` | **Criar.** Navegação por data/seção + lista de matérias. |
| `templates/dou/materia.html` | **Criar.** Detalhe da matéria. |
| `templates/dou/captura.html` | **Criar.** Saúde da ingestão. |
| `app/utils/permissions.py` | **Modificar.** Registrar o módulo `dou`. |
| `app/blueprints/__init__.py` | **Modificar.** Exportar `dou_bp`. |
| `main.py` | **Modificar.** Registrar o blueprint. |
| `templates/partials/sidebar.html` | **Modificar.** Item de menu. |
| `tests/fixtures/dou_sample_article.xml` | **Criar.** Amostra para o parser. |
| `tests/test_dou_xml_parser.py` | **Criar.** Testes do parser. |
| `tests/test_dou_ingestion.py` | **Criar.** Testes de idempotência e republicação. |
| `CLAUDE.md` | **Modificar.** Blueprint, serviços, env vars, exceção de multi-tenancy. |
| `docs/MANUAL_DIARIO_OFICIAL.md` | **Criar.** Manual de uso. |
| `app/services/manual_renderer.py` | **Modificar.** Registrar o manual em `_MANUALS`. |
| `app/services/manual_assistant_service.py` | **Modificar.** Registrar em `_MANUAL_FILES`. |

---

## Task 1: Parser de XML do DOU

O parser é a peça mais valiosa a testar e a única que precisa mudar se a Imprensa Nacional alterar o schema. É função pura: sem rede, sem banco, sem Flask.

**Files:**
- Create: `app/services/dou_xml_parser.py`
- Create: `tests/fixtures/dou_sample_article.xml`
- Create: `tests/fixtures/dou_sample_minimo.xml`
- Test: `tests/test_dou_xml_parser.py`

**Interfaces:**
- Consumes: nada (primeira task).
- Produces:
  - `parse_article_xml(xml_bytes: bytes) -> list[dict]` — cada dict traz exatamente as chaves: `art_id`, `id_materia`, `pub_name`, `pub_date` (`datetime.date | None`), `edicao`, `pagina`, `pdf_page`, `orgao_hierarquia`, `identifica`, `art_type`, `art_class`, `ementa`, `titulo`, `subtitulo`, `texto`, `texto_html`, `raw_xml`, `hash`.
  - `strip_html(value: str | None) -> str`
  - `article_hash(art_id, id_materia, pub_date, pub_name, raw_xml) -> str`

- [ ] **Step 1: Criar a fixture de uma matéria completa**

Criar `tests/fixtures/dou_sample_article.xml`. Reproduz o formato real do INLABS: declaração de encoding, atributos no `<article>`, HTML escapado dentro de `<Texto>`.

```xml
<?xml version="1.0" encoding="ISO-8859-1"?>
<articles fixed="1">
<article id="12345678" name="PORTARIA Nº 1.234, DE 8 DE AGOSTO DE 2026" idOficio="99887" pubName="DO1" artType="Portaria" pubDate="10/08/2026" artClass="00012:00003" artCategory="Ministério da Previdência Social/Instituto Nacional do Seguro Social" artSize="2100" artNotes="" numberPage="42" pdfPage="http://pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?jornal=515&amp;pagina=42&amp;data=10/08/2026" editionNumber="152" highlightType="" highlightPriority="" highlightimage="" highlightimagename="" idMateria="87654321">
<body>
<Identifica>PORTARIA Nº 1.234, DE 8 DE AGOSTO DE 2026</Identifica>
<Data>10/08/2026</Data>
<Ementa>Dispõe sobre o Fator Acidentário de Prevenção - FAP e dá outras providências.</Ementa>
<Titulo>Título de exemplo</Titulo>
<SubTitulo>Subtítulo de exemplo</SubTitulo>
<Texto>&lt;p class="identifica"&gt;PORTARIA Nº 1.234&lt;/p&gt;&lt;p class="dou-paragraph"&gt;O MINISTRO resolve: Art. 1º Fica aprovado o índice composto do FAP.&lt;/p&gt;</Texto>
</body>
</article>
</articles>
```

- [ ] **Step 2: Criar a fixture mínima (atributos ausentes)**

Criar `tests/fixtures/dou_sample_minimo.xml`. Exercita o caminho defensivo: campo ausente vira `None`, nunca exceção.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<articles>
<article id="999" pubName="DO3" idMateria="111">
<body>
<Identifica>AVISO DE LICITAÇÃO</Identifica>
</body>
</article>
</articles>
```

- [ ] **Step 3: Escrever o teste que falha**

Criar `tests/test_dou_xml_parser.py`:

```python
#!/usr/bin/env python3
"""
Testes do parser de XML do DOU (app/services/dou_xml_parser.py).

Função pura: não precisa de rede, banco nem contexto Flask.

    uv run python tests/test_dou_xml_parser.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from defusedxml.common import EntitiesForbidden

from app.services.dou_xml_parser import parse_article_xml, strip_html, article_hash

FIXTURES = Path(__file__).resolve().parent / 'fixtures'

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def test_materia_completa():
    print('\n1. Matéria completa')
    artigos = parse_article_xml((FIXTURES / 'dou_sample_article.xml').read_bytes())

    check('devolve exatamente 1 matéria', len(artigos) == 1, f'veio {len(artigos)}')
    a = artigos[0]

    check('art_id', a['art_id'] == '12345678', repr(a['art_id']))
    check('id_materia', a['id_materia'] == '87654321', repr(a['id_materia']))
    check('pub_name', a['pub_name'] == 'DO1', repr(a['pub_name']))
    check('pub_date vira date', a['pub_date'] == date(2026, 8, 10), repr(a['pub_date']))
    check('edicao', a['edicao'] == '152', repr(a['edicao']))
    check('pagina', a['pagina'] == '42', repr(a['pagina']))
    check('art_type', a['art_type'] == 'Portaria', repr(a['art_type']))
    check('art_class', a['art_class'] == '00012:00003', repr(a['art_class']))
    check(
        'orgao_hierarquia vem de artCategory',
        a['orgao_hierarquia'] == 'Ministério da Previdência Social/Instituto Nacional do Seguro Social',
        repr(a['orgao_hierarquia']),
    )
    check('identifica', a['identifica'].startswith('PORTARIA Nº 1.234'), repr(a['identifica']))
    check('ementa', 'Fator Acidentário' in (a['ementa'] or ''), repr(a['ementa']))
    check('titulo', a['titulo'] == 'Título de exemplo', repr(a['titulo']))
    check('subtitulo', a['subtitulo'] == 'Subtítulo de exemplo', repr(a['subtitulo']))
    check('pdf_page preservado', 'pesquisa.in.gov.br' in (a['pdf_page'] or ''), repr(a['pdf_page']))


def test_texto_e_html():
    print('\n2. Texto: HTML preservado e versão limpa')
    a = parse_article_xml((FIXTURES / 'dou_sample_article.xml').read_bytes())[0]

    check('texto_html mantém as tags', '<p class="identifica">' in a['texto_html'], repr(a['texto_html'][:80]))
    check('texto não tem tags', '<p' not in a['texto'], repr(a['texto'][:80]))
    check('texto mantém o conteúdo', 'Fica aprovado o índice composto do FAP' in a['texto'], repr(a['texto'][:120]))
    check('texto preserva acentuação', 'Art. 1º' in a['texto'], repr(a['texto'][:120]))


def test_acentuacao_iso8859():
    print('\n3. Encoding declarado no XML é respeitado')
    a = parse_article_xml((FIXTURES / 'dou_sample_article.xml').read_bytes())[0]
    check('acento correto na ementa', 'Prevenção' in a['ementa'], repr(a['ementa']))
    check('acento correto no órgão', 'Previdência' in a['orgao_hierarquia'], repr(a['orgao_hierarquia']))


def test_atributos_ausentes():
    print('\n4. Matéria mínima: atributo ausente vira None, não exceção')
    artigos = parse_article_xml((FIXTURES / 'dou_sample_minimo.xml').read_bytes())

    check('parseia sem erro', len(artigos) == 1, f'veio {len(artigos)}')
    a = artigos[0]
    check('pub_date ausente vira None', a['pub_date'] is None, repr(a['pub_date']))
    check('art_type ausente vira None', a['art_type'] is None, repr(a['art_type']))
    check('ementa ausente vira None', a['ementa'] is None, repr(a['ementa']))
    check('texto ausente vira string vazia', a['texto'] == '', repr(a['texto']))
    check('identifica presente mesmo assim', a['identifica'] == 'AVISO DE LICITAÇÃO', repr(a['identifica']))
    check('hash é gerado', bool(a['hash']) and len(a['hash']) == 64, repr(a['hash']))


def test_raw_xml_e_hash():
    print('\n5. raw_xml e hash')
    raw = (FIXTURES / 'dou_sample_article.xml').read_bytes()
    a = parse_article_xml(raw)[0]

    check('raw_xml guarda o <article>', a['raw_xml'].lstrip().startswith('<article'), repr(a['raw_xml'][:40]))
    check('hash tem 64 chars (sha256 hex)', len(a['hash']) == 64, repr(a['hash']))

    b = parse_article_xml(raw)[0]
    check('hash é determinístico', a['hash'] == b['hash'])

    alterado = raw.replace(b'Fica aprovado', b'Fica revogado')
    c = parse_article_xml(alterado)[0]
    check('conteúdo diferente muda o hash', a['hash'] != c['hash'])


def test_xml_invalido():
    print('\n6. XML inválido')
    try:
        parse_article_xml(b'<nao fechado')
        check('XML quebrado levanta exceção', False, 'não levantou')
    except Exception:
        check('XML quebrado levanta exceção', True)


def test_xml_hostil():
    print('\n7. XML hostil: bomba de entidades é recusada')
    # "billion laughs": com o parser da stdlib, a expansão recursiva de
    # entidades consome toda a memória do processo. defusedxml recusa antes.
    bomba = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE lolz [<!ENTITY lol "lol">'
        b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
        b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>'
        b'<articles><article id="1">&lol3;</article></articles>'
    )
    try:
        parse_article_xml(bomba)
        check('bomba de entidades é recusada', False, 'parseou sem reclamar')
    except EntitiesForbidden:
        check('bomba de entidades é recusada', True)
    except Exception as exc:
        check('bomba de entidades é recusada', False,
              f'levantou {exc.__class__.__name__} em vez de EntitiesForbidden')


def test_strip_html():
    print('\n7. strip_html')
    check('remove tags', strip_html('<p>Olá <b>mundo</b></p>') == 'Olá mundo', repr(strip_html('<p>Olá <b>mundo</b></p>')))
    check('None vira string vazia', strip_html(None) == '')
    check('string vazia continua vazia', strip_html('') == '')
    check('colapsa espaços', strip_html('<p>a</p>\n\n  <p>b</p>') == 'a b', repr(strip_html('<p>a</p>\n\n  <p>b</p>')))


def main():
    print('=' * 60)
    print('TESTES DO PARSER DE XML DO DOU')
    print('=' * 60)

    test_materia_completa()
    test_texto_e_html()
    test_acentuacao_iso8859()
    test_atributos_ausentes()
    test_raw_xml_e_hash()
    test_xml_invalido()
    test_xml_hostil()
    test_strip_html()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Rodar o teste e confirmar que falha**

```bash
uv run python tests/test_dou_xml_parser.py
```

Esperado: `ModuleNotFoundError: No module named 'app.services.dou_xml_parser'`.

- [ ] **Step 5: Implementar o parser**

Criar `app/services/dou_xml_parser.py`:

```python
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
```

- [ ] **Step 6: Declarar `defusedxml` como dependência direta**

Já está no `uv.lock` como transitiva, então nada será baixado — mas depender de um pacote que só existe porque outro o puxou quebra silenciosamente no dia em que esse outro trocar de dependências.

Em `pyproject.toml`, acrescentar à lista `dependencies`, ao lado de `"requests>=2.32.3"`:

```toml
    "defusedxml>=0.7.1",
```

Depois sincronizar e confirmar que nada novo foi instalado:

```bash
uv sync
```

Esperado: `uv` resolve sem baixar pacote novo (a versão 0.7.1 já está no lock).

- [ ] **Step 7: Rodar o teste e confirmar que passa**

```bash
uv run python tests/test_dou_xml_parser.py
```

Esperado: `✅ Todos os testes passaram`, exit 0 — inclusive o teste 7, que prova que a bomba de entidades é recusada.

- [ ] **Step 8: Commit**

```bash
git add app/services/dou_xml_parser.py tests/test_dou_xml_parser.py tests/fixtures/dou_sample_article.xml tests/fixtures/dou_sample_minimo.xml pyproject.toml uv.lock
git commit -m "feat(dou): parser puro do XML do Diário Oficial

Bytes de XML do INLABS -> dicts prontos para DouArticle. Sem rede, sem
banco, sem Flask: é a peça que muda se a Imprensa Nacional alterar o
schema, e a única que precisa mudar nesse caso.

Atributo ausente vira None em vez de exceção, e o encoding declarado no
XML (ISO-8859-1 ou UTF-8) é respeitado lendo bytes em vez de str.

Parse via defusedxml, não xml.etree: o XML vem de um ZIP baixado da rede,
e o parser da stdlib expande entidades — uma bomba 'billion laughs' dentro
do ZIP consumiria toda a memória do servidor."
```

---

## Task 2: Modelos e migração

**Files:**
- Modify: `app/models.py` (acrescentar ao final do arquivo)
- Create: `database/add_dou_tables.py`

**Interfaces:**
- Consumes: nada.
- Produces: `DouEdition`, `DouArticle`, `DouSyncRun` importáveis de `app.models`. Constantes `DouEdition.XML_SECTIONS`, `DouEdition.PDF_SECTIONS`, `DouEdition.SECTION_LABELS`.

- [ ] **Step 1: Acrescentar os modelos ao final de `app/models.py`**

Anexar ao final do arquivo (após `CommunicationSyncState`):

```python
class DouEdition(db.Model):
    """Tabela dou_editions - uma edição do DOU por (data, seção).

    **Sem law_firm_id, deliberadamente.** O DOU é dado público federal, byte a
    byte idêntico para todo escritório: replicá-lo por tenant duplicaria ~32 GB
    por ano por escritório sem proteger sigilo nenhum. É um catálogo público
    compartilhado. O que for específico de escritório em fases futuras
    (watchlist, marcação de leitura) entra em tabela própria, com law_firm_id.
    """
    __tablename__ = 'dou_editions'

    # Seções do XML: as terminadas em E são as edições extras, arquivos separados
    XML_SECTIONS = ('DO1', 'DO2', 'DO3', 'DO1E', 'DO2E', 'DO3E')
    # Seções do PDF assinado (minúsculas na URL) — o PDF já contempla as extras
    PDF_SECTIONS = ('do1', 'do2', 'do3')
    SECTION_LABELS = {
        'DO1': 'Seção 1 — Atos Normativos',
        'DO2': 'Seção 2 — Pessoal',
        'DO3': 'Seção 3 — Contratos e Licitações',
        'DO1E': 'Seção 1 — Edição Extra',
        'DO2E': 'Seção 2 — Edição Extra',
        'DO3E': 'Seção 3 — Edição Extra',
    }

    STATUS_PENDING = 'pending'
    STATUS_DOWNLOADED = 'downloaded'
    STATUS_PARSED = 'parsed'
    STATUS_NOT_PUBLISHED = 'not_published'
    STATUS_ERROR = 'error'

    __table_args__ = (
        db.UniqueConstraint('data_publicacao', 'secao', name='uq_dou_editions_data_secao'),
        db.Index('ix_dou_editions_data_secao', 'data_publicacao', 'secao'),
    )

    id = db.Column(db.Integer, primary_key=True)
    data_publicacao = db.Column(db.Date, nullable=False, index=True)
    secao = db.Column(db.String(10), nullable=False, index=True)

    qtd_materias = db.Column(db.Integer, default=0, nullable=False)

    zip_path = db.Column(db.String(500))        # relativo: uploads/dou/YYYY/MM/DD/...
    zip_bytes = db.Column(db.BigInteger)
    content_signature = db.Column(db.String(64))  # SHA-256 do ZIP — detecta republicação

    pdf_path = db.Column(db.String(500))        # nulo nas seções *E (o PDF cobre as extras)
    pdf_bytes = db.Column(db.BigInteger)
    pdf_purged_at = db.Column(db.DateTime)      # marcado quando a retenção poda o PDF

    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING, index=True)
    error_message = db.Column(db.Text)

    baixado_em = db.Column(db.DateTime)
    processado_em = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    articles = db.relationship(
        'DouArticle', back_populates='edition',
        cascade='all, delete-orphan', passive_deletes=True,
    )

    @property
    def secao_label(self):
        return self.SECTION_LABELS.get(self.secao, self.secao)

    @property
    def pdf_disponivel(self):
        return bool(self.pdf_path) and not self.pdf_purged_at

    def __repr__(self):
        return f'<DouEdition {self.data_publicacao} {self.secao} status={self.status}>'


class DouArticle(db.Model):
    """Tabela dou_articles - uma matéria publicada no DOU.

    Sem law_firm_id pelo mesmo motivo de DouEdition. ``raw_xml`` guarda o
    <article> verbatim: se o parser mapear um campo errado, o dado não se perde
    — reprocessa a partir do banco, sem rebaixar do INLABS.
    """
    __tablename__ = 'dou_articles'

    # A unicidade espelha exatamente a chave usada no upsert da ingestão. Se
    # divergirem, o lookup não encontra a linha, tenta INSERT e a constraint
    # barra — derrubando a edição inteira. Foi o que aconteceu quando a
    # unicidade estava só no `hash`: uma matéria idêntica reaparecendo em outra
    # edição (republicação, suplemento) colidia globalmente.
    # O `hash` fica como índice simples: serve para detectar mudança de
    # conteúdo, não para identificar a matéria.
    __table_args__ = (
        db.UniqueConstraint('edition_id', 'art_id', 'id_materia',
                            name='uq_dou_articles_edition_materia'),
        db.Index('ix_dou_articles_pubdate_pubname', 'pub_date', 'pub_name'),
        db.Index('ix_dou_articles_hash', 'hash'),
    )

    id = db.Column(db.Integer, primary_key=True)
    edition_id = db.Column(
        db.Integer, db.ForeignKey('dou_editions.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )

    # Chaves do INLABS
    art_id = db.Column(db.String(50), index=True)
    id_materia = db.Column(db.String(50), index=True)

    # Desnormalizados da edição, para filtro barato sem JOIN
    pub_name = db.Column(db.String(10), index=True)
    pub_date = db.Column(db.Date, index=True)

    edicao = db.Column(db.String(20))
    pagina = db.Column(db.String(20))
    pdf_page = db.Column(db.Text)               # URL da página no pesquisa.in.gov.br

    orgao_hierarquia = db.Column(db.String(500), index=True)   # artCategory
    identifica = db.Column(db.String(500))      # "PORTARIA Nº 1.234, DE ..."
    art_type = db.Column(db.String(100), index=True)
    art_class = db.Column(db.String(255))

    ementa = db.Column(db.Text)
    titulo = db.Column(db.Text)
    subtitulo = db.Column(db.Text)

    # Texto longo: o comprimento declarado faz o MySQL escolher LONGTEXT (o
    # TEXT padrão são 64 KB em bytes, e matéria de DOU passa disso com folga —
    # foi o que obrigou o ALTER de process_communications.texto no passado).
    texto = db.Column(db.Text(16777215))        # texto limpo, sem tags
    texto_html = db.Column(db.Text(16777215))   # conteúdo original de <Texto>
    raw_xml = db.Column(db.Text(16777215))      # o <article> inteiro, verbatim

    hash = db.Column(db.String(64), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    edition = db.relationship('DouEdition', back_populates='articles')

    def __repr__(self):
        return f'<DouArticle {self.pub_name} {self.pub_date} {self.identifica!r}>'


class DouSyncRun(db.Model):
    """Tabela dou_sync_runs - auditoria de cada execução da captura do DOU.

    Alimenta a aba Captura da tela. Sem law_firm_id: a captura é global.
    """
    __tablename__ = 'dou_sync_runs'

    MODO_CRON = 'cron'
    MODO_BACKFILL = 'backfill'
    MODO_MANUAL = 'manual'

    STATUS_RUNNING = 'running'
    STATUS_SUCCESS = 'success'
    STATUS_PARTIAL = 'partial'
    STATUS_ERROR = 'error'

    id = db.Column(db.Integer, primary_key=True)
    modo = db.Column(db.String(20), nullable=False, default=MODO_CRON, index=True)

    iniciado_em = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
    finalizado_em = db.Column(db.DateTime)

    data_inicial = db.Column(db.Date)
    data_final = db.Column(db.Date)

    edicoes_baixadas = db.Column(db.Integer, default=0, nullable=False)
    materias_inseridas = db.Column(db.Integer, default=0, nullable=False)
    materias_atualizadas = db.Column(db.Integer, default=0, nullable=False)
    nao_publicados = db.Column(db.Integer, default=0, nullable=False)  # 404 esperados
    erros = db.Column(db.Integer, default=0, nullable=False)

    status = db.Column(db.String(20), nullable=False, default=STATUS_RUNNING, index=True)
    detalhe_json = db.Column(db.JSON)           # por dia/seção, para diagnóstico

    def __repr__(self):
        return f'<DouSyncRun {self.modo} {self.iniciado_em} status={self.status}>'
```

- [ ] **Step 2: Verificar que os modelos importam e as tabelas nascem no SQLite**

```bash
uv run python -c "
from main import app
from app.models import db, DouEdition, DouArticle, DouSyncRun
with app.app_context():
    db.create_all()
    print('OK:', DouEdition.__tablename__, DouArticle.__tablename__, DouSyncRun.__tablename__)
    print('secoes XML:', DouEdition.XML_SECTIONS)
"
```

Esperado: imprime os três nomes de tabela e a tupla de seções, sem traceback.

- [ ] **Step 3: Escrever a migração**

Criar `database/add_dou_tables.py`, no padrão standalone e idempotente do projeto:

```python
"""
Cria as tabelas do módulo Diário Oficial: dou_editions, dou_articles e
dou_sync_runs.

Idempotente: tabela já existente é apenas reportada e pulada.

    uv run python database/add_dou_tables.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app
from app.models import db, DouEdition, DouArticle, DouSyncRun

# Ordem importa: dou_articles tem FK para dou_editions
MODELOS = (DouEdition, DouArticle, DouSyncRun)


def add_dou_tables():
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            existentes = set(inspector.get_table_names())

            criadas = []
            for modelo in MODELOS:
                nome = modelo.__tablename__
                if nome in existentes:
                    print(f"✓ A tabela '{nome}' já existe — pulando")
                    continue
                modelo.__table__.create(db.engine)
                criadas.append(nome)
                print(f"✓ Tabela '{nome}' criada com sucesso")

            if not criadas:
                print('\nNada a fazer: todas as tabelas já existiam.')
            else:
                print(f"\n✓ {len(criadas)} tabela(s) criada(s): {', '.join(criadas)}")

        except Exception as e:
            print(f'✗ Erro ao criar as tabelas do DOU: {str(e)}')
            raise


if __name__ == '__main__':
    print('Criando as tabelas do módulo Diário Oficial...')
    add_dou_tables()
    print('Migração concluída!')
```

- [ ] **Step 4: Rodar a migração duas vezes para provar a idempotência**

```bash
uv run python database/add_dou_tables.py
uv run python database/add_dou_tables.py
```

Esperado: na primeira execução, "criada com sucesso" (ou "já existe", se o `db.create_all()` do Step 2 já as criou); na segunda, **todas** reportadas como "já existe" e a mensagem "Nada a fazer". Nenhum traceback nas duas.

- [ ] **Step 5: Commit**

```bash
git add app/models.py database/add_dou_tables.py
git commit -m "feat(dou): modelos DouEdition, DouArticle e DouSyncRun + migração

Catálogo global do DOU: as três tabelas não têm law_firm_id, exceção
consciente ao invariante multi-tenant do projeto. O DOU é dado público
federal idêntico para todo escritório; replicá-lo por tenant custaria
~32 GB/ano por escritório sem proteger sigilo algum.

hash UNIQUE em dou_articles e content_signature em dou_editions são o que
tornam reprocessar um dia seguro (UPDATE, nunca INSERT duplicado)."
```

---

## Task 3: Client do INLABS

**Files:**
- Create: `app/services/inlabs_client.py`
- Test: `tests/test_inlabs_client.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `is_configured() -> bool`
  - `InlabsClient(email=None, password=None, timeout=None)` com `login() -> None`, `download_xml_zip(data: date, secao: str) -> bytes | None`, `download_pdf(data: date, secao: str) -> bytes | None` (retorno `None` = HTTP 404 = não publicado)
  - Exceções `InlabsError`, `InlabsNotConfigured`, `InlabsAuthError`
  - `xml_filename(data, secao) -> str`, `pdf_filename(data, secao) -> str`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_inlabs_client.py`. Testa montagem de URL, configuração e tratamento de status **sem tocar a rede** — um transporte falso substitui a sessão HTTP.

```python
#!/usr/bin/env python3
"""
Testes do client do INLABS (app/services/inlabs_client.py).

Não toca a rede: a sessão HTTP é substituída por um duplo que devolve
respostas programadas. Cobre montagem de URL, headers obrigatórios,
404 como estado normal e degradação sem credenciais.

    uv run python tests/test_inlabs_client.py
"""

import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import inlabs_client as ic

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


class FakeResponse:
    def __init__(self, status_code=200, content=b'', cookies=None):
        self.status_code = status_code
        self.content = content
        self.cookies = cookies or {}


class FakeSession:
    """Duplo da requests.Session: registra chamadas e devolve respostas fixas."""

    def __init__(self, respostas=None, cookie='COOKIE-FAKE'):
        self.chamadas = []
        self.respostas = respostas or {}
        self.cookies = {}
        self._cookie = cookie

    def request(self, method, url, **kwargs):
        self.chamadas.append({'method': method, 'url': url, **kwargs})
        if 'logar.php' in url:
            if self._cookie is not None:
                self.cookies['inlabs_session_cookie'] = self._cookie
            return FakeResponse(200)
        return self.respostas.get(url, FakeResponse(404))


def test_nomes_de_arquivo():
    print('\n1. Montagem dos nomes de arquivo')
    d = date(2026, 8, 10)
    check('XML usa hífen e seção maiúscula',
          ic.xml_filename(d, 'DO1') == '2026-08-10-DO1.zip', ic.xml_filename(d, 'DO1'))
    check('XML de edição extra',
          ic.xml_filename(d, 'DO1E') == '2026-08-10-DO1E.zip', ic.xml_filename(d, 'DO1E'))
    check('PDF usa underscore e seção minúscula',
          ic.pdf_filename(d, 'do1') == '2026_08_10_ASSINADO_do1.pdf', ic.pdf_filename(d, 'do1'))
    check('PDF normaliza seção passada em maiúscula',
          ic.pdf_filename(d, 'DO2') == '2026_08_10_ASSINADO_do2.pdf', ic.pdf_filename(d, 'DO2'))


def test_sem_credenciais():
    print('\n2. Degradação sem credenciais')
    antigo_email = os.environ.pop('INLABS_EMAIL', None)
    antiga_senha = os.environ.pop('INLABS_PASSWORD', None)
    try:
        check('is_configured() é False sem .env', ic.is_configured() is False)
        try:
            ic.InlabsClient().login()
            check('login sem credenciais levanta InlabsNotConfigured', False, 'não levantou')
        except ic.InlabsNotConfigured:
            check('login sem credenciais levanta InlabsNotConfigured', True)
    finally:
        if antigo_email:
            os.environ['INLABS_EMAIL'] = antigo_email
        if antiga_senha:
            os.environ['INLABS_PASSWORD'] = antiga_senha


def test_login_e_headers():
    print('\n3. Login e headers obrigatórios do download')
    d = date(2026, 8, 10)
    url = f'{ic.URL_DOWNLOAD}2026-08-10&dl=2026-08-10-DO1.zip'
    fake = FakeSession(respostas={url: FakeResponse(200, b'PK\x03\x04conteudo')})

    client = ic.InlabsClient(email='a@b.com', password='x')
    client._session = fake
    conteudo = client.download_xml_zip(d, 'DO1')

    check('devolve os bytes do ZIP', conteudo == b'PK\x03\x04conteudo', repr(conteudo))
    check('fez login antes de baixar', any('logar.php' in c['url'] for c in fake.chamadas))

    login = next(c for c in fake.chamadas if 'logar.php' in c['url'])
    check('login é POST', login['method'] == 'POST', login['method'])
    check('login manda email e password',
          login['data'] == {'email': 'a@b.com', 'password': 'x'}, repr(login.get('data')))

    download = next(c for c in fake.chamadas if 'dl=' in c['url'])
    headers = download['headers']
    check('manda o cookie da sessão',
          headers['Cookie'] == 'inlabs_session_cookie=COOKIE-FAKE', repr(headers.get('Cookie')))
    check("manda o header origem='736372697074'",
          headers['origem'] == '736372697074', repr(headers.get('origem')))
    check('download tem timeout', download.get('timeout') is not None)


def test_404_nao_e_erro():
    print('\n4. HTTP 404 é estado normal, não exceção')
    fake = FakeSession()  # tudo que não for login devolve 404
    client = ic.InlabsClient(email='a@b.com', password='x')
    client._session = fake

    resultado = client.download_xml_zip(date(2026, 8, 10), 'DO1E')
    check('404 devolve None em vez de levantar', resultado is None, repr(resultado))


def test_login_sem_cookie():
    print('\n5. Credencial inválida (login não devolve cookie)')
    fake = FakeSession(cookie=None)
    client = ic.InlabsClient(email='a@b.com', password='errada')
    client._session = fake
    try:
        client.login()
        check('login sem cookie levanta InlabsAuthError', False, 'não levantou')
    except ic.InlabsAuthError:
        check('login sem cookie levanta InlabsAuthError', True)


def main():
    print('=' * 60)
    print('TESTES DO CLIENT DO INLABS')
    print('=' * 60)

    test_nomes_de_arquivo()
    test_sem_credenciais()
    test_login_e_headers()
    test_404_nao_e_erro()
    test_login_sem_cookie()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

```bash
uv run python tests/test_inlabs_client.py
```

Esperado: `ModuleNotFoundError: No module named 'app.services.inlabs_client'`.

- [ ] **Step 3: Implementar o client**

Criar `app/services/inlabs_client.py`:

```python
"""
Client do INLABS (Imprensa Nacional) — único ponto do sistema que fala com
https://inlabs.in.gov.br.

Mecanismo confirmado contra a implementação de referência oficial da Imprensa
Nacional (github.com/Imprensa-Nacional/inlabs, public/python/):

  1. POST /logar.php com form {email, password} → cookie inlabs_session_cookie
  2. GET /index.php?p=YYYY-MM-DD&dl=<arquivo> com os headers Cookie e
     origem=736372697074
  3. XML:  YYYY-MM-DD-DO1.zip     (seções DO1 DO2 DO3 DO1E DO2E DO3E)
     PDF:  YYYY_MM_DD_ASSINADO_do1.pdf  (do1 do2 do3; já contempla as extras)
  4. HTTP 404 = não publicado naquele dia/seção. É estado normal, não erro.

Três defeitos do script oficial que este client corrige de propósito:
  - lá, login() chama a si mesmo sem teto em ConnectionError (recursão infinita
    se a rede cair) → aqui, retry com limite e backoff;
  - lá, nenhuma requisição tem timeout (uma conexão presa trava o cron) → aqui,
    timeout explícito em tudo;
  - lá, há exit() dentro da função de download → aqui, erro vira exceção e quem
    chama decide.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date

import requests

logger = logging.getLogger(__name__)

URL_LOGIN = 'https://inlabs.in.gov.br/logar.php'
URL_DOWNLOAD = 'https://inlabs.in.gov.br/index.php?p='

# Marca que a Imprensa Nacional espera nos downloads automatizados
# ('736372697074' é "script" em hexadecimal)
ORIGEM_SCRIPT = '736372697074'

DEFAULT_TIMEOUT = int(os.environ.get('DOU_DOWNLOAD_TIMEOUT', '120'))
MAX_RETRIES = 3
BACKOFF_BASE = 2  # segundos: 2, 4, 8


class InlabsError(Exception):
    """Falha genérica ao falar com o INLABS."""


class InlabsNotConfigured(InlabsError):
    """INLABS_EMAIL / INLABS_PASSWORD ausentes no .env."""


class InlabsAuthError(InlabsError):
    """Login recusado: o INLABS não devolveu o cookie de sessão."""


def is_configured() -> bool:
    """True quando há credenciais no ambiente. Sem elas o módulo não roda."""
    return bool(os.environ.get('INLABS_EMAIL') and os.environ.get('INLABS_PASSWORD'))


def xml_filename(data: date, secao: str) -> str:
    """2026-08-10 + 'DO1' → '2026-08-10-DO1.zip' (seção em MAIÚSCULAS)."""
    return f"{data.strftime('%Y-%m-%d')}-{secao.upper()}.zip"


def pdf_filename(data: date, secao: str) -> str:
    """2026-08-10 + 'do1' → '2026_08_10_ASSINADO_do1.pdf' (seção em minúsculas)."""
    return f"{data.strftime('%Y_%m_%d')}_ASSINADO_{secao.lower()}.pdf"


class InlabsClient:
    """Sessão autenticada com o INLABS. Reutilize a instância entre downloads."""

    def __init__(self, email: str | None = None, password: str | None = None,
                 timeout: int | None = None):
        self._email = email or os.environ.get('INLABS_EMAIL')
        self._password = password or os.environ.get('INLABS_PASSWORD')
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._session = requests.Session()
        self._cookie: str | None = None

    # ------------------------------------------------------------------ login

    def login(self) -> None:
        """Autentica e guarda o cookie de sessão. Idempotente por instância."""
        if not self._email or not self._password:
            raise InlabsNotConfigured(
                'INLABS_EMAIL e INLABS_PASSWORD não configurados no .env'
            )

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        payload = {'email': self._email, 'password': self._password}

        self._request_com_retry('POST', URL_LOGIN, headers=headers, data=payload)

        cookie = self._session.cookies.get('inlabs_session_cookie')
        if not cookie:
            raise InlabsAuthError(
                'INLABS não devolveu inlabs_session_cookie — verifique as credenciais'
            )
        self._cookie = cookie
        logger.info('INLABS: sessão autenticada')

    def _garantir_sessao(self) -> None:
        if not self._cookie:
            self.login()

    # --------------------------------------------------------------- download

    def download_xml_zip(self, data: date, secao: str) -> bytes | None:
        """Baixa o ZIP de XML da (data, seção). None quando não publicado (404)."""
        return self._download(data, xml_filename(data, secao))

    def download_pdf(self, data: date, secao: str) -> bytes | None:
        """Baixa o PDF assinado da (data, seção). None quando não publicado (404)."""
        return self._download(data, pdf_filename(data, secao))

    def _download(self, data: date, arquivo: str) -> bytes | None:
        self._garantir_sessao()
        url = f"{URL_DOWNLOAD}{data.strftime('%Y-%m-%d')}&dl={arquivo}"

        resposta = self._request_com_retry('GET', url, headers=self._headers_download())

        # Cookie expirado no meio de um backfill longo: relogin transparente,
        # uma única retentativa. Segunda falha propaga.
        if resposta.status_code in (401, 403):
            logger.info('INLABS: sessão expirada, refazendo login')
            self._cookie = None
            self.login()
            resposta = self._request_com_retry('GET', url, headers=self._headers_download())

        if resposta.status_code == 404:
            logger.info('INLABS: %s não publicado', arquivo)
            return None
        if resposta.status_code != 200:
            raise InlabsError(f'INLABS devolveu HTTP {resposta.status_code} para {arquivo}')

        return resposta.content

    def _headers_download(self) -> dict:
        return {'Cookie': f'inlabs_session_cookie={self._cookie}', 'origem': ORIGEM_SCRIPT}

    # ---------------------------------------------------------------- retry

    def _request_com_retry(self, method: str, url: str, **kwargs):
        """Retry com teto e backoff exponencial.

        O script oficial recorre infinitamente em ConnectionError; aqui a
        recursão vira laço com limite, e o erro final propaga em vez de travar.
        """
        kwargs.setdefault('timeout', self._timeout)
        ultimo_erro = None

        for tentativa in range(1, MAX_RETRIES + 1):
            try:
                return self._session.request(method, url, **kwargs)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as exc:
                ultimo_erro = exc
                if tentativa == MAX_RETRIES:
                    break
                espera = BACKOFF_BASE ** tentativa
                logger.warning(
                    'INLABS: falha de rede (%s), tentativa %d/%d, aguardando %ds',
                    exc.__class__.__name__, tentativa, MAX_RETRIES, espera,
                )
                time.sleep(espera)

        raise InlabsError(
            f'INLABS inacessível após {MAX_RETRIES} tentativas: {ultimo_erro}'
        ) from ultimo_erro
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

```bash
uv run python tests/test_inlabs_client.py
```

Esperado: `✅ Todos os testes passaram`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add app/services/inlabs_client.py tests/test_inlabs_client.py
git commit -m "feat(dou): client do INLABS com retry, timeout e relogin

Único ponto do sistema que fala com inlabs.in.gov.br. Mecanismo conferido
contra a implementação de referência oficial da Imprensa Nacional.

Corrige três defeitos do script oficial de propósito: a recursão infinita
de login() em ConnectionError vira laço com teto; toda requisição ganha
timeout; e o exit() dentro do download vira exceção. HTTP 404 devolve None
— é 'não publicado', não erro."
```

---

## Task 4: Serviço de ingestão

Orquestra: client → disco → parser → upsert → auditoria. É o único módulo que conhece as três camadas.

**Files:**
- Create: `app/services/dou_ingestion_service.py`
- Test: `tests/test_dou_ingestion.py`

**Interfaces:**
- Consumes: `inlabs_client.InlabsClient`, `dou_xml_parser.parse_article_xml`, modelos `DouEdition`/`DouArticle`/`DouSyncRun`.
- Produces:
  - `storage_dir(data: date) -> Path` — caminho **relativo** `uploads/dou/YYYY/MM/DD`
  - `ingest_zip_bytes(edition: DouEdition, zip_bytes: bytes) -> tuple[int, int]` — `(inseridas, atualizadas)`
  - `ingest_date(data, secoes=None, with_pdf=True, dry_run=False, client=None) -> dict`
  - `sync_recent(recheck_days=None, hoje=None, with_pdf=True, dry_run=False, modo='cron') -> DouSyncRun`
  - `backfill(desde: date, ate: date | None = None, with_pdf=True, dry_run=False) -> DouSyncRun`
  - `purge_old_pdfs(retention_months=None) -> int`
  - `secoes_configuradas() -> tuple[str, ...]`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_dou_ingestion.py`. Usa um client falso: nenhuma rede envolvida.

```python
#!/usr/bin/env python3
"""
Testes da ingestão do DOU (app/services/dou_ingestion_service.py).

Não toca a rede: um client falso devolve ZIPs montados em memória. Cobre o
que mais importa no módulo — idempotência e republicação.

    uv run python tests/test_dou_ingestion.py
"""

import io
import sys
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, DouEdition, DouArticle, DouSyncRun
from app.services import dou_ingestion_service as ingestion

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
DATA_TESTE = date(2026, 8, 10)

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def montar_zip(*xmls: bytes) -> bytes:
    """Monta um ZIP em memória com um arquivo .xml por matéria, como o INLABS."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for i, conteudo in enumerate(xmls):
            z.writestr(f'materia_{i}.xml', conteudo)
    return buffer.getvalue()


class FakeClient:
    """Duplo do InlabsClient: devolve ZIPs fixos, sem rede."""

    def __init__(self, zips: dict, pdfs: dict | None = None):
        self.zips = zips        # {(data, secao): bytes | None}
        self.pdfs = pdfs or {}

    def login(self):
        pass

    def download_xml_zip(self, data, secao):
        return self.zips.get((data, secao))

    def download_pdf(self, data, secao):
        return self.pdfs.get((data, secao.lower()))


def limpar_dados_de_teste():
    """Remove qualquer resíduo da data de teste."""
    edicoes = DouEdition.query.filter_by(data_publicacao=DATA_TESTE).all()
    for e in edicoes:
        db.session.delete(e)
    DouSyncRun.query.filter_by(modo=DouSyncRun.MODO_MANUAL).delete()
    db.session.commit()


def test_ingestao_basica():
    print('\n1. Ingestão de um ZIP com duas matérias')
    limpar_dados_de_teste()

    xml_a = (FIXTURES / 'dou_sample_article.xml').read_bytes()
    xml_b = (FIXTURES / 'dou_sample_minimo.xml').read_bytes()
    zip_bytes = montar_zip(xml_a, xml_b)

    client = FakeClient({(DATA_TESTE, 'DO1'): zip_bytes})
    resultado = ingestion.ingest_date(DATA_TESTE, secoes=['DO1'], with_pdf=False, client=client)

    check('relata 2 matérias inseridas',
          resultado['materias_inseridas'] == 2, str(resultado))
    check('relata 0 atualizadas', resultado['materias_atualizadas'] == 0, str(resultado))

    edicao = DouEdition.query.filter_by(data_publicacao=DATA_TESTE, secao='DO1').first()
    check('criou a edição', edicao is not None)
    check('status ficou parsed', edicao.status == DouEdition.STATUS_PARSED, edicao.status)
    check('qtd_materias = 2', edicao.qtd_materias == 2, str(edicao.qtd_materias))
    check('gravou content_signature', bool(edicao.content_signature))
    check('zip_path é relativo',
          edicao.zip_path.startswith('uploads/dou/'), repr(edicao.zip_path))
    check('arquivo existe em disco', Path(edicao.zip_path).exists(), edicao.zip_path)

    artigos = DouArticle.query.filter_by(edition_id=edicao.id).all()
    check('2 matérias no banco', len(artigos) == 2, str(len(artigos)))
    check('desnormalizou pub_date', all(a.pub_date is not None or a.pub_name == 'DO3' for a in artigos))


def test_idempotencia():
    print('\n2. Idempotência: reingerir o mesmo ZIP não duplica')
    xml_a = (FIXTURES / 'dou_sample_article.xml').read_bytes()
    zip_bytes = montar_zip(xml_a)

    client = FakeClient({(DATA_TESTE, 'DO2'): zip_bytes})
    ingestion.ingest_date(DATA_TESTE, secoes=['DO2'], with_pdf=False, client=client)
    antes = DouArticle.query.join(DouEdition).filter(
        DouEdition.data_publicacao == DATA_TESTE, DouEdition.secao == 'DO2'
    ).count()

    segundo = ingestion.ingest_date(DATA_TESTE, secoes=['DO2'], with_pdf=False, client=client)
    depois = DouArticle.query.join(DouEdition).filter(
        DouEdition.data_publicacao == DATA_TESTE, DouEdition.secao == 'DO2'
    ).count()

    check('mesma contagem de matérias', antes == depois, f'{antes} → {depois}')
    check('nada foi inserido na segunda vez',
          segundo['materias_inseridas'] == 0, str(segundo))
    check('assinatura igual pula o reprocesso',
          segundo.get('inalterado') is True, str(segundo))


def test_republicacao():
    print('\n3. Republicação: conteúdo diferente atualiza, não duplica')
    xml_a = (FIXTURES / 'dou_sample_article.xml').read_bytes()
    xml_alterado = xml_a.replace(b'Fica aprovado', b'Fica revogado')

    client1 = FakeClient({(DATA_TESTE, 'DO3'): montar_zip(xml_a)})
    ingestion.ingest_date(DATA_TESTE, secoes=['DO3'], with_pdf=False, client=client1)

    client2 = FakeClient({(DATA_TESTE, 'DO3'): montar_zip(xml_alterado)})
    resultado = ingestion.ingest_date(DATA_TESTE, secoes=['DO3'], with_pdf=False, client=client2)

    edicao = DouEdition.query.filter_by(data_publicacao=DATA_TESTE, secao='DO3').first()
    artigos = DouArticle.query.filter_by(edition_id=edicao.id).all()

    check('continua com 1 matéria (UPDATE, não INSERT)', len(artigos) == 1, str(len(artigos)))
    check('relata 1 atualizada', resultado['materias_atualizadas'] == 1, str(resultado))
    check('texto novo foi gravado', 'revogado' in artigos[0].texto, artigos[0].texto[:80])
    check('hash mudou junto', artigos[0].hash is not None)


def test_nao_publicado():
    print('\n4. Seção não publicada (404) não é erro')
    client = FakeClient({})  # tudo devolve None
    resultado = ingestion.ingest_date(DATA_TESTE, secoes=['DO1E'], with_pdf=False, client=client)

    check('contabiliza como não publicado',
          resultado['nao_publicados'] == 1, str(resultado))
    check('não conta como erro', resultado['erros'] == 0, str(resultado))

    edicao = DouEdition.query.filter_by(data_publicacao=DATA_TESTE, secao='DO1E').first()
    check('registra a edição como not_published',
          edicao is not None and edicao.status == DouEdition.STATUS_NOT_PUBLISHED,
          edicao.status if edicao else 'sem edição')


def test_dry_run():
    print('\n5. dry-run não grava nada')
    limpar_dados_de_teste()
    xml_a = (FIXTURES / 'dou_sample_article.xml').read_bytes()
    client = FakeClient({(DATA_TESTE, 'DO1'): montar_zip(xml_a)})

    ingestion.ingest_date(DATA_TESTE, secoes=['DO1'], with_pdf=False,
                          dry_run=True, client=client)

    check('nenhuma edição criada',
          DouEdition.query.filter_by(data_publicacao=DATA_TESTE).count() == 0)


def test_storage_dir():
    print('\n6. Caminho de armazenamento')
    caminho = ingestion.storage_dir(date(2026, 8, 10))
    check('caminho relativo por ano/mês/dia',
          str(caminho) == 'uploads/dou/2026/08/10', str(caminho))
    check('não é absoluto', not caminho.is_absolute(), str(caminho))


def main():
    print('=' * 60)
    print('TESTES DA INGESTÃO DO DOU')
    print('=' * 60)

    with app.app_context():
        db.create_all()
        test_ingestao_basica()
        test_idempotencia()
        test_republicacao()
        test_nao_publicado()
        test_dry_run()
        test_storage_dir()
        limpar_dados_de_teste()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

```bash
uv run python tests/test_dou_ingestion.py
```

Esperado: `ModuleNotFoundError: No module named 'app.services.dou_ingestion_service'`.

- [ ] **Step 3: Implementar o serviço de ingestão**

Criar `app/services/dou_ingestion_service.py`:

```python
"""
Ingestão do Diário Oficial da União.

Orquestra as três camadas: pede bytes ao inlabs_client, grava em disco, chama o
dou_xml_parser e faz upsert no banco, registrando a execução em DouSyncRun.

Duas propriedades sustentam o módulo:

  * **Idempotência** — o hash da matéria é UNIQUE e o upsert casa por
    (edition_id, art_id, id_materia). Reprocessar um dia é UPDATE, nunca
    INSERT duplicado.
  * **Janela de reverificação** — o INLABS reescreve datas passadas (edições
    republicadas, suplementos acrescentados depois). Um cron que só olha "hoje"
    perde isso. Toda execução reconfere os últimos DOU_RECHECK_DAYS dias
    comparando o SHA-256 do ZIP com content_signature.

A ordem em ingest_zip_bytes importa: o hash é calculado **antes** de gravar o
arquivo. Gravar antes de comparar sobrescreveria um arquivo íntegro por um
download possivelmente truncado.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import defusedxml.ElementTree as ElementTree
from defusedxml.common import DefusedXmlException

from app.models import db, DouEdition, DouArticle, DouSyncRun
from app.services import inlabs_client
from app.services.dou_xml_parser import parse_article_xml

logger = logging.getLogger(__name__)

BASE_UPLOAD_DIR = Path('uploads/dou')
DEFAULT_RECHECK_DAYS = 7
DEFAULT_PDF_RETENTION_MONTHS = 24


def secoes_configuradas() -> tuple[str, ...]:
    """Seções a capturar. DOU_SECOES no .env sobrescreve; padrão é todas."""
    bruto = os.environ.get('DOU_SECOES', '').strip()
    if not bruto:
        return DouEdition.XML_SECTIONS
    secoes = tuple(s.strip().upper() for s in bruto.split(',') if s.strip())
    return secoes or DouEdition.XML_SECTIONS


def recheck_days() -> int:
    try:
        return int(os.environ.get('DOU_RECHECK_DAYS', DEFAULT_RECHECK_DAYS))
    except ValueError:
        return DEFAULT_RECHECK_DAYS


def storage_dir(data: date) -> Path:
    """uploads/dou/YYYY/MM/DD — sempre relativo (dev e produção têm raízes diferentes)."""
    return BASE_UPLOAD_DIR / data.strftime('%Y') / data.strftime('%m') / data.strftime('%d')


def _pdf_secao(secao: str) -> str | None:
    """DO1 → do1. Seções extras (DO1E) não têm PDF próprio: o do1 já as contempla."""
    secao = secao.upper()
    if secao.endswith('E'):
        return None
    return secao.lower() if secao.lower() in DouEdition.PDF_SECTIONS else None


# ----------------------------------------------------------------- ingestão

def ingest_zip_bytes(edition: DouEdition, zip_bytes: bytes) -> tuple[int, int]:
    """Descompacta o ZIP, parseia cada XML e faz upsert. Devolve (inseridas, atualizadas).

    Um XML malformado — ou hostil — não derruba a edição inteira: a matéria é
    registrada em log e o laço segue para a próxima.
    """
    inseridas = atualizadas = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for nome in z.namelist():
            if not nome.lower().endswith('.xml'):
                continue
            try:
                artigos = parse_article_xml(z.read(nome))
            except ElementTree.ParseError as exc:
                logger.warning('DOU: XML inválido em %s (%s) — pulando', nome, exc)
                continue
            except DefusedXmlException as exc:
                # DTD ou expansão de entidades: XML hostil, não apenas quebrado.
                # Registra em nível de erro para aparecer no log de produção.
                logger.error('DOU: XML hostil recusado em %s (%s) — pulando', nome, exc)
                continue

            for dados in artigos:
                existente = DouArticle.query.filter_by(
                    edition_id=edition.id,
                    art_id=dados['art_id'],
                    id_materia=dados['id_materia'],
                ).first()

                if existente is None:
                    db.session.add(DouArticle(edition_id=edition.id, **dados))
                    inseridas += 1
                elif existente.hash != dados['hash']:
                    for campo, valor in dados.items():
                        setattr(existente, campo, valor)
                    atualizadas += 1

    return inseridas, atualizadas


def _baixar_pdf(client, data: date, secao: str, edition: DouEdition, destino: Path) -> None:
    """Baixa o PDF assinado da seção, quando ela tem um. Falha aqui não derruba o XML."""
    pdf_secao = _pdf_secao(secao)
    if not pdf_secao:
        return
    try:
        conteudo = client.download_pdf(data, pdf_secao)
    except inlabs_client.InlabsError as exc:
        logger.warning('DOU: PDF %s %s falhou (%s) — XML preservado', data, secao, exc)
        return
    if conteudo is None:
        return

    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / inlabs_client.pdf_filename(data, pdf_secao)
    caminho.write_bytes(conteudo)
    edition.pdf_path = str(caminho)
    edition.pdf_bytes = len(conteudo)
    edition.pdf_purged_at = None


def ingest_date(data: date, secoes=None, with_pdf: bool = True,
                dry_run: bool = False, client=None) -> dict:
    """Captura uma data inteira. Devolve o resumo agregado das seções.

    Commit por (dia, seção): uma execução interrompida retoma sem perder o que
    já fez e sem duplicar.
    """
    secoes = tuple(secoes) if secoes else secoes_configuradas()
    client = client or inlabs_client.InlabsClient()

    resumo = {
        'data': data.isoformat(), 'edicoes_baixadas': 0, 'materias_inseridas': 0,
        'materias_atualizadas': 0, 'nao_publicados': 0, 'erros': 0,
        'inalterado': True, 'detalhes': [],
    }

    for secao in secoes:
        try:
            conteudo = client.download_xml_zip(data, secao)
        except inlabs_client.InlabsError as exc:
            logger.error('DOU: download de %s %s falhou: %s', data, secao, exc)
            resumo['erros'] += 1
            resumo['inalterado'] = False
            if not dry_run:
                _marcar_erro(data, secao, str(exc))
            resumo['detalhes'].append({'secao': secao, 'resultado': 'erro', 'erro': str(exc)})
            continue

        if conteudo is None:
            resumo['nao_publicados'] += 1
            if not dry_run:
                _marcar_status(data, secao, DouEdition.STATUS_NOT_PUBLISHED)
            resumo['detalhes'].append({'secao': secao, 'resultado': 'nao_publicado'})
            continue

        assinatura = hashlib.sha256(conteudo).hexdigest()
        edition = _obter_edicao(data, secao) if not dry_run else None

        # Assinatura igual → o ZIP não mudou. Descarta sem tocar disco nem banco.
        if edition is not None and edition.content_signature == assinatura \
                and edition.status == DouEdition.STATUS_PARSED:
            resumo['detalhes'].append({'secao': secao, 'resultado': 'inalterado'})
            continue

        resumo['inalterado'] = False
        resumo['edicoes_baixadas'] += 1

        if dry_run:
            resumo['detalhes'].append({'secao': secao, 'resultado': 'baixaria',
                                       'bytes': len(conteudo)})
            continue

        try:
            destino = storage_dir(data)
            destino.mkdir(parents=True, exist_ok=True)
            caminho_zip = destino / inlabs_client.xml_filename(data, secao)
            caminho_zip.write_bytes(conteudo)

            edition.zip_path = str(caminho_zip)
            edition.zip_bytes = len(conteudo)
            edition.content_signature = assinatura
            edition.status = DouEdition.STATUS_DOWNLOADED
            edition.baixado_em = datetime.now()
            edition.error_message = None
            db.session.flush()

            inseridas, atualizadas = ingest_zip_bytes(edition, conteudo)

            # flush antes de contar: as matérias novas ainda estão pendentes na
            # sessão e não apareceriam no COUNT
            db.session.flush()
            edition.qtd_materias = DouArticle.query.filter_by(edition_id=edition.id).count()
            edition.status = DouEdition.STATUS_PARSED
            edition.processado_em = datetime.now()

            if with_pdf:
                _baixar_pdf(client, data, secao, edition, destino)

            db.session.commit()

            resumo['materias_inseridas'] += inseridas
            resumo['materias_atualizadas'] += atualizadas
            resumo['detalhes'].append({
                'secao': secao, 'resultado': 'ok',
                'inseridas': inseridas, 'atualizadas': atualizadas,
            })

        except Exception as exc:  # noqa: BLE001 — erro de uma seção não derruba as outras
            db.session.rollback()
            logger.exception('DOU: falha ao processar %s %s', data, secao)
            resumo['erros'] += 1
            _marcar_erro(data, secao, str(exc))
            resumo['detalhes'].append({'secao': secao, 'resultado': 'erro', 'erro': str(exc)})

    return resumo


def _obter_edicao(data: date, secao: str) -> DouEdition:
    edition = DouEdition.query.filter_by(data_publicacao=data, secao=secao).first()
    if edition is None:
        edition = DouEdition(data_publicacao=data, secao=secao,
                             status=DouEdition.STATUS_PENDING)
        db.session.add(edition)
        db.session.flush()
    return edition


def _marcar_status(data: date, secao: str, status: str) -> None:
    edition = _obter_edicao(data, secao)
    # Nunca rebaixar uma edição já processada para "não publicado"
    if edition.status != DouEdition.STATUS_PARSED:
        edition.status = status
    db.session.commit()


def _marcar_erro(data: date, secao: str, mensagem: str) -> None:
    """Falha nunca é registrada como sucesso: a próxima execução tenta de novo."""
    try:
        edition = _obter_edicao(data, secao)
        edition.status = DouEdition.STATUS_ERROR
        edition.error_message = mensagem[:2000]
        db.session.commit()
    except Exception:
        db.session.rollback()


# ---------------------------------------------------------------- execuções

def _executar(modo: str, datas, with_pdf: bool, dry_run: bool) -> DouSyncRun:
    """Roda a ingestão sobre uma lista de datas, com auditoria em DouSyncRun."""
    # Os contadores são inicializados explicitamente, e não pelo default da
    # coluna: em dry-run o objeto nunca é gravado, o default do INSERT nunca
    # roda, e os atributos ficariam None — o primeiro `+=` estouraria TypeError.
    run = DouSyncRun(modo=modo, status=DouSyncRun.STATUS_RUNNING,
                     data_inicial=min(datas) if datas else None,
                     data_final=max(datas) if datas else None,
                     edicoes_baixadas=0, materias_inseridas=0,
                     materias_atualizadas=0, nao_publicados=0, erros=0)
    if not dry_run:
        db.session.add(run)
        db.session.commit()

    client = inlabs_client.InlabsClient()
    detalhes = []

    try:
        client.login()
    except inlabs_client.InlabsError as exc:
        logger.error('DOU: login no INLABS falhou: %s', exc)
        run.status = DouSyncRun.STATUS_ERROR
        run.erros = 1
        run.finalizado_em = datetime.now()
        run.detalhe_json = {'erro': str(exc)}
        if not dry_run:
            db.session.commit()
        return run

    for data in datas:
        resumo = ingest_date(data, with_pdf=with_pdf, dry_run=dry_run, client=client)
        run.edicoes_baixadas += resumo['edicoes_baixadas']
        run.materias_inseridas += resumo['materias_inseridas']
        run.materias_atualizadas += resumo['materias_atualizadas']
        run.nao_publicados += resumo['nao_publicados']
        run.erros += resumo['erros']
        detalhes.append(resumo)

    run.finalizado_em = datetime.now()
    run.detalhe_json = {'dias': detalhes}
    if run.erros == 0:
        run.status = DouSyncRun.STATUS_SUCCESS
    elif run.materias_inseridas or run.materias_atualizadas or run.edicoes_baixadas:
        run.status = DouSyncRun.STATUS_PARTIAL
    else:
        run.status = DouSyncRun.STATUS_ERROR

    if not dry_run:
        db.session.commit()
    return run


def sync_recent(recheck: int | None = None, hoje: date | None = None,
                with_pdf: bool = True, dry_run: bool = False,
                modo: str = DouSyncRun.MODO_CRON) -> DouSyncRun:
    """Modo do cron: hoje mais a janela de reverificação dos dias anteriores."""
    hoje = hoje or date.today()
    janela = recheck if recheck is not None else recheck_days()
    datas = [hoje - timedelta(days=i) for i in range(janela + 1)]
    return _executar(modo, sorted(datas), with_pdf, dry_run)


def backfill(desde: date, ate: date | None = None,
             with_pdf: bool = True, dry_run: bool = False) -> DouSyncRun:
    """Resgate histórico. Commit por dia — interrompível e retomável."""
    ate = ate or date.today()
    datas = []
    cursor = desde
    while cursor <= ate:
        datas.append(cursor)
        cursor += timedelta(days=1)
    return _executar(DouSyncRun.MODO_BACKFILL, datas, with_pdf, dry_run)


def ingest_single_date(data: date, with_pdf: bool = True,
                       dry_run: bool = False) -> DouSyncRun:
    """Reprocessa uma data específica (botão da tela e --data do CLI)."""
    return _executar(DouSyncRun.MODO_MANUAL, [data], with_pdf, dry_run)


# ----------------------------------------------------------------- retenção

def purge_old_pdfs(retention_months: int | None = None) -> int:
    """Remove PDFs mais antigos que a janela de retenção. XML e texto nunca são podados.

    Sem isso, ~32 GB/ano esgotam o disco de um servidor compartilhado com
    produção em cerca de três anos.
    """
    if retention_months is None:
        try:
            retention_months = int(os.environ.get(
                'DOU_PDF_RETENTION_MONTHS', DEFAULT_PDF_RETENTION_MONTHS))
        except ValueError:
            retention_months = DEFAULT_PDF_RETENTION_MONTHS

    if retention_months <= 0:      # 0 = nunca podar
        return 0

    limite = date.today() - timedelta(days=retention_months * 30)
    edicoes = DouEdition.query.filter(
        DouEdition.data_publicacao < limite,
        DouEdition.pdf_path.isnot(None),
        DouEdition.pdf_purged_at.is_(None),
    ).all()

    podados = 0
    for edicao in edicoes:
        caminho = Path(edicao.pdf_path)
        try:
            if caminho.exists():
                caminho.unlink()
            edicao.pdf_purged_at = datetime.now()
            podados += 1
        except OSError as exc:
            logger.warning('DOU: não foi possível remover %s: %s', caminho, exc)

    db.session.commit()
    logger.info('DOU: %d PDF(s) podados (retenção de %d meses)', podados, retention_months)
    return podados
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

```bash
uv run python tests/test_dou_ingestion.py
```

Esperado: `✅ Todos os testes passaram`, exit 0.

- [ ] **Step 5: Rodar também o teste do parser, para garantir que nada regrediu**

```bash
uv run python tests/test_dou_xml_parser.py && uv run python tests/test_inlabs_client.py
```

Esperado: os dois terminam com `✅ Todos os testes passaram`.

- [ ] **Step 6: Commit**

```bash
git add app/services/dou_ingestion_service.py tests/test_dou_ingestion.py
git commit -m "feat(dou): serviço de ingestão com idempotência e janela de reverificação

Orquestra client -> disco -> parser -> upsert -> auditoria.

Duas propriedades sustentam o módulo: o upsert casa por (edition_id,
art_id, id_materia), então reprocessar um dia é UPDATE e nunca duplica; e
a janela de reverificação reconfere os últimos 7 dias comparando o SHA-256
do ZIP, porque o INLABS reescreve datas passadas — um cron que só olha
'hoje' perderia as republicações.

O hash é calculado antes de gravar o arquivo: gravar antes de comparar
sobrescreveria um arquivo íntegro por um download truncado."
```

---

## Task 5: Script de sincronização (cron, backfill, poda)

**Files:**
- Create: `scripts/sync_dou.py`

**Interfaces:**
- Consumes: `dou_ingestion_service.sync_recent/backfill/ingest_single_date/purge_old_pdfs`, `inlabs_client.is_configured`.
- Produces: CLI. Nenhuma API consumida por outras tasks.

- [ ] **Step 1: Escrever o script**

Criar `scripts/sync_dou.py`, no padrão de `scripts/sync_process_communications.py`:

```python
#!/usr/bin/env python3
"""
Captura do Diário Oficial da União (INLABS) — cron.

Baixa os ZIPs de XML das seções configuradas (padrão: DO1 DO2 DO3 DO1E DO2E
DO3E) e os PDFs assinados, quebra o XML matéria a matéria e persiste.

Regras (ver app/services/dou_ingestion_service.py):
  - HTTP 404 é estado normal ("não publicado"), não erro;
  - o INLABS reescreve datas passadas, então toda execução reconfere a janela
    dos últimos DOU_RECHECK_DAYS dias (padrão 7) comparando o SHA-256 do ZIP;
  - falha de uma (data, seção) marca a edição como 'error' e a próxima execução
    tenta de novo — falha nunca é registrada como sucesso.

Modos de execução:
  - Diário (padrão): hoje + janela de reverificação. É o modo do cron.
  - Data única (--data): reprocessa uma data específica.
  - BACKFILL (--backfill --desde): resgate histórico. O INLABS mantém uma janela
    móvel de ~4 meses; o que não for capturado agora se perde. Commit por dia,
    interrompível e retomável (dedup por hash).
  - Poda (--purge-pdfs): remove PDFs além da retenção. XML e texto nunca são
    podados.

Execução manual:
  uv run python scripts/sync_dou.py
  uv run python scripts/sync_dou.py --dry-run
  uv run python scripts/sync_dou.py --data 2026-08-10
  uv run python scripts/sync_dou.py --secoes DO1,DO3
  uv run python scripts/sync_dou.py --sem-pdf
  uv run python scripts/sync_dou.py --backfill --desde 2026-04-13
  uv run python scripts/sync_dou.py --purge-pdfs

Cron sugerido (3x/dia: a edição normal sai de manhã, as extras a qualquer hora):
  0 7,12,19 * * * cd /sites/intellexia && flock -n /tmp/intellexia_dou.lock \
      uv run python scripts/sync_dou.py >> /var/log/intellexia/sync_dou.log 2>&1
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # type: ignore[import]
load_dotenv(project_root / '.env')


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _parse_data(valor: str) -> date:
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        raise argparse.ArgumentTypeError(f'data inválida: {valor} (use YYYY-MM-DD)')


def _resumir(run) -> None:
    _log(
        f"📊 {run.modo}: {run.edicoes_baixadas} edição(ões) baixada(s), "
        f"{run.materias_inseridas} matéria(s) nova(s), "
        f"{run.materias_atualizadas} atualizada(s), "
        f"{run.nao_publicados} não publicada(s), {run.erros} erro(s) "
        f"— status {run.status}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Captura do Diário Oficial da União (INLABS)')
    parser.add_argument('--data', type=_parse_data, help='reprocessa uma data específica (YYYY-MM-DD)')
    parser.add_argument('--backfill', action='store_true', help='resgate histórico (exige --desde)')
    parser.add_argument('--desde', type=_parse_data, help='data inicial do backfill (YYYY-MM-DD)')
    parser.add_argument('--ate', type=_parse_data, help='data final do backfill (padrão: hoje)')
    parser.add_argument('--secoes', help='subconjunto de seções, ex.: DO1,DO3')
    parser.add_argument('--sem-pdf', action='store_true', help='baixa só o XML')
    parser.add_argument('--purge-pdfs', action='store_true', help='poda PDFs além da retenção e sai')
    parser.add_argument('--dry-run', action='store_true', help='não grava nada')
    args = parser.parse_args()

    # Erro de argumento é reportado antes de qualquer checagem de ambiente:
    # quem digitou o comando errado precisa ver o erro real, não "credenciais
    # ausentes".
    if args.backfill and not args.desde:
        _log('❌ --backfill exige --desde YYYY-MM-DD')
        return 2

    if args.secoes:
        os.environ['DOU_SECOES'] = args.secoes

    from main import app
    from app.services import dou_ingestion_service as ingestion
    from app.services import inlabs_client

    with app.app_context():
        if args.purge_pdfs:
            podados = ingestion.purge_old_pdfs()
            _log(f'🗑️  {podados} PDF(s) podado(s)')
            return 0

        if not inlabs_client.is_configured():
            _log('⚠️  INLABS_EMAIL/INLABS_PASSWORD ausentes no .env — nada a fazer')
            return 0

        with_pdf = not args.sem_pdf

        if args.backfill:
            _log(f'⏳ Backfill de {args.desde} até {args.ate or date.today()}...')
            run = ingestion.backfill(args.desde, args.ate, with_pdf=with_pdf, dry_run=args.dry_run)
        elif args.data:
            _log(f'⏳ Reprocessando {args.data}...')
            run = ingestion.ingest_single_date(args.data, with_pdf=with_pdf, dry_run=args.dry_run)
        else:
            _log('⏳ Captura diária (hoje + janela de reverificação)...')
            run = ingestion.sync_recent(with_pdf=with_pdf, dry_run=args.dry_run)

        _resumir(run)
        return 0 if run.status != 'error' else 1


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: Verificar o `--help` e o caminho sem credenciais**

```bash
uv run python scripts/sync_dou.py --help
```

Esperado: imprime a ajuda com todos os modos, sem traceback.

- [ ] **Step 3: Verificar a degradação graciosa sem credenciais**

```bash
INLABS_EMAIL= INLABS_PASSWORD= uv run python scripts/sync_dou.py
```

Esperado: `⚠️  INLABS_EMAIL/INLABS_PASSWORD ausentes no .env — nada a fazer`, exit 0, nenhum traceback.

> Se o `.env` já tiver credenciais, o `load_dotenv` as recarrega e este teste não vale — nesse caso, confirme o comportamento com `--dry-run` e observe que nada é gravado.

- [ ] **Step 4: Verificar o dry-run contra o INLABS real (exige credenciais no `.env`)**

```bash
uv run python scripts/sync_dou.py --data 2026-08-10 --secoes DO1 --dry-run
```

Esperado: login bem-sucedido e o resumo indicando que baixaria a edição, sem gravar nada. Confirmar em seguida que nenhuma linha foi criada:

```bash
uv run python -c "
from main import app
from app.models import DouEdition
with app.app_context():
    print('edições gravadas:', DouEdition.query.count())
"
```

- [ ] **Step 5: Commit**

```bash
git add scripts/sync_dou.py
git commit -m "feat(dou): script de captura (cron, backfill, reprocesso e poda)

Cron 3x/dia porque a edição normal sai de manhã e as extras a qualquer
hora. O backfill é comando manual, não acoplado ao deploy: são ~11 GB e
horas de download, e o INLABS mantém janela móvel de ~4 meses — o que não
for capturado agora se perde.

Sem credenciais no .env o script loga e sai com 0, no mesmo contrato de
degradação graciosa do email_service."
```

---

## Task 6: Blueprint, telas e registro do módulo

Registro, permissões e menu vão junto do blueprint: sem eles a tela não abre, então não são deliverables separáveis.

**Files:**
- Create: `app/blueprints/dou.py`
- Create: `templates/dou/acervo.html`
- Create: `templates/dou/materia.html`
- Create: `templates/dou/captura.html`
- Modify: `app/utils/permissions.py`
- Modify: `app/blueprints/__init__.py`
- Modify: `main.py:54-89`
- Modify: `templates/partials/sidebar.html`
- Test: `tests/test_dou_routes.py`

**Interfaces:**
- Consumes: modelos `DouEdition`/`DouArticle`/`DouSyncRun`, `dou_ingestion_service.ingest_single_date`.
- Produces: endpoints `dou.acervo`, `dou.materia`, `dou.captura`, `dou.reprocessar`, `dou.baixar_pdf`.

- [ ] **Step 1: Registrar o módulo em `app/utils/permissions.py`**

Três edições no arquivo:

1. Em `MODULE_PERMISSIONS`, após a linha `'communications': 'Monitoramento de Processos',`:

```python
    'dou': 'Diario Oficial',
```

2. Em `_RESTRICTED_BY_DEFAULT`, acrescentar `'dou'` ao conjunto (fica fora dos defaults de não-admin, concedível por usuário):

```python
_RESTRICTED_BY_DEFAULT = ADMIN_ONLY_MODULES | {'clients', 'lawyers', 'courts', 'dou'}
```

3. Em `ENDPOINT_MODULE_MAP`, após a linha `'communications.': 'communications',`:

```python
    'dou.': 'dou',
```

- [ ] **Step 2: Criar o blueprint**

Criar `app/blueprints/dou.py`:

```python
"""
Diário Oficial — acervo do DOU capturado do INLABS.

Duas frentes: o **acervo** (navegar por data e seção, filtrar por órgão e tipo
de ato, ler a matéria, baixar o PDF assinado) e a **captura** (saúde da
ingestão, com reprocesso de data).

Esta tela nunca baixa nada de forma síncrona numa requisição de usuário: o
download é responsabilidade do cron (scripts/sync_dou.py). O botão
"reprocessar" é a única exceção e roda uma data por vez.

As tabelas do DOU não têm law_firm_id — é um catálogo público compartilhado
(ver docstring de DouEdition). Por isso este blueprint não filtra por tenant;
a proteção é a permissão de módulo, aplicada pelo middleware.
"""

from datetime import datetime

from pathlib import Path

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, send_file, abort)
from sqlalchemy import func

from app.models import db, DouEdition, DouArticle, DouSyncRun
from app.services import dou_ingestion_service as ingestion

dou_bp = Blueprint('dou', __name__, url_prefix='/dou')

PER_PAGE = 30


def _parse_data(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        return None


@dou_bp.route('/')
def index():
    return redirect(url_for('dou.acervo'))


@dou_bp.route('/acervo')
def acervo():
    """Navegação por data e seção, com filtro por órgão e tipo de ato."""
    data = _parse_data(request.args.get('data'))
    secao = (request.args.get('secao') or '').strip().upper()
    orgao = (request.args.get('orgao') or '').strip()
    tipo = (request.args.get('tipo') or '').strip()
    page = request.args.get('page', 1, type=int)

    # Datas disponíveis, da mais recente para a mais antiga
    datas = [
        d[0] for d in db.session.query(DouEdition.data_publicacao)
        .filter(DouEdition.status == DouEdition.STATUS_PARSED)
        .distinct().order_by(DouEdition.data_publicacao.desc()).limit(180).all()
    ]

    if data is None and datas:
        data = datas[0]

    edicoes = []
    materias = None
    if data:
        edicoes = (DouEdition.query
                   .filter_by(data_publicacao=data)
                   .order_by(DouEdition.secao).all())

        query = DouArticle.query.filter(DouArticle.pub_date == data)
        if secao:
            query = query.filter(DouArticle.pub_name == secao)
        if orgao:
            query = query.filter(DouArticle.orgao_hierarquia.ilike(f'%{orgao}%'))
        if tipo:
            query = query.filter(DouArticle.art_type == tipo)

        materias = (query.order_by(DouArticle.pub_name, DouArticle.id)
                    .paginate(page=page, per_page=PER_PAGE, error_out=False))

    tipos = [
        t[0] for t in db.session.query(DouArticle.art_type)
        .filter(DouArticle.pub_date == data, DouArticle.art_type.isnot(None))
        .distinct().order_by(DouArticle.art_type).all()
    ] if data else []

    return render_template(
        'dou/acervo.html',
        datas=datas, data_selecionada=data, edicoes=edicoes,
        materias=materias, tipos=tipos,
        f_secao=secao, f_orgao=orgao, f_tipo=tipo,
        secoes=DouEdition.XML_SECTIONS, section_labels=DouEdition.SECTION_LABELS,
    )


@dou_bp.route('/materia/<int:article_id>')
def materia(article_id):
    artigo = DouArticle.query.get_or_404(article_id)
    return render_template('dou/materia.html', artigo=artigo, edicao=artigo.edition)


@dou_bp.route('/edicao/<int:edition_id>/pdf')
def baixar_pdf(edition_id):
    """Entrega o PDF assinado da edição, se ainda existir em disco."""
    edicao = DouEdition.query.get_or_404(edition_id)
    if not edicao.pdf_disponivel:
        flash('O PDF assinado desta edição não está disponível.', 'warning')
        return redirect(url_for('dou.acervo', data=edicao.data_publicacao.isoformat()))

    caminho = Path(edicao.pdf_path)
    if not caminho.exists():
        abort(404)
    return send_file(caminho.resolve(), as_attachment=True, download_name=caminho.name)


@dou_bp.route('/captura')
def captura():
    """Saúde da ingestão: execuções recentes e cobertura por dia."""
    execucoes = (DouSyncRun.query
                 .order_by(DouSyncRun.iniciado_em.desc()).limit(20).all())

    cobertura = (db.session.query(
        DouEdition.data_publicacao,
        func.count(DouEdition.id).label('secoes'),
        func.sum(DouEdition.qtd_materias).label('materias'),
    ).group_by(DouEdition.data_publicacao)
     .order_by(DouEdition.data_publicacao.desc()).limit(60).all())

    com_erro = (DouEdition.query
                .filter(DouEdition.status == DouEdition.STATUS_ERROR)
                .order_by(DouEdition.data_publicacao.desc()).limit(50).all())

    return render_template('dou/captura.html', execucoes=execucoes,
                           cobertura=cobertura, com_erro=com_erro,
                           total_materias=DouArticle.query.count())


@dou_bp.route('/captura/reprocessar', methods=['POST'])
def reprocessar():
    """Reprocessa uma data. Único ponto em que a tela dispara download."""
    data = _parse_data(request.form.get('data'))
    if not data:
        flash('Informe uma data válida (AAAA-MM-DD).', 'danger')
        return redirect(url_for('dou.captura'))

    try:
        run = ingestion.ingest_single_date(data)
    except Exception as exc:  # noqa: BLE001 — erro vira mensagem, não 500
        flash(f'Falha ao reprocessar {data:%d/%m/%Y}: {exc}', 'danger')
        return redirect(url_for('dou.captura'))

    flash(
        f'{data:%d/%m/%Y}: {run.materias_inseridas} matéria(s) nova(s), '
        f'{run.materias_atualizadas} atualizada(s), {run.erros} erro(s).',
        'success' if run.erros == 0 else 'warning',
    )
    return redirect(url_for('dou.captura'))
```

- [ ] **Step 3: Exportar e registrar o blueprint**

Em `app/blueprints/__init__.py`, acrescentar após a linha `from app.blueprints.communications import communications_bp`:

```python
from app.blueprints.dou import dou_bp
```

E `'dou_bp',` ao final da lista `__all__`.

Em `main.py`, acrescentar `dou_bp` à lista de import (linha 54-61), ao final da tupla:

```python
    impugnacao_references_bp, docs_bp, communications_bp, dou_bp,
```

E, após `app.register_blueprint(communications_bp)` (linha 89):

```python
app.register_blueprint(dou_bp)
```

- [ ] **Step 4: Acrescentar o item de menu**

Em `templates/partials/sidebar.html`, logo após o bloco `{% endif %}` que fecha o item de `communications` (o que usa `bi-broadcast`), inserir:

```html
            {% if can_view_module('dou') %}
            <li class="nav-item">
              <a href="{{ url_for('dou.acervo') }}"
                class="nav-link {{ 'active' if request.endpoint and request.endpoint.startswith('dou.') else '' }}"
                style="font-size: 0.9em;">
                <i class="nav-icon bi bi-newspaper" style="margin-right: 8px; color: #6c757d;"></i>
                <p style="margin-left: 15px;" title="Diário Oficial da União">Diário Oficial</p>
              </a>
            </li>
            {% endif %}
```

- [ ] **Step 5: Criar a tela do acervo**

Criar `templates/dou/acervo.html`:

```html
{% extends "layout/base.html" %}
{% from "partials/page_hero.html" import page_hero %}

{% block title %}Diário Oficial{% endblock %}

{% block content %}
{{ page_hero(
     'Diário Oficial da União',
     'Acervo das edições capturadas do INLABS',
     'bi bi-newspaper',
     [{'label': 'Início', 'href': url_for('dashboard.index')},
      {'label': 'Diário Oficial', 'active': True}]) }}

<div class="row mb-3">
  <div class="col-12 d-flex justify-content-end">
    <a href="{{ url_for('dou.captura') }}" class="btn btn-outline-secondary btn-sm">
      <i class="bi bi-activity me-1"></i>Estado da captura
    </a>
  </div>
</div>

{% if not datas %}
<div class="card border-0 shadow-sm">
  <div class="card-body text-center py-5">
    <i class="bi bi-inbox display-4 text-muted"></i>
    <h5 class="mt-3">Nenhuma edição capturada ainda</h5>
    <p class="text-muted mb-0">
      Rode <code>uv run python scripts/sync_dou.py</code> ou aguarde a próxima
      execução automática.
    </p>
  </div>
</div>
{% else %}

<div class="card border-0 shadow-sm mb-4">
  <div class="card-body">
    <form method="get" class="row g-2 align-items-end">
      <div class="col-md-3">
        <label class="form-label small text-muted mb-1">Data</label>
        <select name="data" class="form-select form-select-sm" onchange="this.form.submit()">
          {% for d in datas %}
          <option value="{{ d.isoformat() }}" {{ 'selected' if d == data_selecionada }}>
            {{ d.strftime('%d/%m/%Y') }}
          </option>
          {% endfor %}
        </select>
      </div>
      <div class="col-md-3">
        <label class="form-label small text-muted mb-1">Seção</label>
        <select name="secao" class="form-select form-select-sm">
          <option value="">Todas</option>
          {% for s in secoes %}
          <option value="{{ s }}" {{ 'selected' if s == f_secao }}>{{ section_labels[s] }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-md-2">
        <label class="form-label small text-muted mb-1">Tipo de ato</label>
        <select name="tipo" class="form-select form-select-sm">
          <option value="">Todos</option>
          {% for t in tipos %}
          <option value="{{ t }}" {{ 'selected' if t == f_tipo }}>{{ t }}</option>
          {% endfor %}
        </select>
      </div>
      <div class="col-md-3">
        <label class="form-label small text-muted mb-1">Órgão</label>
        <input type="text" name="orgao" value="{{ f_orgao }}" class="form-control form-control-sm"
               placeholder="ex.: Previdência">
      </div>
      <div class="col-md-1">
        <button type="submit" class="btn btn-primary btn-sm w-100">
          <i class="bi bi-funnel"></i>
        </button>
      </div>
    </form>
  </div>
</div>

{% if edicoes %}
<div class="row g-2 mb-4">
  {% for e in edicoes %}
  <div class="col-md-4">
    <div class="card border-0 shadow-sm h-100">
      <div class="card-body py-2 px-3 d-flex justify-content-between align-items-center">
        <div>
          <div class="small fw-semibold">{{ e.secao_label }}</div>
          <div class="text-muted" style="font-size: .8rem;">
            {% if e.status == 'parsed' %}
              {{ e.qtd_materias }} matéria(s)
            {% elif e.status == 'not_published' %}
              não publicada
            {% elif e.status == 'error' %}
              <span class="text-danger">falha na captura</span>
            {% else %}
              {{ e.status }}
            {% endif %}
          </div>
        </div>
        {% if e.pdf_disponivel %}
        <a href="{{ url_for('dou.baixar_pdf', edition_id=e.id) }}"
           class="btn btn-outline-danger btn-sm" title="PDF assinado">
          <i class="bi bi-file-earmark-pdf"></i>
        </a>
        {% endif %}
      </div>
    </div>
  </div>
  {% endfor %}
</div>
{% endif %}

<div class="card border-0 shadow-sm">
  <div class="card-body p-0">
    {% if materias and materias.items %}
    <div class="table-responsive">
      <table class="table table-hover align-middle mb-0">
        <thead class="table-light">
          <tr>
            <th style="width: 90px;">Seção</th>
            <th>Matéria</th>
            <th>Órgão</th>
            <th style="width: 90px;">Página</th>
          </tr>
        </thead>
        <tbody>
          {% for m in materias.items %}
          <tr>
            <td><span class="badge text-bg-secondary">{{ m.pub_name }}</span></td>
            <td>
              <a href="{{ url_for('dou.materia', article_id=m.id) }}" class="fw-semibold text-decoration-none">
                {{ m.identifica or m.titulo or '(sem identificação)' }}
              </a>
              {% if m.ementa %}
              <div class="text-muted small text-truncate" style="max-width: 620px;">{{ m.ementa }}</div>
              {% endif %}
            </td>
            <td class="small text-muted">{{ m.orgao_hierarquia or '—' }}</td>
            <td class="small">{{ m.pagina or '—' }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    {% if materias.pages > 1 %}
    <div class="card-footer bg-white d-flex justify-content-between align-items-center">
      <small class="text-muted">
        Página {{ materias.page }} de {{ materias.pages }} — {{ materias.total }} matéria(s)
      </small>
      <div class="btn-group btn-group-sm">
        {% if materias.has_prev %}
        <a class="btn btn-outline-secondary"
           href="{{ url_for('dou.acervo', data=data_selecionada.isoformat(), secao=f_secao, tipo=f_tipo, orgao=f_orgao, page=materias.prev_num) }}">Anterior</a>
        {% endif %}
        {% if materias.has_next %}
        <a class="btn btn-outline-secondary"
           href="{{ url_for('dou.acervo', data=data_selecionada.isoformat(), secao=f_secao, tipo=f_tipo, orgao=f_orgao, page=materias.next_num) }}">Próxima</a>
        {% endif %}
      </div>
    </div>
    {% endif %}

    {% else %}
    <div class="text-center py-5 text-muted">
      <i class="bi bi-search display-6"></i>
      <p class="mt-2 mb-0">Nenhuma matéria para os filtros escolhidos.</p>
    </div>
    {% endif %}
  </div>
</div>

{% endif %}
{% endblock %}
```

- [ ] **Step 6: Criar a tela de detalhe da matéria**

Criar `templates/dou/materia.html`:

```html
{% extends "layout/base.html" %}
{% from "partials/page_hero.html" import page_hero %}

{% block title %}{{ artigo.identifica or 'Matéria do DOU' }}{% endblock %}

{% block content %}
{{ page_hero(
     artigo.identifica or 'Matéria do Diário Oficial',
     artigo.orgao_hierarquia or '',
     'bi bi-file-text',
     [{'label': 'Diário Oficial', 'href': url_for('dou.acervo')},
      {'label': 'Matéria', 'active': True}]) }}

<div class="row">
  <div class="col-lg-8">
    <div class="card border-0 shadow-sm mb-4">
      <div class="card-body">
        {% if artigo.ementa %}
        <div class="alert alert-light border">
          <div class="small text-muted mb-1">Ementa</div>
          {{ artigo.ementa }}
        </div>
        {% endif %}
        {% if artigo.titulo %}<h5>{{ artigo.titulo }}</h5>{% endif %}
        {% if artigo.subtitulo %}<h6 class="text-muted">{{ artigo.subtitulo }}</h6>{% endif %}
        <div class="dou-texto mt-3" style="white-space: pre-wrap; line-height: 1.7;">{{ artigo.texto }}</div>
      </div>
    </div>
  </div>

  <div class="col-lg-4">
    <div class="card border-0 shadow-sm mb-4">
      <div class="card-header bg-white fw-semibold">Dados da publicação</div>
      <div class="card-body small">
        <dl class="row mb-0">
          <dt class="col-5 text-muted">Seção</dt><dd class="col-7">{{ artigo.pub_name }}</dd>
          <dt class="col-5 text-muted">Data</dt>
          <dd class="col-7">{{ artigo.pub_date.strftime('%d/%m/%Y') if artigo.pub_date else '—' }}</dd>
          <dt class="col-5 text-muted">Edição</dt><dd class="col-7">{{ artigo.edicao or '—' }}</dd>
          <dt class="col-5 text-muted">Página</dt><dd class="col-7">{{ artigo.pagina or '—' }}</dd>
          <dt class="col-5 text-muted">Tipo</dt><dd class="col-7">{{ artigo.art_type or '—' }}</dd>
          <dt class="col-5 text-muted">Órgão</dt><dd class="col-7">{{ artigo.orgao_hierarquia or '—' }}</dd>
        </dl>
      </div>
      <div class="card-footer bg-white d-grid gap-2">
        {% if artigo.pdf_page %}
        <a href="{{ artigo.pdf_page }}" target="_blank" rel="noopener"
           class="btn btn-outline-primary btn-sm">
          <i class="bi bi-box-arrow-up-right me-1"></i>Ver no portal oficial
        </a>
        {% endif %}
        {% if edicao and edicao.pdf_disponivel %}
        <a href="{{ url_for('dou.baixar_pdf', edition_id=edicao.id) }}"
           class="btn btn-outline-danger btn-sm">
          <i class="bi bi-file-earmark-pdf me-1"></i>PDF assinado da edição
        </a>
        {% endif %}
        <a href="{{ url_for('dou.acervo', data=artigo.pub_date.isoformat() if artigo.pub_date else '') }}"
           class="btn btn-outline-secondary btn-sm">
          <i class="bi bi-arrow-left me-1"></i>Voltar ao acervo
        </a>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 7: Criar a tela de captura**

Criar `templates/dou/captura.html`:

```html
{% extends "layout/base.html" %}
{% from "partials/page_hero.html" import page_hero %}

{% block title %}Captura do Diário Oficial{% endblock %}

{% block content %}
{{ page_hero(
     'Captura do Diário Oficial',
     'Estado da ingestão das edições do INLABS',
     'bi bi-activity',
     [{'label': 'Diário Oficial', 'href': url_for('dou.acervo')},
      {'label': 'Captura', 'active': True}]) }}

<div class="row g-3 mb-4">
  <div class="col-md-4">
    <div class="card border-0 shadow-sm">
      <div class="card-body">
        <div class="text-muted small">Matérias no acervo</div>
        <div class="h3 mb-0">{{ '{:,}'.format(total_materias).replace(',', '.') }}</div>
      </div>
    </div>
  </div>
  <div class="col-md-8">
    <div class="card border-0 shadow-sm">
      <div class="card-body">
        <form method="post" action="{{ url_for('dou.reprocessar') }}" class="row g-2 align-items-end">
          <div class="col-auto">
            <label class="form-label small text-muted mb-1">Reprocessar data</label>
            <input type="date" name="data" class="form-control form-control-sm" required>
          </div>
          <div class="col-auto">
            <button type="submit" class="btn btn-primary btn-sm">
              <i class="bi bi-arrow-clockwise me-1"></i>Reprocessar
            </button>
          </div>
          <div class="col">
            <small class="text-muted d-block">
              Rebaixa a data do INLABS e reprocessa. Seguro: reprocessar atualiza, nunca duplica.
            </small>
          </div>
        </form>
      </div>
    </div>
  </div>
</div>

{% if com_erro %}
<div class="card border-0 shadow-sm mb-4 border-start border-danger border-4">
  <div class="card-header bg-white fw-semibold text-danger">
    <i class="bi bi-exclamation-triangle me-1"></i>Edições com falha ({{ com_erro|length }})
  </div>
  <div class="table-responsive">
    <table class="table table-sm mb-0">
      <thead class="table-light"><tr><th>Data</th><th>Seção</th><th>Erro</th></tr></thead>
      <tbody>
        {% for e in com_erro %}
        <tr>
          <td>{{ e.data_publicacao.strftime('%d/%m/%Y') }}</td>
          <td>{{ e.secao }}</td>
          <td class="small text-muted">{{ e.error_message or '—' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endif %}

<div class="row g-3">
  <div class="col-lg-6">
    <div class="card border-0 shadow-sm">
      <div class="card-header bg-white fw-semibold">Cobertura por dia</div>
      <div class="table-responsive" style="max-height: 480px; overflow-y: auto;">
        <table class="table table-sm table-hover mb-0">
          <thead class="table-light"><tr><th>Data</th><th>Seções</th><th>Matérias</th></tr></thead>
          <tbody>
            {% for data, secoes, materias in cobertura %}
            <tr>
              <td>
                <a href="{{ url_for('dou.acervo', data=data.isoformat()) }}" class="text-decoration-none">
                  {{ data.strftime('%d/%m/%Y') }}
                </a>
              </td>
              <td>{{ secoes }}</td>
              <td>{{ materias or 0 }}</td>
            </tr>
            {% else %}
            <tr><td colspan="3" class="text-center text-muted py-4">Nenhuma edição capturada.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="col-lg-6">
    <div class="card border-0 shadow-sm">
      <div class="card-header bg-white fw-semibold">Execuções recentes</div>
      <div class="table-responsive" style="max-height: 480px; overflow-y: auto;">
        <table class="table table-sm mb-0">
          <thead class="table-light">
            <tr><th>Início</th><th>Modo</th><th>Novas</th><th>Atual.</th><th>Erros</th><th>Status</th></tr>
          </thead>
          <tbody>
            {% for r in execucoes %}
            <tr>
              <td class="small">{{ r.iniciado_em|datetime_sp }}</td>
              <td class="small">{{ r.modo }}</td>
              <td>{{ r.materias_inseridas }}</td>
              <td>{{ r.materias_atualizadas }}</td>
              <td>{{ r.erros }}</td>
              <td>
                <span class="badge text-bg-{{ 'success' if r.status == 'success' else ('warning' if r.status == 'partial' else ('danger' if r.status == 'error' else 'secondary')) }}">
                  {{ r.status }}
                </span>
              </td>
            </tr>
            {% else %}
            <tr><td colspan="6" class="text-center text-muted py-4">Nenhuma execução registrada.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 8: Escrever o teste de rotas**

Criar `tests/test_dou_routes.py`:

```python
#!/usr/bin/env python3
"""
Testes das rotas do módulo Diário Oficial.

Usa app.test_client() no padrão dos demais testes de rota do projeto.

    uv run python tests/test_dou_routes.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import User
from app.utils.permissions import (MODULE_PERMISSIONS, ENDPOINT_MODULE_MAP,
                                   ROLE_DEFAULT_MODULE_PERMISSIONS)

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def test_registro_do_modulo():
    print('\n1. Registro do módulo nas permissões')
    check("'dou' está em MODULE_PERMISSIONS", 'dou' in MODULE_PERMISSIONS)
    check("rótulo é 'Diario Oficial'", MODULE_PERMISSIONS.get('dou') == 'Diario Oficial',
          repr(MODULE_PERMISSIONS.get('dou')))
    check("prefixo 'dou.' mapeado", ENDPOINT_MODULE_MAP.get('dou.') == 'dou',
          repr(ENDPOINT_MODULE_MAP.get('dou.')))
    check('admin tem o módulo por padrão', 'dou' in ROLE_DEFAULT_MODULE_PERMISSIONS['admin'])
    check('não-admin NÃO tem por padrão (concedível)',
          'dou' not in ROLE_DEFAULT_MODULE_PERMISSIONS['lawyer'])


def test_rotas_registradas():
    print('\n2. Rotas registradas')
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    for esperado in ('dou.acervo', 'dou.materia', 'dou.captura',
                     'dou.reprocessar', 'dou.baixar_pdf'):
        check(f'{esperado} existe', esperado in endpoints)


def test_exige_login():
    print('\n3. Acesso sem login')
    with app.test_client() as c:
        resposta = c.get('/dou/acervo', follow_redirects=False)
        check('redireciona para o login', resposta.status_code in (301, 302),
              str(resposta.status_code))


def test_acervo_com_login():
    print('\n4. Acervo com sessão de admin')
    with app.app_context():
        usuario = User.query.filter_by(role='admin').first()
        if usuario is None:
            print('  ⏭️  nenhum usuário admin no banco — pulando')
            return
        user_id, firm_id = usuario.id, usuario.law_firm_id

    with app.test_client() as c:
        with c.session_transaction() as sessao:
            sessao['user_id'] = user_id
            sessao['law_firm_id'] = firm_id
            sessao['user_role'] = 'admin'

        resposta = c.get('/dou/acervo')
        check('acervo responde 200', resposta.status_code == 200, str(resposta.status_code))
        check('renderiza o título do módulo',
              'Diário Oficial'.encode() in resposta.data)

        resposta = c.get('/dou/captura')
        check('captura responde 200', resposta.status_code == 200, str(resposta.status_code))

        resposta = c.get('/dou/')
        check('raiz redireciona para o acervo', resposta.status_code in (301, 302),
              str(resposta.status_code))


def main():
    print('=' * 60)
    print('TESTES DAS ROTAS DO DIÁRIO OFICIAL')
    print('=' * 60)

    test_registro_do_modulo()
    test_rotas_registradas()
    test_exige_login()
    test_acervo_com_login()

    print('\n' + '=' * 60)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 9: Rodar o teste de rotas**

```bash
uv run python tests/test_dou_routes.py
```

Esperado: `✅ Todos os testes passaram`, exit 0.

- [ ] **Step 10: Subir a aplicação e conferir as telas no navegador**

```bash
uv run python main.py
```

Abrir `http://localhost:5000/dou/acervo` e `http://localhost:5000/dou/captura`. Conferir:
- o item "Diário Oficial" aparece no menu lateral, com o ícone de jornal;
- com o banco vazio, o acervo mostra o estado vazio ("Nenhuma edição capturada ainda"), não um erro;
- a aba Captura carrega e o formulário de reprocessar data aparece;
- o layout não quebra em largura de celular (reduzir a janela).

Encerrar com Ctrl-C.

- [ ] **Step 11: Commit**

```bash
git add app/blueprints/dou.py templates/dou/ app/utils/permissions.py app/blueprints/__init__.py main.py templates/partials/sidebar.html tests/test_dou_routes.py
git commit -m "feat(dou): tela de acervo e de captura, com registro do módulo

Acervo navega por data e seção, filtra por órgão e tipo de ato e entrega o
PDF assinado; a aba Captura mostra cobertura por dia, execuções recentes e
edições com falha, com botão de reprocessar data.

O módulo 'dou' fica fora dos defaults de não-admin, concedível por usuário
na Administração de Usuários — mesmo tratamento dos cadastros. A tela nunca
baixa nada de forma síncrona, exceto o botão de reprocessar."
```

---

## Task 7: Documentação

**Files:**
- Modify: `CLAUDE.md`
- Create: `docs/MANUAL_DIARIO_OFICIAL.md`
- Modify: `app/services/manual_renderer.py`
- Modify: `app/services/manual_assistant_service.py`
- Modify: `.env.example` (se existir no repositório)

**Interfaces:**
- Consumes: nada em código.
- Produces: nada em código.

- [ ] **Step 1: Registrar o módulo no `CLAUDE.md`**

Quatro edições:

1. Na tabela "Função de cada blueprint", após a linha de `communications`:

```markdown
| `dou` | `/dou` | **Diário Oficial**: acervo do DOU capturado do INLABS (Imprensa Nacional). Captura diária dos ZIPs de XML das seções `DO1 DO2 DO3 DO1E DO2E DO3E` mais os PDFs assinados, quebrando cada edição matéria a matéria. Tela de acervo (navegação por data/seção, filtro por órgão e tipo de ato) e de captura (cobertura, falhas, reprocesso) |
```

2. Na tabela da Camada de Serviços, após `communication_monitor_service`:

```markdown
| `inlabs_client`                        | Cliente HTTP do INLABS (Imprensa Nacional) — todo acesso isolado aqui: login, cookie de sessão, montagem de URL, retry com teto, timeout e relogin transparente |
| `dou_xml_parser`                       | XML do DOU → dicts. Função pura, sem rede/banco/Flask — a peça que muda se a Imprensa Nacional alterar o schema |
| `dou_ingestion_service`                | Ingestão do DOU: download → disco → parse → upsert → auditoria. Dedup por hash, janela de reverificação e retenção de PDF — fonte única da tela e do cron |
```

3. Uma seção nova, após "Integração Comunica PJe (DJEN)":

```markdown
### Integração INLABS / Diário Oficial da União

Portal de dados abertos da Imprensa Nacional. Todo acesso isolado em
`app/services/inlabs_client.py`, com o mecanismo conferido contra a
implementação de referência oficial (`github.com/Imprensa-Nacional/inlabs`).

- **Login**: `POST /logar.php` com form `{email, password}` → cookie
  `inlabs_session_cookie`. Downloads exigem os headers `Cookie` e
  `origem: 736372697074`.
- **Arquivos**: XML em `YYYY-MM-DD-<SECAO>.zip` (seções em MAIÚSCULAS,
  `DO1 DO2 DO3 DO1E DO2E DO3E` — as terminadas em `E` são as edições extras,
  arquivos separados); PDF assinado em `YYYY_MM_DD_ASSINADO_<secao>.pdf`
  (minúsculas, `do1 do2 do3` — o PDF **já contempla as extras**).
- **HTTP 404 é estado normal** ("não publicado naquele dia/seção"), não erro.
- **Janela móvel**: o portal mantém ~4 meses de edições e descarta o resto. O
  que não for capturado se perde — daí o `--backfill`.
- **O INLABS reescreve datas passadas** (republicações, suplementos). Por isso
  toda execução reconfere os últimos `DOU_RECHECK_DAYS` dias comparando o
  SHA-256 do ZIP com `dou_editions.content_signature`. Um cron que só olha
  "hoje" perde essas republicações.
- **Exceção de multi-tenancy**: `dou_editions`, `dou_articles` e
  `dou_sync_runs` **não têm `law_firm_id`**. O DOU é dado público federal,
  idêntico para todo escritório; replicá-lo por tenant custaria ~32 GB/ano por
  escritório sem proteger sigilo nenhum. É um catálogo público compartilhado.
  O que for específico de escritório (watchlist, marcação de leitura) entra em
  tabela própria, com `law_firm_id` — o invariante continua valendo para todo
  dado de negócio.
- **Retenção**: `DOU_PDF_RETENTION_MONTHS` (padrão 24) poda apenas os PDFs;
  XML, texto e metadados nunca são podados.
```

4. No bloco de variáveis de ambiente, ao final:

```bash
# INLABS / Diário Oficial da União (opcional — em branco desativa a captura)
INLABS_EMAIL=...
INLABS_PASSWORD=...
DOU_SECOES=DO1,DO2,DO3,DO1E,DO2E,DO3E   # padrão: todas
DOU_RECHECK_DAYS=7                      # janela de reverificação
DOU_PDF_RETENTION_MONTHS=24             # 0 = nunca podar
DOU_DOWNLOAD_TIMEOUT=120                # segundos
```

- [ ] **Step 2: Escrever o manual do usuário**

Criar `docs/MANUAL_DIARIO_OFICIAL.md`, usando os marcadores de realce do projeto (`> [!DOU]`, `> [!INFO]`, `> [!ALERTA]`, `:btn-<estilo>[Texto]`):

```markdown
# Manual — Diário Oficial

A tela **Diário Oficial** guarda, dentro do IntellexIA, as edições do Diário
Oficial da União publicadas pela Imprensa Nacional. Todo dia o sistema baixa as
edições, separa cada matéria publicada e deixa tudo pronto para consulta.

> [!DOU] O conteúdo vem do portal de dados abertos da Imprensa Nacional
> (INLABS), em formato XML. Como o próprio portal avisa, esse formato **não
> substitui a versão certificada** — para uso oficial, baixe o PDF assinado da
> edição, disponível na própria tela.

## Acervo

É a tela principal. Você escolhe uma **data** e o sistema mostra as seções
capturadas naquele dia:

- **Seção 1** — atos normativos (portarias, resoluções, decretos).
- **Seção 2** — pessoal do serviço público federal.
- **Seção 3** — contratos, licitações e avisos.
- **Edições Extras** — publicações fora da edição normal do dia.

Abaixo das seções vem a lista de matérias. Clique em qualquer uma para ler o
inteiro teor.

### Filtros

| Filtro | Para que serve |
|---|---|
| Data | O dia da publicação. A lista começa sempre no dia mais recente capturado. |
| Seção | Restringe a uma seção do Diário. |
| Tipo de ato | Portaria, Resolução, Aviso, Extrato — os tipos existentes naquele dia. |
| Órgão | Busca por parte do nome do órgão. Ex.: digitar `Previdência` traz tudo do Ministério da Previdência Social. |

> [!INFO] Nesta versão ainda **não há busca por palavra dentro do texto** das
> matérias. A navegação é por data, seção, órgão e tipo de ato.

### PDF assinado

Quando a edição tem o PDF assinado guardado, aparece o botão vermelho de PDF ao
lado da seção. É o arquivo oficial da Imprensa Nacional, com assinatura digital
— o que você junta em processo.

> [!ALERTA] Os PDFs são guardados por tempo limitado (24 meses, por padrão), por
> causa do tamanho. O texto das matérias, esse **nunca é apagado**. Se o PDF de
> uma edição antiga não estiver mais disponível, o botão não aparece.

## Captura

Mostra a saúde da coleta. Serve para responder "o Diário de ontem entrou?".

- **Matérias no acervo** — total acumulado.
- **Cobertura por dia** — quantas seções e quantas matérias entraram em cada dia.
- **Execuções recentes** — cada rodada automática, com quantas matérias eram
  novas, quantas foram atualizadas e quantos erros houve.
- **Edições com falha** — o que não entrou, e por quê.

### Reprocessar uma data

Se um dia aparecer incompleto ou com falha, informe a data e clique em
:btn-primary[Reprocessar]. O sistema baixa aquele dia de novo.

> [!INFO] Reprocessar é sempre seguro: matéria que já existe é **atualizada**,
> nunca duplicada. Se a Imprensa Nacional republicou a edição com correções,
> reprocessar é justamente como trazer o texto corrigido.

## Perguntas frequentes

**Com que frequência o sistema busca o Diário?**
Três vezes por dia. A edição normal sai de manhã; as edições extras podem sair a
qualquer hora, por isso as buscas seguintes.

**Por que um dia aparece sem nenhuma matéria?**
Fins de semana e feriados não têm publicação. Nesse caso o dia consta como "não
publicado", o que é normal.

**Por que uma matéria de ontem mudou de texto?**
A Imprensa Nacional às vezes republica uma edição com correções. O sistema
reconfere os últimos dias automaticamente e traz a versão mais recente.

**Consigo ver edições de anos anteriores?**
Só a partir de quando o sistema começou a capturar. O portal da Imprensa
Nacional mantém apenas alguns meses disponíveis para download; edições mais
antigas que isso não podem mais ser resgatadas.
```

- [ ] **Step 3: Registrar o manual no renderer e no assistente**

Em `app/services/manual_renderer.py:44-51`, acrescentar a entrada à tupla `_MANUALS`, antes de `("conectar-ia", ...)` (a ordem da tupla é a ordem do índice lateral):

```python
_MANUALS = (
    ("dashboard", "Dashboard Principal", "MANUAL_DASHBOARD.md"),
    ("painel-fap", "Painel FAP", "MANUAL_PAINEL_FAP.md"),
    ("contestacoes", "Painel de Contestações", "MANUAL_PAINEL_CONTESTACOES.md"),
    ("revisor-peticoes", "Revisor de Petições", "MANUAL_REVISOR_PETICOES.md"),
    ("diario-oficial", "Diário Oficial", "MANUAL_DIARIO_OFICIAL.md"),
    ("notificacoes", "Notificações por E-mail", "MANUAL_NOTIFICACOES.md"),
    ("conectar-ia", "Conectar sua IA (MCP)", "MANUAL_MCP.md"),
)
```

Em `app/services/manual_assistant_service.py:23-29`, acrescentar à tupla `_MANUAL_FILES`:

```python
_MANUAL_FILES = (
    ("Dashboard Principal", "MANUAL_DASHBOARD.md"),
    ("Painel FAP", "MANUAL_PAINEL_FAP.md"),
    ("Painel de Contestações", "MANUAL_PAINEL_CONTESTACOES.md"),
    ("Revisor de Petições", "MANUAL_REVISOR_PETICOES.md"),
    ("Diário Oficial", "MANUAL_DIARIO_OFICIAL.md"),
    ("Notificações por E-mail", "MANUAL_NOTIFICACOES.md"),
)
```

No mesmo arquivo, `_SYSTEM_INSTRUCTIONS` enumera os painéis cobertos — se a lista não for atualizada, o assistente **recusa perguntas sobre o novo manual mesmo tendo o texto no prompt**. Trocar a frase de abertura por:

```python
_SYSTEM_INSTRUCTIONS = """Você é o assistente de ajuda do sistema IntellexIA. \
Seu papel é tirar dúvidas dos usuários sobre os painéis e recursos do IntellexIA \
cobertos pelos manuais: Dashboard Principal, Painel FAP, Painel de Contestações, \
Revisor de Petições, Diário Oficial e Notificações por E-mail.
```

- [ ] **Step 4: Conferir que o manual renderiza e o assistente o enxerga**

```bash
uv run python -c "
from main import app
from app.services import manual_renderer, manual_assistant_service
with app.app_context():
    print('MANUAIS:', manual_renderer._MANUALS)
    print('ARQUIVOS DO ASSISTENTE:', manual_assistant_service._MANUAL_FILES)
"
```

Esperado: o novo manual aparece nas duas coleções.

Depois subir a aplicação e abrir `http://localhost:5000/docs/manuais`, confirmando que "Diário Oficial" aparece no índice lateral e que os avisos `[!DOU]`, `[!INFO]` e `[!ALERTA]` renderizam coloridos, e o `:btn-primary[Reprocessar]` vira um botão.

- [ ] **Step 5: Rodar toda a bateria de testes do módulo**

```bash
uv run python tests/test_dou_xml_parser.py && \
uv run python tests/test_dou_ingestion.py && \
uv run python tests/test_inlabs_client.py && \
uv run python tests/test_dou_routes.py
```

Esperado: os quatro terminam com `✅ Todos os testes passaram`.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/MANUAL_DIARIO_OFICIAL.md app/services/manual_renderer.py app/services/manual_assistant_service.py
git commit -m "docs(dou): manual do usuário e registro do módulo no CLAUDE.md

Documenta o mecanismo do INLABS (seções, headers, 404 como estado normal,
janela móvel de ~4 meses) e, sobretudo, a exceção de multi-tenancy: as
tabelas do DOU não têm law_firm_id, e esse é o ponto que mais confundiria
quem chegar depois."
```

---

## Após a implementação — passos operacionais

Estes não são tasks de código; são o que põe o módulo em produção.

1. **Preencher as credenciais** no `.env` de produção: `INLABS_EMAIL` e `INLABS_PASSWORD`.
2. **Rodar a migração** em produção: `uv run python database/add_dou_tables.py`.
3. **Instalar o cron**:
   ```cron
   0 7,12,19 * * * cd /sites/intellexia && flock -n /tmp/intellexia_dou.lock \
       uv run python scripts/sync_dou.py >> /var/log/intellexia/sync_dou.log 2>&1
   ```
4. **Conceder o módulo** aos usuários que devem vê-lo, em Administração de Usuários.
5. **Rodar o backfill** quando houver janela: `uv run python scripts/sync_dou.py --backfill --desde 2026-04-13`. São ~11 GB e várias horas. Monitorar o disco durante (`df -h`).
6. **Agendar a poda mensal** de PDFs:
   ```cron
   0 3 1 * * cd /sites/intellexia && uv run python scripts/sync_dou.py --purge-pdfs \
       >> /var/log/intellexia/sync_dou.log 2>&1
   ```

---

## Cobertura do spec

| Seção do spec | Task |
|---|---|
| §3 Mecanismo do INLABS | Task 3 |
| §3.1 Correção dos defeitos do script oficial | Task 3 |
| §3.2 Credenciais e degradação graciosa | Task 3, Task 5 |
| §4 Arquitetura e fronteiras | Tasks 1, 3, 4 |
| §5.1 Exceção de multi-tenancy | Task 2 (docstrings), Task 7 (CLAUDE.md) |
| §5.2 `dou_editions` | Task 2 |
| §5.3 `dou_articles` | Task 2 |
| §5.4 `dou_sync_runs` | Task 2 |
| §6.1 Dedup por hash | Task 4 |
| §6.2 Janela de reverificação | Task 4 |
| §6.3 Cadência do cron | Task 5 |
| §6.4 Commit por unidade | Task 4 |
| §6.5 Falha não avança marca d'água | Task 4 |
| §7 Arquivos em disco e retenção | Task 4 (`purge_old_pdfs`), Task 5 (`--purge-pdfs`) |
| §8.1 Aba Acervo | Task 6 |
| §8.2 Aba Captura | Task 6 |
| §8.3 Permissões | Task 6 |
| §9 Script de sincronização e backfill | Task 5 |
| §10 Tratamento de erro | Tasks 3, 4 |
| §11 Testes | Tasks 1, 3, 4, 6 |
| §12 Migração | Task 2 |
| §13 Documentação | Task 7 |
| §14 Variáveis de ambiente | Task 3, Task 4, Task 7 |
