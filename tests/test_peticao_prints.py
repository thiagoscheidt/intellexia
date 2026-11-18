#!/usr/bin/env python3
"""
Prints das petições protocoladas (`peticao_prints_service`, `prints_das_peticoes`).

1. Leitura do .md: a legenda nos três lugares em que a conversão a deixa (antes
   do bloco, 1ª linha lida da imagem, no meio do bloco anterior), continuação de
   print que quebrou de página, e o que não é legenda (item de lista, fim de
   frase, timbre sem legenda, rodapé "CEP" colado na frente).
2. PDF montado aqui: timbre repetido, molduras de sombra, legenda no pé da
   página anterior e print em duas partes — a figura certa para cada legenda.
3. Busca e ferramenta: filtros, escritório, envelope e link.
4. Imagem: baixa uma vez (download injetado), grava o cache da petição inteira,
   emenda as partes; a rota entrega ao escritório dono e só a ele.

Escritórios descartáveis, removidos no fim. Não usa o Google Drive.

    uv run python tests/test_peticao_prints.py
"""

import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app
from app.models import db, KnowledgeBase, LawFirm, User, UserPageVisit
from app.services import peticao_prints_service as svc

CNPJS = ('00000000002101', '00000000002292')
PROCESSO = '5047933-95.2025.4.04.7100'
_falhas = []


def check(nome: str, condicao: bool, detalhe: str = '') -> None:
    if condicao:
        print(f'  ✅ {nome}')
    else:
        print(f'  ❌ {nome}{" — " + detalhe if detalhe else ""}')
        _falhas.append(nome)


# ── material ─────────────────────────────────────────────────────────────────

MD = """# Impugnação

Texto da peça, sem imagem.

CONBAS – B94 nº 6322736802 **(ev. 1:16)**

> *[Texto dentro de imagem]*
> CONBAS - Dados Basicos da Concessao
> NB 6322736802 FULANO DE TESTE

- a) o segurado sofreu acidente de trajeto, conforme CAT nº 2017.194.308-2/01 **(ev. 1:6, pág. 11)**;

> *[Texto dentro de imagem]*
> ESCRITORIO DE TESTE (timbre)

CEP 88010-301 **Laudo Médico Pericial do INSS** – **B91 nº 6313323282 (ev. 1:6, pág. 16)**

> *[Texto dentro de imagem]*
> SABI - Laudo Médico
> *[Texto dentro de imagem]*
> continuação do laudo, CID M75

Florianópolis/SC, 18 de novembro de 2026.
"""

MD_LEGENDA_NO_BLOCO = """## CAT 2017.391.991-0/01 (ev. 1:7, pág. 4)

> *[Texto dentro de imagem]*
> Comunicação de Acidente de Trabalho
> Laudo Médico Pericial do INSS – B91 nº 6207772419 (ev. 42:8, pág. 14)
> INSS - SABI - Laudo Médico
"""

MD_LEGENDA_NA_IMAGEM = """Ao analisar as informações constantes na CAT, em conjunto com os laudos médicos periciais do INSS e com a sentença proferida no processo previdenciário, resta evidente que o acidente foi de trajeto **(ev. 1:6, pág. 11)**.

> *[Texto dentro de imagem]*
> CAT nº 2017.194.308-2/01 (ev. 1:6, pág. 11)
> Comunicação de Acidente de Trabalho

e, como se vê no acórdão (doc. anexo, pág. 17-18).

> *[Texto dentro de imagem]*
> texto de um acórdão
"""


def _png(cor, largura=600, altura=300) -> bytes:
    from PIL import Image

    saida = io.BytesIO()
    Image.new('RGB', (largura, altura), cor).save(saida, 'PNG')
    return saida.getvalue()


CORES = {'conbas': (200, 30, 30), 'laudo1': (30, 160, 30), 'laudo2': (30, 30, 200)}


