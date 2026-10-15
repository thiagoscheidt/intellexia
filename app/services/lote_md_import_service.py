"""Lote de Markdown do escritório (petições protocoladas + decisões) → bases.

A pasta tem a estrutura que o escritório entrega (ver o LEIA-ME do lote):

    <pasta>/
    ├── decisoes/                 _INDICE_decisoes.csv + um .md por decisão
    └── peticoes_protocoladas/    _INDICE_peticoes.csv + um .md por petição

Os arquivos entram **como vieram**: nada é renomeado, limpo ou reconvertido, e
a pasta de origem não é tocada (cada base recebe uma cópia). O CSV é só o
índice — é dele que sai a ligação com o que já existe, sem ler nome nem
conteúdo do .md:

- decisão → Base de Jurisprudência. "PDF de origem" é o `nome_arquivo` da
  planilha Banco Mestre (a mesma chave do "Anexar em lote"); sem par por nome,
  processo + instância + data (a chave de duplicata da base). Decisão que já
  existe e não tem arquivo recebe o .md sem passar pela IA; a que não existe
  vai para a fila de leitura. Decisão que já tem arquivo não é trocada.
- petição → Base de Conhecimento, indexada aqui mesmo e já concluída (ver
  `_ingerir_na_base`); impugnação à contestação vai **também** para
  as Peças-modelo, ligada pelo id do Drive do "Link" (o mesmo
  `source_drive_file_id` da importação pela planilha).

Duas etapas: `planejar` só lê (a conferência que o script mostra antes de
gravar) e `executar` grava. Rodar de novo é seguro: o que já entrou é
reconhecido pela chave de cada base e pulado — é o que vai permitir, mais
adiante, atualizar a partir do Drive com o mesmo CSV.
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from werkzeug.utils import secure_filename

from app.models import (
    db,
    ImpugnacaoReferenceModel,
    JurisprudenceDecision,
    JurisprudenceUpload,
    KnowledgeBase,
)
from app.services import jurisprudence_normalizer as norm
from app.services import jurisprudence_service as juris
from app.services import jurisprudence_upload_service as envios
from app.services.impugnacao_import_service import normalize_tribunal
from app.utils.text_files import read_text_file

PASTA_PADRAO = os.path.join('instance', 'importacao', 'lote_md')
PASTA_DECISOES = 'decisoes'
PASTA_PETICOES = 'peticoes_protocoladas'
CATEGORIA_BASE = 'Petições protocoladas'

# Ações do plano.
ANEXAR = 'anexar'                  # decisão existente recebe o .md
LER_IA = 'ler_ia'                  # decisão nova: fila de leitura da IA
PECA_MODELO = 'peca_modelo'
BASE_CONHECIMENTO = 'base_conhecimento'
PULAR = 'pular'

# Base a que a linha se destina (a impugnação gera duas linhas, uma em cada).
DESTINO_JURISPRUDENCIA = 'jurisprudencia'
DESTINO_BASE = 'base_conhecimento'
DESTINO_PECAS = 'pecas_modelo'

ROTULOS = {
    ANEXAR: 'Jurisprudência — anexar à decisão existente',
    LER_IA: 'Jurisprudência — decisão nova (leitura pela IA)',
    PECA_MODELO: 'Peças-modelo',
    BASE_CONHECIMENTO: 'Base de Conhecimento',
    PULAR: 'Pulado',
}


class LoteInvalido(Exception):
    """Pasta sem a estrutura esperada (mensagem pronta para o terminal)."""


@dataclass
class Item:
    origem: str                    # 'decisao' | 'peticao'
    acao: str
    arquivo: str                   # nome do .md como está no índice
    linha: int                     # linha no CSV (cabeçalho = 1); 0 = fora do índice
    motivo: str = ''
    caminho: Optional[Path] = None
    sha: Optional[str] = None
    alvo_id: Optional[int] = None  # decisão/peça/arquivo já existente envolvido
    dados: dict = field(default_factory=dict)
    resultado: str = ''
    criado_id: Optional[int] = None
    destino: str = ''              # DESTINO_* — vale também para a linha pulada


# ── Leitura tolerante do índice ───────────────────────────────────────

def _chave_coluna(nome: str) -> str:
    return norm.chave(nome).replace(' ', '')


def ler_indice(caminho: Path) -> list[dict]:
    """Linhas do CSV como `{chave da coluna: valor}`, numeradas em `_linha`.

    O CSV vem do Excel de quem gerou o lote: separador (tabulação, `;` ou `,`)
    e codificação (UTF-8 ou cp1252) variam, e célula com as teses passa do
    limite padrão do módulo `csv`. As colunas são achadas pelo nome sem acento,
    caixa nem espaço — "Órgão julgador" e "ORGAO JULGADOR" são a mesma.
    """
    texto = read_text_file(caminho)
    primeira = texto.split('\n', 1)[0]
    separador = max(('\t', ';', ','), key=primeira.count)
    csv.field_size_limit(1 << 30)
    leitor = csv.reader(io.StringIO(texto, newline=''), delimiter=separador)
    cabecalho = next(leitor, None)
    if not cabecalho:
        return []
    chaves = [_chave_coluna(c) for c in cabecalho]
    linhas = []
    for numero, valores in enumerate(leitor, start=2):
        if not any((v or '').strip() for v in valores):
            continue
        linha = {c: (valores[i].strip() if i < len(valores) else '') for i, c in enumerate(chaves) if c}
        linha['_linha'] = numero
        linhas.append(linha)
    return linhas


def _col(linha: dict, *nomes: str) -> str:
    for nome in nomes:
        valor = linha.get(_chave_coluna(nome))
        if valor:
            return valor
    return ''


def _chave_nome(nome: str) -> str:
    # Cópia Windows → Linux pode trazer o nome em NFD; a comparação não pode depender disso.
    return unicodedata.normalize('NFC', nome or '').strip().casefold()


def nome_extraido(nome: str) -> str:
    """O nome como estava no zip, quando o descompactador o estragou.

    O zip do lote marca os nomes como UTF-8, mas o `unzip` do servidor ignora
    a marca e decodifica pela página de código do DOS: "SENTENÇA" chega ao
    disco como "SENTEN├ЗA" (cp866) ou "SENTEN├çA" (cp437). Desfazer é exato —
    nome correto não sobrevive à volta (Ç não existe em cp866, e em cp437 vira
    um byte que não é UTF-8 válido) e fica como está. A pasta não é renomeada.
    """
    for codigo in ('cp866', 'cp437'):
        try:
            reparado = nome.encode(codigo).decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if reparado != nome:
            return reparado
    return nome


def _arquivos_md(pasta: Path) -> dict[str, Path]:
    arquivos = {}
    for p in sorted(pasta.rglob('*.md')):
        if p.is_file():
            arquivos.setdefault(_chave_nome(nome_extraido(p.name)), p)
            arquivos.setdefault(_chave_nome(p.name), p)
    return arquivos


def _sha(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _subpasta(pasta: Path, nome: str) -> Optional[Path]:
    for filho in pasta.iterdir() if pasta.is_dir() else []:
        if filho.is_dir() and _chave_nome(filho.name) == _chave_nome(nome):
            return filho
    return None


def _indice_da_pasta(pasta: Path) -> Optional[Path]:
    candidatos = sorted(p for p in pasta.glob('*.csv') if p.name.upper().startswith('_INDICE'))
    return candidatos[0] if candidatos else None


# ── Plano ─────────────────────────────────────────────────────────────

def _fora_do_indice(origem: str, arquivos: dict[str, Path], usados: set[Path]) -> list[Item]:
    return [Item(origem=origem, acao=PULAR, arquivo=nome_extraido(caminho.name), linha=0, caminho=caminho,
                 motivo='arquivo fora do índice CSV')
            for caminho in dict.fromkeys(arquivos.values()) if caminho not in usados]


def _tipo_da_decisao(linha: dict) -> Optional[str]:
    embargos = norm.chave(_col(linha, 'Embargos de declaração'))
    como_no_nome = norm.chave(_col(linha, 'Tipo (como no nome do arquivo)'))
    if embargos in ('SIM', 'S', 'X') or como_no_nome.endswith('ED'):
        return norm.TIPO_EMBARGOS
    return norm.tipo_documento(_col(linha, 'Tipo'))


def _planejar_decisoes(pasta: Path, law_firm_id: int) -> list[Item]:
    indice = _indice_da_pasta(pasta)
    if indice is None:
        raise LoteInvalido(f'Não achei o _INDICE_*.csv em {pasta}.')
    arquivos = _arquivos_md(pasta)

    decisoes = JurisprudenceDecision.query.filter_by(law_firm_id=law_firm_id).all()
    por_nome: dict[str, list[JurisprudenceDecision]] = {}
    for d in decisoes:
        if d.original_filename:
            por_nome.setdefault(envios._chave_do_arquivo(d.original_filename), []).append(d)
    enviados = {u.file_hash: u for u in JurisprudenceUpload.query.filter(
        JurisprudenceUpload.law_firm_id == law_firm_id, JurisprudenceUpload.file_hash.isnot(None))}

    itens, usados, ocupadas, na_fila = [], set(), set(), set()
    assinaturas: dict[str, Optional[str]] = {}

    def assinatura_anexada(decisao) -> Optional[str]:
        if decisao.pdf_path not in assinaturas:
            caminho_anexo = Path(decisao.pdf_path)
            assinaturas[decisao.pdf_path] = _sha(caminho_anexo) if caminho_anexo.is_file() else None
        return assinaturas[decisao.pdf_path]

    def decidir(item: Item, candidatas: list, forte: bool) -> bool:
        """Anexa à decisão livre ou pula. `forte` = casou pelo nome do PDF ou
        pela chave de duplicata da base (processo + instância + data). False =
        par fraco (sem instância) já ocupado: é outra decisão do mesmo processo
        e dia, e vai para a IA."""
        livres = [d for d in candidatas if not d.pdf_path and d.id not in ocupadas]
        if livres:
            item.acao, item.alvo_id = ANEXAR, livres[0].id
            item.dados['decisoes'] = [d.id for d in livres]
            ocupadas.update(d.id for d in livres)
            return True
        igual = next((d for d in candidatas if d.pdf_path and assinatura_anexada(d) == item.sha), None)
        if igual is not None:
            item.alvo_id, item.motivo = igual.id, f'este arquivo já está anexado (decisão #{igual.id})'
            return True
        if not forte:
            return False
        alvo = candidatas[0]
        item.alvo_id = alvo.id
        if alvo.id in ocupadas:
            # Mesmo documento em duas cópias do PDF ("Acórdão - IRANI.pdf" e
            # "12_05_2026 - ACÓRDÃO - IRANI - ….pdf"): a base não guarda dois.
            item.motivo = f'mesma decisão de outra linha deste lote (decisão #{alvo.id})'
        else:
            item.motivo = f'decisão já tem arquivo anexado (decisão #{alvo.id})'
        return True

    sem_par_pelo_nome = []
    for linha in ler_indice(indice):
        nome = _col(linha, 'Arquivo .md')
        item = Item(origem='decisao', acao=PULAR, arquivo=nome, linha=linha['_linha'],
                    destino=DESTINO_JURISPRUDENCIA)
        itens.append(item)
        caminho = arquivos.get(_chave_nome(nome))
        if not nome or caminho is None:
            item.motivo = 'arquivo .md não encontrado na pasta'
            continue
        usados.add(caminho)
        item.caminho, item.sha = caminho, _sha(caminho)
        item.dados = {'processo': _col(linha, 'Processo'), 'tipo': _tipo_da_decisao(linha),
                      'data': norm.para_data(_col(linha, 'Data')),
                      'pdf_de_origem': _col(linha, 'PDF de origem')}
        candidatas = por_nome.get(envios._chave_do_arquivo(item.dados['pdf_de_origem'])) or []
        if not (candidatas and decidir(item, candidatas, forte=True)):
            sem_par_pelo_nome.append(item)

    # Segunda passada, só depois que os nomes escolheram: o par por processo é
    # mais fraco e não pode tomar a decisão de quem casou pelo nome — senão o
    # resultado dependeria da ordem das linhas no CSV.
    for item in sem_par_pelo_nome:
        processo, tipo, data = item.dados['processo'], item.dados['tipo'], item.dados['data']
        digitos = norm.numero_cnj(processo) or norm.digitos(processo)
        mesma = juris.mesma_decisao(law_firm_id, digitos, tipo, data) if (digitos and tipo and data) else None
        if mesma is not None and decidir(item, [mesma], forte=True):
            continue
        candidatas = []
        if digitos and data and tipo in (None, norm.TIPO_OUTRA):
            # Índice sem instância (ex.: Tipo vazio): processo + data bastam,
            # desde que só uma decisão os tenha.
            mesmo_dia = JurisprudenceDecision.query.filter_by(
                law_firm_id=law_firm_id, processo_digits=digitos, data_julgamento=data).all()
            candidatas = mesmo_dia if len(mesmo_dia) == 1 else []
        if candidatas and decidir(item, candidatas, forte=False):
            continue

        anterior = enviados.get(item.sha)
        if anterior is not None:
            item.alvo_id = anterior.decision_id
            item.motivo = f'já enviado à fila de leitura (envio #{anterior.id}, situação {anterior.status})'
            continue
        if item.sha in na_fila:
            item.motivo = 'conteúdo idêntico a outra linha deste lote'
            continue
        na_fila.add(item.sha)
        item.acao = LER_IA
    return itens + _fora_do_indice('decisao', arquivos, usados)


# Só o rótulo; o número em si é lido por `norm.numero_cnj`, o padrão CNJ único
# do sistema (aceita com ou sem pontuação — o lote tem "Processo nº
# 50109013720224047108", que os padrões exatos de outros módulos não pegam).
_ROTULO_PROCESSO = re.compile(
    r'(?:processo(?:\s+de\s+origem)?|autos(?:\s+da\s+ação)?|proc\.)[\s*]*(?:n[º°o.]*|número)?[\s*:.]*(?=\d)',
    re.IGNORECASE)
_ENDERECAMENTO = re.compile(r'EXCELENT[IÍ]SSIM', re.IGNORECASE)


def processo_do_texto(texto: str) -> Optional[str]:
    """Número CNJ da própria petição, lido do texto — o índice CSV não traz.

    Medido no lote: o número vem rotulado logo após o endereçamento
    ("EXCELENTÍSSIMO… Processo nº 5052299-94.2022.4.04.7000") — na maioria
    até o caractere 130 do corpo, mas em ~25 petições o endereçamento só
    aparece entre 4 e 7 mil caracteres adiante. Por isso a ordem: (1) o número
    rotulado logo depois do endereçamento; (2) rotulado no começo do corpo;
    (3) sem rótulo, só bem no início. Número solto no meio do texto é
    precedente ou processo apenso, nunca o da peça — fica sem número (3 do lote).
    O cabeçalho do .md (antes do primeiro `---`) é pulado: lá está o link do
    Drive, não o processo.
    """
    corte = texto[:4000].find('\n---')
    corpo = texto[corte + 4:] if corte >= 0 else texto
    def rotulado(inicio: int, fim: int) -> Optional[str]:
        for rotulo in _ROTULO_PROCESSO.finditer(corpo, inicio, fim):
            # 25 caracteres = um CNJ formatado; o número tem de ser o do rótulo.
            numero = norm.numero_cnj(corpo[rotulo.end():rotulo.end() + 25])
            if numero:
                return numero
        return None

    enderecamento = _ENDERECAMENTO.search(corpo[:15000])
    numero = (rotulado(enderecamento.start(), enderecamento.start() + 1500) if enderecamento else None) \
        or rotulado(0, 2500) or norm.numero_cnj(corpo[:600])
    return norm.formatar_cnj(numero) if numero else None


def _eh_impugnacao(peca: str) -> bool:
    return 'IMPUGNACAO A CONTESTACAO' in norm.chave(peca)


def _planejar_peticoes(pasta: Path, law_firm_id: int) -> list[Item]:
    indice = _indice_da_pasta(pasta)
    if indice is None:
        raise LoteInvalido(f'Não achei o _INDICE_*.csv em {pasta}.')
    arquivos = _arquivos_md(pasta)

    na_base = {k.file_hash: k for k in KnowledgeBase.query.filter(
        KnowledgeBase.law_firm_id == law_firm_id, KnowledgeBase.is_active.is_(True),
        KnowledgeBase.file_hash.isnot(None))}
    pecas = ImpugnacaoReferenceModel.query.filter_by(law_firm_id=law_firm_id).all()
    pecas_por_drive = {p.source_drive_file_id: p for p in pecas if p.source_drive_file_id}
    pecas_por_hash = {p.file_hash: p for p in pecas if p.file_hash}

    itens, usados = [], set()
    vistos_base, vistos_peca = set(), set()
    for linha in ler_indice(indice):
        nome = _col(linha, 'Arquivo .md')
        numero = linha['_linha']
        caminho = arquivos.get(_chave_nome(nome))
        situacao = norm.chave(_col(linha, 'Situação'))
        if not nome or caminho is None or (situacao and situacao != 'CONVERTIDO'):
            motivo = (f'situação "{_col(linha, "Situação")}" no índice' if situacao and situacao != 'CONVERTIDO'
                      else 'arquivo .md não encontrado na pasta')
            itens.append(Item(origem='peticao', acao=PULAR, arquivo=nome, linha=numero, motivo=motivo,
                              destino=DESTINO_BASE))
            continue
        usados.add(caminho)
        sha = _sha(caminho)
        dados = {
            'processo': processo_do_texto(read_text_file(caminho)),
            'numero': _col(linha, 'Nº', 'N'), 'autora': _col(linha, 'Autora'),
            'tribunal': _col(linha, 'Tribunal'), 'orgao': _col(linha, 'Órgão julgador'),
            'peca': _col(linha, 'Peça'), 'protocolo': _col(linha, 'Protocolo'),
            'teses': _col(linha, 'Teses'), 'paginas': _col(linha, 'Páginas'),
            'paginas_ocr': _col(linha, 'Páginas com OCR'),
            'drive_id': envios.id_do_drive(_col(linha, 'Link')),
            'link': _col(linha, 'Link')[:500] or None,
        }

        base = Item(origem='peticao', acao=BASE_CONHECIMENTO, arquivo=nome, linha=numero, destino=DESTINO_BASE,
                    caminho=caminho, sha=sha, dados=dados)
        existente = na_base.get(sha)
        if existente is not None and existente.processing_status != 'completed':
            base.alvo_id = existente.id  # entrou antes e não terminou: indexa a mesma linha
        elif existente is not None:
            base.acao, base.alvo_id = PULAR, existente.id
            base.motivo = f'já está na Base de Conhecimento (arquivo #{existente.id})'
            faltando = {
                'completar_link': bool(dados['link'] and not existente.source_url),
                'completar_processo': bool(dados['processo'] and not existente.lawsuit_number),
            }
            if any(faltando.values()):
                # Cópia: `dados` é o mesmo objeto da linha da peça-modelo, e a
                # marca não pode vazar para lá (o alvo_id dela é id de peça).
                base.dados = {**dados, **faltando}
        elif sha in vistos_base:
            base.acao, base.motivo = PULAR, 'conteúdo idêntico a outra linha deste lote'
        vistos_base.add(sha)
        itens.append(base)

        if not _eh_impugnacao(dados['peca']):
            continue
        peca = Item(origem='peticao', acao=PECA_MODELO, arquivo=nome, linha=numero, destino=DESTINO_PECAS,
                    caminho=caminho, sha=sha, dados=dados)
        existente = pecas_por_drive.get(dados['drive_id']) or pecas_por_hash.get(sha)
        if existente is not None and existente.file_hash == sha and existente.ingestion_status != 'completed':
            # Criada por este lote e interrompida no meio da indexação: retoma a mesma linha.
            peca.alvo_id = existente.id
        elif existente is not None:
            peca.acao, peca.alvo_id = PULAR, existente.id
            peca.motivo = f'já existe como peça-modelo (#{existente.id} "{existente.title}")'
        elif (dados['drive_id'] or sha) in vistos_peca:
            peca.acao, peca.motivo = PULAR, 'mesma peça em outra linha deste lote'
        vistos_peca.add(dados['drive_id'] or sha)
        itens.append(peca)
    return itens + _fora_do_indice('peticao', arquivos, usados)


def planejar(pasta: str, law_firm_id: int) -> list[Item]:
    """O que cada linha do lote vai virar. Só lê — nada é gravado."""
    raiz = Path(pasta)
    if not raiz.is_dir():
        raise LoteInvalido(f'Pasta não encontrada: {pasta}')
    decisoes, peticoes = _subpasta(raiz, PASTA_DECISOES), _subpasta(raiz, PASTA_PETICOES)
    if decisoes is None and peticoes is None:
        raise LoteInvalido(f'{pasta} não tem as pastas "{PASTA_DECISOES}" nem "{PASTA_PETICOES}".')
    itens = []
    if decisoes is not None:
        itens += _planejar_decisoes(decisoes, law_firm_id)
    if peticoes is not None:
        itens += _planejar_peticoes(peticoes, law_firm_id)
    return itens


def filtrar(itens: list[Item], *, so: Optional[str] = None, sem_pecas: bool = False,
            so_pecas: bool = False) -> list[Item]:
    """Recorte do plano para uma rodada.

    - `so`: 'decisoes' ou 'peticoes' — uma das pastas do lote;
    - `sem_pecas`: tudo menos as peças-modelo (a impugnação continua indo para
      a Base de Conhecimento) — a peça é a etapa lenta, ~1 min 45 s cada por
      causa das 3 chamadas de IA, contra ~3 s de um arquivo da Base;
    - `so_pecas`: só as peças-modelo, para rodar à parte.

    O planejamento é sempre do lote inteiro (é ele que resolve duplicatas e
    quem fica com cada decisão); o recorte vem depois, então rodar em partes dá
    o mesmo resultado que rodar de uma vez.
    """
    if sem_pecas and so_pecas:
        raise ValueError('sem_pecas e so_pecas não combinam.')
    if so:
        origem = {'decisoes': 'decisao', 'peticoes': 'peticao'}[so]
        itens = [i for i in itens if i.origem == origem]
    if sem_pecas:
        itens = [i for i in itens if i.destino != DESTINO_PECAS]
    if so_pecas:
        itens = [i for i in itens if i.destino == DESTINO_PECAS]
    return itens


def resumo(itens: list[Item]) -> dict[str, int]:
    contagem: dict[str, int] = {}
    for item in itens:
        contagem[item.acao] = contagem.get(item.acao, 0) + 1
    return contagem


# ── Execução ──────────────────────────────────────────────────────────

def _copiar(item: Item, pasta: str, carimbo_no_fim: bool = False) -> str:
    """Cópia byte a byte para a pasta da base; a origem fica intacta."""
    os.makedirs(pasta, exist_ok=True)
    seguro = secure_filename(item.arquivo) or 'arquivo.md'
    carimbo = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    if carimbo_no_fim:  # padrão do upload da base de conhecimento
        raiz, ext = os.path.splitext(seguro)
        destino = os.path.join(pasta, f'{raiz}_{carimbo}{ext}')
    else:
        destino = os.path.join(pasta, f'{carimbo}_{seguro}')
    shutil.copyfile(item.caminho, destino)
    return destino


def _descricao(dados: dict, com_teses: bool = True) -> str:
    partes = [p for p in (dados.get('autora'), dados.get('tribunal'), dados.get('orgao')) if p]
    linhas = [f'Petição protocolada — {dados.get("peca") or "peça"}']
    if partes:
        linhas.append(' · '.join(partes))
    if dados.get('protocolo'):
        linhas.append(f'Protocolo: {dados["protocolo"]}')
    ocr, paginas = dados.get('paginas_ocr') or '', dados.get('paginas') or ''
    if ocr.isdigit() and int(ocr) > 0:
        linhas.append(f'Texto obtido por OCR em {ocr} de {paginas or "?"} páginas.')
    if com_teses and dados.get('teses'):
        linhas.append(f'Teses: {dados["teses"]}')
    return '\n'.join(linhas)


def _anexar_decisao(item: Item, law_firm_id: int, indexar: bool) -> str:
    from app.services import jurisprudence_index_service as indice
    nome = item.arquivo
    destino = _copiar(item, envios._pasta(law_firm_id))
    alvos = JurisprudenceDecision.query.filter(
        JurisprudenceDecision.law_firm_id == law_firm_id,
        JurisprudenceDecision.id.in_(item.dados['decisoes'])).all()
    for decisao in alvos:
        envios._anexar(decisao, destino, nome)
    db.session.commit()
    if indexar:
        for decisao in alvos:
            indice.preparar_e_indexar(decisao)
        db.session.commit()
    item.criado_id = alvos[0].id if alvos else None
    return f'anexado à decisão #{", #".join(str(d.id) for d in alvos)}'


def _enfileirar_decisao(item: Item, law_firm_id: int, user_id: int) -> str:
    upload = envios.receber_baixado(law_firm_id, str(item.caminho), item.arquivo, user_id,
                                    mover=False, iniciar=False)
    item.criado_id = upload.id
    if upload.status == JurisprudenceUpload.STATUS_REVIEW:
        return f'envio #{upload.id} em "revisar" (idêntico a uma decisão já lida)'
    return f'envio #{upload.id} na fila de leitura'


def _criar_peca(item: Item, law_firm_id: int, user_id: int, processar: bool) -> str:
    from app.services.impugnacao_reference_ingestion import ingest_reference
    dados = item.dados
    peca = None
    if item.alvo_id:
        peca = ImpugnacaoReferenceModel.query.filter_by(id=item.alvo_id, law_firm_id=law_firm_id).first()
    if peca is not None:
        peca.ingestion_status, peca.ingestion_error = 'processing', None
        db.session.commit()
        item.criado_id = peca.id
        if not processar:
            return f'peça-modelo #{peca.id} retomada (processamento pendente)'
        ingest_reference(law_firm_id, peca.id, is_new=True, preserve_curated_fields=True)
        db.session.refresh(peca)
        if peca.ingestion_status != 'completed':
            return f'peça-modelo #{peca.id} retomada, mas a indexação falhou: {peca.ingestion_error or "sem detalhe"}'
        return f'peça-modelo #{peca.id} retomada e indexada ({peca.chunks_count or 0} trechos)'
    destino = _copiar(item, os.path.join('uploads', 'impugnacao_references', str(law_firm_id)))
    autora, peca_rotulo = dados.get('autora') or '', dados.get('peca') or ''
    titulo = (f'{autora} — {peca_rotulo}' if autora and peca_rotulo else autora or Path(item.arquivo).stem)
    peca = ImpugnacaoReferenceModel(
        law_firm_id=law_firm_id, user_id=user_id, title=titulo[:250],
        case_name=autora[:255] or None, trf_region=normalize_tribunal(dados.get('tribunal')),
        orgao_julgador=(dados.get('orgao') or '')[:255] or None,
        original_filename=item.arquivo[:255], file_path=destino,
        file_size=os.path.getsize(destino), file_type='md', file_hash=item.sha,
        source_drive_file_id=dados.get('drive_id'),
        source_theses_json=[dados['teses']] if dados.get('teses') else None,
        status='active', ingestion_status='processing',
    )
    db.session.add(peca)
    db.session.commit()
    item.criado_id = peca.id
    if not processar:
        return f'peça-modelo #{peca.id} criada (processamento pendente)'
    ingest_reference(law_firm_id, peca.id, is_new=True, preserve_curated_fields=True)
    db.session.refresh(peca)
    if peca.ingestion_status != 'completed':
        return f'peça-modelo #{peca.id} criada, mas a indexação falhou: {peca.ingestion_error or "sem detalhe"}'
    return f'peça-modelo #{peca.id} indexada ({peca.chunks_count or 0} trechos)'


def _ingerir_na_base(arquivo: KnowledgeBase, dados: dict) -> int:
    """Indexa no Qdrant + Meilisearch da Base, como o processamento normal faz
    — o mesmo leitor de texto e o mesmo ingestor, com `file_id`. Devolve o
    número de trechos.

    O lote **não** passa pelo `process_knowledge_base`: aquele fluxo pede à IA
    a extração estruturada e, a partir dela, liga o documento a processo
    judicial (criando processo, cliente e réu) e grava benefícios de petição
    inicial. Aqui os metadados já vêm do índice CSV, e 1.304 petições
    protocoladas não podem virar processo no Painel por inferência da IA.
    A descrição do índice vai sem as teses: ela se repete em cada trecho, e
    as teses inteiras ficam na descrição do arquivo, no banco.
    """
    from app.agents.knowledge_base.knowledge_ingestion_agent import KnowledgeIngestionAgent
    from app.services.document_processor_service import DocumentProcessorService
    documento = DocumentProcessorService().process_document(file_path=arquivo.file_path)
    texto = KnowledgeIngestionAgent().process_file(
        processed_document=documento, source_name=arquivo.original_filename,
        category=arquivo.category, description=_descricao(dados, com_teses=False),
        tags=arquivo.tags, lawsuit_number=arquivo.lawsuit_number, file_id=arquivo.id,
    )
    if not texto:
        raise RuntimeError('o arquivo não tem texto para indexar')
    return len(documento.chunks_with_pages or []) or 1


def _criar_na_base(item: Item, law_firm_id: int, user_id: int) -> str:
    arquivo = None
    if item.alvo_id:
        arquivo = KnowledgeBase.query.filter_by(id=item.alvo_id, law_firm_id=law_firm_id).first()
    if arquivo is None:
        destino = _copiar(item, os.path.join('uploads', 'knowledge_base', str(law_firm_id)),
                          carimbo_no_fim=True)
        arquivo = KnowledgeBase(
            user_id=user_id, law_firm_id=law_firm_id, original_filename=item.arquivo[:255],
            file_path=destino, file_size=os.path.getsize(destino), file_type='MD', file_hash=item.sha,
        )
        db.session.add(arquivo)
    arquivo.description = _descricao(item.dados)
    arquivo.source_url = item.dados.get('link') or arquivo.source_url
    arquivo.lawsuit_number = item.dados.get('processo') or arquivo.lawsuit_number
    arquivo.category = CATEGORIA_BASE
    arquivo.tags = (item.dados.get('peca') or '')[:500] or None
    # 'processing' e não 'pending': o cron do process_knowledge_base pega pendentes.
    arquivo.processing_status = 'processing'
    arquivo.processing_error_message = None
    db.session.commit()
    item.criado_id = arquivo.id
    try:
        trechos = _ingerir_na_base(arquivo, item.dados)
    except Exception as erro:
        db.session.rollback()
        arquivo.processing_status = 'error'
        arquivo.processing_error_message = f'Indexação do lote: {erro}'[:2000]
        db.session.commit()
        raise
    arquivo.processing_status = 'completed'
    arquivo.processed_at = datetime.now()
    db.session.commit()
    return f'arquivo #{arquivo.id} indexado na Base de Conhecimento ({trechos} trechos)'


def _completar_campos(itens: list[Item], law_firm_id: int) -> None:
    """Link do Drive e número do processo para o que entrou sem eles — só os
    campos (e o número no payload do índice, para a busca exata por processo),
    sem reindexar o texto."""
    alvos = {i.alvo_id: i for i in itens
             if i.acao == PULAR and i.motivo.startswith('já está na Base')
             and (i.dados.get('completar_link') or i.dados.get('completar_processo'))}
    if not alvos:
        return
    from app.agents.knowledge_base.knowledge_ingestion_agent import KnowledgeIngestionAgent
    agente = None
    for arquivo in KnowledgeBase.query.filter(KnowledgeBase.law_firm_id == law_firm_id,
                                              KnowledgeBase.id.in_(list(alvos))):
        item, feito = alvos[arquivo.id], []
        if item.dados.get('completar_link') and not arquivo.source_url:
            arquivo.source_url = item.dados['link']
            feito.append('link do Drive')
        if item.dados.get('completar_processo') and not arquivo.lawsuit_number:
            arquivo.lawsuit_number = item.dados['processo']
            try:
                agente = agente or KnowledgeIngestionAgent()
                agente.update_lawsuit_number_by_file_id(arquivo.id, arquivo.lawsuit_number)
                feito.append('número do processo')
            except Exception as erro:
                feito.append(f'número do processo (índice não atualizado: {erro})')
        db.session.commit()
        if feito:
            item.resultado = ' e '.join(feito) + ' preenchido'


def _executar_um(item: Item, law_firm_id: int, user_id: int, indexar: bool, processar_pecas: bool) -> None:
    try:
        if item.acao == ANEXAR:
            item.resultado = _anexar_decisao(item, law_firm_id, indexar)
        elif item.acao == LER_IA:
            item.resultado = _enfileirar_decisao(item, law_firm_id, user_id)
        elif item.acao == PECA_MODELO:
            item.resultado = _criar_peca(item, law_firm_id, user_id, processar_pecas)
        elif item.acao == BASE_CONHECIMENTO:
            item.resultado = _criar_na_base(item, law_firm_id, user_id)
    except Exception as erro:
        db.session.rollback()
        item.resultado = f'ERRO: {erro}'


def executar(itens: list[Item], law_firm_id: int, user_id: int, *, indexar: bool = True,
             processar_pecas: bool = True, paralelo: int = 1,
             progresso: Optional[Callable[[int, int, Item], None]] = None) -> None:
    """Grava o plano. Uma linha com problema não derruba o lote: o erro fica no
    `resultado` dela e o resto segue.

    `paralelo` > 1 processa vários documentos ao mesmo tempo, cada um no seu
    contexto de aplicação (sessão de banco própria). O tempo da peça-modelo é
    quase todo espera da IA, então trabalhadores em paralelo rendem perto de
    N vezes. As linhas do plano são independentes entre si — o planejamento já
    resolveu quem fica com cada decisão e o que é duplicado — e o que der
    recusa por limite do provedor vira erro na linha e é retomado na próxima
    rodada.
    """
    _completar_campos(itens, law_firm_id)
    acionaveis = [i for i in itens if i.acao != PULAR]
    if paralelo <= 1:
        for posicao, item in enumerate(acionaveis, start=1):
            _executar_um(item, law_firm_id, user_id, indexar, processar_pecas)
            if progresso:
                progresso(posicao, len(acionaveis), item)
        return

    from concurrent.futures import ThreadPoolExecutor
    from flask import current_app
    import threading

    app_obj = current_app._get_current_object()
    trava, feitos = threading.Lock(), [0]

    def rodar(item: Item) -> None:
        with app_obj.app_context():
            try:
                _executar_um(item, law_firm_id, user_id, indexar, processar_pecas)
            finally:
                db.session.remove()
        with trava:
            feitos[0] += 1
            if progresso:
                progresso(feitos[0], len(acionaveis), item)

    with ThreadPoolExecutor(max_workers=paralelo, thread_name_prefix='lote-md') as pool:
        list(pool.map(rodar, acionaveis))


def gravar_relatorio(itens: list[Item], caminho: str) -> None:
    os.makedirs(os.path.dirname(caminho) or '.', exist_ok=True)
    with open(caminho, 'w', encoding='utf-8-sig', newline='') as fh:
        saida = csv.writer(fh, delimiter=';')
        saida.writerow(['Origem', 'Linha do índice', 'Arquivo .md', 'Destino', 'Motivo', 'Resultado', 'Id'])
        for item in itens:
            saida.writerow([item.origem, item.linha or '', item.arquivo, ROTULOS[item.acao],
                            item.motivo, item.resultado, item.criado_id or item.alvo_id or ''])
