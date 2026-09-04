"""Saneamento determinístico dos achados devolvidos pelo agente revisor.

Função pura: sem Flask, sem banco, sem rede, sem LLM. É o que permite testar
os casos do briefing como asserção literal, sem gastar chamada de modelo.

Todo descarte é **devolvido junto**, com regra e motivo. Filtro silencioso vira
caixa-preta: quando o revisor deixasse de apontar algo, ninguém saberia
distinguir "o modelo não viu" de "o saneador comeu".

Regras implementadas até aqui (remessa R02):

    R1 — RPI-12: a correção propõe algo que o documento já atende.
    R2 — RPI-13: o mesmo achado devolvido mais de uma vez.
    R3 — RPI-07: o achado cai dentro de uma citação direta.
    R4 — RPI-10: o intervalo entre DCB e DIB está contado errado.
    R6 — falso positivo em que o próprio achado diz não haver divergência.

A R4 é a única que **corrige** em vez de descartar. A correção não pode ser
silenciosa pelo mesmo motivo do descarte, então fica gravada no próprio achado,
em ``sanitizer_fix``, onde o advogado a lê junto do apontamento.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Any

# Aspas simples, duplas e as tipográficas que o Word costuma produzir.
_TRECHO_CITADO = re.compile(r"'([^']+)'|\"([^\"]+)\"|[“„]([^”“]+)[”“]|«([^»]+)»")

# Proposta curta demais não prova nada: "e", "nº" ou "1" aparecem em qualquer
# petição, e descartar por causa disso engoliria achado legítimo.
_MINIMO_PROPOSTA = 3


def normalizar_espacos(valor: Any) -> str:
    """Colapsa espaços e quebras de linha, preservando caixa e pontuação.

    A caixa é preservada de propósito: "corrigir para 'Sendas Distribuidora S.A.'"
    num documento que traz "SENDAS DISTRIBUIDORA S.A." é achado de verdade, e
    comparar sem diferenciar maiúsculas o descartaria.
    """
    return ' '.join(str(valor or '').split())


def trechos_citados(valor: Any) -> list[str]:
    """Extrai o que está entre aspas — é assim que o modelo marca o valor proposto."""
    achados = []
    for grupos in _TRECHO_CITADO.findall(str(valor or '')):
        for grupo in grupos:
            if grupo:
                achados.append(normalizar_espacos(grupo))
    return achados


def normalizar_campo(valor: Any) -> str:
    """Normalização usada na identidade do achado: espaços colapsados e caixa baixa."""
    return ' '.join(str(valor or '').strip().split()).lower()


# Campos que definem a identidade de um achado. `location_excerpt` fica de fora
# de propósito: no caso real (pontos 15 e 21) os dois apontamentos citavam
# trechos diferentes do mesmo problema, e incluí-lo deixaria a duplicata passar.
_CAMPOS_IDENTIDADE = ('category', 'severity', 'description',
                      'location', 'correction', 'manual_reference')


def fingerprint_achado(achado: dict | None) -> str:
    """Fingerprint estável de um achado.

    É o mesmo valor que identifica achado marcado como "não pertinente" entre
    revisões — `fap_review_service.build_finding_fingerprint` delega aqui. Se os
    dois divergissem, um achado descartado pelo advogado deixaria de ser
    reconhecido na revisão seguinte e voltaria a aparecer.
    """
    if not isinstance(achado, dict):
        return ''

    payload = {campo: normalizar_campo(achado.get(campo)) for campo in _CAMPOS_IDENTIDADE}
    serializado = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serializado.encode('utf-8')).hexdigest()


# ── R6 ──────────────────────────────────────────────────────────────────
# Veio do agente (`_should_ignore_finding`), sem mudança de comportamento: o
# modelo às vezes devolve como "achado" uma conferência que ele mesmo declara
# em ordem ("razão social grafada de forma consistente, sem divergências").

_MENCIONA_EMPRESA = (
    'razao social', 'razão social', 'nome da empresa',
    'nome da autora', 'empresa autora',
)

_DIZ_QUE_ESTA_OK = (
    'sem divergencia', 'sem divergências', 'sem divergencia detectada',
    'sem divergências detectadas', 'nao ha divergencia', 'não há divergência',
    'nenhuma divergencia', 'nenhuma divergência', 'grafada de forma consistente',
    'grafado de forma consistente', 'consistente em todo o documento',
    'sem problema', 'sem inconsistencias', 'sem inconsistências',
)


def _achado_se_declara_sem_problema(achado: dict) -> str | None:
    """Motivo do descarte, se o próprio texto do achado disser que está tudo certo."""
    varredura = ' '.join(
        normalizar_campo(achado.get(campo))
        for campo in ('category', 'description', 'location', 'correction', 'manual_reference')
    )
    if not varredura.strip():
        return None
    if not any(termo in varredura for termo in _MENCIONA_EMPRESA):
        return None
    if not any(termo in varredura for termo in _DIZ_QUE_ESTA_OK):
        return None
    return 'o próprio achado declara que a razão social está consistente'


# ── R3 ──────────────────────────────────────────────────────────────────
# RPI-07: transcrição de sentença, doutrina e texto de lei não são corrigidos
# na peça em elaboração — são reproduzidos como estão. O prompt também orienta
# isso, mas quem garante é o código.

# Só aspas duplas delimitam citação. A aspa simples é o que a R1 usa para
# marcar valor proposto, e em português ela também é apóstrofo ("d'Água"):
# tratá-la como delimitador faria uma palavra apostrofada silenciar todo o
# texto em volta dela.
_ASPAS_RETAS = '"'
_ASPAS_DIRECIONAIS = (('“', '”'), ('«', '»'))

# Trecho curto demais casa em qualquer lugar e não prova localização.
_MINIMO_TRECHO = 8

# Um par de aspas mais longo que isto quase certamente é emparelhamento errado
# — uma aspa solta lá atrás deslocando todos os pares — e não uma citação. Uma
# transcrição de acórdão inteira cabe folgada nesse limite.
_MAX_SPAN_CITACAO = 4000


def _spans_de_citacao(documento: str) -> list[tuple[int, int]]:
    """Intervalos do documento que estão entre aspas duplas.

    Só pares **fechados** contam: aspa de abertura sem fechamento é erro de
    digitação, e deixá-la abrir um intervalo faria todo o resto da peça deixar
    de ser auditado.
    """
    spans: list[tuple[int, int]] = []

    # Direcionais: a própria forma diz quem abre e quem fecha, então o
    # emparelhamento é confiável mesmo com uma aspa solta no meio.
    for abre, fecha in _ASPAS_DIRECIONAIS:
        pilha: list[int] = []
        for i, ch in enumerate(documento):
            if ch == abre:
                pilha.append(i)
            elif ch == fecha and pilha:
                spans.append((pilha.pop(), i))

    # Retas: são idênticas na abertura e no fechamento, então só resta parear
    # na ordem — 1ª com 2ª, 3ª com 4ª. Sobrando uma, ela fica de fora.
    posicoes = [i for i, ch in enumerate(documento) if ch == _ASPAS_RETAS]
    for a, b in zip(posicoes[::2], posicoes[1::2]):
        spans.append((a, b))

    return [(a, b) for a, b in spans if b - a <= _MAX_SPAN_CITACAO]


def _achado_dentro_de_citacao(achado: dict, documento: str,
                              spans: list[tuple[int, int]]) -> str | None:
    """Motivo do descarte, se o trecho do achado só ocorrer dentro de citação.

    Exige que **todas** as ocorrências do trecho estejam citadas. Quando a
    mesma frase aparece dentro e fora das aspas não há como saber a qual o
    achado se refere, e descartar engoliria um apontamento legítimo.
    """
    if not spans:
        return None

    trecho = normalizar_espacos(achado.get('location_excerpt'))
    if len(trecho) < _MINIMO_TRECHO:
        return None

    ocorrencias = []
    inicio = documento.find(trecho)
    while inicio != -1:
        ocorrencias.append(inicio)
        inicio = documento.find(trecho, inicio + 1)

    if not ocorrencias:
        return None

    fim_trecho = len(trecho)
    for posicao in ocorrencias:
        if not any(a < posicao and posicao + fim_trecho - 1 < b
                   for a, b in spans):
            return None

    return ('o trecho está dentro de uma citação direta, que é reproduzida '
            'como consta na origem e não corrigida na peça')


# ── R4 ──────────────────────────────────────────────────────────────────
# RPI-10: o intervalo entre a DCB do benefício anterior e a DIB do seguinte,
# sem contar o dia da cessação. LLM fazendo aritmética de data erra, e o aceite
# do briefing é numérico — por isso quem conta é o código.

LIMITE_RESTABELECIMENTO = 60

_DATA_BR = re.compile(r'\b(\d{2})/(\d{2})/(\d{4})\b')
_QUANTIDADE_DE_DIAS = re.compile(r'\b(\d{1,4})\s*dias?\b', re.IGNORECASE)

# Sem esses termos, duas datas num achado são duas datas quaisquer — vigência e
# protocolo, por exemplo. Recalcular ali corromperia um apontamento correto.
_TESE_DOS_60_DIAS = ('restabelecimento', 'restabelec', 'prorrogação', 'prorrogacao',
                     'dcb', 'dib')

_CAMPOS_COM_TEXTO = ('description', 'correction')


def _para_data(valor: Any) -> date | None:
    """Aceita ``date``/``datetime`` ou ``'dd/mm/aaaa'``. Devolve ``None`` se não der."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = normalizar_espacos(valor)
    casamento = _DATA_BR.search(texto)
    if not casamento:
        return None
    try:
        return date(int(casamento.group(3)), int(casamento.group(2)), int(casamento.group(1)))
    except ValueError:
        return None


