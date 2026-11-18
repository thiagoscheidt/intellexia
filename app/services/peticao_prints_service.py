"""
Prints das petições protocoladas — fonte única da ferramenta do MCP, da rota da
API e da imagem servida na Base de Conhecimento.

O escritório põe nas petições os prints que sustentam o argumento (CONBAS,
INFBEN, laudo do SABI, CAT, tela do FAP...), cada um com uma legenda padronizada
logo acima — "CONBAS – B94 nº 6322736802 (ev. 1:16)". O mesmo print volta nas
peças seguintes do processo (impugnação → apelação → contrarrazões → embargos).

Nada é pré-processado:

- **O índice é o .md que já está na base.** A conversão das petições guardou a
  legenda e o texto lido dentro de cada imagem (``> *[Texto dentro de imagem]*``),
  então localizar um print é ler os .md — sem IA, sem tabela nova.
- **A imagem sai do PDF original na hora do pedido.** O .md perdeu a figura; o
  PDF está no Drive (``knowledge_base.source_url``) e é baixado pela conta de
  serviço. Ao baixar, todos os prints da petição vão para o cache em
  ``instance/prints_peticoes/`` — o segundo pedido da mesma peça é imediato.

Medido em 18/11/2026 (10 petições, 42 figuras): 33 das 42 figuras tinham a
legenda com sistema e evento; as outras eram continuação de um print que
quebrou de página, que aqui é juntada à figura anterior. Busca nos 1.168 .md:
0,8 s; download do PDF: ~3,6 s.
"""
from __future__ import annotations

import difflib
import hashlib
import io
import os
import re
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

CATEGORIA = 'Petições protocoladas'
MARCA_IMAGEM = '[Texto dentro de imagem]'

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR_CACHE = os.path.join(_RAIZ, 'instance', 'prints_peticoes')

# Ordem importa: o primeiro que casar dá o rótulo (laudo judicial antes do laudo
# do INSS, que casa qualquer "laudo médico"; "Tela do FAP" antes de "CAT", que
# aparece dentro de legenda de FAP).
SISTEMAS: tuple[tuple[str, str], ...] = (
    ('CONBAS', r'\bCONBAS\b'),
    ('INFBEN', r'\bINFBEN\b'),
    ('HISCAL', r'\bHISCAL\b'),
    ('HISCRE', r'\bHISCRE\b'),
    ('HISMED', r'\bHISMED\b'),
    ('PLENUS', r'\bPLENUS\b'),
    ('SUB', r'\bSUB\b|Sistema [ÚU]nico de Benef'),
    # Laudo citado com o número de um processo é o da perícia judicial.
    ('Laudo médico judicial', r'laudo (m[ée]dico )?(pericial )?judicial|per[íi]cia judicial'
                              r'|laudo m[ée]dico[^(]{0,40}processo n'),
    ('Laudo médico pericial do INSS', r'laudo m[ée]dico|\bSABI\b'),
    ('Tela do FAP', r'FAP ?WEB|telas? (d[oa] )?(sistema )?(do )?FAP|consulta do FAP|massa salarial'
                    r'|v[íi]nculos do ano'),
    ('CNIS', r'\bCNIS\b|rela[çc][õo]es previdenci[áa]rias'),
    ('CAT', r'\bCAT\b|comunica[çc][ãa]o de acidente'),
    ('CTPS', r'\bCTPS\b|carteira de trabalho'),
    ('Sentença', r'\bsenten[çc]a\b'),
    ('Acórdão', r'\bac[óo]rd[ãa]o\b'),
    ('Decisão', r'\bdecis[ãa]o\b'),
    ('Implantação', r'\bimplanta[çc][ãa]o\b'),
)

# A legenda do escritório sempre cita onde o documento está ("(ev. 1:6, pág. 16)",
# "(Id. 276159211 – pág. 21)", "(doc. anexo, pág. 17-18)"). É o que separa a
# legenda de um parágrafo qualquer que por acaso precede uma imagem (o timbre no
# topo, a assinatura no fim).
_REFERENCIA = re.compile(
    r'\((?:[^()]*?\b)?(?:ev(?:ento)?\.?\s*\d|id\.?\s*\d|doc\.|anexo|evento\s*\d)[^()]*\)', re.I)