def _pdf(caminho: str) -> None:
    """4 páginas: timbre e rodapé em todas; CONBAS com moldura na 2; legenda do
    laudo no pé da 3; laudo em duas partes no topo da 4."""
    import fitz

    doc = fitz.open()
    timbre = None
    for _ in range(4):
        doc.new_page(width=595, height=842)
    paginas = [doc[i] for i in range(4)]   # página nova invalida os objetos das anteriores
    for page in paginas:
        if timbre is None:
            timbre = page.insert_image(fitz.Rect(0, 0, 595, 69), stream=_png((90, 90, 90), 2000, 230))
        else:
            page.insert_image(fitz.Rect(0, 0, 595, 69), xref=timbre)
        page.insert_text((80, 820), 'Rua de Teste, 100 - CEP 88010-301 - escritorio.teste', fontsize=8)
    paginas[0].insert_text((80, 120), 'Texto da peça, sem imagem, primeira página.', fontsize=11)

    p = paginas[1]
    p.insert_text((80, 100), 'Texto antes do print, um parágrafo qualquer da peça.', fontsize=11)
    p.insert_text((80, 140), 'CONBAS – B94 nº 6322736802 (ev. 1:16)', fontsize=11)
    for y in (150, 250, 350):   # moldura de sombra: faixas mais largas, atrás do print
        p.insert_image(fitz.Rect(116, y, 523, y + 100), stream=_png((150, 150, 150), 1695, 420))
    p.insert_image(fitz.Rect(135, 165, 504, 430), stream=_png(CORES['conbas']))
    p.insert_text((80, 480), 'Texto depois do print.', fontsize=11)

    p = paginas[2]
    p.insert_text((80, 100), 'Um parágrafo longo da peça que ocupa a página inteira.', fontsize=11)
    p.insert_text((80, 780), 'Laudo Médico Pericial do INSS – B91 nº 6313323282 (ev. 1:6, pág. 16)', fontsize=10)

    p = paginas[3]
    p.insert_image(fitz.Rect(135, 80, 504, 300), stream=_png(CORES['laudo1']))
    p.insert_image(fitz.Rect(135, 300, 504, 420), stream=_png(CORES['laudo2'], 600, 150))
    p.insert_text((80, 500), 'Florianópolis/SC, 18 de novembro de 2026.', fontsize=11)
    doc.save(caminho)


# ── 1. leitura do .md ────────────────────────────────────────────────────────

def test_markdown():
    print('\n1. Leitura do .md')
    prints = svc.prints_do_markdown(MD)
    check('dois prints (timbre e item de lista ficam de fora)', len(prints) == 2,
          str([p.legenda for p in prints]))
    if len(prints) == 2:
        conbas, laudo = prints
        check('legenda limpa (sem negrito)', conbas.legenda == 'CONBAS – B94 nº 6322736802 (ev. 1:16)',
              conbas.legenda)
        check('sistema e NB da legenda', conbas.sistema == 'CONBAS' and conbas.numeros == ['6322736802'])
        check('referência separada', conbas.referencia == '(ev. 1:16)', conbas.referencia)
        check('texto lido da imagem guardado', 'FULANO DE TESTE' in conbas.texto_imagem)
        check('rodapé "CEP" colado na frente sai', laudo.legenda.startswith('Laudo Médico Pericial'),
              laudo.legenda)
        check('laudo do INSS reconhecido', laudo.sistema == 'Laudo médico pericial do INSS', laudo.sistema)
        check('duas figuras seguidas sem legenda = um print em 2 partes', laudo.partes == 2, str(laudo.partes))
        check('ordem 1 e 2', [p.ordem for p in prints] == [1, 2])

    dois = svc.prints_do_markdown(MD_LEGENDA_NO_BLOCO)
    check('legenda no meio do bloco da figura anterior abre print novo',
          [p.sistema for p in dois] == ['CAT', 'Laudo médico pericial do INSS'], str([p.legenda for p in dois]))
    if len(dois) == 2:
        check('texto lido depois da legenda vai ao print novo', 'SABI' in dois[1].texto_imagem
              and 'SABI' not in dois[0].texto_imagem)

    um = svc.prints_do_markdown(MD_LEGENDA_NA_IMAGEM)
    check('legenda lida como 1ª linha da imagem vale; parágrafo longo e fim de frase não',
          [p.legenda for p in um] == ['CAT nº 2017.194.308-2/01 (ev. 1:6, pág. 11)'], str([p.legenda for p in um]))

    check('legenda grudada em texto lido ("7253-10 CTPS (ev...)") começa no documento',
          svc.legenda('> 7253-10 CTPS **(ev. 1:7, pág. 9)**') == 'CTPS (ev. 1:7, pág. 9)',
          svc.legenda('> 7253-10 CTPS **(ev. 1:7, pág. 9)**'))
    check('item de lista não é legenda', not svc.legenda('- a) conforme CAT nº 1 **(ev. 1:6, pág. 11)**;'))
    check('frase que segue depois da referência não é legenda',
          not svc.legenda('Como se vê no CONBAS (ev. 1:16), o benefício foi concedido.'))


