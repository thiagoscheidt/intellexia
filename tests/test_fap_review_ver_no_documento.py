#!/usr/bin/env python3
"""
RPI-14 — "Ver no documento" do Revisor de Petições.

Medido antes da correção, clicando no botão num Chromium de verdade:
- DOCX de 6 MB levava até 5 s para chegar ao trecho, sem aviso de carregamento,
  e nos primeiros instantes o modal ainda mostrava o documento do achado anterior;
- trecho de tabela ("Item | Vigência do FAP | CNPJ") caía em outro lugar, porque
  a busca era célula a célula;
- PDF (7 das 15 revisões) nunca navegava: só pulava de página quando a
  localização escrita pelo modelo citava "página N".

Script standalone no padrão do projeto. Os PDFs são gerados na hora; o teste de
rota usa um escritório descartável, removido no fim.

    uv run python tests/test_fap_review_ver_no_documento.py
"""

import json
import re
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import fitz  # PyMuPDF

from app.utils.document_utils import localizar_pagina_pdf

_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


def _pdf(paginas: list[str]) -> Path:
    """PDF de texto com uma string por página."""
    destino = Path(tempfile.mkdtemp()) / 'peticao.pdf'
    doc = fitz.open()
    for texto in paginas:
        pagina = doc.new_page()
        pagina.insert_textbox(fitz.Rect(50, 50, 550, 800), texto, fontsize=11)
    doc.save(destino)
    doc.close()
    return destino


PETICAO = [
    'EXCELENTISSIMO SENHOR JUIZ FEDERAL. SENDAS DISTRIBUIDORA S.A., inscrita no CNPJ '
    'sob o nº 06.057.223/0001-71, vem propor a presente ação.',
    'DOS FATOS. O segurado sofreu acidente em 10/01/2025, conforme a Comunicação de '
    'Acidente de Trabalho (CAT) apresentada pela empresa.',
    'DOS PEDIDOS. Dá-se à causa o valor de R$ 1.000,00 (mil reais). Nestes termos, '
    'pede deferimento.',
]


# ── localizar_pagina_pdf ────────────────────────────────────────────────

def test_acha_a_pagina_do_trecho():
    print('\n1. PDF — acha a página onde o trecho está')

    pdf = _pdf(PETICAO)
    check('trecho da página 2', localizar_pagina_pdf(pdf, 'conforme a Comunicação de Acidente de Trabalho') == 2,
          str(localizar_pagina_pdf(pdf, 'conforme a Comunicação de Acidente de Trabalho')))
    check('trecho da página 3', localizar_pagina_pdf(pdf, 'Dá-se à causa o valor') == 3)
    check('trecho da página 1', localizar_pagina_pdf(pdf, 'SENDAS DISTRIBUIDORA S.A.') == 1)


def test_tolera_acento_caixa_e_pontuacao():
    print('\n2. PDF — o modelo copia o trecho com pequenas diferenças')

    pdf = _pdf(PETICAO)
    # Mesma normalização do preview DOCX: sem acento, sem caixa, sem pontuação.
    check('sem acento e em minúsculas',
          localizar_pagina_pdf(pdf, 'conforme a comunicacao de acidente de trabalho') == 2)
    check('pontuação diferente', localizar_pagina_pdf(pdf, 'SENDAS DISTRIBUIDORA S/A, inscrita') == 1,
          str(localizar_pagina_pdf(pdf, 'SENDAS DISTRIBUIDORA S/A, inscrita')))
    check('quebra de linha no meio do trecho',
          localizar_pagina_pdf(pdf, 'conforme a\nComunicação de   Acidente') == 2)


def test_trecho_que_atravessa_a_quebra_de_pagina():
    print('\n3. PDF — trecho que começa numa página e termina na outra')

    pdf = _pdf(['Texto inicial. O pedido de exclusão do benefício', 'decorre do nexo afastado. Fim.'])
    check('abre na página onde o trecho começa',
          localizar_pagina_pdf(pdf, 'exclusão do benefício decorre do nexo') == 1,
          str(localizar_pagina_pdf(pdf, 'exclusão do benefício decorre do nexo')))