_NUMEROS = re.compile(r'\d[\d./\-]{6,}\d')
_MARKDOWN = re.compile(r'</?(?:u|mark|b|i|strong|em)>|[*_`]+|^#+\s*', re.I)


class PrintIndisponivel(Exception):
    """O print existe no .md mas a imagem não pôde ser entregue."""

    def __init__(self, mensagem: str, status: int = 409):
        super().__init__(mensagem)
        self.status = status


# ── leitura do .md ────────────────────────────────────────────────────────────

@dataclass
class PrintMd:
    ordem: int                     # 1, 2, 3... dentro da petição
    legenda: str
    sistema: str
    numeros: list[str]             # NB, CAT, processo citados na legenda (só dígitos)
    referencia: str                # "(ev. 1:6, pág. 16)"
    texto_imagem: str              # o que a conversão leu dentro da figura
    partes: int = 1                # figuras seguidas sem legenda nova (print que quebrou)


def _limpar(linha: str) -> str:
    texto = _MARKDOWN.sub('', linha.strip())
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto.lstrip('-–• ').strip()


def chave(texto: str) -> str:
    """Comparação tolerante: sem acento, sem caixa, só letras e números."""
    sem_acento = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]', '', sem_acento.lower())


def sistema_da_legenda(legenda: str) -> str:
    for rotulo, padrao in SISTEMAS:
        if re.search(padrao, legenda, re.I):
            return rotulo
    return 'Outro'


_ITEM_DE_LISTA = re.compile(r'^\(?[a-z0-9ivx]{1,3}[).]\s', re.I)
_RODAPE_CEP = re.compile(r'^.*?\bCEP\s*\d{2}\.?\d{3}-?\d{3}\s*[-–]?\s*', re.I)
MAX_LEGENDA = 200


def legenda(linha: str) -> str:
    """A legenda contida na linha, ou ''.

    Legenda do escritório é curta, termina na referência ao processo — "(ev. 1:6,
    pág. 16)" — e não é item de lista ("a) o segurado sofreu..., conforme CAT
    (ev. 1:6, pág. 11);" é parágrafo, não legenda). O rodapé do timbre ("CEP
    88010-301") que a conversão às vezes cola na frente sai.

    Linha de citação é texto lido de uma imagem: quando a legenda grudou nele
    ("7253-10 CTPS (ev. 1:7, pág. 9)", "Tua 1% Laudo Médico ..."), ela começa
    no nome do documento.
    """
    bruto = (linha or '').strip()
    citacao = bruto.startswith('>')
    if citacao:
        bruto = bruto[1:].strip()
    tentativas = [bruto]
    if '**' in bruto and not bruto.startswith(('**', '#')):
        tentativas.append(bruto[bruto.index('**'):])
    for tentativa in tentativas:
        texto = _RODAPE_CEP.sub('', _limpar(tentativa)).strip().rstrip('*_ ').strip()
        if citacao:
            inicio = min((m.start() for _r, padrao in SISTEMAS
                          for m in [re.search(padrao, texto, re.I)] if m), default=0)
            texto = texto[inicio:]
        if _e_legenda(texto):
            return texto
    return ''


def _e_legenda(texto: str) -> bool:
    # Legenda começa com o nome do documento, em maiúscula: "acórdão (doc. anexo,
    # pág. 17-18)." é o fim de uma frase da peça.
    if (not texto or len(texto) > MAX_LEGENDA or _ITEM_DE_LISTA.match(texto)
            or not (texto[0].isupper() or texto[0].isdigit())):
        return False
    ref = None
    for ref in _REFERENCIA.finditer(texto):
        pass
    if not ref or texto[ref.end():].strip(' .:'):
        return False
    # Legenda é o nome de um documento; vírgula seguida de minúscula antes da
    # referência é frase da peça ("Outrossim, na forma do art. 1.007... (doc. anexo).").
    return not re.search(r',\s+[a-zà-ú]', texto[:ref.start()])


