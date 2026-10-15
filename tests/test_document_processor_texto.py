"""
Markdown e texto puro no DocumentProcessorService: lidos direto, sem conversão.

Antes, o .md passava pelo Docling, que não pagina Markdown (0 páginas, 0
trechos — só o full_text), e o .txt era recusado por ele ("File format not
allowed") e saía vazio. Estas verificações trancam o caminho direto que as
três bases (Base de Conhecimento, Peças-modelo e Jurisprudência) usam.

Executar:
    uv run python tests/test_document_processor_texto.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.document_processor_service import DocumentProcessorService  # noqa: E402

FALHAS = []


def check(rotulo, condicao, extra=''):
    print(f"  {'✓' if condicao else '✗'} {rotulo}" + (f' — {extra}' if extra and not condicao else ''))
    if not condicao:
        FALHAS.append(rotulo)


def _arquivo(pasta, nome, conteudo: bytes) -> str:
    caminho = os.path.join(pasta, nome)
    with open(caminho, 'wb') as f:
        f.write(conteudo)
    return caminho


def main():
    print('=' * 60)
    print('PROCESSADOR: MARKDOWN E TEXTO PURO')
    print('=' * 60)
    processador = DocumentProcessorService()
    with tempfile.TemporaryDirectory() as pasta:
        partes = ['# Impugnação ao FAP', '## 1. DOS FATOS']
        partes += [f'Parágrafo {i} ' + 'texto da peça ' * 30 for i in range(12)]
        partes += ['## 2. DO ACIDENTE DE TRAJETO', 'Benefícios contestados:\n| NB | Espécie |\n|:---|---:|\n'
                   '| 6123456789 | B91 |\n| 6987654321 | B94 |']
        partes += [f'Fundamento {i} ' + 'fundamentação ' * 40 for i in range(5)]
        md = _arquivo(pasta, 'peca.md', '\n\n'.join(partes).encode('utf-8'))
        r = processador.process_document(md)
        check('.md vira páginas sintéticas com trechos', r.total_pages == 3 and len(r.chunks_with_pages) == 3,
              (r.total_pages, len(r.chunks_with_pages)))
        check('o texto mantém a marcação Markdown', r.full_text.startswith('# Impugnação ao FAP'))
        check('títulos ## numerados viram seção',
              [c['section'] for c in r.chunks_with_pages][:2] == ['1. DOS FATOS', '2. DO ACIDENTE DE TRAJETO'],
              [c['section'] for c in r.chunks_with_pages])
        check('tabela Markdown sai no formato do pdfplumber, sem a linha separadora',
              len(r.tables) == 1 and r.tables[0]['text'] == ['NB | Espécie', '6123456789 | B91', '6987654321 | B94'],
              r.tables)
        check('a tabela herda a seção da página', r.tables and r.tables[0]['section'] == '2. DO ACIDENTE DE TRAJETO')
        check('parágrafo nunca é cortado entre páginas',
              all(not c['text'].endswith('texto da') for c in r.chunks_with_pages))

        txt = _arquivo(pasta, 'nota.txt', 'Ação de revisão do FAP — vigência 2021.'.encode('cp1252'))
        r = processador.process_document(txt)
        check('.txt em cp1252 é lido (antes saía vazio)',
              r.total_pages == 1 and 'Ação de revisão do FAP — vigência 2021.' in r.full_text, r.full_text)

        bom = _arquivo(pasta, 'bom.md', '﻿# Título'.encode('utf-8'))
        check('BOM do UTF-8 não entra no texto', processador.process_document(bom).full_text == '# Título')

        vazio = _arquivo(pasta, 'vazio.md', b'\n\n  \n')
        r = processador.process_document(vazio)
        check('arquivo vazio não inventa página', r.total_pages == 0 and not r.chunks_with_pages)

    print('\n' + '=' * 60)
    if FALHAS:
        print(f'❌ {len(FALHAS)} falha(s): {", ".join(FALHAS)}')
        return 1
    print('✅ Todos os testes passaram')
    return 0


if __name__ == '__main__':
    sys.exit(main())
