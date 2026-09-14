"""Formatação de CNPJ (completo e raiz) e CPF para exibição.

Fonte única da máscara. Antes existia uma cópia privada no blueprint
``disputes_center`` — e foi justamente por ser privada que o gerador de
petições não a enxergou e passou anos escrevendo o CNPJ na peça exatamente
como havia sido digitado no cadastro (GER-01).

Não confundir com ``dou_alert_service.formatar_cnpj``: aquela recebe dígitos
já extraídos e normalizados do texto do Diário Oficial e é estrita de
propósito. A daqui recebe o que veio do cadastro, que é campo de texto livre.
"""

TAMANHO_CNPJ = 14


def apenas_digitos(valor) -> str:
    """Tudo que não for dígito sai. ``None`` vira string vazia."""
    return ''.join(ch for ch in (valor or '') if ch.isdigit())


def formatar_cnpj(valor) -> str:
    """``'19630496000105'`` → ``'19.630.496/0001-05'``.

    Devolve o valor como veio quando não dá para mascarar — cadastro
    incompleto, ``'Não informado'``, ou um CNPJ alfanumérico (regra que passa
    a valer a partir de 2026), em que mascarar por posição corromperia o dado.
    Formatar o que já está formatado devolve a mesma coisa.
    """
    digitos = apenas_digitos(valor)
    if len(digitos) != TAMANHO_CNPJ:
        return valor if valor else ''
    return f'{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:14]}'


# ── Identificadores que o portal FAP manda como número ──────────────────
# A API de procurações devolve CNPJ raiz e CPF como inteiro: 00.482.840
# chega como 482840. Depois disso, str() não tem como saber quantos zeros
# faltam — só o tamanho do documento sabe (retorno da homologação de
# "Máscara de CNPJ no template", Painel FAP → Procurações).

TAMANHO_CNPJ_RAIZ = 8
TAMANHO_CPF = 11


def completar_zeros(valor, tamanho: int) -> str | None:
    """Só os dígitos, completados com zero à esquerda até ``tamanho``.

    ``None`` e vazio viram ``None``, para a coluna continuar nula. Mais dígitos
    do que o tamanho não é zero faltando, é outro dado: volta como veio, sem
    corte — cortar inventaria um documento que não existe.
    """
    digitos = apenas_digitos(None if valor is None else str(valor))
    if not digitos:
        return None
    if len(digitos) > tamanho:
        return digitos
    return digitos.zfill(tamanho)


def formatar_cnpj_raiz(valor) -> str:
    """``482840`` → ``'00.482.840'``. O que não cabe em 8 dígitos volta como veio."""
    digitos = completar_zeros(valor, TAMANHO_CNPJ_RAIZ)
    if digitos is None:
        return ''
    if len(digitos) != TAMANHO_CNPJ_RAIZ:
        return str(valor)
    return f'{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}'


def formatar_cpf(valor) -> str:
    """``7488971`` → ``'000.074.889-71'``. O que não cabe em 11 dígitos volta como veio."""
    digitos = completar_zeros(valor, TAMANHO_CPF)
    if digitos is None:
        return ''
    if len(digitos) != TAMANHO_CPF:
        return str(valor)
    return f'{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:11]}'