def parece_legenda(linha: str) -> bool:
    return bool(legenda(linha))


def _novo_print(prints: list, texto_legenda: str) -> PrintMd:
    sem_ref = _REFERENCIA.sub('', texto_legenda)
    ref = None
    for ref in _REFERENCIA.finditer(texto_legenda):
        pass
    p = PrintMd(
        ordem=len(prints) + 1,
        legenda=texto_legenda,
        sistema=sistema_da_legenda(texto_legenda),
        numeros=[n for n in (re.sub(r'\D', '', x) for x in _NUMEROS.findall(sem_ref)) if len(n) >= 7],
        referencia=ref.group(0) if ref else '',
        texto_imagem='',
        partes=0,
    )
    prints.append(p)
    return p


def prints_do_markdown(texto: str) -> list[PrintMd]:
    """Prints da petição, na ordem em que aparecem.

    Cada ``[Texto dentro de imagem]`` é uma figura e o print é a figura com a
    legenda dela. A conversão põe a legenda em três lugares, e os três valem:
    a linha logo antes do bloco da imagem (o normal); a primeira linha lida
    dentro da imagem; ou no meio do bloco da figura anterior, quando duas
    figuras seguidas viraram um bloco só — aí a legenda abre um print novo
    mesmo sem a marca. Figura sem legenda própria logo depois de outra é
    continuação (o print que quebrou de página) e soma uma parte à anterior.
    Figura cujo texto de cima não é legenda (timbre, assinatura) fica de fora.
    """
    linhas = (texto or '').splitlines()
    prints: list[PrintMd] = []
    pendente = ''          # legenda vista que ainda não ganhou figura
    atual: Optional[PrintMd] = None   # print recebendo o texto lido da imagem
    anonima = False        # figura sem legenda: o texto lido dela não vai a print nenhum
    recem_aberta = False   # figura acabou de abrir: a 1ª linha lida pode ser a legenda
    i = 0
    while i < len(linhas):
        linha = linhas[i]
        i += 1
        if not linha.strip():
            continue
        citacao = linha.lstrip().startswith('>')
        if not citacao:
            pendente = legenda(linha)
            atual, anonima, recem_aberta = None, False, False
            continue
        if MARCA_IMAGEM in linha:
            if pendente:
                atual, anonima = _novo_print(prints, pendente), False
                atual.partes = 1
                pendente = ''
            elif atual is not None or (prints and not anonima and _so_imagens_desde(linhas, i - 1)):
                atual = atual or prints[-1]
                atual.partes += 1
            else:
                atual, anonima = None, True
            recem_aberta = True
            continue
        achada = legenda(linha)
        if achada:
            if anonima and recem_aberta:
                atual, anonima = _novo_print(prints, achada), False
                atual.partes = 1
            else:
                pendente = achada
                atual, anonima = None, False
            recem_aberta = False
            continue
        if pendente:
            # legenda no meio do bloco seguida de mais texto lido: as duas
            # figuras viraram um bloco só — o texto já é da figura nova
            atual, anonima = _novo_print(prints, pendente), False
            atual.partes = 1
            pendente = ''
        recem_aberta = False
        if atual is not None and len(atual.texto_imagem) < 1500:
            atual.texto_imagem = (atual.texto_imagem + ' ' + _limpar(linha.lstrip()[1:])).strip()[:1500]
    return [p for p in prints if p.partes]


def _so_imagens_desde(linhas: list[str], indice: int) -> bool:
    """Entre esta marca e a figura anterior só houve citação (nenhum texto da peça)."""
    for j in range(indice - 1, -1, -1):
        if not linhas[j].strip():
            continue
        return linhas[j].lstrip().startswith('>')
    return False


# ── localizar ────────────────────────────────────────────────────────────────

