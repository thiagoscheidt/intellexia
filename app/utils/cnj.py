"""Utilidades do número CNJ (Resolução CNJ 65/2008).

No formato NNNNNNN-DD.AAAA.J.TR.OOOO, J identifica o segmento de justiça e
TR o tribunal dentro dele — a sigla do tribunal é derivável do próprio número,
sem consulta externa.
"""
import re

_TJ_POR_CODIGO_UF = {
    '01': 'TJAC', '02': 'TJAL', '03': 'TJAP', '04': 'TJAM', '05': 'TJBA',
    '06': 'TJCE', '07': 'TJDFT', '08': 'TJES', '09': 'TJGO', '10': 'TJMA',
    '11': 'TJMT', '12': 'TJMS', '13': 'TJMG', '14': 'TJPA', '15': 'TJPB',
    '16': 'TJPR', '17': 'TJPE', '18': 'TJPI', '19': 'TJRJ', '20': 'TJRN',
    '21': 'TJRS', '22': 'TJRO', '23': 'TJRR', '24': 'TJSC', '25': 'TJSE',
    '26': 'TJSP', '27': 'TJTO',
}


def cnj_digits(value):
    """Só os dígitos do número do processo ('' se vazio)."""
    return re.sub(r'\D', '', value or '')


def tribunal_sigla_from_cnj(process_number):
    """Sigla do tribunal (TRF4, TJSC, TRT12...) derivada do número CNJ.

    None se o número não tiver os 20 dígitos ou o segmento não for mapeável.
    """
    digits = cnj_digits(process_number)
    if len(digits) != 20:
        return None
    segmento, tr = digits[13], digits[14:16]
    if segmento == '4':
        return f'TRF{int(tr)}'
    if segmento == '5':
        return f'TRT{int(tr)}'
    if segmento == '8':
        return _TJ_POR_CODIGO_UF.get(tr)
    return {'1': 'STF', '3': 'STJ', '7': 'STM'}.get(segmento)


def ensure_tribunal_sigla(process):
    """Preenche process.tribunal com a sigla derivada do número, se vazio.

    Trata lixo de importações antigas ('None'/'null' como string) como vazio.
    Retorna a sigla aplicada ou None se nada mudou.
    """
    atual = (process.tribunal or '').strip()
    if atual and atual.lower() not in ('none', 'null'):
        return None
    sigla = tribunal_sigla_from_cnj(process.process_number)
    if sigla:
        process.tribunal = sigla
    return sigla
