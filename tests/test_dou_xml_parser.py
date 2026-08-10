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
    print('\n8. strip_html')
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
