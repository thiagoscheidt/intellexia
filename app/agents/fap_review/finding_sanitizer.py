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
    R7 — FB-02: petição x anexo/planilha divergindo só na formatação.

A R4 é a única que **corrige** em vez de descartar. A correção não pode ser
silenciosa pelo mesmo motivo do descarte, então fica gravada no próprio achado,
em ``sanitizer_fix``, onde o advogado a lê junto do apontamento. Desde a RPI-36
ela também grava a conta do par (``contagem_dias``) e rebaixa para conferência
— fora da pontuação — o par de 58 dias ou mais e a diferença de 1 dia.
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


# ── RPI-38: achado que conclui estar certo não sustenta risco ───────────
# Não descarta o achado (a conclusão pode ajudar quem revisa); só impede que
# ele apareça como base de um "risco jurídico" no resumo executivo. Caso real:
# revisão 175, o único achado sobre índices concluía que o par estava correto
# e o resumo listava "possível erro de índices".

_CONCLUSAO_CORRETO = re.compile(
    r'(?:\b(?:est[aá]|est[aã]o|permanece|permanecem|mant[eé]m-se)\s+corret[oa]s?\b'
    r'|\bn[aã]o\s+h[aá]\s+(?:erro|diverg[eê]ncia|inconsist[eê]ncia)'
    r'|\bsem\s+(?:erro|diverg[eê]ncia|inconsist[eê]ncia)s?\b'
    r'|\bnenhuma\s+corre[cç][aã]o\b|\bn[aã]o\s+(?:requer|exige|precisa\s+de)\s+corre[cç][aã]o'
    r'|\bnada\s+a\s+corrigir\b)')
# "Verificar se o valor está correto" é pergunta, não conclusão.
_DUVIDA = re.compile(r'\b(?:se|verificar|verifique|confirmar|confirme|conferir|confira|checar|cheque|avaliar|avalie|revisar|revise)\b')


def achado_conclui_correto(achado: dict) -> bool:
    """O próprio achado conclui que o ponto está certo ("o cálculo está correto")."""
    if not isinstance(achado, dict):
        return False
    texto = ' '.join(normalizar_campo(achado.get(c)) for c in ('description', 'correction'))
    for frase in re.split(r'[.;!?]', texto):
        m = _CONCLUSAO_CORRETO.search(frase)
        if m and not _DUVIDA.search(frase[:m.start()]):
            return True
    return False

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
# RPI-10/RPI-36: o intervalo entre a DCB do benefício anterior e a DIB do
# seguinte, contando só os dias entre as duas datas (DIB − DCB − 1). LLM fazendo
# aritmética de data erra, e o aceite é numérico — por isso quem conta é o código.
# A conta vai no achado (``contagem_dias``) para o advogado refazê-la.

LIMITE_RESTABELECIMENTO = 60

# RPI-36: de 58 dias para cima (inclusive acima de 60) o par é só conferido —
# perto do limite a conta decide a tese, e quem decide é a equipe, não o Revisor.
INICIO_CONFERENCIA = 58