def test_formulario_com_rotulo_e_valor_intercalados():
    print('\n4b. PDF — formulário (CAT): rótulo e valor não saem juntos no texto')

    # Medido numa CAT real: a extração do PDF intercala as colunas
    # ("19 data do acidente 23 houve afastamento 27 07 2018"), e o modelo
    # devolve o trecho montado ("19 - Data do Acidente: 27/07/2018"). A frase
    # contínua não existe no PDF; as palavras existem, na mesma página.
    pdf = _pdf([
        'CAT - Comunicação de Acidente de Trabalho\n19 - Data do Acidente:\n23 - Houve afastamento?\n'
        '27/07/2018\nSim\n22 - Tipo:\nUrbana\nTRAJETO\n25 - Local do acidente:\nVIA PUBLICA',
        'Atestado médico\nCID S82\nEmitente: Dr. Fulano\nData: 28/07/2018',
    ])
    check('acha a página pelo conjunto de palavras',
          localizar_pagina_pdf(pdf, '19 - Data do Acidente: 27/07/2018') == 1,
          str(localizar_pagina_pdf(pdf, '19 - Data do Acidente: 27/07/2018')))
    check('outro campo do mesmo formulário', localizar_pagina_pdf(pdf, '22 - Tipo: TRAJETO') == 1)
    # Palavras soltas que existem nas duas páginas não bastam para escolher.
    check('empate entre páginas não vira chute', localizar_pagina_pdf(pdf, 'Data 2018 acidente médico') is None,
          str(localizar_pagina_pdf(pdf, 'Data 2018 acidente médico')))
    check('metade das palavras não basta', localizar_pagina_pdf(pdf, 'Data do Acidente em Curitiba no Paraná') is None,
          str(localizar_pagina_pdf(pdf, 'Data do Acidente em Curitiba no Paraná')))


def test_nao_acha_nao_chuta():
    print('\n4. PDF — sem o trecho, não inventa página')

    pdf = _pdf(PETICAO)
    check('trecho que não existe', localizar_pagina_pdf(pdf, 'texto que não está na petição') is None)
    check('trecho vazio', localizar_pagina_pdf(pdf, '') is None)
    check('trecho curto demais para provar localização', localizar_pagina_pdf(pdf, 'a') is None)
    check('arquivo que não é PDF', localizar_pagina_pdf(Path(__file__), 'teste') is None)
    check('arquivo que não existe', localizar_pagina_pdf('/nao/existe.pdf', 'teste') is None)


# ── rota do preview para PDF ────────────────────────────────────────────

def test_rota_abre_o_pdf_na_pagina():
    print('\n5. PDF — o botão abre o PDF direto na página do trecho')

    from main import app
    from app.models import (db, LawFirm, User, UserPageVisit, FapReviewAuditLog,
                            FapReviewPetition, FapReviewExecution)

    def remover(firm_id):
        db.session.rollback()
        UserPageVisit.query.filter_by(law_firm_id=firm_id).delete()
        FapReviewAuditLog.query.filter_by(law_firm_id=firm_id).delete()
        FapReviewExecution.query.filter_by(law_firm_id=firm_id).delete()
        FapReviewPetition.query.filter_by(law_firm_id=firm_id).delete()
        User.query.filter_by(law_firm_id=firm_id).delete()
        LawFirm.query.filter_by(id=firm_id).delete()
        db.session.commit()

    pdf = _pdf(PETICAO)
    with app.app_context():
        velho = LawFirm.query.filter_by(name='__TESTE_RPI14__').first()
        if velho:
            remover(velho.id)
        firm = LawFirm(name='__TESTE_RPI14__', cnpj='00000000000191')
        db.session.add(firm); db.session.flush()
        user = User(law_firm_id=firm.id, name='Teste', email='rpi14@teste.invalid',
                    password_hash='x', role='admin')
        db.session.add(user); db.session.flush()
        exe = FapReviewExecution(law_firm_id=firm.id, user_id=user.id, execution_type='revision',
                                 status='completed', main_document_path=str(pdf),
                                 main_document_filename='peticao.pdf')
        db.session.add(exe); db.session.commit()
        firm_id, exe_id = firm.id, exe.id
        sessao = dict(user_id=user.id, law_firm_id=firm.id, user_role='admin', user_name='Teste')

        try:
            client = app.test_client()
            with client.session_transaction() as s:
                s.update(sessao)
            base = f'/fap-review/revision/{exe_id}/document/main'

            r = client.get(f'{base}/preview', query_string={'trecho': 'Dá-se à causa o valor'})
            destino = r.headers.get('Location', '')
            check('redireciona para o PDF', r.status_code == 302 and base in destino, f'{r.status_code} {destino}')
            check('na página do trecho', destino.endswith('#page=3'), destino)

            r = client.get(f'{base}/preview', query_string={'trecho': 'não existe', 'destaque': 'Pedidos, página 2'})
            destino = r.headers.get('Location', '')
            check('sem o trecho, usa a página citada na localização', destino.endswith('#page=2'), destino)

            r = client.get(f'{base}/preview', query_string={'trecho': 'não existe', 'destaque': 'Dos pedidos'})
            destino = r.headers.get('Location', '')
            check('sem trecho nem página, abre no início', '#page=' not in destino, destino)

            # RPI-25: "ver trecho" nos dados extraídos dos anexos, pelo mesmo caminho.
            print('\n5b. RPI-25 — "ver trecho" do dado extraído abre o anexo no lugar certo')
            from docx import Document as _Docx
            anexo_docx = Path(tempfile.mkdtemp()) / 'laudo.docx'
            documento = _Docx()
            documento.add_paragraph('Laudo pericial.')
            documento.add_paragraph('Conclusão: incapacidade temporária de 30 dias.')
            documento.save(anexo_docx)
            exe = db.session.get(FapReviewExecution, exe_id)
            exe.auxiliary_documents_json = json.dumps([
                {'name': '2. CAT.pdf', 'path': str(pdf)},
                {'name': 'laudo.docx', 'path': str(anexo_docx)},
            ])
            db.session.commit()
            aux = f'/fap-review/revision/{exe_id}/document/aux'

            r = client.get(f'{aux}/0/preview', query_string={'trecho': 'Dá-se à causa o valor'})
            destino = r.headers.get('Location', '')
            check('anexo PDF abre na página do trecho', r.status_code == 302 and destino.endswith(f'{aux}/0#page=3'),
                  f'{r.status_code} {destino}')

            r = client.get(f'{aux}/1/preview', query_string={'trecho': 'incapacidade temporária de 30 dias'})
            html = r.data.decode('utf-8')
            check('anexo DOCX abre o preview', r.status_code == 200 and 'docx-preview' in html, str(r.status_code))
            check('com o trecho para grifar', 'incapacidade tempor' in html and 'excerpt' in html)

            r = client.get(f'{aux}/9/preview', query_string={'trecho': 'x'})
            check('anexo inexistente não quebra', r.status_code in (302, 404), str(r.status_code))
        finally:
            remover(firm_id)


