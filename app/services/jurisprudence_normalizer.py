"""Normalização dos campos da Base de Jurisprudência — funções puras.

Sem banco, sem Flask, sem rede: é a peça que decide que "SENTENÇA" e
"SENTENCA" são a mesma instância e que "TRF4 - 2a Vara Federal de Blumenau" é
TRF4 + 2ª Vara Federal de Blumenau + SC. Usada igual pela importação da
planilha e pela leitura de PDF, para as duas portas gravarem o mesmo formato.

Medido no Banco Mestre FAP (515 decisões): 155 textos de tribunal para 8
siglas, 251 grafias de tese para 219 chaves, SENTENÇA/SENTENCA e
FAVORÁVEL/FAVORAVEL misturados — pedir padronização no prompt não bastou.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Optional

TIPO_SENTENCA = 'sentenca'
TIPO_ACORDAO = 'acordao'
TIPO_EMBARGOS = 'embargos'
TIPO_OUTRA = 'outra'

TIPO_LABELS = {
    TIPO_SENTENCA: 'Sentença',
    TIPO_ACORDAO: 'Acórdão',
    TIPO_EMBARGOS: 'Embargos de declaração',
    TIPO_OUTRA: 'Outra',
}
TIPO_LABELS_CURTOS = {
    TIPO_SENTENCA: 'Sentença',
    TIPO_ACORDAO: 'Acórdão',
    TIPO_EMBARGOS: 'Embargos',
    TIPO_OUTRA: 'Outra',
}

RESULTADO_FAVORAVEL = 'favoravel'
RESULTADO_PARCIAL = 'parcial'
RESULTADO_DESFAVORAVEL = 'desfavoravel'

RESULTADO_LABELS = {
    RESULTADO_FAVORAVEL: 'Favorável',
    RESULTADO_PARCIAL: 'Parcialmente favorável',
    RESULTADO_DESFAVORAVEL: 'Desfavorável',
}
RESULTADO_LABELS_CURTOS = {
    RESULTADO_FAVORAVEL: 'Favorável',
    RESULTADO_PARCIAL: 'Parcialmente',
    RESULTADO_DESFAVORAVEL: 'Desfavorável',
}
# Força do resultado para a empresa — decide a "virada" e a ordem das sugestões.
RESULTADO_PESO = {RESULTADO_DESFAVORAVEL: 0, RESULTADO_PARCIAL: 1, RESULTADO_FAVORAVEL: 2}
# Ordem da trilha do processo.
TIPO_ORDEM = {TIPO_SENTENCA: 0, TIPO_EMBARGOS: 1, TIPO_ACORDAO: 2, TIPO_OUTRA: 3}

# Sinônimos da busca, herdados da ferramenta que o escritório já usava.
# Buscar um termo de um grupo acha qualquer termo do grupo.
SINONIMOS = [
    ['TRAJETO', 'PERCURSO', 'IN ITINERE', 'DESLOCAMENTO', 'CASA-TRABALHO', 'ACIDENTE DE TRAJETO'],
    ['FAP', 'FATOR ACIDENTARIO', 'FATOR ACIDENTARIO DE PREVENCAO'],
    ['NTEP', 'NEXO TECNICO', 'NEXO TECNICO EPIDEMIOLOGICO', 'NEXO CAUSAL'],
    ['FREQUENCIA', 'INDICE DE FREQUENCIA', 'ERRO NA FREQUENCIA'],
    ['GRAVIDADE', 'INDICE DE GRAVIDADE', 'ERRO NA GRAVIDADE'],
    ['CUSTO', 'INDICE DE CUSTO', 'ERRO NO CUSTO'],
    ['RETROATIVIDADE', 'RETROATIVO', 'IRRETROATIVIDADE'],
    ['CNAE', 'CLASSIFICACAO NACIONAL', 'ERRO NO CNAE', 'SUBCLASSE CNAE'],
    ['ROTATIVIDADE', 'TAXA DE ROTATIVIDADE', 'TURNOVER'],
    ['CONTRADITORIO', 'AMPLA DEFESA', 'DEVIDO PROCESSO', 'AUSENCIA DE CONTRADITORIO'],
    ['MOTIVACAO', 'FUNDAMENTACAO', 'FALTA DE MOTIVACAO'],
    ['INCONSTITUCIONALIDADE', 'INCONSTITUCIONAL', 'VICIO DE LEGALIDADE'],
    ['BIS IN IDEM', 'DUPLA COBRANCA', 'DUPLICIDADE'],
    ['AUXILIO-DOENCA', 'AUXILIO DOENCA', 'BENEFICIO PREVIDENCIARIO', 'B91', 'B31'],
    ['RESTABELECIMENTO', 'RESTABELECIMENTO DE BENEFICIO', 'RESTABELECIDO', 'REATIVACAO DE BENEFICIO',
     'RETORNO DE BENEFICIO', 'PRORROGACAO', 'PRORROGACAO DE BENEFICIO', 'PRORROGADO',
     'PEDIDO DE PRORROGACAO'],
]


# ── Texto ──────────────────────────────────────────────────────────────

def sem_acento(texto) -> str:
    if texto is None:
        return ''
    return ''.join(
        c for c in unicodedata.normalize('NFKD', str(texto))
        if not unicodedata.combining(c)
    )


def chave(texto) -> str:
    """Chave de comparação: sem acento, maiúsculas, espaços únicos, sem
    pontuação nas pontas. É o que decide se duas grafias são a mesma tese."""
    valor = sem_acento(texto).upper()
    valor = re.sub(r'\s+', ' ', valor).strip()
    return valor.strip(' .;,:-–—')


def texto_de_busca(texto) -> str:
    """Forma em que o texto é guardado e comparado na busca."""
    return re.sub(r'\s+', ' ', sem_acento(texto).lower()).strip()


_SINONIMOS_BUSCA = [[texto_de_busca(t) for t in grupo] for grupo in SINONIMOS]


def expandir_termo(termo: str) -> list[str]:
    """Termo da busca → ele e seus equivalentes, já em forma de busca."""
    alvo = texto_de_busca(termo)
    if not alvo:
        return []
    for grupo in _SINONIMOS_BUSCA:
        if alvo in grupo:
            return list(dict.fromkeys([alvo, *grupo]))
    return [alvo]


def termos_da_consulta(consulta: str) -> list[list[str]]:
    """Consulta → lista de termos, cada um com seus equivalentes.

    Aspas juntam palavras num termo só ("acidente de trajeto"). Um termo que é
    frase inteira de um grupo de sinônimos também é reconhecido sem aspas:
    "in itinere" continua sendo um termo, não "in" + "itinere".
    """
    consulta = consulta or ''
    termos: list[str] = [m for m in re.findall(r'"([^"]+)"', consulta) if m.strip()]
    resto = texto_de_busca(re.sub(r'"[^"]*"', ' ', consulta))

    frases = sorted(
        {t for grupo in _SINONIMOS_BUSCA for t in grupo if ' ' in t},
        key=len, reverse=True,
    )
    for frase in frases:
        padrao = rf'(?<!\w){re.escape(frase)}(?!\w)'
        if re.search(padrao, resto):
            termos.append(frase)
            resto = re.sub(padrao, ' ', resto)

    termos.extend(p for p in resto.split() if len(p) >= 2)
    return [expandir_termo(t) for t in termos if expandir_termo(t)]


# ── Processo, datas, listas ────────────────────────────────────────────

def digitos(texto) -> str:
    return re.sub(r'\D', '', str(texto or ''))


def parece_numero_de_processo(consulta: str) -> bool:
    """Consulta que é só um número de processo (com ou sem pontuação)."""
    consulta = (consulta or '').strip()
    return bool(consulta) and len(digitos(consulta)) >= 15 and not re.search(r'[A-Za-z]{3,}', consulta)


def formatar_cnj(numero_digitos: str) -> str:
    d = digitos(numero_digitos)
    if len(d) != 20:
        return numero_digitos or ''
    return f'{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}'


def para_data(valor) -> Optional[date]:
    if valor is None or valor == '':
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()[:10]
    for formato in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y'):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def para_lista(valor) -> list[str]:
    """Lista da IA ou string "a; b; c" da planilha → lista limpa, sem repetição."""
    if valor is None:
        return []
    if isinstance(valor, (list, tuple)):
        itens = [str(v) for v in valor if v is not None]
    else:
        itens = str(valor).split(';')
    vistos: dict[str, str] = {}
    for item in itens:
        limpo = re.sub(r'\s+', ' ', item).strip()
        if limpo and chave(limpo) not in vistos:
            vistos[chave(limpo)] = limpo
    return list(vistos.values())


def texto_limpo(valor, limite: Optional[int] = None) -> Optional[str]:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto or texto.lower() in ('none', 'null', 'nan'):
        return None
    return texto[:limite] if limite else texto


# ── Instância e resultado ──────────────────────────────────────────────

def tipo_documento(valor) -> Optional[str]:
    k = chave(valor)
    if not k:
        return None
    if k.startswith('EMBARGOS') or k.startswith('ED ') or k == 'ED':
        return TIPO_EMBARGOS
    if k.startswith('SENTENCA'):
        return TIPO_SENTENCA
    if k.startswith('ACORDAO'):
        return TIPO_ACORDAO
    return TIPO_OUTRA


def resultado(valor) -> Optional[str]:
    k = chave(valor)
    if not k:
        return None
    if k.startswith('PARCIAL'):
        return RESULTADO_PARCIAL
    if k.startswith('DESFAVORAVEL') or k.startswith('IMPROCEDENTE'):
        return RESULTADO_DESFAVORAVEL
    if k.startswith('FAVORAVEL') or k.startswith('PROCEDENTE'):
        return RESULTADO_FAVORAVEL
    return None


# ── Tribunal, órgão, UF ────────────────────────────────────────────────

_SIGLA = re.compile(r'^(TRF\s?\d|STJ|STF|TST|TNU|TRT\s?\d{1,2}|TJ[A-Z]{2}|CARF|CRPS)\b', re.IGNORECASE)

# Grafias sem acento que a IA deixou passar, para o mesmo órgão não aparecer
# duas vezes ("Criciuma" e "Criciúma").
_GRAFIAS = {
    r'\bCivel\b': 'Cível',
    r'\bSao Paulo\b': 'São Paulo',
    r'\bFlorianopolis\b': 'Florianópolis',
    r'\bItajai\b': 'Itajaí',
    r'\bCriciuma\b': 'Criciúma',
    r'\bChapeco\b': 'Chapecó',
    r'\bJundiai\b': 'Jundiaí',
    r'\bTubarao\b': 'Tubarão',
    r'\bJaragua do Sul\b': 'Jaraguá do Sul',
    r'\bCampo Mourao\b': 'Campo Mourão',
    r'\bSanto Andre\b': 'Santo André',
    r'\bBento Goncalves\b': 'Bento Gonçalves',
    r'\bUberlandia\b': 'Uberlândia',
    r'\bRegiao\b': 'Região',
}


def ajustar_orgao(texto) -> Optional[str]:
    """ "2a Turma" → "2ª Turma"; grafias sem acento dos nomes de cidade."""
    texto = texto_limpo(texto, 255)
    if not texto:
        return None
    texto = re.sub(r'\b(\d{1,2})\s?[aª](?=\s)', r'\1ª', texto)
    texto = re.sub(r'\b(\d{1,2})\s?[oº](?=\s)', r'\1º', texto)
    for padrao, certo in _GRAFIAS.items():
        texto = re.sub(padrao, certo, texto)
    return re.sub(r'\s+', ' ', texto).strip()


def separar_tribunal(tribunal, orgao_julgador=None) -> tuple[Optional[str], Optional[str]]:
    """ "TRF4 - 2a Vara Federal de Blumenau" → ("TRF4", "2ª Vara Federal de Blumenau").

    Para acórdão a planilha traz só a sigla e o órgão vem em orgao_julgador.
    Quando os dois existem, o órgão explícito vence.
    """
    bruto = texto_limpo(tribunal) or ''
    sigla = None
    unidade = None
    m = _SIGLA.match(bruto)
    if m:
        sigla = re.sub(r'\s', '', m.group(1)).upper()
        resto = bruto[m.end():].strip(' -–—')
        unidade = resto or None
    elif bruto:
        partes = re.split(r'\s[-–—]\s', bruto, maxsplit=1)
        sigla = partes[0].strip().upper()[:20]
        unidade = partes[1].strip() if len(partes) > 1 else None
    orgao = ajustar_orgao(orgao_julgador) or ajustar_orgao(unidade)
    return sigla, orgao


# Código de origem do número CNJ (dígitos 17-18) → UF, só onde é inequívoco.
# J=4 (Justiça Federal); TR=04 (TRF4) e 03 (TRF3) cobrem ~85% do acervo.
_UF_POR_ORIGEM = {
    ('404', '70'): 'PR', ('404', '71'): 'RS', ('404', '72'): 'SC',
    ('403', '60'): 'MS', ('403', '61'): 'SP', ('403', '63'): 'SP',
}
_UF_POR_SECAO = re.compile(r'\bSJ([A-Z]{2})\b')
_UFS = {
    'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG', 'PA',
    'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO',
}


def uf_do_processo(processo, orgao=None, uf_informada=None) -> Optional[str]:
    informada = (uf_informada or '').strip().upper()
    if informada in _UFS:
        return informada
    bruto = str(processo or '')
    m = re.search(r'/([A-Z]{2})\b', bruto)
    if m and m.group(1) in _UFS:
        return m.group(1)
    d = digitos(bruto)
    if len(d) == 20:
        uf = _UF_POR_ORIGEM.get((d[13:16], d[16:18]))
        if uf:
            return uf
    m = _UF_POR_SECAO.search(str(orgao or '').upper())
    if m and m.group(1) in _UFS:
        return m.group(1)
    m = re.search(r'\b([A-Z]{2})$', str(orgao or '').strip())
    if m and m.group(1) in _UFS:
        return m.group(1)
    return None


def regiao_do_processo(processo) -> Optional[str]:
    """TRF de origem pelo número CNJ (J=4, TR=01..06)."""
    d = digitos(processo)
    if len(d) == 20 and d[13] == '4' and d[14:16] in ('01', '02', '03', '04', '05', '06'):
        return f'TRF{int(d[14:16])}'
    return None


# ── Vigência ───────────────────────────────────────────────────────────

def vigencia(valor) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """ "2017 a 2021" → ("2017 a 2021", 2017, 2021); 2018.0 → ("2018", 2018, 2018).

    Texto sem ano nenhum (a planilha tem "teste") não vira vigência.
    """
    if valor is None or valor == '':
        return None, None, None
    if isinstance(valor, (int, float)):
        ano = int(valor)
        return (str(ano), ano, ano) if 1990 <= ano <= 2100 else (None, None, None)
    anos = [int(a) for a in re.findall(r'\b(19[9]\d|20\d{2})\b', str(valor))]
    if not anos:
        return None, None, None
    inicio, fim = min(anos), max(anos)
    texto = str(inicio) if inicio == fim else f'{inicio} a {fim}'
    return texto, inicio, fim


# ── Citação ────────────────────────────────────────────────────────────

_CLASSES_ABREVIADAS = [
    ('APELACAO/REMESSA NECESSARIA', 'ApRemNec'),
    ('APELACAO', 'AC'),
    ('REMESSA NECESSARIA', 'RemNec'),
    ('AGRAVO INTERNO', 'AgInt'),
    ('AGRAVO DE INSTRUMENTO', 'AI'),
    ('AGRAVO EM RECURSO ESPECIAL', 'AREsp'),
    ('RECURSO ESPECIAL', 'REsp'),
    ('RECURSO EXTRAORDINARIO COM AGRAVO', 'ARE'),
    ('RECURSO EXTRAORDINARIO', 'RE'),
    ('EMBARGOS DE DECLARACAO', 'ED'),
    ('MANDADO DE SEGURANCA', 'MS'),
    ('RECURSO INOMINADO', 'RI'),
]


def abreviar_classe(classe) -> Optional[str]:
    k = chave(classe)
    for prefixo, sigla in _CLASSES_ABREVIADAS:
        if k.startswith(prefixo):
            return sigla
    return None


def _nome_proprio(texto) -> str:
    """ "DESEMBARGADORA FEDERAL MARIA DE FÁTIMA" → "Desembargadora Federal Maria de Fátima"."""
    texto = (texto or '').strip()
    if not texto or not texto.isupper():
        return texto
    minusculas = {'de', 'da', 'do', 'das', 'dos', 'e'}
    palavras = texto.lower().split()
    return ' '.join(p if (i and p in minusculas) else p.capitalize() for i, p in enumerate(palavras))


def eh_primeiro_grau(tipo, orgao) -> bool:
    return tipo == TIPO_SENTENCA or bool(re.search(r'\bvara\b|juizado|\bjf\b', sem_acento(orgao or '').lower()))


def citacao(d) -> str:
    """Referência pronta para colar na peça. `d` é a decisão (objeto ou dict)."""
    def campo(nome):
        return d.get(nome) if isinstance(d, dict) else getattr(d, nome, None)

    tribunal = campo('tribunal') or ''
    orgao = campo('orgao_julgador') or ''
    processo = campo('processo') or formatar_cnj(campo('processo_digits') or '')
    processo = re.sub(r'/[A-Z]{2}$', '', processo.strip())
    tipo = campo('tipo_documento')
    data_j = campo('data_julgamento')
    data_txt = data_j.strftime('%d/%m/%Y') if isinstance(data_j, date) else ''
    relator = _nome_proprio(campo('relator') or '')

    if eh_primeiro_grau(tipo, orgao):
        local = ' – '.join(p for p in (tribunal, orgao) if p)
        evento = 'embargos de declaração julgados' if tipo == TIPO_EMBARGOS else 'sentença proferida'
        partes = [local, f'Processo nº {processo}' if processo else '',
                  f'{evento} em {data_txt}' if data_txt else '']
    else:
        sigla = abreviar_classe(campo('classe_processual'))
        if tipo == TIPO_EMBARGOS and sigla and sigla != 'ED':
            sigla = f'ED na {sigla}'
        numero = f'{sigla} {processo}' if sigla else processo
        partes = [tribunal, numero, orgao,
                  f'Rel. {relator}' if relator else '',
                  f'julgado em {data_txt}' if data_txt else '']
    return '(' + ', '.join(p for p in partes if p) + ')'