# RPI-36: 1 dia de diferença em relação à conta pode ser proposital.
TOLERANCIA_DIAS = 1

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

    Contam-se só os dias entre as duas datas, sem a DCB e sem a DIB:
    ``(DIB − DCB) − 1``. Regra do escritório confirmada com a área de benefícios
    em 05/11/2026 (RPI-36), a mesma dos exemplos da RPI-10 — 22/12/2017 →
    22/01/2018 dá 30, 01/01/2020 → 02/01/2020 dá 0 e 31/01/2022 → 10/03/2022
    dá 37 (caso GIASSI). É restabelecimento com até 60 dias, 60 incluído.

    Devolve ``None`` quando não há como calcular — data ilegível, ou DIB
    anterior à DCB, que é dado inconsistente e não intervalo negativo.
    """
    inicio, fim = _para_data(dcb), _para_data(dib)
    if inicio is None or fim is None or fim < inicio:
        return None
    return max(0, (fim - inicio).days - 1)


def conta_dos_dias(dcb: date, dib: date, dias: int) -> str:
    """A conta como o advogado a refaz à mão: ``10/03/2022 − 31/01/2022 − 1 = 37 dias``."""
    return f'{dib:%d/%m/%Y} − {dcb:%d/%m/%Y} − 1 = {dias} {"dia" if dias == 1 else "dias"}'


def _dias_no_documento(documento: str, dias: int) -> bool:
    """O documento traz "N dias" (ou "N (extenso) dias")?"""
    padrao = rf'(?<![\d.,/]){dias}\s*(?:\([^)]{{0,40}}\)\s*)?dias?\b'
    return bool(re.search(padrao, documento, re.IGNORECASE))


def _com_conta(achado: dict, contagem: dict) -> dict:
    ajustado = dict(achado)
    ajustado['contagem_dias'] = contagem
    return ajustado


def _como_conferencia(achado: dict, contagem: dict, aviso: str) -> dict:
    """RPI-36: o par fica para conferência — aparece com a conta, mas não é erro.

    A gravidade cai para FORMAL (nunca conta como crítico no resumo) e a marca
    ``contagem_dias.conferencia`` tira o achado da pontuação do advogado.
    """
    ajustado = _com_conta(achado, {**contagem, 'conferencia': True, 'aviso': aviso,
                                   'motivo': f"{contagem['conta']}. {aviso}"})
    ajustado['severity'] = 'FORMAL'
    return ajustado


def _aplicar_r4(achado: dict, documento: str) -> tuple[dict | None, str | None]:
    """Recalcula o intervalo do par DCB/DIB citado no achado.

    Returns:
        ``(achado, None)`` — o achado como deve seguir (com a conta em
        ``contagem_dias`` quando há par calculável, e o número corrigido quando
        o modelo errou a conta), ou ``(None, motivo)`` quando a própria petição
        segue a regra e o achado aponta erro que não existe.
    """
    texto = ' '.join(normalizar_campo(achado.get(campo)) for campo in _CAMPOS_COM_TEXTO)
    if not any(termo in texto for termo in _TESE_DOS_60_DIAS):
        return achado, None

    datas = {_para_data(f'{d}/{m}/{a}') for d, m, a in _DATA_BR.findall(texto)}
    datas.discard(None)
    if len(datas) != 2:
        # Uma data só não fecha intervalo; três ou mais não dizem qual par é o
        # da tese. Nos dois casos, chutar é pior que não mexer.
        return achado, None

    dcb, dib = sorted(datas)
    real = dias_entre_beneficios(dcb, dib)
    if real is None:
        return achado, None

    conta = conta_dos_dias(dcb, dib, real)
    contagem = {'regra': 'R4', 'dcb': f'{dcb:%d/%m/%Y}', 'dib': f'{dib:%d/%m/%Y}',
                'dias': real, 'conta': conta}

    if real >= INICIO_CONFERENCIA:
        aviso = (f'Com {INICIO_CONFERENCIA} dias ou mais o par fica para '
                 f'conferência, não é erro')
        if real > LIMITE_RESTABELECIMENTO:
            aviso += (f'; acima de {LIMITE_RESTABELECIMENTO} dias não é restabelecimento '
                       f'e o benefício normalmente não entra na petição — se entrou, a '
                       f'equipe avalia caso a caso')
        return _como_conferencia(achado, contagem, aviso), None

    aviso_um_dia = (f'A diferença de {TOLERANCIA_DIAS} dia em relação a esta '
                     f'conta pode ser proposital: fica para conferência, não é erro')

    # O limite legal citado no próprio texto não é o intervalo alegado.
    citados = {int(n) for n in _QUANTIDADE_DE_DIAS.findall(texto)}
    citados.discard(LIMITE_RESTABELECIMENTO)

    if len(citados) == 1:
        alegado = next(iter(citados))
        if alegado == real:
            return _com_conta(achado, contagem), None
        if (documento and _dias_no_documento(documento, alegado)
                and not _dias_no_documento(documento, real)):
            # O número citado é o da petição, não a conta do modelo.
            if abs(alegado - real) <= TOLERANCIA_DIAS:
                return _como_conferencia(achado, contagem, aviso_um_dia), None
            return _com_conta(achado, contagem), None
        # RPI-10: o modelo errou a conta — o apontamento vale, o número não.
        correcao = {
            'regra': 'R4',
            'de': alegado,
            'para': real,
            'motivo': (f'entre a DCB de {dcb:%d/%m/%Y} e a DIB de {dib:%d/%m/%Y} há '
                       f'{real} dias, não {alegado} — contam-se só os dias entre as '
                       f'duas datas'),
        }
        return _com_conta(_aplicar_correcao_de_dias(achado, correcao), contagem), None

    if len(citados) == 2 and real in citados:
        outro = next(iter(citados - {real}))
        if (documento and _dias_no_documento(documento, real)
                and not _dias_no_documento(documento, outro)):
            # Caso GIASSI (RPI-36): a petição traz a conta certa e o modelo
            # aponta outra.
            return None, (f'a petição traz {real} dias, que é a conta pela regra '
                          f'({conta}); o achado apontava {outro}')
        if abs(outro - real) <= TOLERANCIA_DIAS:
            return _como_conferencia(achado, contagem, aviso_um_dia), None

    return _com_conta(achado, contagem), None


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


# ── R7 ──────────────────────────────────────────────────────────────────
# FB-02: no cruzamento com os documentos auxiliares, o modelo aponta como
# divergente "S.A" contra "S.A." e um NIT escrito com pontos contra o mesmo NIT
# só em dígitos. O anexo vem do órgão com a grafia dele; a petição não está
# errada por isso. Vale SÓ para petição x anexo/planilha: dentro da própria
# petição o manual exige grafia idêntica, e esse achado continua.

# Sinal de que o achado compara com fonte externa: nome de arquivo, planilha
# ou documento auxiliar. "Anexo" sozinho não conta — a tabela de documentos
# anexos é parte da petição.
_ORIGEM_EXTERNA = re.compile(
    r'\.(?:pdf|docx?|xlsx?|csv)\b|\bplanilha\b|\bdocumentos?\s+auxiliar(?:es)?\b',
    re.IGNORECASE)

# Identificador (NB 10 dígitos, NIT/CPF 11, CEI 12, CNPJ 14) compara só dígitos.
# Número que não é identificador — valor, data — não: "1.000,00" e "10.000,0"
# têm os mesmos dígitos e são valores diferentes.
_SO_IDENTIFICADOR = re.compile(r'^[\d.\-/\s]+$')
_MINIMO_DIGITOS_IDENTIFICADOR = 10

# Só pontuação e espaço. Caixa e acento continuam valendo (ver normalizar_espacos).
_PONTUACAO = re.compile(r'[\s.,;:/\-]+')


def _forma_comparavel(valor: str) -> tuple[str, str]:
    if any(c.isdigit() for c in valor):
        if _SO_IDENTIFICADOR.match(valor):
            digitos = re.sub(r'\D', '', valor)
            if len(digitos) >= _MINIMO_DIGITOS_IDENTIFICADOR:
                return 'identificador', digitos
        return 'literal', valor
    return 'texto', _PONTUACAO.sub('', valor)


def _divergencia_so_de_formatacao(achado: dict) -> str | None:
    """Motivo do descarte, se os valores contrapostos só diferem na formatação."""
    texto = ' '.join(str(achado.get(campo) or '') for campo in ('description', 'correction'))
    if not _ORIGEM_EXTERNA.search(texto):
        return None
    valores = {v for v in trechos_citados(texto) if len(v) >= _MINIMO_PROPOSTA}
    # Com um valor só não há contraposição para julgar.
    if len(valores) < 2:
        return None
    if len({_forma_comparavel(v) for v in valores}) != 1:
        return None
    return ('a divergência com o documento de origem é só de formatação: '
            + ' x '.join(f'"{v}"' for v in sorted(valores)))


def sanear(achados: list, documento_texto: str = '') -> tuple[list, list[dict]]:
    """Aplica as regras de saneamento a uma lista de achados.

    Args:
        achados: achados crus do modelo, como dicts.
        documento_texto: texto extraído da petição analisada. Vazio desliga as
            regras que dependem do documento — sem ele não há o que comparar, e
            chutar descartaria achado legítimo.

    Returns:
        (mantidos, descartes), onde cada descarte é
        ``{'regra': 'R1'|'R2'|'R3'|'R4'|'R6'|'R7', 'motivo': str, 'achado': dict}``.
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

        motivo = _divergencia_so_de_formatacao(achado)
        if motivo:
            descartes.append({'regra': 'R7', 'motivo': motivo, 'achado': achado})
            continue

        ajustado, motivo = _aplicar_r4(achado, documento)
        if ajustado is None:
            descartes.append({'regra': 'R4', 'motivo': motivo, 'achado': achado})
            continue
        achado = ajustado

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