def _caminho_md(kb) -> Optional[str]:
    caminho = kb.file_path or ''
    if not os.path.isabs(caminho):
        caminho = os.path.join(_RAIZ, caminho)
    return caminho if caminho.lower().endswith('.md') and os.path.isfile(caminho) else None


def _ler(caminho: str) -> str:
    with open(caminho, encoding='utf-8', errors='replace') as fh:
        return fh.read()


def drive_id(source_url: Optional[str]) -> Optional[str]:
    m = re.search(r'(?:/d/|[?&]id=)([\w-]{20,})', source_url or '')
    return m.group(1) if m else None


def data_da_peticao(nome: str) -> Optional[str]:
    m = re.match(r'(\d{4}-\d{2}-\d{2})', nome or '')
    return m.group(1) if m else None


def peticoes(law_firm_id: int, numero_processo: Optional[str] = None):
    """Petições protocoladas do escritório com .md — mais recente primeiro."""
    from app.models import KnowledgeBase
    from app.utils.cnj import filtro_numero_processo

    query = KnowledgeBase.query.filter(
        KnowledgeBase.law_firm_id == law_firm_id,
        KnowledgeBase.is_active.is_(True),
        KnowledgeBase.category == CATEGORIA,
    )
    if numero_processo:
        query = query.filter(filtro_numero_processo(
            numero_processo, coluna_mascara=KnowledgeBase.lawsuit_number, varios_numeros=True))
    return query.order_by(KnowledgeBase.original_filename.desc(), KnowledgeBase.id.desc()).all()


def localizar(law_firm_id: int, *, numero_processo: Optional[str] = None,
              numero: Optional[str] = None, sistema: Optional[str] = None,
              termo: Optional[str] = None) -> list[tuple]:
    """Todos os prints que atendem aos filtros: lista de (KnowledgeBase, PrintMd).

    ``numero`` casa pelos dígitos com qualquer número da legenda (NB, CAT,
    processo) — completo ou parte, mínimo 5 dígitos. ``sistema`` casa com o
    rótulo (CONBAS, CAT, "laudo"...). ``termo`` procura na legenda e no texto
    lido dentro da imagem (ex.: o nome do segurado).
    """
    digitos = re.sub(r'\D', '', numero or '')
    if numero and len(digitos) < 5:
        raise ValueError('Informe ao menos 5 dígitos do número (NB, CAT ou processo).')
    chave_sistema = chave(sistema) if sistema else ''
    chave_termo = chave(termo) if termo else ''

    achados = []
    for kb in peticoes(law_firm_id, numero_processo):
        caminho = _caminho_md(kb)
        if not caminho:
            continue
        texto = _ler(caminho)
        if MARCA_IMAGEM not in texto:
            continue
        # atalhos: o número ou o termo nem aparece na petição
        if digitos and digitos not in re.sub(r'\D', '', texto):
            continue
        if chave_termo and chave_termo not in chave(texto):
            continue
        for p in prints_do_markdown(texto):
            if digitos and not any(digitos in n for n in p.numeros):
                continue
            if chave_sistema and chave_sistema not in chave(p.sistema) and chave_sistema not in chave(p.legenda):
                continue
            if chave_termo and chave_termo not in chave(p.legenda) and chave_termo not in chave(p.texto_imagem):
                continue
            achados.append((kb, p))
    return achados


# ── Drive ────────────────────────────────────────────────────────────────────

_cache_acesso: dict[str, tuple[bool, float]] = {}
_lock_acesso = threading.Lock()
_ACESSO_TTL = 600


def drive_do_escritorio(law_firm_id: int) -> bool:
    """A conta de serviço do Drive é da instalação e só serve ao escritório configurado."""
    from app.services import google_drive_client as gdrive

    return gdrive.configurado() and gdrive.law_firm_id_configurado() == law_firm_id


