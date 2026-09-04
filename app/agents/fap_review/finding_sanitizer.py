"""Saneamento determinístico dos achados devolvidos pelo agente revisor.

Função pura: sem Flask, sem banco, sem rede, sem LLM. É o que permite testar
os casos do briefing como asserção literal, sem gastar chamada de modelo.

Todo descarte é **devolvido junto**, com regra e motivo. Filtro silencioso vira
caixa-preta: quando o revisor deixasse de apontar algo, ninguém saberia
distinguir "o modelo não viu" de "o saneador comeu".

Regras implementadas até aqui (remessa R02):

    R1 — RPI-12: a correção propõe algo que o documento já atende.
    R2 — RPI-13: o mesmo achado devolvido mais de uma vez.
    R6 — falso positivo em que o próprio achado diz não haver divergência.
"""

from __future__ import annotations

import hashlib
import json
import re
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
        ``{'regra': 'R1'|'R2'|'R6', 'motivo': str, 'achado': dict}``.
    """
    documento = normalizar_espacos(documento_texto)

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

        motivo = _correcao_ja_atendida(achado, documento) if documento else None
        if motivo:
            descartes.append({'regra': 'R1', 'motivo': motivo, 'achado': achado})
            continue

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