# ── telas ───────────────────────────────────────────────────────────────

def test_preview_docx():
    print('\n6. DOCX — o preview chega ao trecho e avisa quando não acha')

    preview = (RAIZ / 'templates' / 'fap_review' / 'document_preview.html').read_text(encoding='utf-8')
    check('rolagem instantânea, não suave', "behavior: 'smooth'" not in preview)
    check('reposiciona quando as imagens terminam de carregar',
          "addEventListener('load'" in preview)
    check('linha de tabela entra na busca do trecho', re.search(r"\.docx-preview tr\b", preview) is not None)
    check('avisa quando o trecho não é localizado', 'preview-aviso' in preview)
    check('linha de tabela junta as células com espaço', "join(' ')" in preview)


def test_botao_ver_trecho_nos_anexos():
    print('\n7b. RPI-25 — dado extraído do anexo tem botão "ver trecho"')

    resultado = (RAIZ / 'templates' / 'fap_review' / 'revision_result.html').read_text(encoding='utf-8')
    check('botão no dado extraído', 'view-aux-excerpt-btn' in resultado)
    check('só quando há trecho e arquivo', re.search(
        r'\{% if fact\.source_excerpt and aux_link %\}\s*<button[^>]*view-aux-excerpt-btn', resultado) is not None)
    check('abre no mesmo modal do "ver no documento"',
          'data-preview-url' in resultado and 'dataset.previewUrl' in resultado)


def test_modal_do_resultado():
    print('\n7. Modal — aviso de carregamento e PDF pela rota que localiza')

    resultado = (RAIZ / 'templates' / 'fap_review' / 'revision_result.html').read_text(encoding='utf-8')
    check('há aviso de carregamento sobre o documento', 'findingPageLoading' in resultado)
    check('o aviso sai quando o documento carrega', "findingPageIframe.addEventListener('load'" in resultado)
    # Navegador que baixa PDF em vez de exibir nunca dispara o load do iframe.
    check('o aviso tem prazo e não prende o modal', 'FINDING_PAGE_LOADING_MAX_MS' in resultado
          and 'setTimeout(hideFindingPageLoading' in resultado)
    check('PDF passa pela rota que localiza a página',
          resultado.count('/preview?') >= 1 and '#page=${pageNumber}' not in resultado)


def main() -> int:
    test_acha_a_pagina_do_trecho()
    test_tolera_acento_caixa_e_pontuacao()
    test_trecho_que_atravessa_a_quebra_de_pagina()
    test_formulario_com_rotulo_e_valor_intercalados()
    test_nao_acha_nao_chuta()
    test_rota_abre_o_pdf_na_pagina()
    test_preview_docx()
    test_botao_ver_trecho_nos_anexos()
    test_modal_do_resultado()

    print('\n' + '=' * 62)
    if _falhas:
        print(f'❌ {len(_falhas)} verificação(ões) falharam:')
        for nome in _falhas:
            print(f'   - {nome}')
        return 1
    print('✅ Tudo verde')
    return 0


if __name__ == '__main__':
    sys.exit(main())