def pdfs_acessiveis(law_firm_id: int, ids: set) -> dict:
    """{id do Drive: True/False} — se a conta de serviço consegue abrir cada PDF.

    Pergunta arquivo por arquivo (cache de 10 min), e não pela listagem: a
    listagem só traz o que foi compartilhado **com a conta**, e o PDF aberto
    "para qualquer pessoa com o link" baixa normalmente sem aparecer nela
    (medido em 18/11/2026: a petição da Toniolo de 2025 baixava e não estava
    na lista). Id fora do dicionário = não dá para saber (Drive não configurado
    para o escritório ou fora do ar) — a resposta então não afirma nada.
    """
    if not ids or not drive_do_escritorio(law_firm_id):
        return {}
    from app.services import google_drive_client as gdrive

    agora = time.time()
    resultado, faltam = {}, []
    with _lock_acesso:
        for fid in ids:
            guardado = _cache_acesso.get(fid)
            if guardado and guardado[1] > agora:
                resultado[fid] = guardado[0]
            else:
                faltam.append(fid)
    if faltam:
        cliente = gdrive.cliente()
        for fid in faltam:
            try:
                cliente.metadados(fid)
                acessivel = True
            except gdrive.DriveSemAcesso:
                acessivel = False
            except gdrive.DriveErro:
                continue
            resultado[fid] = acessivel
            with _lock_acesso:
                _cache_acesso[fid] = (acessivel, agora + _ACESSO_TTL)
    return resultado


# ── extração do PDF ──────────────────────────────────────────────────────────

@dataclass
class FiguraPdf:
    pagina: int
    legenda: str
    retangulo: tuple
    imagens: list = field(default_factory=list)   # [(bytes, ext)] — mais de uma = continuação


def _decorativa(rect, outros) -> bool:
    """Moldura de sombra do Word: faixa mais larga que outra figura e que a cerca.

    As petições do escritório põem cada print numa caixa com sombra, que o PDF
    guarda como 2–3 faixas de imagem atrás do print — mais largas que ele dos
    dois lados e encostadas nele na vertical.
    """
    for o in outros:
        if o is rect:
            continue
        if rect.x0 < o.x0 - 2 and rect.x1 > o.x1 + 2 and rect.y0 < o.y1 + 25 and rect.y1 > o.y0 - 25:
            return True
    return False