def dias_entre_beneficios(dcb: Any, dib: Any) -> int | None:
    """Dias entre a cessação de um benefício e o início do seguinte.

    O dia da cessação não conta: ``(DIB − DCB) − 1``. É a fórmula que satisfaz
    os dois exemplos do aceite — 22/12/2017 → 22/01/2018 dá 30, e 01/01/2020 →
    02/01/2020 dá 0. A frase do documento de feedbacks ("não contar o primeiro
    dia e contar o último") daria 31 no primeiro caso, contradizendo o próprio
    exemplo de quem a escreveu; seguimos os exemplos.

    Devolve ``None`` quando não há como calcular — data ilegível, ou DIB
    anterior à DCB, que é dado inconsistente e não intervalo negativo.
    """
    inicio, fim = _para_data(dcb), _para_data(dib)
    if inicio is None or fim is None or fim < inicio:
        return None
    return max(0, (fim - inicio).days - 1)


def _recalcular_intervalo(achado: dict) -> tuple[str, dict | None, str | None]:
    """Confere o intervalo citado no achado contra o que as datas dizem.

    Returns:
        ``(acao, correcao, motivo)`` — ``acao`` é ``'manter'``, ``'corrigir'``
        ou ``'descartar'``.
    """
    texto = ' '.join(normalizar_campo(achado.get(campo)) for campo in _CAMPOS_COM_TEXTO)
    if not any(termo in texto for termo in _TESE_DOS_60_DIAS):
        return 'manter', None, None

    datas = {_para_data(f'{d}/{m}/{a}') for d, m, a in _DATA_BR.findall(texto)}
    datas.discard(None)
    if len(datas) != 2:
        # Uma data só não fecha intervalo; três ou mais não dizem qual par é o
        # da tese. Nos dois casos, chutar é pior que não mexer.
        return 'manter', None, None

    dcb, dib = sorted(datas)
    real = dias_entre_beneficios(dcb, dib)
    if real is None:
        return 'manter', None, None

    if real > LIMITE_RESTABELECIMENTO:
        return 'descartar', None, (
            f'entre a DCB de {dcb:%d/%m/%Y} e a DIB de {dib:%d/%m/%Y} há {real} dias, '
            f'acima dos {LIMITE_RESTABELECIMENTO} que caracterizam restabelecimento'
        )

    # O limite legal citado no próprio texto não é o intervalo alegado.
    citados = {int(n) for n in _QUANTIDADE_DE_DIAS.findall(texto)}
    citados.discard(LIMITE_RESTABELECIMENTO)
    if len(citados) != 1:
        return 'manter', None, None

    alegado = citados.pop()
    if alegado == real:
        return 'manter', None, None

    return 'corrigir', {
        'regra': 'R4',
        'de': alegado,
        'para': real,
        'motivo': (f'entre a DCB de {dcb:%d/%m/%Y} e a DIB de {dib:%d/%m/%Y} há '
                   f'{real} dias, não {alegado} — o dia da cessação não conta'),
    }, None


