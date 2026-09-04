"""Formatação de CNPJ para exibição.

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