def figuras_do_pdf(caminho_pdf: str) -> list[FiguraPdf]:
    """Prints do PDF na ordem de leitura, cada um com a legenda que está logo acima.

    Fica de fora: o que se repete em quase toda página (timbre), imagem pequena
    (ícone) e as molduras de sombra. Figura sem texto entre ela e a anterior —
    colada embaixo, ou no topo da página seguinte — é continuação e vira mais
    uma parte da figura anterior. Legenda que ficou sozinha no pé da página
    anterior vale para a primeira figura da página seguinte.
    """
    import fitz

    doc = fitz.open(caminho_pdf)
    aparicoes: dict[int, int] = {}
    for page in doc:
        for info in page.get_images(full=True):
            aparicoes[info[0]] = aparicoes.get(info[0], 0) + 1
    repetida = max(3, len(doc) // 2)
    # Cabeçalho e rodapé (endereço, telefone do escritório) são texto que se
    # repete em quase toda página: se contasse, toda figura do topo da página
    # pareceria ter texto antes e nenhum print de duas páginas seria emendado.
    textos: dict[str, int] = {}
    for page in doc:
        for k in {chave(re.sub(r'\d', '', b[4])) for b in page.get_text('blocks') if b[6] == 0}:
            textos[k] = textos.get(k, 0) + 1

    figuras: list[FiguraPdf] = []
    legenda_no_pe = ''   # legenda no fim da página anterior, sem figura depois dela
    for pno, page in enumerate(doc):
        timbre = [r for info in page.get_images(full=True) if aparicoes.get(info[0], 0) >= repetida
                  for r in page.get_image_rects(info[0])]
        blocos = [b for b in page.get_text('blocks')
                  if b[6] == 0 and _significativo(b[4])
                  and textos.get(chave(re.sub(r'\d', '', b[4])), 0) < repetida
                  and not any(fitz.Rect(b[:4]).intersects(r) for r in timbre)]
        candidatas = []
        for info in page.get_images(full=True):
            xref = info[0]
            if aparicoes.get(xref, 0) >= repetida:
                continue
            for rect in page.get_image_rects(xref):
                if rect.width >= 60 and rect.height >= 30:
                    candidatas.append((rect, xref))
        retangulos = [r for r, _ in candidatas]
        conteudo = sorted(((r, x) for r, x in candidatas if not _decorativa(r, retangulos)),
                          key=lambda c: (c[0].y0, c[0].x0))

        topo = 0.0
        for rect, xref in conteudo:
            extraida = doc.extract_image(xref)
            imagem = (extraida['image'], extraida['ext'])
            entre = [b for b in blocos if b[1] >= topo - 2 and b[3] <= rect.y0 + 2]
            if not entre and topo == 0.0 and legenda_no_pe:
                figuras.append(FiguraPdf(pno + 1, legenda_no_pe, tuple(rect), [imagem]))
            elif not entre and figuras:
                figuras[-1].imagens.append(imagem)
            else:
                acima = [b for b in entre if b[3] >= rect.y0 - 90]
                legenda = re.sub(r'\s+', ' ', acima[-1][4]).strip() if acima else ''
                figuras.append(FiguraPdf(pno + 1, legenda, tuple(rect), [imagem]))
            legenda_no_pe = ''
            topo = rect.y1

        depois = [b for b in blocos if b[1] >= topo - 2]
        if depois:
            ultimo = re.sub(r'\s+', ' ', depois[-1][4]).strip()
            legenda_no_pe = ultimo if parece_legenda(ultimo) else ''
            # Texto depois da última figura: a figura do topo da próxima página não
            # é continuação dela. A marca vazia quebra o encadeamento.
            if not legenda_no_pe and figuras and figuras[-1].imagens:
                figuras.append(FiguraPdf(pno + 1, '', (), []))
        else:
            legenda_no_pe = ''
    return [f for f in figuras if f.imagens]


def _significativo(texto: str) -> bool:
    """Texto que separa figuras. Número de folha e carimbo curto não contam."""
    return len(re.sub(r'\s+', '', texto or '')) >= 4


def casar(prints: list[PrintMd], figuras: list[FiguraPdf]) -> dict[int, FiguraPdf]:
    """Liga cada print do .md à figura do PDF pela legenda.

    Igual ou contida (o bloco de texto do PDF às vezes traz a legenda colada a
    outra linha) vale; senão a mais parecida acima de 0,8. A mesma figura não
    serve a dois prints, e a ordem desempata legendas repetidas na peça.
    """
    usadas: set[int] = set()
    resultado: dict[int, FiguraPdf] = {}
    chaves_fig = [chave(f.legenda) for f in figuras]
    for p in prints:
        alvo = chave(p.legenda)
        if not alvo:
            continue
        melhor, nota = None, 0.0
        for i, cf in enumerate(chaves_fig):
            if i in usadas or not cf:
                continue
            if cf == alvo or (len(alvo) >= 12 and (alvo in cf or cf in alvo)):
                melhor, nota = i, 1.0
                break
            r = difflib.SequenceMatcher(None, alvo, cf).ratio()
            if r > nota:
                melhor, nota = i, r
        if melhor is not None and nota >= 0.8:
            usadas.add(melhor)
            resultado[p.ordem] = figuras[melhor]
    return resultado


def _juntar(imagens: list) -> tuple[bytes, str]:
    """Uma imagem só: a figura, ou as partes empilhadas quando o print quebrou de página."""
    if len(imagens) == 1:
        return imagens[0]
    from PIL import Image

    partes = [Image.open(io.BytesIO(b)).convert('RGB') for b, _ in imagens]
    largura = max(p.width for p in partes)
    partes = [p if p.width == largura else p.resize((largura, round(p.height * largura / p.width)))
              for p in partes]
    folha = Image.new('RGB', (largura, sum(p.height for p in partes)), 'white')
    y = 0
    for p in partes:
        folha.paste(p, (0, y))
        y += p.height
    saida = io.BytesIO()
    folha.save(saida, 'JPEG', quality=92)
    return saida.getvalue(), 'jpeg'


def _arquivo_cache(law_firm_id: int, kb_id: int, p: PrintMd) -> str:
    assinatura = hashlib.sha1(p.legenda.encode()).hexdigest()[:10]
    return os.path.join(DIR_CACHE, str(int(law_firm_id)), f'{int(kb_id)}_{p.ordem}_{assinatura}')


def _no_cache(base: str) -> Optional[tuple[str, str]]:
    for ext in ('jpeg', 'png', 'jpg'):
        if os.path.isfile(f'{base}.{ext}'):
            return f'{base}.{ext}', ext
    return None


def imagem_do_print(law_firm_id: int, kb_id: int, ordem: int, *, baixar=None) -> tuple[str, str]:
    """Caminho da imagem do print ``ordem`` da petição ``kb_id`` (e a extensão).

    Na primeira vez baixa o PDF do Drive e grava no cache **todos** os prints da
    petição que casaram. ``baixar(file_id, pasta) -> caminho`` é injetável nos
    testes; o padrão é a conta de serviço.
    """
    from app.models import KnowledgeBase

    kb = KnowledgeBase.query.filter_by(id=kb_id, law_firm_id=law_firm_id, is_active=True).first()
    caminho_md = _caminho_md(kb) if kb else None
    if not caminho_md:
        raise PrintIndisponivel('Petição não encontrada na Base de Conhecimento.', 404)
    prints = prints_do_markdown(_ler(caminho_md))
    alvo = next((p for p in prints if p.ordem == ordem), None)
    if not alvo:
        raise PrintIndisponivel('Esse print não existe nesta petição.', 404)

    pronto = _no_cache(_arquivo_cache(law_firm_id, kb.id, alvo))
    if pronto:
        return pronto

    fid = drive_id(kb.source_url)
    if not fid:
        raise PrintIndisponivel('A petição não tem o link do PDF original no Drive.', 409)
    if baixar is None:
        if not drive_do_escritorio(law_firm_id):
            raise PrintIndisponivel('O Google Drive não está configurado para este escritório nesta instalação.',
                                    503)
        from app.services import google_drive_client as gdrive

        def baixar(file_id, pasta):
            try:
                return gdrive.cliente().baixar(file_id, pasta)[0]
            except gdrive.DriveSemAcesso:
                raise PrintIndisponivel(
                    'O PDF desta petição não está compartilhado com o IntellexIA no Google Drive. '
                    'Abra o original pelo link do Drive ou peça para compartilhar a pasta das petições '
                    'com a conta de serviço.', 409)
            except gdrive.DriveErro as erro:
                raise PrintIndisponivel(f'Google Drive indisponível: {erro}', 503)

    with tempfile.TemporaryDirectory(prefix='prints_') as pasta:
        pdf = baixar(fid, pasta)
        try:
            figuras = figuras_do_pdf(pdf)
        except Exception as erro:  # PDF corrompido ou que não é PDF
            raise PrintIndisponivel(f'Não foi possível ler o PDF da petição ({type(erro).__name__}).', 409)

    ligados = casar(prints, figuras)
    os.makedirs(os.path.join(DIR_CACHE, str(int(law_firm_id))), exist_ok=True)
    for p in prints:
        figura = ligados.get(p.ordem)
        if not figura:
            continue
        conteudo, ext = _juntar(figura.imagens)
        base = _arquivo_cache(law_firm_id, kb.id, p)
        parcial = f'{base}.{ext}.part'
        with open(parcial, 'wb') as fh:
            fh.write(conteudo)
        os.replace(parcial, f'{base}.{ext}')

    pronto = _no_cache(_arquivo_cache(law_firm_id, kb.id, alvo))
    if not pronto:
        raise PrintIndisponivel(
            'O print está citado na petição, mas não foi possível localizá-lo no PDF '
            '(a legenda no PDF não bate com a do texto). Abra o original pelo link do Drive.', 409)
    return pronto