def _aplicar_correcao_de_dias(achado: dict, correcao: dict) -> dict:
    """Devolve cópia do achado com o número de dias corrigido no texto."""
    ajustado = dict(achado)
    padrao = re.compile(rf'\b{correcao["de"]}(\s*dias?)\b', re.IGNORECASE)
    for campo in _CAMPOS_COM_TEXTO:
        valor = ajustado.get(campo)
        if isinstance(valor, str):
            ajustado[campo] = padrao.sub(lambda m: f'{correcao["para"]}{m.group(1)}', valor)
    ajustado['sanitizer_fix'] = correcao
    return ajustado


def _correcao_ja_atendida(achado: dict, documento: str) -> str | None:
    """Motivo do descarte, se a correção pedir algo que o documento já tem."""
    for proposta in trechos_citados(achado.get('correction')):
        if len(proposta) < _MINIMO_PROPOSTA:
            continue
        if proposta in documento:
            return f'a correção propõe "{proposta}", que o documento já traz exatamente assim'
    return None


def sanear(achados: list, documento_texto: str = '') -> tuple[list, list[dict]]:
    """Aplica as regras de saneamento a uma lista de achados.

    Args:
        achados: achados crus do modelo, como dicts.
        documento_texto: texto extraído da petição analisada. Vazio desliga as
            regras que dependem do documento — sem ele não há o que comparar, e
            chutar descartaria achado legítimo.

    Returns:
        (mantidos, descartes), onde cada descarte é
        ``{'regra': 'R1'|'R2'|'R3'|'R6', 'motivo': str, 'achado': dict}``.
    """
    documento = normalizar_espacos(documento_texto)
    spans_citados = _spans_de_citacao(documento) if documento else []

    mantidos: list = []
    descartes: list[dict] = []
    vistos: dict[str, int] = {}

    for achado in achados if isinstance(achados, list) else []:
        if not isinstance(achado, dict):
            mantidos.append(achado)
            continue

        motivo = _achado_se_declara_sem_problema(achado)
        if motivo:
            descartes.append({'regra': 'R6', 'motivo': motivo, 'achado': achado})
            continue

        motivo = _achado_dentro_de_citacao(achado, documento, spans_citados)
        if motivo:
            descartes.append({'regra': 'R3', 'motivo': motivo, 'achado': achado})
            continue

        motivo = _correcao_ja_atendida(achado, documento) if documento else None
        if motivo:
            descartes.append({'regra': 'R1', 'motivo': motivo, 'achado': achado})
            continue

        acao, correcao, motivo = _recalcular_intervalo(achado)
        if acao == 'descartar':
            descartes.append({'regra': 'R4', 'motivo': motivo, 'achado': achado})
            continue
        if acao == 'corrigir':
            achado = _aplicar_correcao_de_dias(achado, correcao)

        marca = fingerprint_achado(achado)
        if marca and marca in vistos:
            descartes.append({
                'regra': 'R2',
                'motivo': f'repetição do ponto {vistos[marca]}, com mesma descrição, '
                          f'localização e sugestão',
                'achado': achado,
            })
            continue

        mantidos.append(achado)
        if marca:
            # Número do ponto como o advogado vê na tela: 1..N sobre os mantidos.
            vistos[marca] = len(mantidos)

    return mantidos, descartes