# ── 2. PDF ───────────────────────────────────────────────────────────────────

def _cor(imagem: bytes, y_frac=0.1):
    from PIL import Image

    im = Image.open(io.BytesIO(imagem)).convert('RGB')
    return im.getpixel((im.width // 2, int(im.height * y_frac)))


def _perto(c1, c2):
    return all(abs(a - b) < 25 for a, b in zip(c1, c2))


def test_pdf(pasta):
    print('\n2. Figuras do PDF')
    caminho = os.path.join(pasta, 'peticao.pdf')
    _pdf(caminho)
    figuras = svc.figuras_do_pdf(caminho)
    check('timbre e molduras de sombra ficam de fora: 2 figuras', len(figuras) == 2,
          str([(f.pagina, f.legenda, len(f.imagens)) for f in figuras]))
    if len(figuras) == 2:
        # A fonte padrão do PyMuPDF troca o travessão por "·": compara como o serviço compara.
        check('legenda logo acima da figura',
              svc.chave(figuras[0].legenda) == svc.chave('CONBAS – B94 nº 6322736802 (ev. 1:16)'),
              figuras[0].legenda)
        check('o print é a imagem do conteúdo, não a moldura', _perto(_cor(figuras[0].imagens[0][0]),
                                                                      CORES['conbas']))
        check('legenda no pé da página anterior vale para a figura do topo',
              figuras[1].legenda.startswith('Laudo Médico Pericial do INSS'), figuras[1].legenda)
        check('figura colada embaixo é continuação (2 partes)', len(figuras[1].imagens) == 2)
    ligados = svc.casar(svc.prints_do_markdown(MD), figuras)
    check('cada print do .md casa com a figura da sua legenda',
          len(ligados) == 2 and ligados[1] is figuras[0] and ligados[2] is figuras[1])
    return caminho


# ── 3/4. banco ───────────────────────────────────────────────────────────────

def _cleanup():
    for cnpj in CNPJS:
        firm = LawFirm.query.filter_by(cnpj=cnpj).first()
        if not firm:
            continue
        KnowledgeBase.query.filter_by(law_firm_id=firm.id).delete()
        for u in User.query.filter_by(law_firm_id=firm.id).all():
            UserPageVisit.query.filter_by(user_id=u.id).delete()
            db.session.delete(u)
        shutil.rmtree(os.path.join(svc.DIR_CACHE, str(firm.id)), ignore_errors=True)
        db.session.delete(firm)
    db.session.commit()


def _setup(pasta):
    _cleanup()
    usuarios, arquivos = [], []
    for i, cnpj in enumerate(CNPJS):
        firm = LawFirm(name=f'Escritório Teste Prints {i}', cnpj=cnpj)
        db.session.add(firm)
        db.session.flush()
        u = User(law_firm_id=firm.id, name=f'adv {i}', role='admin', is_active=True,
                 email=f'adv{i}__test_prints@example.com')
        u.set_password('x')
        db.session.add(u)
        db.session.flush()
        usuarios.append(u)
    md = os.path.join(pasta, '2026-11-18 - EMPRESA TESTE - IMPUGNAÇÃO.md')
    with open(md, 'w', encoding='utf-8') as fh:
        fh.write(MD)
    kb = KnowledgeBase(user_id=usuarios[0].id, law_firm_id=usuarios[0].law_firm_id,
                       original_filename=os.path.basename(md), file_path=md, file_type='md',
                       category=svc.CATEGORIA, lawsuit_number=PROCESSO, is_active=True,
                       processing_status='completed',
                       source_url='https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view')
    db.session.add(kb)
    db.session.commit()
    arquivos.append(kb)
    return usuarios, kb


def test_busca(usuarios, kb):
    print('\n3. Busca e ferramenta')
    from fastmcp.exceptions import ToolError
    from mcp_server.tools.peticao_prints import petition_prints_handler

    a, b = usuarios[0].law_firm_id, usuarios[1].law_firm_id
    check('pelo processo (sem pontuação)', len(svc.localizar(a, numero_processo='50479339520254047100')) == 2)
    check('pelo NB (parte do número)', [p.ordem for _k, p in svc.localizar(a, numero='6313323')] == [2])
    check('pelo sistema', [p.ordem for _k, p in svc.localizar(a, numero_processo=PROCESSO, sistema='conbas')] == [1])
    check('pelo texto lido da imagem', [p.ordem for _k, p in svc.localizar(a, termo='fulano de teste')] == [1])
    check('outro escritório não acha', svc.localizar(b, numero_processo=PROCESSO) == [])
    try:
        svc.localizar(a, numero='123')
        check('número curto demais recusa', False)
    except ValueError:
        check('número curto demais recusa', True)

    try:
        petition_prints_handler(a, sistema='CONBAS')
        check('sem processo, número ou termo: recusa', False)
    except ToolError:
        check('sem processo, número ou termo: recusa', True)
    r = petition_prints_handler(a, numero_processo=PROCESSO, limite=1, app_public_url='https://app.teste')
    check('envelope paginado', r['total_encontrado'] == 2 and r['retornados'] == 1 and r['tem_mais']
          and r['proximo_deslocamento'] == 1)
    item = r['itens'][0]
    check('link da imagem na Base de Conhecimento',
          item['url_imagem'] == f'https://app.teste/knowledge-base/{kb.id}/print/1', item['url_imagem'])
    check('data da petição pelo nome', item['data_peticao'] == '2026-11-18')
    check('nada encontrado vem com dica', 'dica' in petition_prints_handler(a, numero='99999999'))


def test_imagem(usuarios, kb, pdf):
    print('\n4. Imagem')
    a = usuarios[0].law_firm_id
    downloads = []

    def baixar(fid, pasta):
        downloads.append(fid)
        destino = os.path.join(pasta, 'baixado.pdf')
        shutil.copy(pdf, destino)
        return destino

    caminho, ext = svc.imagem_do_print(a, kb.id, 2, baixar=baixar)
    from PIL import Image
    im = Image.open(caminho)
    check('print em 2 partes vem emendado numa imagem só',
          _perto(im.convert('RGB').getpixel((im.width // 2, 10)), CORES['laudo1'])
          and _perto(im.convert('RGB').getpixel((im.width // 2, im.height - 10)), CORES['laudo2']))
    check('baixou o PDF uma vez, pelo id do Drive', downloads == ['1AbCdEfGhIjKlMnOpQrStUvWxYz012345'])

    def sem_rede(fid, pasta):
        raise AssertionError('não devia baixar de novo')

    caminho1, _ = svc.imagem_do_print(a, kb.id, 1, baixar=sem_rede)
    check('o outro print da petição já estava no cache', _perto(_cor(open(caminho1, 'rb').read()),
                                                                CORES['conbas']))
    try:
        svc.imagem_do_print(usuarios[1].law_firm_id, kb.id, 1, baixar=sem_rede)
        check('outro escritório: 404', False)
    except svc.PrintIndisponivel as e:
        check('outro escritório: 404', e.status == 404)
    try:
        svc.imagem_do_print(a, kb.id, 9, baixar=sem_rede)
        check('print inexistente: 404', False)
    except svc.PrintIndisponivel as e:
        check('print inexistente: 404', e.status == 404)

    c = app.test_client()
    for u, esperado in ((usuarios[0], 200), (usuarios[1], 404)):
        with c.session_transaction() as s:
            s.clear()
            s['user_id'], s['law_firm_id'], s['user_role'] = u.id, u.law_firm_id, u.role
        resp = c.get(f'/knowledge-base/{kb.id}/print/1')
        check(f'rota: {"dono" if esperado == 200 else "outro escritório"} → {esperado}',
              resp.status_code == esperado, f'{resp.status_code} {resp.data[:120]!r}')
        if esperado == 200:
            check('rota entrega imagem', resp.mimetype.startswith('image/'), resp.mimetype)


def main():
    pasta = tempfile.mkdtemp(prefix='test_prints_')
    try:
        test_markdown()
        pdf = test_pdf(pasta)
        with app.app_context():
            try:
                usuarios, kb = _setup(pasta)
                test_busca(usuarios, kb)
                test_imagem(usuarios, kb, pdf)
            finally:
                db.session.rollback()
                _cleanup()
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    print('\n' + '=' * 62)
    if _falhas:
        print(f'❌ {len(_falhas)} falha(s): {", ".join(_falhas)}')
        sys.exit(1)
    print('✅ Tudo verde')


if __name__ == '__main__':
    main()
