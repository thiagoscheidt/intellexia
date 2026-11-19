"""Conteúdo dos anexos das contestações do FAP: texto e tipo do documento.

Função pura (sem banco, rede ou Flask). Os anexos são extratos dos sistemas do
INSS e já vêm com texto — numa amostra de 40 em 18/11/2026 nenhum era imagem —,
então o texto sai do PDF pelo PyMuPDF, sem IA e sem OCR. O tipo e os campos
saem por regra, do cabeçalho de cada extrato (amostra de 120: CONBAS 47,
INFBEN 30, eSocial 11, CNIS 5, CAT 4, HISMED 2, o resto outro).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

TIPOS = {
    'CONBAS': 'CONBAS (concessão do benefício)',
    'INFBEN': 'INFBEN (informações do benefício)',
    'HISMED': 'HISMED (perícias médicas)',
    'CAT': 'CAT (comunicação de acidente)',
    'CNIS': 'CNIS (vínculos e remunerações)',
    'ESOCIAL': 'Insumos do eSocial',
    'OUTRO': 'Outro documento',
}
# Texto menor que isto é PDF de imagem (ou vazio): não vale como conteúdo.
MINIMO_DE_TEXTO = 40

# Ordem importa: o CONBAS cita "Situação:" como o INFBEN, e o HISMED também.
_REGRAS = (
    ('HISMED', ('HISMED', 'HISTORICO DE PERICIAS MEDICAS')),
    ('CONBAS', ('CONBAS', 'INFORMACOES DA CONCESSAO DO BENEFICIO')),
    ('CAT', ('COMUNICACAO DE ACIDENTE DE TRABALHO', 'CAT - COMUNICACAO')),
    ('CNIS', ('CADASTRO NACIONAL DE INFORMACOES SOCIAIS', 'CNIS -')),
    ('ESOCIAL', ('INSUMOS ESOCIAL',)),
    ('INFBEN', ('INFBEN', 'CONREV', 'INFORMACOES DO BENEFICIO')),
)
_CID = re.compile(r'(?<![A-Z0-9])([A-TV-Z]\d{2}(?:\.\d)?)(?![A-Z0-9])')
_CAT_NUMERO = re.compile(r'\b(\d{4}\.\d{6}\.\d/\d{2})\b')
_ESPECIE = re.compile(r'ESPECIE:\s*(\d{2})\s*-')


def _sem_acento(texto: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', texto) if not unicodedata.combining(c)).upper()


def extrair_texto(caminho: str) -> str:
    import fitz  # PyMuPDF

    with fitz.open(caminho) as doc:
        return '\n'.join(p.get_text() for p in doc).strip()


def classificar(texto: Optional[str]) -> tuple[str, dict]:
    """``(tipo, campos)``. Campos só do que a regra acha com segurança."""
    t = _sem_acento(texto or '')
    tipo = 'OUTRO'
    for nome, marcas in _REGRAS:
        if any(m in t for m in marcas):
            tipo = nome
            break
    if tipo == 'INFBEN' or (tipo == 'OUTRO' and 'NB:' in t and 'SITUACAO:' in t and 'DIB:' in t):
        tipo = 'INFBEN'

    campos: dict = {}
    especie = _ESPECIE.search(t)
    if especie and tipo in ('CONBAS', 'INFBEN', 'HISMED'):
        campos['especie'] = especie.group(1)
    if tipo == 'HISMED':
        # A espécie (B91…) tem cara de CID; ela vem como "91 - …", sem letra.
        cids = list(dict.fromkeys(_CID.findall(t)))
        if cids:
            campos['cids'] = cids
    if tipo == 'CAT':
        numero = _CAT_NUMERO.search(t)
        if numero:
            campos['cat_numero'] = numero.group(1)
        if re.search(r'\bTRAJETO\b', t):
            campos['cat_tipo'] = 'TRAJETO'
        elif re.search(r'\bTIPICO\b', t):
            campos['cat_tipo'] = 'TIPICO'
        elif re.search(r'\bDOENCA\b', t):
            campos['cat_tipo'] = 'DOENCA'
    return tipo, campos


_NOME_TIPO = (
    ('HISMED', re.compile(r'HISMED|PERICIAS? MEDICAS?|SABI')),
    ('CONBAS', re.compile(r'CONBAS|DADOS BASICOS DA CONCESSAO')),
    ('INFBEN', re.compile(r'INFBEN|CONREV')),
    ('CNIS', re.compile(r'CNIS|(?<![A-Z])VINCULOS?(?![A-Z])')),  # não "vinculado ao CNPJ"
    ('CAT', re.compile(r'(?<![A-Z])CAT(?![A-Z])|COMUNICACAO DE ACIDENTE')),
    ('ESOCIAL', re.compile(r'ESOCIAL|INSUMOS')),
)


def tipo_pelo_nome(nome: Optional[str]) -> str:
    """Tipo pelo nome do arquivo — para o PDF digitalizado, que não tem texto
    ("CONBAS-B92.pdf", "Dados Básicos da Concessão - CONBAS.pdf")."""
    n = _sem_acento(nome or '')
    for tipo, padrao in _NOME_TIPO:
        if padrao.search(n):
            return tipo
    return 'OUTRO'


_MOTOR_OCR = None
DPI_OCR = 150


def ocr(caminho: str, dpi: int = DPI_OCR) -> str:
    """Texto de um PDF digitalizado pelo RapidOCR (vem com o Docling; o
    servidor não tem Tesseract). Medido em 18/11/2026: ~8 s por página com o
    servidor carregado; perde acento e às vezes cola palavras — quem mostra o
    texto avisa que é leitura por OCR."""
    global _MOTOR_OCR
    import fitz  # PyMuPDF

    if _MOTOR_OCR is None:
        from rapidocr import RapidOCR
        _MOTOR_OCR = RapidOCR()
    paginas = []
    with fitz.open(caminho) as doc:
        for pagina in doc:
            r = _MOTOR_OCR(pagina.get_pixmap(dpi=dpi).tobytes('png'))
            paginas.append('\n'.join(getattr(r, 'txts', None) or ()))
    return '\n'.join(paginas).strip()


def instancia_do_recalculo(tipo_recalculo: Optional[str]) -> Optional[int]:
    t = (tipo_recalculo or '').upper()
    if 'SEGUNDA' in t:
        return 2
    if 'PRIMEIRA' in t:
        return 1
    return None
