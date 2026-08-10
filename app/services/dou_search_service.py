"""
Busca no acervo do Diário Oficial (Meilisearch).

Índice dedicado, alimentado pela ingestão e reconstruível a partir do banco. O
MySQL é a fonte da verdade; este índice é descartável. Daí as duas regras que
valem em todo o arquivo: indexar nunca derruba a captura, buscar nunca derruba
a tela.

O ponto central é o tratamento de identificadores. O Meilisearch tokeniza
separando em '.', '/' e '-', então `19.630.496/0001-05` vira os tokens 19, 630,
496, 0001, 05 e quem digitasse `19630496000105` não acharia nada — em 31% do
acervo, que é a fatia que contém CNPJ. Por isso os identificadores são
extraídos, normalizados para só dígitos e guardados em campos próprios, e a
consulta é roteada para esses campos quando o termo é um número.
"""

from __future__ import annotations

import re

# Formatos conferidos contra o acervo real:
#   CNPJ     19.630.496/0001-05     -> 14 dígitos
#   processo 15414.630210/2026-80   -> 17 dígitos
_RE_CNPJ = re.compile(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}')
_RE_CNPJ_DIGITOS = re.compile(r'(?<!\d)\d{14}(?!\d)')
_RE_PROCESSO = re.compile(r'\d{5}\.\d{6}/\d{4}-\d{2}')

TAM_CNPJ = 14
TAM_PROCESSO = 17

# Pontuação aceita num termo que ainda assim é "só um número"
_PONTUACAO_DE_NUMERO = re.compile(r'[\s.\-/]')


def so_digitos(valor: str | None) -> str:
    """'19.630.496/0001-05' → '19630496000105'."""
    return re.sub(r'\D', '', valor or '')


def _unicos(valores) -> list[str]:
    """Preserva a ordem de aparição e remove repetidos."""
    vistos, saida = set(), []
    for v in valores:
        if v not in vistos:
            vistos.add(v)
            saida.append(v)
    return saida


def extrair_cnpjs(texto: str | None) -> list[str]:
    """Todos os CNPJs do texto, normalizados. Cobre as duas grafias."""
    if not texto:
        return []
    achados = [so_digitos(m) for m in _RE_CNPJ.findall(texto)]
    achados += _RE_CNPJ_DIGITOS.findall(texto)
    return _unicos(achados)


def extrair_processos(texto: str | None) -> list[str]:
    """Todos os números de processo administrativo, normalizados."""
    if not texto:
        return []
    return _unicos(so_digitos(m) for m in _RE_PROCESSO.findall(texto))


def orgao_raiz(hierarquia: str | None) -> str | None:
    """Primeiro nível de 'Ministério X/Autarquia Y/Diretoria Z'.

    A hierarquia completa tem centenas de valores distintos e não vira faceta
    usável; a raiz tem dezenas.
    """
    if not hierarquia:
        return None
    return (hierarquia.split('/')[0] or '').strip() or None


def classificar_consulta(termo: str) -> tuple[str, str]:
    """Decide por qual campo a consulta vai. Devolve (tipo, termo_normalizado).

    tipo é 'cnpj', 'processo' ou 'texto'.

    O identificador só é reconhecido quando o termo **inteiro** é o número —
    aceitando pontuação e espaço. Sem esse guarda, "portaria 19630496000105 de
    agosto" viraria busca de CNPJ e perderia o resto da frase.
    """
    termo = (termo or '').strip()
    if not termo:
        return ('texto', '')

    digitos = so_digitos(termo)
    if digitos and not _PONTUACAO_DE_NUMERO.sub('', termo).strip(digitos):
        if len(digitos) == TAM_CNPJ:
            return ('cnpj', digitos)
        if len(digitos) == TAM_PROCESSO:
            return ('processo', digitos)

    return ('texto', termo)
